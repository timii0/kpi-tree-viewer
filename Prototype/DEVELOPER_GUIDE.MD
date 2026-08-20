# Developer Guide — KPI Tree Viewer

This document covers the internals of every core file: what each function does, what parameters it expects, how data flows between modules, and how to make common changes.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Data Model](#data-model)
3. [kpi_statistics.py](#kpi_statisticspy)
4. [converter.py](#converterpy)
5. [cascade.py](#cascadepy)
6. [editor.py](#editorpy)
7. [app.py](#apppy)
8. [Hierarchy Definition Format](#hierarchy-definition-format)
9. [Goals CSV Format](#goals-csv-format)
10. [Common Changes](#common-changes)

---

## Architecture Overview

```
kpi_statistics.py          Pulls raw data from Teradata → teradata_cache.parquet
        │
        ▼
converter.py               Builds base tree JSON (baselines only, no goals)
        │                  Used by cascade.py via `from converter import build_tree`
        │
cascade.py                 Builds tree, applies goals, cascades stretch, exports JSON + CSV
        │                  Called by editor.py and app.py's Hierarchy Builder tab
        │
        ├──► output/{name}.json           Tree with cascaded goals
        └──► output/{name}_cascaded.csv   Flat summary table
        
editor.py                  Tkinter GUI for designing hierarchy definitions
                           On Save: writes hierarchy JSON, then calls cascade()

app.py                     Streamlit viewer (read-only). Loads tree JSONs from output/
```

---

## Data Model

### Tree Node (JSON)

Every node in the tree JSON has this structure:

```json
{
    "id": "category;name",       // Unique identifier used for goal matching
    "name": "DL",                // Display name
    "category": "carrier",       // Dimension category (maps to hierarchy level)
    "type": "Goal",              // Always "Goal" currently
    "tier": 2,                   // Depth level (integer for primary, X.1/X.2 for splits)
    "num": 808479,               // Numerator (count of successes)
    "den": 1162327,              // Denominator (total opportunities)
    "baseline": 0.6624,          // num/den ratio (pre-goal or post-cascade)
    "goal": 0.6956,              // Target rate after cascading
    "contribution": 0.6327,      // This node's den / parent's den
    "path": "sys/DL",            // Slash-separated path from root
    "children": [],              // Child nodes (same structure)
    "split": true                // (optional) Present only on split branch nodes
}
```

### Key Relationships

| Field | Formula | Notes |
|-------|---------|-------|
| `baseline` | `num / den` | Computed after tree build |
| `goal` | `goal_num / den` | Set by cascade or equals baseline if no goal |
| `contribution` | `child.den / parent.den` | Den-based by default |
| `tier` | Integer for primary, +0.1/0.2 for splits | Inherited by descendants |

---

## kpi_statistics.py

**Purpose:** Connects to Teradata, runs a SQL query, saves results as `teradata_cache.parquet`.

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TD_HOST` | `dwprod` | Teradata hostname (env: `TD_HOST`) |
| `TD_USER` | prompt | Username (env: `TD_USER`) |
| `TD_PASS` | prompt | Password (env: `TD_PASS`) |
| `TD_LOGMECH` | `LDAP` | Auth mechanism (env: `TD_LOGMECH`) |

### SQL Query Columns

The query selects these columns from `zods_kpi.flp_dtl_m`:

| Output Column | Source | Description |
|---------------|--------|-------------|
| `sys` | Literal `'sys'` | Always "sys" — root dimension |
| `ml_dc_1` | `ML_DC_Cd` | Carrier (ML or DC) |
| `ml_dc_2` | `Ownr_Crr_Cd` | Operating carrier (9E, OO, YX, DL) |
| `dom_int` | `Dom_Intl_Cd` | Domestic (D) or International (I) |
| `station` | `Schd_Orig_Stn_Cd` | Origin station code |
| `fleet` | `schd_fleet` | Aircraft fleet type |
| `frst_flt_ind` | `Frst_Flt_Ct` | First flight indicator (0/1) |
| `vendor` | `pax_vendor` | Vendor |
| `Mo_Nb` | `Mo_Nb` | Month number (1-12) |
| `num` | `D0_Ct` | D0 count (numerator) |
| `den` | `DOT_OA_Sub_Op_Ct` | Total operations (denominator) |

### Filters

- `data_cut = 'STANDARD'`
- `DOT_OA_Sub_Op_Ct = 1` (one row per operation)
- Date range: `2025-06-01` to `2026-05-30`

### To Modify

- **Change KPI:** Replace `D0_Ct` in the `num` column with another metric column.
- **Change date range:** Update the `flt_orig_dt between` clause.
- **Add dimensions:** Add columns to the SELECT and ensure they appear in `AVAILABLE_COLUMNS` in editor.py.

---

## converter.py

**Purpose:** Builds a KPI tree from parquet data + hierarchy definition. Used as a library by cascade.py.

### Functions

#### `apply_transform_series(series, transform)`

Applies a value transform to a pandas Series.

| Parameter | Type | Description |
|-----------|------|-------------|
| `series` | `pd.Series` | Raw column data |
| `transform` | `dict or None` | Transform specification |

**Transform types:**

| Type | Behavior | Example |
|------|----------|---------|
| `None` | Strip whitespace, cast to string | — |
| `int_flag` | Cast to int, map via `{"1": "Label", "0": "Label"}` | First flight |
| `map` | String map via `{"key": "value"}` | Custom labels |

**Returns:** Transformed `pd.Series`

---

#### `build_tree(df, hierarchy)`

Builds the full KPI tree from a DataFrame and hierarchy definition.

| Parameter | Type | Description |
|-----------|------|-------------|
| `df` | `pd.DataFrame` | Must contain `num`, `den`, and all dimension columns |
| `hierarchy` | `dict` | Hierarchy JSON with `{"levels": [...]}` structure |

**Returns:** Root node dict (tree structure)

**Internal flow:**

1. `prepare_columns(node)` — Pre-transforms all hierarchy columns into `_lvl_{category}` columns on the DataFrame.
2. Creates root node from `df["num"].sum()` / `df["den"].sum()`.
3. `build_level(parent, parent_df, h_nodes, tier, split_offset=0)` — Recursive. Groups `parent_df` by the current hierarchy column, creates child nodes, recurses.
4. Post-processing:
   - `calc_baselines(n)` — Sets `baseline = num/den` and `goal = baseline` for every node.
   - `calc_contributions(n)` — Sets `contribution = child.den / parent.den` for every child.
   - `set_paths(n, pp)` — Builds slash-separated path strings.

**Split offset logic in `build_level`:**

```python
if is_split:
    split_idx += 1
    node_tier = tier + split_idx * 0.1    # e.g. 3.1, 3.2
    child_offset = split_idx * 0.1
else:
    node_tier = tier + split_offset        # Inherits parent's offset
    child_offset = split_offset

# Recurse with:
build_level(node, filtered_df, h_children, tier + 1, child_offset)
```

---

## cascade.py

**Purpose:** Full pipeline — builds tree, applies explicit goals, cascades stretch to descendants, exports JSON + CSV.

### Configuration Constants

| Constant | Default | Description |
|----------|---------|-------------|
| `GOALS_FILE` | `goals.csv` | Path to goals CSV |
| `HIERARCHY_FILE` | `hierarchy.json` | Default hierarchy definition |
| `CACHE_FILE` | `teradata_cache.parquet` | Data cache |
| `OUTPUT_FILE` | `output/output.json` | Default output path |
| `CARRIER_ALIASES` | `{"ML": "DL", "DL": "DL", "DC": "DC"}` | Node name resolution |
| `CASCADE_BASIS` | (imported from `config.py`) | Controls contributions + stretch distribution |

### Functions

#### `parse_levels(hierarchy)`

Flattens the hierarchy tree into an ordered list of tuples.

| Parameter | Type | Description |
|-----------|------|-------------|
| `hierarchy` | `dict` | `{"levels": [...]}` |

**Returns:** `list[(column, category, transform, split)]`

Used for CSV column ordering and YTD computation.

---

#### `find_node_by_id(node, node_id)`

Depth-first search for a node by its `id` field.

| Parameter | Type | Description |
|-----------|------|-------------|
| `node` | `dict` | Root of subtree to search |
| `node_id` | `str` | Target id (e.g. `"carrier;DL"`) |

**Returns:** Node dict or `None`

---

#### `resolve_goal_target(node_name)`

Resolves carrier aliases in goal target names.

| Parameter | Type | Example |
|-----------|------|---------|
| `node_name` | `str` | `"carrier;ML"` → `"carrier;DL"` |

---

#### `cascade_goals(node)`

Core cascading logic. Distributes parent's num delta to children proportionally.

| Parameter | Type | Description |
|-----------|------|-------------|
| `node` | `dict` | Anchor node (must have `_goal_num` and `_baseline_num` set) |

**Algorithm:**

```
For each child (skipping those with _goal_set=True):
    contribution = child.num / parent._baseline_num
    child_goal_num = child.num + (parent._goal_num - parent._baseline_num) * contribution
    child.goal = child_goal_num / child.den
```

Then recurses into each child.

**Key insight:** Contribution here is **num-based** (child_num / parent_baseline_num), not den-based. This means nodes with higher performance get proportionally more stretch.

---

#### `apply_goals_from_csv(tree, goals_df)`

Applies explicit goal values from the goals CSV to matching tree nodes.

| Parameter | Type | Description |
|-----------|------|-------------|
| `tree` | `dict` | Root node |
| `goals_df` | `pd.DataFrame` | Goals CSV loaded as DataFrame |

Sets on each matched node: `baseline`, `num`, `den`, `goal`, `_goal_num`, `_goal_den`, `_baseline_num`, `_baseline_den`, `_goal_set`, `_stretch`.

---

#### `propagate_goal_nums(node)`

After cascading, writes `_goal_num` back into the `num` field so the tree JSON has consistent values. Also syncs non-anchor parents with their children's sum.

---

#### `clean_flags(node)`

Removes all internal `_` prefixed cascade flags from the tree before serialization.

---

#### `collect_goal_table(node, levels, rows, ancestors, tier_offset, parent_baseline_num)`

Flattens the tree into rows for CSV export.

| Parameter | Type | Description |
|-----------|------|-------------|
| `node` | `dict` | Current node |
| `levels` | `list` | From `parse_levels()` |
| `rows` | `list` | Accumulator (pass None to start) |
| `ancestors` | `dict` | Column→value mapping from ancestors |
| `tier_offset` | `float` | Subtracted from tier for relative numbering |
| `parent_baseline_num` | `float` | Parent's baseline num (for contribution calc) |

**Contribution in CSV:** `child._baseline_num / parent_baseline_num` (num-based).

---

#### `compute_ytd(df, levels)`

Adds `YTD_Num` and `YTD_Den` columns to the output DataFrame.

| Parameter | Type | Description |
|-----------|------|-------------|
| `df` | `pd.DataFrame` | Cascaded output table |
| `levels` | `list` | From `parse_levels()` |

**Logic:**
- Month-level rows: cumulative sum of `num` within each parent group.
- Below-month rows: YTD = own goal value.
- Non-month rows: YTD = full year value.

---

#### `cascade(goals_file, hierarchy_file, cache_file, output_file)`

Main entry point. Orchestrates the full pipeline.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `goals_file` | `Path` | `goals.csv` | Goals CSV path |
| `hierarchy_file` | `Path` | `hierarchy.json` | Hierarchy JSON path |
| `cache_file` | `Path` | `teradata_cache.parquet` | Data cache path |
| `output_file` | `Path` | `output/output.json` | Output tree JSON path |

**Outputs:**
- `{output_file}` — Tree JSON
- `{output_file.parent}/{output_file.stem}_cascaded.csv` — Flat CSV

**Returns:** Root node dict

---

## editor.py

**Purpose:** Tkinter desktop app for designing hierarchy definitions visually.

### Class: `HierarchyDesigner`

#### Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `self.root_data` | `dict` | In-memory hierarchy (wrapped with a virtual root) |
| `self.json_file` | `str` | Path to the current hierarchy JSON file |
| `self.node_lookup` | `dict` | Treeview item_id → node dict |
| `self.parent_lookup` | `dict` | Treeview item_id → parent item_id |

#### Key Methods

| Method | Description |
|--------|-------------|
| `_load_file(filepath)` | Loads hierarchy JSON, wraps in virtual root, populates treeview |
| `_get_save_data()` | Returns `{"levels": [...]}` — unwraps virtual root |
| `add_child()` | Dialog to add a new dimension node under the selected parent |
| `edit_node()` | Dialog to modify column, category, and split flag |
| `toggle_split()` | Toggles `"split": true` on the selected node |
| `delete_node()` | Removes selected node and its children |
| `save_json()` | Saves hierarchy, then calls `cascade()` to build tree + CSV |
| `new_tree()` | Creates a blank hierarchy with a user-provided name |
| `open_tree()` | File dialog to open an existing hierarchy from `hierarchies/` |

#### Constants

| Constant | Description |
|----------|-------------|
| `AVAILABLE_COLUMNS` | List of `(column, category)` tuples for quick-select in Add dialog |
| `TRANSFORMS` | Dict of category → transform definition (auto-applied on add) |
| `HIERARCHIES_DIR` | `./hierarchies/` — where hierarchy files are saved |

---

## app.py

**Purpose:** Streamlit read-only viewer for exploring built KPI trees.

### Tabs

| Tab | Content |
|-----|---------|
| Tree | Interactive expandable tree + node detail panel with QA validation |
| Graph | Plotly network diagram (Graph view) or hierarchy definition diagram (Hierarchy view) |
| Statistics | Displays the `{kpi}_cascaded.csv` as a table |
| Hierarchy Builder | UI to select a hierarchy and build a new tree via `cascade()` |

### Key Functions

#### `build_path_index(node, index=None)`
Creates a dict mapping `path` → node for O(1) lookups.

#### `count_nodes(node)`
Returns total node count in the tree (recursive).

#### `validate_contributions(node)`
Checks that contribution sums to 1.0 for both primary and split groups at every level.

**Returns:** List of `{"node": name, "total": float}` for failures.

#### `validate_rollup(node)`
Checks that children's num sums to parent's num, and contribution sums are valid.

**Returns:** List of issue dicts with `type`, `node`, and details.

#### `display_tree(node, depth=0, ancestors=None)`
Recursive Streamlit renderer. Uses expanders for parent nodes, buttons for leaves. Depth-limited by `MAX_TREE_DEPTH` sidebar slider.

#### `build_tree_from_hierarchy(df, hierarchy_def)`
Duplicate of converter.py's `build_tree()` — used by the Hierarchy Builder tab. Same logic including split offset inheritance.

### Session State Keys

| Key | Type | Description |
|-----|------|-------------|
| `tree_data` | `dict` | Currently loaded tree root node |
| `loaded_kpi` | `str` | Name of the currently loaded KPI |
| `selected_path` | `str` | Path of the currently selected node |
| `path_index` | `dict` | path → node mapping |
| `node_count` | `int` | Total nodes in tree |
| `max_depth` | `int` | Maximum depth of current tree |
| `validation_issues` | `list` | Contribution validation results |
| `rollup_issues` | `list` | Num rollup validation results |

---

## Hierarchy Definition Format

```json
{
    "levels": [
        {
            "column": "sys",           // DataFrame column name
            "category": "system",      // Logical category name (used in node.id)
            "children": [
                {
                    "column": "ml_dc_1",
                    "category": "carrier",
                    "children": [
                        {
                            "column": "fleet",
                            "category": "fleet",
                            "split": true,          // Split branch
                            "children": [...]
                        },
                        {
                            "column": "ml_dc_2",
                            "category": "dc_carrier",
                            "children": [...]
                        }
                    ]
                }
            ]
        }
    ]
}
```

### Fields

| Field | Required | Description |
|-------|----------|-------------|
| `column` | Yes | Name of the DataFrame column to group by |
| `category` | Yes | Logical name (used in `node.id` as `"category;value"`) |
| `children` | No | Nested hierarchy levels |
| `split` | No | If `true`, this branch is a split (alternate view of same data) |
| `transform` | No | Value transform applied to the column before grouping |

### Optional Fields (root level)

| Field | Description |
|-------|-------------|
| `name` | Display name for the hierarchy (e.g. "D0 Hierarchy") |
| `version` | Version string |
| `root` | Metadata about the root node |

---

## Goals CSV Format

```csv
KPI_Name,Node_Name,Baseline,Baseline_Num,Baseline_Den,Stretch,KPI_Num,KPI_Den,Goal
D0,system;sys,68.29,1216960,1782050,5%,1277808,1782050,71.70
D0,carrier;ML,66.24,769980,1162327,5%,808479,1162327,69.56
D0,carrier;DC,72.13,446980,619723,5%,469329,619723,75.73
```

| Column | Type | Description |
|--------|------|-------------|
| `KPI_Name` | str | KPI identifier (e.g. "D0") |
| `Node_Name` | str | Node id format: `category;name`. Aliases resolved via `CARRIER_ALIASES` |
| `Baseline` | float | Baseline rate as percentage (e.g. 68.29 = 68.29%) |
| `Baseline_Num` | int | Baseline numerator |
| `Baseline_Den` | int | Baseline denominator |
| `Stretch` | str | Target stretch percentage (e.g. "5%") |
| `KPI_Num` | int | Goal numerator |
| `KPI_Den` | int | Goal denominator |
| `Goal` | float | Goal rate as percentage |

---

## Common Changes

### Change contribution basis (num vs den)

Contributions and cascade stretch are now controlled by a **single setting** in `config.py`:

```python
# config.py
CASCADE_BASIS = "num"  # or "den"
```

This controls all three places at once:
- `converter.py` → `calc_contributions()` (tree building)
- `cascade.py` → `cascade_goals()` (stretch distribution)
- `app.py` → `calc_contributions()` (viewer display)

To switch from num-based to den-based, just change the value in `config.py`. No code edits elsewhere.

---

### Use a custom contribution formula

If neither "num" nor "den" fits your needs, modify `calc_contributions()` in both `converter.py` and `app.py`:

```python
def calc_contributions(n):
    if not n.get("children"):
        return
    total = sum(your_formula(c) for c in n["children"])
    for c in n["children"]:
        c["contribution"] = your_formula(c) / total if total > 0 else 0
        calc_contributions(c)
```

Also update `cascade_goals()` in `cascade.py` to use the same formula for the cascade `contribution` variable.

---

### Add a new dimension

1. **Add the column to the SQL query** in `kpi_statistics.py`:
   ```sql
   new_column_name as new_col,
   ```

2. **Re-run** `python kpi_statistics.py` to refresh the parquet cache.

3. **Restart `editor.py`** — the new column appears automatically in the Quick Select dropdown (dimensions are auto-discovered from the parquet schema).

4. **Add the dimension** in the hierarchy editor (or manually edit hierarchy JSON).

5. **(Optional)** Add a value transform in `editor.py`'s `TRANSFORMS` dict if the raw values need labeling.

---

### Add a value mapping (transform) for a column

Value mappings convert raw data values into display-friendly labels in the tree
(e.g. `"1"` → `"First Flight"`, `"D"` → `"Domestic"`).

**To add a mapping using an existing transform type:**

1. Add an entry to `TRANSFORMS` in `editor.py`, keyed by the **column name**:
   ```python
   TRANSFORMS = {
       "frst_flt_ind": {"type": "int_flag", "map": {"1": "First Flight", "0": "Not First Flight"}},
       "dom_int": {"type": "map", "map": {"D": "Domestic", "I": "International"}},
   }
   ```

2. That's it. The transform is automatically:
   - Attached to the hierarchy node when adding that column in the editor
   - Applied during tree building by `converter.py` → `apply_transform_series()`

**Supported transform types:**

| Type | Input | Behavior | Use Case |
|------|-------|----------|----------|
| `int_flag` | Numeric column (0/1) | Casts to int, then maps via `{"1": "Label", "0": "Label"}` | Binary indicators |
| `map` | String column | Direct string→string mapping via dict. Unmapped values pass through | Renaming categories |

**Example — mapping fleet codes to readable names:**
```python
TRANSFORMS = {
    "frst_flt_ind": {"type": "int_flag", "map": {"1": "First Flight", "0": "Not First Flight"}},
    "fleet": {"type": "map", "map": {"738": "737-800", "739": "737-900", "321": "A321"}},
}
```

---

### Add a new transform type (custom logic)

If the existing `int_flag` and `map` types don't cover your needs, you can add a new type:

1. **Define the transform** in `editor.py`'s `TRANSFORMS` dict:
   ```python
   TRANSFORMS = {
       "frst_flt_ind": {"type": "int_flag", "map": {...}},
       "my_column": {"type": "my_type", "map": {...}},
   }
   ```

2. **Handle it** in `converter.py`'s `apply_transform_series()`:
   ```python
   if kind == "my_type":
       # Your transformation logic on the pandas Series
       return transformed_series
   ```

3. **Also handle it** in `app.py`'s `apply_transform()` inside `build_tree_from_hierarchy()`.

---

### Change the cascade distribution method

The cascade distribution and tree node contributions are both controlled by `CASCADE_BASIS` in `config.py` — the single source of truth:

```python
# config.py
CASCADE_BASIS = "num"   # Currently set to num-based
```

**This one setting controls three things:**
1. Tree node contributions (`converter.py` → `calc_contributions`)
2. Cascade stretch distribution (`cascade.py` → `cascade_goals`)
3. App display contributions (`app.py` → `calc_contributions`)

**Options:**
- `"num"` (current default): `child.num / parent.num` — distributes stretch proportionally to performance share. Every child gets the same percentage improvement as the parent.
- `"den"`: `child.den / parent.den` — distributes stretch proportionally to volume share. Larger-volume children get more absolute stretch regardless of current performance.

To switch, change the value in `config.py`:

```python
CASCADE_BASIS = "den"
```

No other code changes needed — all three modules import from `config.py` automatically.

---

### Add a new KPI (different from D0)

1. **Update `kpi_statistics.py`** — change the `num` column in the SQL query to the new KPI's numerator (e.g. `A0_Ct`, `CANCEL_Ct`).

2. **Update `goals.csv`** — add goal rows with matching `Node_Name` values.

3. **Run the pipeline:**
   ```bash
   python kpi_statistics.py      # New parquet with new KPI data
   python editor.py              # Design hierarchy, Save to build
   ```

---

### Change the goal year

In `cascade.py` → `cascade()` function:

```python
out_df["Goal_Yr"] = 2027    # Change this value
```

---

### Change carrier aliases

In `cascade.py`:

```python
CARRIER_ALIASES = {"ML": "DL", "DL": "DL", "DC": "DC"}
```

Add or modify entries as needed. Format: `{"data_value": "tree_value"}`.

---

### Modify QA validation thresholds

In `app.py`:

```python
# Contribution tolerance (currently 0.1%)
if abs(total - 1.0) > 0.001:

# Num rollup tolerance (currently scales with child count)
if parent_num > 0 and abs(child_sum - parent_num) > len(primary):
```

Adjust `0.001` or the rollup formula as needed.
