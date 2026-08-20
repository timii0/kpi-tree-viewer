# KPI Tree Viewer

Interactive tool for visualizing KPI goal trees, cascading stretch targets down organizational hierarchies, and inspecting performance at every level.

## What It Does

1. **Extracts KPI data** from Teradata into a local parquet cache
2. **Designs hierarchy definitions** via a Tkinter editor (`editor.py`)
3. **Builds a KPI tree** from the cached data using a configurable hierarchy definition
4. **Cascades goals** from leadership targets down to every node proportionally based on num contribution
5. **Visualizes the tree** in a Streamlit app with interactive graph view, hierarchy diagram, and statistics
6. **Validates rollup** — ensures children's num sums to parent at every level and contributions are consistent

## Project Structure

```
Prototype/
├── app.py                  # Streamlit viewer (main UI)
├── config.py               # Shared configuration (CASCADE_BASIS)
├── editor.py               # Tkinter hierarchy designer (create/edit hierarchy definitions)
├── kpi_statistics.py       # Teradata query → teradata_cache.parquet
├── converter.py            # Builds the base tree JSON from parquet + hierarchy
├── cascade.py              # Applies goals from goals.csv and cascades stretch down
├── hierarchy.json          # Default hierarchy definition (nesting order + transforms)
├── hierarchies/            # Saved hierarchy definitions (one per KPI variant)
├── goals.csv               # Leadership goal targets (truth source for anchors)
├── teradata_cache.parquet  # Cached raw data (flat rows with dimensions + num/den)
├── output/                 # Generated tree JSONs + cascaded CSVs (consumed by app.py)
├── legacy/                 # Archived output files (non-D0 KPIs, from previous tool version)
├── assets/                 # Logo and static files
├── notebook.ipynb          # Step-by-step workflow notebook
└── requirements.txt        # Python dependencies
```

## Prerequisites

- Python 3.12 or later
- Network access to Teradata (`dwprod`) for data refresh (optional if parquet cache exists)

## Setup

```bash
cd Prototype

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate         # Linux/macOS
# .venv\Scripts\activate.bat      # Windows cmd
# .venv\Scripts\Activate.ps1      # Windows PowerShell

# Install dependencies
pip install -r requirements.txt
```

**Note:** `teradatasql` is only needed for refreshing data from Teradata (`kpi_statistics.py`). If you already have `teradata_cache.parquet`, you can skip it:

```bash
pip install streamlit pandas numpy pyarrow plotly networkx pillow
```

## Usage

### Step 1: Refresh data cache (optional)

Queries Teradata and writes `teradata_cache.parquet`. Requires `TD_USER` and `TD_PASS` environment variables (or prompts interactively):

```bash
python kpi_statistics.py
```

Skip this step if the parquet cache is already up to date.

### Step 2: Design a hierarchy

Launch the Tkinter hierarchy editor to create or modify hierarchy definitions:

```bash
python editor.py
```

Add dimensions (column + category), arrange nesting order, toggle split branches. Saving a hierarchy also builds the tree and runs cascade automatically, outputting results to `output/`.

**Note:** `editor.py` requires a graphical display (X server). It will not work on headless environments like Red Hat DevSpaces or remote containers. On those platforms, use the Hierarchy Builder tab in the Streamlit viewer or edit hierarchy JSON files manually.

### Step 3: Build and cascade (standalone)

If running without the editor, use cascade.py directly. It reads the hierarchy, builds the tree, applies goals from `goals.csv`, cascades stretch, and writes:
- `output/{name}.json` (tree with cascaded goal values)
- `output/{name}_cascaded.csv` (flat summary with YTD expectations)

```bash
python cascade.py
```

### Step 4: Launch the viewer

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
```

On a local machine this opens at `http://localhost:8501`.

**On Red Hat DevSpaces / headless environments:**
1. Run the command above
2. Watch for a notification in the IDE: "A new process is listening on port 8501"
3. Click "Open in New Tab" to access the app via the DevSpaces proxy URL
4. If no notification appears, check the "Endpoints" section in the DevSpaces dashboard for a routed URL to port 8501

Use the sidebar to select a KPI, adjust max stations, and control tree display depth.

## App Features

- **Tree Tab** — Expandable tree with lazy rendering (depth-limited). Select any node to view properties (baseline, goal, contribution, num, den). Includes QA validation showing contribution sums and rollup checks.

- **Graph Tab** — Two views:
  - *Graph*: Plotly network diagram rooted at the selected node. Color-coded by type. Hover for full node details.
  - *Hierarchy*: Renders the hierarchy definition used to build the currently selected tree. Automatically matches the hierarchy file from `hierarchies/` by KPI name, falling back to `hierarchy.json`.

- **Statistics Tab** — Displays the cascaded CSV for the selected KPI from the output directory.

- **Hierarchy Builder Tab** — Select a saved hierarchy and build a new KPI tree directly from the Streamlit UI. Runs cascade and outputs to `output/`.

- **QA Validation** — Two checks run at every level:
  - *Contribution Sum*: Verifies primary and split children contributions each sum to 100%
  - *Num Rollup*: Verifies children's num sums to parent's num (with rounding tolerance for cascaded values)

## Cascading Logic

1. Anchor nodes are identified by `Node_Name` in `goals.csv` (format: `category;name`, e.g. `carrier;ML`)
2. Carrier aliases are resolved (`ML` → `DL` in data)
3. Each anchor receives explicit baseline/goal values from the CSV
4. The num delta (`goal_num - baseline_num`) is distributed to children proportionally by each child's num contribution (`child_num / parent_num`)
5. Den stays constant — only num grows, so the rate improvement cascades uniformly
6. Children with their own explicit goals are skipped during cascading
7. After cascading, `propagate_goal_nums` writes goal_num back into the `num` field at every level so the tree is internally consistent

## Split Branches and Tier Numbering

Split branches provide alternate dimensional views of the same data without affecting the primary rollup. They are marked with `"split": true` in the hierarchy definition.

**Tier numbering rules:**
- Primary (non-split) nodes use integer tiers: 1, 2, 3, 4, ...
- Split branches at the same level get incrementing offsets: `.1`, `.2`, `.3`, etc.
- All descendants of a split branch inherit their parent's offset
- There is no hard limit on the number of splits at a level (`.1` through `.9` are safe; beyond `.9` would collide with the next integer tier)

**Example** (hierarchy with 3 splits at carrier level):
```
sys (1) → carrier (2) → dc_carrier (3.0)     [primary branch]
                       → fleet (3.1, split)    [1st split branch]
                       → dom_int (3.2, split)  [2nd split branch]
                       → vendor (3.3, split)   [3rd split branch]
```

Children inherit the offset:
```
fleet (3.1) → station (4.1)       [inherits .1 from fleet]
dom_int (3.2) → station (4.2)     [inherits .2 from dom_int]
vendor (3.3) → station (4.3)      [inherits .3 from vendor]
dc_carrier (3.0) → month (4.0)    [primary, no offset]
```

This allows each split branch to be tracked independently at every depth level.

## Key Files

| File | Role |
|------|------|
| `hierarchy.json` | Default hierarchy definition. Declares nesting order of dimensions and optional value transforms. |
| `hierarchies/` | Directory of saved hierarchy definitions (one per KPI variant, e.g. `D0 4.0.json`). |
| `goals.csv` | Truth source for anchor nodes. Format: `KPI_Name, Node_Name, Baseline, Baseline_Num, Baseline_Den, Stretch, KPI_Num, KPI_Den, Goal`. |
| `kpi_statistics.py` | Connects to Teradata and pulls flight-level KPI data into `teradata_cache.parquet`. |
| `converter.py` | Reads parquet + hierarchy, aggregates at each level, computes baselines and contributions. |
| `cascade.py` | Overlays goals onto matching nodes, cascades stretch proportionally, computes YTD expectations, exports JSON and CSV. |
| `editor.py` | Tkinter app for visually designing hierarchy definitions. Supports split branches. On save, builds the tree and runs cascade. |
| `app.py` | Streamlit app with tree navigation, graph visualization, hierarchy view, statistics, and QA validation. |

## Hierarchy JSON vs Tree JSON

These are two different file types that serve different purposes:

### Hierarchy JSON (`hierarchies/*.json`)

A **template** that defines the nesting order of dimensions. It has no data — just structure. Used as input to build a tree.

```json
{
    "levels": [
        {
            "column": "sys",
            "category": "sys",
            "children": [
                {
                    "column": "ml_dc_1",
                    "category": "ml_dc_1",
                    "children": [
                        {"column": "station", "category": "station"}
                    ]
                },
                {
                    "column": "fleet",
                    "category": "fleet",
                    "split": true
                }
            ]
        }
    ]
}
```

**Key characteristics:**
- Stored in `hierarchies/` (or root `hierarchy.json`)
- Created/edited with `editor.py` or manually
- Defines WHAT dimensions to group by and in what order
- Contains no KPI values (no num, den, baseline, goal)
- Small file (typically <3KB)
- Can include `"split": true` and `"transform": {...}` on nodes

### Tree JSON (`output/*.json`)

A **fully populated tree** with actual KPI data at every node. Built from data + hierarchy. Used by the viewer.

```json
{
    "id": "system;sys",
    "name": "sys",
    "category": "sys",
    "type": "Goal",
    "tier": 1,
    "num": 1277808,
    "den": 1782050,
    "baseline": 0.6891,
    "goal": 0.7170,
    "contribution": 1.0,
    "path": "sys",
    "children": [
        {
            "id": "ml_dc_1;DL",
            "name": "DL",
            "category": "ml_dc_1",
            "tier": 2,
            "num": 808479,
            "den": 1162327,
            "baseline": 0.6624,
            "goal": 0.6956,
            "contribution": 0.6327,
            "path": "sys/DL",
            "children": [...]
        }
    ]
}
```

**Key characteristics:**
- Stored in `output/`
- Generated by `cascade.py` (never hand-edited)
- Contains ACTUAL values: num, den, baseline, goal, contribution at every node
- Each node represents a real group from the data (e.g. carrier "DL", station "ATL")
- Large file (can be 10MB+ with hundreds of stations)
- Has `path`, `tier`, `id` fields for viewer navigation

### Relationship

```
hierarchy.json (template)  +  teradata_cache.parquet (data)  +  goals.csv (targets)
                                         │
                                    cascade.py
                                         │
                                         ▼
                              output/{name}.json (populated tree)
```

The hierarchy defines the shape. The data fills in the values. The goals set targets. The tree JSON is the final product combining all three.

## Data Flow

```
                         kpi_statistics.py
                               │
                               ▼
                      teradata_cache.parquet
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
            ▼                  ▼                  ▼
     hierarchy.json      converter.py        cascade.py
     hierarchies/              │                  │
            │                  ▼                  │
            │           output/{name}.json ◄──────┘
            │                                goals.csv
            ▼                                     │
       editor.py ─────────────────────────────────┘
            │                                     
            ▼                                     
     output/{name}.json                           
     output/{name}_cascaded.csv                   
                               │
                               ▼
                       app.py (Streamlit)
```

## Notes

- `goals.csv` baseline num/den must match the parquet data exactly. If the parquet is refreshed, re-derive the goal values to avoid rollup mismatches.
- The graph view roots from the currently selected node, not the full tree root.
- The parquet cache covers flight data from 2025-06-01 to 2026-05-30.
- YTD expectations in the cascaded CSV use cumulative month-level rollups.
- The hierarchy view under Graph automatically shows the hierarchy matching the selected KPI name.
- Available dimensions in the editor are auto-discovered from the parquet cache columns. If you change the SQL query to add/remove columns, re-run `kpi_statistics.py` then restart `editor.py`.
- The cascade distribution method is controlled by `CASCADE_BASIS` in `config.py` (currently `"num"`). Set to `"den"` for volume-proportional distribution. This single setting controls both tree node contributions and cascade stretch allocation.

## Legacy Files

The `legacy/output/` directory contains tree JSONs from previous versions of this tool. These were generated by an earlier approach that mapped KPI paths directly from the `grp_comb` column in `zods_kpi` tables, rather than building trees dynamically from hierarchy definitions.

**Key differences from current output:**
- Nodes used fixed organizational paths (div → director → manager) instead of configurable dimension hierarchies
- Contribution values were pre-computed externally (not derived from num or den)
- No split branch support
- No cascade — goals were assigned per-node without proportional distribution
- Tree structure was static (changing the hierarchy required re-coding)

These files are kept for reference and comparison but are not used by the current pipeline. The current tool replaces that approach with configurable hierarchies, dynamic tree building from raw data, and automated goal cascading.

## Value Transforms

Transforms convert raw data values into human-readable labels in the tree (e.g. `1` → `"First Flight"`). They are defined in `editor.py`'s `TRANSFORMS` dict, keyed by column name:

```python
TRANSFORMS = {
    "frst_flt_ind": {"type": "int_flag", "map": {"1": "First Flight", "0": "Not First Flight"}},
}
```

When a dimension with a matching column name is added in the editor, its transform is automatically attached to the hierarchy node.

**Supported transform types:**
- `int_flag`: Casts the column to int, then maps via a string dict. Use for binary indicators.
- `map`: Direct string-to-string mapping. Use for renaming categorical values.

**To add a new value mapping:**
1. Add an entry to `TRANSFORMS` in `editor.py`:
   ```python
   TRANSFORMS = {
       "frst_flt_ind": {"type": "int_flag", "map": {"1": "First Flight", "0": "Not First Flight"}},
       "dom_int": {"type": "map", "map": {"D": "Domestic", "I": "International"}},
   }
   ```
2. The transform is auto-applied when building trees via `converter.py`'s `apply_transform_series()`.
3. No code changes needed — just add the dict entry and rebuild.
