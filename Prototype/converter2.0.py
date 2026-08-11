import pandas as pd
import json
from pathlib import Path

OUTPUT_FILE = Path("output") / "D0 2.0.json"
HIERARCHY_FILE = Path("hierarchy.json")

cache_file = "teradata_cache.parquet"
df = pd.read_parquet(cache_file)

print(df)

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


def apply_transform(transform, raw_value):
    """
    Apply a transform rule from the hierarchy definition.
    Supports:
      - "map": dict of raw_value -> display_name
      - "type": coercion type ("int_flag" maps 1/0 to labels)
    Falls back to str(raw_value) if no rule matches.
    """
    if not transform:
        return str(raw_value).strip()

    kind = transform.get("type")

    if kind == "int_flag":
        mapping = transform.get("map", {})
        try:
            key = str(int(float(raw_value)))
        except (ValueError, TypeError):
            key = str(raw_value).strip()
        return mapping.get(key, key)

    if kind == "map":
        mapping = transform.get("map", {})
        key = str(raw_value).strip()
        return mapping.get(key, key)

    return str(raw_value).strip()

root = {
    "id": "Nwk Sys",
    "name": "Nwk Sys",
    "category": "Enterprise",
    "type": "Goal",
    "path": "",
    "num": 0,
    "den": 0,
    "baseline": 0,
    "goal": 0,
    "contribution": 1.0,
    "children": []
}

def find_or_create(parent, name, category):
    for child in parent["children"]:

        if (
            child["name"] == name and
            child["category"] == category
        ):
            return child

    node = {
        "id": f"{category};{name}",
        "name": name,
        "category": category,
        "tier": 0,
        "type": "Goal",
        "path": "",
        "num": 0,
        "den": 0,
        "baseline": 0,
        "goal": 0,
        "contribution": 1.0,
        "children": []
    }

    parent["children"].append(
        node
    )

    return node

for _, row in df.iterrows():

    num = int(row["num"])
    den = int(row["den"])

    current = root

    current["num"] += num
    current["den"] += den

    for column, category, transform in LEVELS:

        value = str(row[column]).strip()

        # Skip empty values
        if (
            not value
            or value.lower() == "nan"
        ):
            continue

        # Apply transform rules from hierarchy definition
        if transform:
            value = apply_transform(
                transform, row[column]
            )

        current = find_or_create(
            current,
            value,
            category
        )

        current["num"] += num
        current["den"] += den

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