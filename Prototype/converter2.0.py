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
        int_series = pd.to_numeric(series, errors="coerce").fillna(-1).astype(int).astype(str)
        return int_series.map(mapping).fillna(series.astype(str).str.strip())

    if kind == "map":
        mapping = transform.get("map", {})
        return series.astype(str).str.strip().map(mapping).fillna(series.astype(str).str.strip())

    return series.astype(str).str.strip()


# ---------------------------------------------------------------------------
# Collect all columns referenced in the hierarchy (for pre-transformation)
# ---------------------------------------------------------------------------

def collect_hierarchy_columns(hierarchy):
    """Walk the hierarchy and collect all (column, category, transform) entries."""
    columns = []

    def walk(node):
        columns.append((node["column"], node["category"], node.get("transform")))
        for child in node.get("children", []):
            walk(child)

    for top in hierarchy.get("levels", []):
        walk(top)

    return columns


# ---------------------------------------------------------------------------
# Recursive tree building that respects branching
# ---------------------------------------------------------------------------

def build_tree(df, hierarchy):
    """
    Build the KPI tree by walking the hierarchy definition recursively.
    Supports split branches: nodes marked with "split": true are tagged
    in the output and their contributions are self-contained.
    """
    # Pre-transform all referenced columns
    all_columns = collect_hierarchy_columns(hierarchy)
    col_map = {}  # category -> transformed column name in df

    for column, category, transform in all_columns:
        col_name = f"_lvl_{category}"
        if col_name not in df.columns:
            df[col_name] = apply_transform_series(df[column], transform)
        col_map[category] = col_name

    # Root aggregation
    total_num = int(df["num"].sum())
    total_den = int(df["den"].sum())

    root = {
        "id": "Nwk Sys",
        "name": "Nwk Sys",
        "category": "Enterprise",
        "type": "Goal",
        "path": "",
        "tier": 1,
        "num": total_num,
        "den": total_den,
        "baseline": 0,
        "goal": 0,
        "contribution": 1.0,
        "children": []
    }

    print("Building tree with branch support...")
    build_start = time.time()

    def build_level(parent_node, parent_df, hierarchy_nodes, tier):
        """
        For each hierarchy node at this level, aggregate the data,
        create tree nodes, and recurse into children.

        hierarchy_nodes: list of hierarchy definition dicts at this level
        parent_df: subset of the dataframe filtered to this parent's scope
        """
        # Count split branches for decimal tier assignment
        split_index = 0

        for h_node in hierarchy_nodes:
            category = h_node["category"]
            col_name = col_map[category]
            is_split = h_node.get("split", False)
            h_children = h_node.get("children", [])

            # Determine tier: primary gets integer, split gets decimal
            if is_split:
                split_index += 1
                node_tier = tier + split_index * 0.1
            else:
                node_tier = tier

            # Aggregate at this level
            agg = parent_df.groupby(col_name, sort=False).agg(
                num=("num", "sum"),
                den=("den", "sum")
            ).reset_index()

            for _, row in agg.iterrows():
                name = str(row[col_name])
                if not name or name.lower() == "nan":
                    continue

                num = int(row["num"])
                den = int(row["den"])

                node = {
                    "id": f"{category};{name}",
                    "name": name,
                    "category": category,
                    "tier": node_tier,
                    "type": "Goal",
                    "path": "",
                    "num": num,
                    "den": den,
                    "baseline": 0,
                    "goal": 0,
                    "contribution": 1.0,
                    "children": []
                }

                if is_split:
                    node["split"] = True

                parent_node["children"].append(node)

                # Recurse into this hierarchy node's children
                if h_children:
                    child_df = parent_df[parent_df[col_name] == name]
                    build_level(node, child_df, h_children, tier + 1)

    # Start from the top-level hierarchy nodes
    top_levels = hierarchy.get("levels", [])
    build_level(root, df, top_levels, 2)

    print(f"Tree built in {time.time() - build_start:.2f}s")
    return root


root = build_tree(df, HIERARCHY)


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def calculate_baselines(node):
    if node["den"] > 0:
        node["baseline"] = node["num"] / node["den"]
    else:
        node["baseline"] = 0

    node["goal"] = node["baseline"]

    for child in node["children"]:
        calculate_baselines(child)


def calculate_contributions(node):
    """
    Calculate contributions. For split branches, contribution is
    relative to the split group's total (siblings share the same parent den).
    Primary and split children are handled the same way — contribution =
    child.den / parent.den — but the QA validation will treat them differently.
    """
    children = node.get("children", [])
    if not children:
        return

    parent_den = node["den"]

    for child in children:
        if parent_den > 0:
            child["contribution"] = child["den"] / parent_den
        else:
            child["contribution"] = 0
        calculate_contributions(child)


def update_paths(node, parent_path=""):
    if parent_path:
        node["path"] = f"{parent_path}/{node['name']}"
    else:
        node["path"] = node["name"]

    for child in node["children"]:
        update_paths(child, node["path"])


calculate_baselines(root)
calculate_contributions(root)
update_paths(root)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(root, f, indent=4, ensure_ascii=False)

print(f"Created {OUTPUT_FILE}")
