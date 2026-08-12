import pandas as pd
import json
from pathlib import Path
import time

OUTPUT_FILE = Path("output") / "D0 2.0.json"
HIERARCHY_FILE = Path("hierarchy.json")

cache_file = "teradata_cache.parquet"

start = time.time()
df = pd.read_parquet(cache_file)
print(f"Loaded {len(df):,} rows in {time.time() - start:.2f}s")

# Load hierarchy definition from JSON
with open(HIERARCHY_FILE, "r", encoding="utf-8") as f:
    HIERARCHY = json.load(f)


def parse_levels(hierarchy):
    """
    Flatten the nested hierarchy JSON into an ordered list of
    (column, category, transform) tuples by walking depth-first.
    """
    levels = []

    def walk(node):
        levels.append((
            node["column"],
            node["category"],
            node.get("transform")
        ))
        for child in node.get("children", []):
            walk(child)

    for top in hierarchy.get("levels", []):
        walk(top)

    return levels


LEVELS = parse_levels(HIERARCHY)


def apply_transform_series(series, transform):
    """
    Apply a transform to an entire pandas Series (vectorized).
    Returns the transformed Series.
    """
    if not transform:
        return series.astype(str).str.strip()

    kind = transform.get("type")

    if kind == "int_flag":
        mapping = transform.get("map", {})
        # Convert to int-string keys for mapping
        int_series = pd.to_numeric(series, errors="coerce").fillna(-1).astype(int).astype(str)
        return int_series.map(mapping).fillna(series.astype(str).str.strip())

    if kind == "map":
        mapping = transform.get("map", {})
        return series.astype(str).str.strip().map(mapping).fillna(series.astype(str).str.strip())

    return series.astype(str).str.strip()


# ---------------------------------------------------------------------------
# Vectorized tree building using multi-level groupby
# ---------------------------------------------------------------------------

def build_tree_fast(df, levels):
    """
    Build the tree using a single groupby on all levels at once,
    then assemble the tree from aggregated groups.
    """
    # Pre-transform all columns into clean string values
    col_names = []
    for column, category, transform in levels:
        col_name = f"_lvl_{category}"
        df[col_name] = apply_transform_series(df[column], transform)
        col_names.append(col_name)

    # Root aggregation
    total_num = int(df["num"].sum())
    total_den = int(df["den"].sum())

    root = {
        "id": "Nwk Sys",
        "name": "Nwk Sys",
        "category": "Enterprise",
        "type": "Goal",
        "path": "",
        "num": total_num,
        "den": total_den,
        "baseline": 0,
        "goal": 0,
        "contribution": 1.0,
        "children": []
    }

    # Pre-aggregate at every prefix length in one pass
    # For N levels, we do N groupby operations (not per-row)
    print("Aggregating levels...")
    agg_start = time.time()

    # Build aggregations for each depth
    level_aggs = {}
    for depth in range(1, len(col_names) + 1):
        group_cols = col_names[:depth]
        agg = df.groupby(group_cols, sort=False).agg(
            num=("num", "sum"),
            den=("den", "sum")
        ).reset_index()
        level_aggs[depth] = agg

    print(f"Aggregation done in {time.time() - agg_start:.2f}s")

    # Now assemble the tree from aggregated data
    print("Assembling tree...")
    assemble_start = time.time()

    # Build a lookup: tuple of values -> (num, den) for each depth
    def assemble_level(parent_node, parent_key, depth):
        """Add children at this depth under parent_key."""
        if depth > len(col_names):
            return

        agg = level_aggs[depth]
        category = levels[depth - 1][1]

        # Filter to rows matching parent key
        if parent_key:
            mask = True
            for i, val in enumerate(parent_key):
                mask = mask & (agg[col_names[i]] == val)
            subset = agg[mask]
        else:
            subset = agg

        # Get unique values at this level
        col = col_names[depth - 1]
        unique_at_level = subset.groupby(col, sort=False).agg(
            num=("num", "sum"),
            den=("den", "sum")
        ).reset_index()

        for _, row in unique_at_level.iterrows():
            name = str(row[col])
            if not name or name.lower() == "nan":
                continue

            num = int(row["num"])
            den = int(row["den"])

            node = {
                "id": f"{category};{name}",
                "name": name,
                "category": category,
                "tier": 0,
                "type": "Goal",
                "path": "",
                "num": num,
                "den": den,
                "baseline": 0,
                "goal": 0,
                "contribution": 1.0,
                "children": []
            }

            parent_node["children"].append(node)

            # Recurse
            child_key = parent_key + (name,) if parent_key else (name,)
            assemble_level(node, child_key, depth + 1)

    assemble_level(root, (), 1)
    print(f"Assembly done in {time.time() - assemble_start:.2f}s")

    return root


root = build_tree_fast(df, LEVELS)

def calculate_baselines(node):

    if node["den"] > 0:

        node["baseline"] = (
            node["num"]
            / node["den"]
        )

    else:

        node["baseline"] = 0

    node["goal"] = node["baseline"]

    for child in node["children"]:

        calculate_baselines(child)


def calculate_contributions(node):

    children = node.get(
        "children",
        []
    )

    if not children:
        return

    parent_den = node["den"]

    for child in children:

        if parent_den > 0:

            child["contribution"] = (
                child["den"]
                / parent_den
            )

        else:
            child["contribution"] = 0
        calculate_contributions(child)

def update_paths(
    node,
    parent_path=""
):

    if parent_path:

        node["path"] = (
            f"{parent_path}/{node['name']}"
        )

    else:

        node["path"] = node["name"]

    for child in node["children"]:

        update_paths(
            child,
            node["path"]
        )
    
def update_tiers(node, tier=1):

    node["tier"] = tier

    for child in node["children"]:
        update_tiers(
            child,
            tier + 1
        )

update_tiers(root)
calculate_baselines(root)
calculate_contributions(root)
update_paths(root)

with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        root,
        f,
        indent=4,
        ensure_ascii=False
    )

print(
    f"Created {OUTPUT_FILE}"
)


# ============================================================================
# DATA FLOW & FILE ROLES
# ============================================================================
#
# ┌─────────────────────────────────────────────────────────────────────────┐
# │                          FILE RESPONSIBILITIES                          │
# ├──────────────────────────┬──────────────────────────────────────────────┤
# │  hierarchy.json          │  Hierarchy definition engine. Declares the  │
# │                          │  nesting order of columns, category labels, │
# │                          │  and optional value transforms.             │
# ├──────────────────────────┼──────────────────────────────────────────────┤
# │  teradata_cache.parquet  │  Raw data source. Flat tabular rows with    │
# │                          │  dimension columns + num/den metric pair.   │
# ├──────────────────────────┼──────────────────────────────────────────────┤
# │  converter2.0.py         │  Pipeline orchestrator. Reads hierarchy +   │
# │  (this file)             │  data, builds the tree, enriches nodes,     │
# │                          │  writes the final JSON.                     │
# ├──────────────────────────┼──────────────────────────────────────────────┤
# │  output/D0 2.0.json      │  Output artifact. Nested JSON tree ready   │
# │                          │  for visualization in app.py.               │
# ├──────────────────────────┼──────────────────────────────────────────────┤
# │  app.py                  │  Viewer / editor. Streamlit app that loads  │
# │                          │  the output JSON and renders the tree.      │
# └──────────────────────────┴──────────────────────────────────────────────┘
#
#
# ┌─────────────────────────────────────────────────────────────────────────┐
# │                         PIPELINE FLOWCHART                              │
# └─────────────────────────────────────────────────────────────────────────┘
#
#  ┌────────────────────┐       ┌────────────────────┐
#  │  hierarchy.json    │       │  teradata_cache    │
#  │                    │       │  .parquet          │
#  │  Nested JSON with  │       │                    │
#  │  column, category, │       │  Flat rows:        │
#  │  transform rules   │       │  sys, ml_dc_1 ...  │
#  └────────┬───────────┘       │  num, den          │
#           │                   └─────────┬──────────┘
#           │                             │
#           ▼                             ▼
#  ┌────────────────────────────────────────────────────────────────┐
#  │  STAGE 1: parse_levels()                                       │
#  │                                                                │
#  │  Input:  Nested hierarchy JSON                                 │
#  │  Output: Flat ordered list [(column, category, transform)...]  │
#  │                                                                │
#  │  State:  LEVELS = [("sys","system",None),                      │
#  │                    ("ml_dc_1","carrier",None),                  │
#  │                    ("frst_flt_ind","first_flt",{...}), ...]     │
#  └────────────────────────────┬───────────────────────────────────┘
#                               │
#                               ▼
#  ┌────────────────────────────────────────────────────────────────┐
#  │  STAGE 2: Row iteration + find_or_create()                     │
#  │                                                                │
#  │  Input:  DataFrame rows + LEVELS list                          │
#  │  Output: Nested tree with aggregated num/den at each node      │
#  │                                                                │
#  │  State:  root                                                  │
#  │           ├── system: sys  (num=Σ, den=Σ)                      │
#  │           │    ├── carrier: DL  (num=Σ, den=Σ)                 │
#  │           │    │    ├── dc_carrier: DL  (num=Σ, den=Σ)         │
#  │           │    │    │    └── ...                                │
#  │           │    │    └── ...                                     │
#  │           │    └── ...                                          │
#  │           └── ...                                               │
#  └────────────────────────────┬───────────────────────────────────┘
#                               │
#                               ▼
#  ┌────────────────────────────────────────────────────────────────┐
#  │  STAGE 3: update_tiers()                                       │
#  │                                                                │
#  │  Input:  Raw tree (tier=0 everywhere)                          │
#  │  Output: Each node tagged with its depth (tier=1,2,3...)       │
#  └────────────────────────────┬───────────────────────────────────┘
#                               │
#                               ▼
#  ┌────────────────────────────────────────────────────────────────┐
#  │  STAGE 4: calculate_baselines()                                │
#  │                                                                │
#  │  Input:  Tree with num/den                                     │
#  │  Output: baseline = num/den, goal = baseline (initial)         │
#  │                                                                │
#  │  State:  Each node gains  baseline: 0.83, goal: 0.83           │
#  └────────────────────────────┬───────────────────────────────────┘
#                               │
#                               ▼
#  ┌────────────────────────────────────────────────────────────────┐
#  │  STAGE 5: calculate_contributions()                            │
#  │                                                                │
#  │  Input:  Tree with den values                                  │
#  │  Output: contribution = child.den / parent.den                 │
#  │                                                                │
#  │  State:  Each child gains  contribution: 0.45                  │
#  └────────────────────────────┬───────────────────────────────────┘
#                               │
#                               ▼
#  ┌────────────────────────────────────────────────────────────────┐
#  │  STAGE 6: update_paths()                                       │
#  │                                                                │
#  │  Input:  Tree with names                                       │
#  │  Output: path = "Nwk Sys/sys/DL/DL/First Flight/DOM/737/..."   │
#  │                                                                │
#  │  State:  Each node gains a slash-delimited breadcrumb path     │
#  └────────────────────────────┬───────────────────────────────────┘
#                               │
#                               ▼
#  ┌────────────────────────────────────────────────────────────────┐
#  │  STAGE 7: Write JSON                                           │
#  │                                                                │
#  │  Input:  Fully enriched tree                                   │
#  │  Output: output/D0 2.0.json                                    │
#  │                                                                │
#  │  State:  Complete nested JSON with:                             │
#  │          id, name, category, tier, type, path,                  │
#  │          num, den, baseline, goal, contribution, children[]     │
#  └────────────────────────────────────────────────────────────────┘
#                               │
#                               ▼
#                    ┌──────────────────────┐
#                    │  app.py (Streamlit)  │
#                    │  Loads JSON, renders │
#                    │  tree + graph + edit │
#                    └──────────────────────┘
#