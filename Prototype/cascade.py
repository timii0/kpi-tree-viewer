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
    """Build the aggregated tree from flat data using groupby (vectorized)."""

    # Pre-transform all columns
    col_names = []
    for column, category, transform in levels:
        col_name = f"_lvl_{category}"
        df[col_name] = _apply_transform_series(df[column], transform)
        col_names.append(col_name)

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

    # Pre-aggregate at every depth
    level_aggs = {}
    for depth in range(1, len(col_names) + 1):
        group_cols = col_names[:depth]
        agg = df.groupby(group_cols, sort=False).agg(
            num=("num", "sum"),
            den=("den", "sum")
        ).reset_index()
        level_aggs[depth] = agg

    def assemble_level(parent_node, parent_key, depth):
        if depth > len(col_names):
            return

        agg = level_aggs[depth]
        category = levels[depth - 1][1]
        col = col_names[depth - 1]

        # Filter to rows matching parent key
        if parent_key:
            mask = pd.Series(True, index=agg.index)
            for i, val in enumerate(parent_key):
                mask = mask & (agg[col_names[i]] == val)
            subset = agg[mask]
        else:
            subset = agg

        # Get unique values at this level
        unique_at_level = subset.groupby(col, sort=False).agg(
            num=("num", "sum"),
            den=("den", "sum")
        ).reset_index()

        for _, row in unique_at_level.iterrows():
            name = str(row[col])
            if not name or name.lower() == "nan":
                continue

            node = {
                "id": f"{category};{name}",
                "name": name,
                "category": category,
                "tier": 0,
                "type": "Goal",
                "path": "",
                "num": int(row["num"]),
                "den": int(row["den"]),
                "baseline": 0,
                "goal": 0,
                "contribution": 1.0,
                "children": []
            }

            parent_node["children"].append(node)
            child_key = parent_key + (name,) if parent_key else (name,)
            assemble_level(node, child_key, depth + 1)

    assemble_level(root, (), 1)

    # Post-processing
    _update_tiers(root)
    _calculate_baselines(root)
    _calculate_contributions(root)
    _update_paths(root)

    return root


def _apply_transform_series(series, transform):
    """Apply a transform to an entire pandas Series (vectorized)."""
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


def cascade_goals(node):
    """
    Cascade goals down the tree. Every node gets:
      - 5% stretch applied to its rate
      - Den grows proportionally with the anchor's den growth factor
        (goal_den / baseline_den from the anchor)
      - goal_num = goal_rate * goal_den
    """
    children = node.get("children", [])

    if not children:
        return

    baseline_den = node.get("_baseline_den", node["den"])
    goal_den_parent = node.get("_goal_den", node["den"])
    stretch = node.get("_stretch", 0.05)

    # Den growth factor from this node's anchor numbers
    den_growth = goal_den_parent / baseline_den if baseline_den > 0 else 1.0

    for child in children:
        # Skip children that have their own explicit goal
        if child.get("_goal_set"):
            continue

        child_baseline_num = child["num"]
        child_baseline_den = child["den"]
        child_baseline_rate = child_baseline_num / child_baseline_den if child_baseline_den > 0 else 0

        # Apply stretch to rate, grow den by anchor's growth factor
        child_goal_rate = child_baseline_rate * (1 + stretch)
        child_goal_den = child_baseline_den * den_growth
        child_goal_num = child_goal_rate * child_goal_den

        # Contribution = child_baseline_den / parent_baseline_den
        child_contribution = child_baseline_den / baseline_den if baseline_den > 0 else 0

        # Store for recursion and output
        child["_goal_num"] = child_goal_num
        child["_goal_den"] = child_goal_den
        child["_baseline_num"] = child_baseline_num
        child["_baseline_den"] = child_baseline_den
        child["_stretch"] = stretch
        child["goal"] = child_goal_rate
        child["contribution"] = child_contribution

        # Recurse
        cascade_goals(child)


def parse_stretch(stretch_str):
    """Parse stretch value like '5%' into a decimal (0.05)."""
    s = str(stretch_str).strip().replace("%", "")
    return float(s) / 100.0


def apply_goals_from_csv(tree, goals_df):
    """
    Apply explicit goals from the input CSV to matching nodes in the tree.
    
    The anchor node:
    - Baseline, Baseline_Num, Baseline_Den from CSV
    - KPI_Num / KPI_Den represent the GOAL num/den
    - Delta for both num and den is cascaded down proportionally
    """
    for _, row in goals_df.iterrows():
        node_name = str(row["Node_Name"]).strip()
        baseline_value = float(row["Baseline"]) / 100.0
        stretch = parse_stretch(row["Stretch"])
        baseline_num = int(str(row["Baseline_Num"]).replace(",", ""))
        baseline_den = int(str(row["Baseline_Den"]).replace(",", ""))
        goal_num = int(str(row["KPI_Num"]).replace(",", ""))
        goal_den = int(str(row["KPI_Den"]).replace(",", ""))

        # Resolve aliases
        node_id = resolve_goal_target(node_name)
        target_node = find_node_by_id(tree, node_id)

        if target_node:
            # CSV is truth for the anchor node
            target_node["baseline"] = baseline_value
            target_node["num"] = goal_num
            target_node["den"] = goal_den
            target_node["_goal_num"] = goal_num
            target_node["_goal_den"] = goal_den
            target_node["_baseline_num"] = baseline_num
            target_node["_baseline_den"] = baseline_den
            target_node["goal"] = goal_num / goal_den if goal_den > 0 else 0
            target_node["_goal_set"] = True
            target_node["_stretch"] = stretch

            num_delta = goal_num - baseline_num
            den_delta = goal_den - baseline_den
            print(f"  Set goal on '{target_node['name']}' "
                  f"(id={node_id}): baseline={baseline_value:.4f}, "
                  f"goal={target_node['goal']:.4f}, stretch={stretch:.2%}")
            print(f"    baseline_num={baseline_num:,}, goal_num={goal_num:,}, "
                  f"num_delta={num_delta:,}")
            print(f"    baseline_den={baseline_den:,}, goal_den={goal_den:,}, "
                  f"den_delta={den_delta:,}")
        else:
            print(f"  WARNING: Could not find node for '{node_name}' "
                  f"(resolved to '{node_id}')")


def clean_internal_flags(node):
    """Remove internal flags used during cascading."""
    node.pop("_goal_set", None)
    node.pop("_parent_baseline", None)
    node.pop("_stretch", None)
    node.pop("_goal_num", None)
    node.pop("_goal_den", None)
    node.pop("_baseline_num", None)
    node.pop("_baseline_den", None)
    for child in node.get("children", []):
        clean_internal_flags(child)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def collect_goal_table(node, rows=None, ancestors=None, levels=None, tier_offset=None):
    """Flatten the tree into a table showing cascaded goals.
    
    Each row has a column for every hierarchy level (using the source
    column name from the query), filled with the ancestor value at that
    level (showing context of where the node sits).
    """
    if rows is None:
        rows = []
    if ancestors is None:
        ancestors = {}
    if levels is None:
        levels = []
    if tier_offset is None:
        # First call — calculate offset so this node becomes tier 1
        tier_offset = node["tier"] - 1

    # Build a category -> column name lookup
    cat_to_col = {cat: col for col, cat, _ in levels}

    # Update ancestors dict with this node's category (keyed by column name)
    current_ancestors = dict(ancestors)
    if node["category"] in cat_to_col:
        current_ancestors[cat_to_col[node["category"]]] = node["name"]

    # Build path from ancestor values in order
    path_parts = [
        current_ancestors[col]
        for col, _, _ in levels
        if col in current_ancestors
    ]
    path = "/".join(path_parts)
    parent_path = "/".join(path_parts[:-1]) if len(path_parts) > 1 else ""
    node_name = path_parts[-1] if path_parts else ""

    # Build row with a column for each hierarchy level (using query column names)
    row = {
        "parent": parent_path,
        "node": node_name,
        "tier": node["tier"] - tier_offset,
    }

    for col, _, _ in levels:
        row[col] = current_ancestors.get(col, "")

    row.update({
        "baseline": (
            node.get("_baseline_num", node["num"]) / node.get("_baseline_den", node["den"])
            if node.get("_baseline_den", node["den"]) > 0
            else node["baseline"]
        ),
        "baseline_num": node.get("_baseline_num", node["num"]),
        "baseline_den": node.get("_baseline_den", node["den"]),
        "goal": node["goal"],
        "stretch": (
            (node["goal"] - (
                node.get("_baseline_num", node["num"]) / node.get("_baseline_den", node["den"])
                if node.get("_baseline_den", node["den"]) > 0 else node["baseline"]
            )) / (
                node.get("_baseline_num", node["num"]) / node.get("_baseline_den", node["den"])
                if node.get("_baseline_den", node["den"]) > 0 else node["baseline"]
            ) * 100
            if (node.get("_baseline_den", node["den"]) > 0 and
                node.get("_baseline_num", node["num"]) > 0)
            else 0
        ),
        "contribution": node["contribution"],
        "num": node.get("_goal_num", node["num"]),
        "den": node.get("_goal_den", node["den"]),
    })

    rows.append(row)

    for child in node.get("children", []):
        collect_goal_table(child, rows, current_ancestors, levels, tier_offset)

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

    # Cascade goals down — process anchors top-down (by tier)
    # Higher-level anchors cascade first, skipping children that have their own goals
    print("\nCascading goals (distributing goal num proportionally)...")

    # Collect all anchor nodes sorted by tier (top-down)
    anchors = []
    for _, row in goals_df.iterrows():
        node_name = str(row["Node_Name"]).strip()
        node_id = resolve_goal_target(node_name)
        anchor = find_node_by_id(tree, node_id)
        if anchor:
            anchors.append(anchor)

    anchors.sort(key=lambda n: n.get("tier", 0))

    for anchor in anchors:
        cascade_goals(anchor)

    # Write output (clean flags first for the JSON)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Export cascaded goals as CSV BEFORE cleaning flags
    # (we need _goal_num for the output)
    # Include all anchor nodes and their descendants
    kpi_name = goals_df["KPI_Name"].iloc[0]
    anchor_rows = []

    # Find the top-most anchor and collect from there
    top_anchor = anchors[0] if anchors else None
    if top_anchor:
        anchor_rows.extend(
            collect_goal_table(top_anchor, levels=levels)
        )

    all_goals_df = pd.DataFrame(anchor_rows)

    # Sort by parent then node (tree order)
    all_goals_df = all_goals_df.sort_values(["parent", "node"]).reset_index(drop=True)

    # Compute YTD actuals (Jan-May 2026) from the parquet
    current_year = int(df["Yr_Nb"].max())
    ytd_df = df[df["Yr_Nb"] == current_year].copy()

    # Build YTD lookup by computing a path key for each row
    # Transform columns the same way as the tree builder
    col_names = []
    for column, category, transform in levels:
        col_name = f"_lvl_{category}"
        if col_name not in ytd_df.columns:
            ytd_df = ytd_df.copy()
            ytd_df[col_name] = _apply_transform_series(ytd_df[column], transform)
        col_names.append(col_name)

    # Aggregate YTD at every depth and build a path -> (num, den) lookup
    ytd_lookup = {}

    # For each depth, group by all columns up to that depth
    for depth in range(1, len(col_names) + 1):
        group_cols = col_names[:depth]
        agg = ytd_df.groupby(group_cols, sort=False).agg(
            ytd_num=("num", "sum"),
            ytd_den=("den", "sum")
        ).reset_index()

        for _, agg_row in agg.iterrows():
            path_key = "/".join(str(agg_row[c]) for c in group_cols)
            ytd_lookup[path_key] = (int(agg_row["ytd_num"]), int(agg_row["ytd_den"]))

    # Build path for each row in output to match against ytd_lookup
    def build_full_path(row):
        parts = []
        for col, _, _ in levels:
            val = row.get(col, "")
            if val and str(val).strip():
                parts.append(str(val))
            else:
                break
        return "/".join(parts)

    all_goals_df["_full_path"] = all_goals_df.apply(build_full_path, axis=1)
    all_goals_df["Goal_Yr"] = 2027
    all_goals_df["YTD_Yr"] = current_year
    all_goals_df["YTD_Num"] = all_goals_df["_full_path"].map(
        lambda p: ytd_lookup.get(p, (0, 0))[0]
    )
    all_goals_df["YTD_Den"] = all_goals_df["_full_path"].map(
        lambda p: ytd_lookup.get(p, (0, 0))[1]
    )
    all_goals_df.drop(columns=["_full_path"], inplace=True)

    # Build export with KPI_Name prepended
    all_goals_df.insert(0, "KPI_Name", kpi_name)

    # Format stretch as percentage string
    all_goals_df["stretch"] = all_goals_df["stretch"].apply(
        lambda x: f"{x:.2f}%"
    )
    # Round baseline and goal to 2 decimal places (as %)
    all_goals_df["baseline"] = (all_goals_df["baseline"] * 100).round(2)
    all_goals_df["goal"] = (all_goals_df["goal"] * 100).round(2)
    # Round num/den columns
    all_goals_df["baseline_num"] = all_goals_df["baseline_num"].round(0).astype(int)
    all_goals_df["baseline_den"] = all_goals_df["baseline_den"].round(0).astype(int)
    all_goals_df["num"] = all_goals_df["num"].round(0).astype(int)
    all_goals_df["den"] = all_goals_df["den"].round(0).astype(int)

    # Rename columns for output clarity
    all_goals_df = all_goals_df.rename(columns={
        "baseline": "Baseline",
        "baseline_num": "Baseline_Num",
        "baseline_den": "Baseline_Den",
        "goal": "Goal",
        "stretch": "Stretch",
        "contribution": "Contribution",
        "num": "KPI_Num",
        "den": "KPI_Den",
        "tier": "Tier",
    })

    CASCADED_CSV_DIR.mkdir(parents=True, exist_ok=True)
    csv_output_path = CASCADED_CSV_DIR / f"{kpi_name}_cascaded.csv"
    all_goals_df.to_csv(csv_output_path, index=False)
    print(f"Wrote cascaded CSV to {csv_output_path}")

    # Now clean internal flags and write JSON
    clean_internal_flags(tree)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(tree, f, indent=4, ensure_ascii=False)

    print(f"Wrote cascaded tree to {output_file}")

    # Print summary table
    display_df = all_goals_df[all_goals_df["Tier"] <= 5].head(20).copy()

    print(f"\n{'=' * 80}")
    print("CASCADED GOALS SUMMARY")
    print("=" * 80)
    print(display_df.to_string(index=False))

    return tree


if __name__ == "__main__":
    cascade()
