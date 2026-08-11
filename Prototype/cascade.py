"""
cascade.py - Goal Cascading Engine

Takes cascading instructions (goal inputs), the hierarchy definition,
and the raw data cache, then cascades goals down the tree proportionally
based on each node's contribution to its parent.

Usage:
    python cascade.py

Inputs:
    - goals.csv         : Goals received (KPI_Name, Node_Name, Baseline, Stretch, etc.)
    - hierarchy.json    : Hierarchy definition engine
    - teradata_cache.parquet : Raw data for building the tree

Output:
    - output/cascaded_goals.json : Full tree with cascaded goals
    - Prints a summary table of cascaded goals
"""

import pandas as pd
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GOALS_FILE = Path("goals.csv")
HIERARCHY_FILE = Path("hierarchy.json")
CACHE_FILE = Path("teradata_cache.parquet")
OUTPUT_FILE = Path("output") / "D0 2.0.json"
CASCADED_CSV_DIR = Path("cascaded_output")

# Mapping of known aliases in goal inputs to actual data values
# "ML" in goal input means "DL" in the data
CARRIER_ALIASES = {
    "ML": "DL",
    "DL": "DL",
    "DC": "DC",
}


# ---------------------------------------------------------------------------
# Hierarchy parsing (shared logic with converter2.0)
# ---------------------------------------------------------------------------

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


def apply_transform(transform, raw_value):
    """Apply a transform rule from the hierarchy definition."""
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


# ---------------------------------------------------------------------------
# Tree building
# ---------------------------------------------------------------------------

def build_tree(df, levels):
    """Build the aggregated tree from flat data using the hierarchy levels."""

    root = {
        "id": "Nwk Sys",
        "name": "Nwk Sys",
        "category": "Enterprise",
        "type": "Goal",
        "path": "",
        "tier": 1,
        "num": 0,
        "den": 0,
        "baseline": 0,
        "goal": 0,
        "contribution": 1.0,
        "children": []
    }

    for _, row in df.iterrows():

        num = int(row["num"])
        den = int(row["den"])

        current = root
        current["num"] += num
        current["den"] += den

        for column, category, transform in levels:

            value = str(row[column]).strip()

            if not value or value.lower() == "nan":
                continue

            if transform:
                value = apply_transform(transform, row[column])

            current = _find_or_create(current, value, category)
            current["num"] += num
            current["den"] += den

    # Post-processing
    _update_tiers(root)
    _calculate_baselines(root)
    _calculate_contributions(root)
    _update_paths(root)

    return root


def _find_or_create(parent, name, category):
    """Find existing child or create a new node."""
    for child in parent["children"]:
        if child["name"] == name and child["category"] == category:
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

    parent["children"].append(node)
    return node


def _update_tiers(node, tier=1):
    node["tier"] = tier
    for child in node["children"]:
        _update_tiers(child, tier + 1)


def _calculate_baselines(node):
    if node["den"] > 0:
        node["baseline"] = node["num"] / node["den"]
    else:
        node["baseline"] = 0

    node["goal"] = node["baseline"]

    for child in node["children"]:
        _calculate_baselines(child)


def _calculate_contributions(node):
    children = node.get("children", [])
    if not children:
        return

    parent_den = node["den"]

    for child in children:
        if parent_den > 0:
            child["contribution"] = child["den"] / parent_den
        else:
            child["contribution"] = 0
        _calculate_contributions(child)


def _update_paths(node, parent_path=""):
    if parent_path:
        node["path"] = f"{parent_path}/{node['name']}"
    else:
        node["path"] = node["name"]

    for child in node["children"]:
        _update_paths(child, node["path"])


# ---------------------------------------------------------------------------
# Goal cascading
# ---------------------------------------------------------------------------

def find_node_by_id(node, node_id):
    """Find a node in the tree by its id (category;name format)."""
    if node["id"] == node_id:
        return node

    for child in node.get("children", []):
        result = find_node_by_id(child, node_id)
        if result:
            return result

    return None


def resolve_goal_target(node_name):
    """
    Resolve a goal target node_name like 'carrier;ML' into the
    actual node id used in the tree (e.g. 'carrier;DL').
    """
    parts = node_name.split(";", 1)
    if len(parts) != 2:
        return node_name

    category, name = parts
    resolved_name = CARRIER_ALIASES.get(name.upper(), name)
    return f"{category};{resolved_name}"


def cascade_goals(node, stretch=None):
    """
    Cascade goals down the tree using the stretch % from the anchor node.

    The anchor node (set from goals.csv) defines the stretch.
    All descendants get:  goal = child_baseline * (1 + stretch)

    This means every node under the anchor improves by the same
    relative stretch percentage.

    Args:
        node: Current tree node
        stretch: The stretch ratio to apply (e.g. 0.05 for 5%)
    """
    # If this node has an explicit stretch from CSV, use it
    if node.get("_goal_set") and node.get("_stretch") is not None:
        stretch = node["_stretch"]

    # If we have a stretch to apply and this node wasn't explicitly set
    if stretch is not None and not node.get("_goal_set"):
        node["goal"] = node["baseline"] * (1 + stretch)

    # Cascade to children
    for child in node.get("children", []):
        cascade_goals(child, stretch)


def parse_stretch(stretch_str):
    """Parse stretch value like '5%' into a decimal (0.05)."""
    s = str(stretch_str).strip().replace("%", "")
    return float(s) / 100.0


def apply_goals_from_csv(tree, goals_df):
    """
    Apply explicit goals from the input CSV to matching nodes in the tree.
    The CSV is the truth source — baseline and goal override computed values.
    Mark those nodes so the cascade knows they are anchors.
    """
    for _, row in goals_df.iterrows():
        node_name = str(row["Node_Name"]).strip()
        goal_value = float(row["Goal"]) / 100.0  # Convert from % to ratio
        baseline_value = float(row["Baseline"]) / 100.0
        stretch = parse_stretch(row["Stretch"])

        # Resolve aliases
        node_id = resolve_goal_target(node_name)

        target_node = find_node_by_id(tree, node_id)

        if target_node:
            # CSV is truth: override baseline, goal, num, and den
            target_node["baseline"] = baseline_value
            target_node["goal"] = goal_value
            target_node["num"] = int(
                str(row["KPI_Num"]).replace(",", "")
            )
            target_node["den"] = int(
                str(row["KPI_Den"]).replace(",", "")
            )
            target_node["_goal_set"] = True
            target_node["_stretch"] = stretch
            print(f"  Set goal on '{target_node['name']}' "
                  f"(id={node_id}): baseline={baseline_value:.4f}, "
                  f"goal={goal_value:.4f}, stretch={stretch:.2%}, "
                  f"num={target_node['num']:,}, den={target_node['den']:,}")
        else:
            print(f"  WARNING: Could not find node for '{node_name}' "
                  f"(resolved to '{node_id}')")


def clean_internal_flags(node):
    """Remove internal flags used during cascading."""
    node.pop("_goal_set", None)
    node.pop("_parent_baseline", None)
    node.pop("_stretch", None)
    for child in node.get("children", []):
        clean_internal_flags(child)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def collect_goal_table(node, rows=None):
    """Flatten the tree into a table showing cascaded goals."""
    if rows is None:
        rows = []

    rows.append({
        "path": node["path"],
        "name": node["name"],
        "category": node["category"],
        "tier": node["tier"],
        "baseline": node["baseline"],
        "goal": node["goal"],
        "stretch": (
            (node["goal"] - node["baseline"]) / node["baseline"] * 100
            if node["baseline"] > 0 else 0
        ),
        "contribution": node["contribution"],
        "num": node["num"],
        "den": node["den"],
    })

    for child in node.get("children", []):
        collect_goal_table(child, rows)

    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def cascade(
    goals_file=GOALS_FILE,
    hierarchy_file=HIERARCHY_FILE,
    cache_file=CACHE_FILE,
    output_file=OUTPUT_FILE
):
    """
    Main cascading function.

    Args:
        goals_file: Path to CSV with goal inputs
        hierarchy_file: Path to hierarchy JSON definition
        cache_file: Path to parquet data cache
        output_file: Path for output JSON

    Returns:
        The enriched tree dict with cascaded goals
    """
    # Load hierarchy
    with open(hierarchy_file, "r", encoding="utf-8") as f:
        hierarchy = json.load(f)

    levels = parse_levels(hierarchy)

    # Load data
    df = pd.read_parquet(cache_file)
    print(f"Loaded {len(df):,} rows from {cache_file}")

    # Build tree
    tree = build_tree(df, levels)
    print(f"Built tree with root: {tree['name']}")

    # Load and apply goals
    goals_df = pd.read_csv(goals_file)
    print(f"\nApplying {len(goals_df)} goal(s) from {goals_file}:")
    apply_goals_from_csv(tree, goals_df)

    # Cascade goals down
    print("\nCascading goals (applying stretch to all descendants)...")
    cascade_goals(tree)

    # Clean up internal flags
    clean_internal_flags(tree)

    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(tree, f, indent=4, ensure_ascii=False)

    print(f"\nWrote cascaded tree to {output_file}")

    # Export cascaded goals as CSV (same format as goals.csv)
    # Only include the anchor node and its descendants
    kpi_name = goals_df["KPI_Name"].iloc[0]
    anchor_rows = []

    for _, row in goals_df.iterrows():
        node_name = str(row["Node_Name"]).strip()
        node_id = resolve_goal_target(node_name)
        anchor_node = find_node_by_id(tree, node_id)

        if anchor_node:
            anchor_rows.extend(collect_goal_table(anchor_node))

    all_goals_df = pd.DataFrame(anchor_rows)

    # Build output in the same format as goals.csv
    export_df = pd.DataFrame({
        "KPI_Name": kpi_name,
        "Node_Name": all_goals_df["category"] + ";" + all_goals_df["name"],
        "Baseline": (all_goals_df["baseline"] * 100).round(2),
        "Stretch": all_goals_df["stretch"].apply(lambda x: f"{x:.2f}%"),
        "KPI_Num": all_goals_df["num"],
        "KPI_Den": all_goals_df["den"],
        "Goal": (all_goals_df["goal"] * 100).round(2),
    })

    CASCADED_CSV_DIR.mkdir(parents=True, exist_ok=True)
    csv_output_path = CASCADED_CSV_DIR / f"{kpi_name}_cascaded.csv"
    export_df.to_csv(csv_output_path, index=False)
    print(f"Wrote cascaded CSV to {csv_output_path}")

    # Print summary table
    summary_df = all_goals_df.copy()

    # Show only first few tiers for readability
    display_df = summary_df[summary_df["tier"] <= 4].copy()
    display_df["baseline"] = display_df["baseline"].apply(
        lambda x: f"{x:.2%}"
    )
    display_df["goal"] = display_df["goal"].apply(
        lambda x: f"{x:.2%}"
    )
    display_df["stretch"] = display_df["stretch"].apply(
        lambda x: f"{x:+.2f}%"
    )
    display_df["contribution"] = display_df["contribution"].apply(
        lambda x: f"{x:.2%}"
    )

    print("\n" + "=" * 80)
    print("CASCADED GOALS SUMMARY (tiers 1-4)")
    print("=" * 80)
    print(
        display_df[
            ["name", "category", "tier", "baseline", "goal", "stretch", "contribution"]
        ].to_string(index=False)
    )

    return tree


if __name__ == "__main__":
    cascade()
