"""
cascade.py - Goal Cascading Engine

Builds a KPI tree, applies goal targets from goals.csv, cascades stretch
proportionally to all descendants, and outputs the enriched tree + CSV.

Usage:
    python cascade.py

Inputs:
    - goals.csv              : Goal targets per anchor node
    - hierarchy.json         : Hierarchy definition (nesting + transforms)
    - teradata_cache.parquet : Raw data

Output:
    - output/D0 2.0.json             : Tree with cascaded goals
    - cascaded_output/D0_cascaded.csv : Flat summary with YTD expectations
"""

import pandas as pd
import json
from pathlib import Path

# Re-use tree building from converter
from converter import build_tree, apply_transform_series

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GOALS_FILE = Path("goals.csv")
HIERARCHY_FILE = Path("hierarchy.json")
CACHE_FILE = Path("teradata_cache.parquet")
OUTPUT_FILE = Path("output") / "D0 2.0.json"
CASCADED_CSV_DIR = Path("cascaded_output")

CARRIER_ALIASES = {"ML": "DL", "DL": "DL", "DC": "DC"}


# ---------------------------------------------------------------------------
# Hierarchy helpers
# ---------------------------------------------------------------------------

def parse_levels(hierarchy):
    """Flatten hierarchy into ordered (column, category, transform, split) tuples."""
    levels = []

    def walk(node):
        levels.append((node["column"], node["category"], node.get("transform"), node.get("split", False)))
        for child in node.get("children", []):
            walk(child)

    for top in hierarchy.get("levels", []):
        walk(top)
    return levels


# ---------------------------------------------------------------------------
# Goal cascading
# ---------------------------------------------------------------------------

def find_node_by_id(node, node_id):
    """Find a node by its id field (depth-first)."""
    if node["id"] == node_id:
        return node
    for child in node.get("children", []):
        result = find_node_by_id(child, node_id)
        if result:
            return result
    return None


def resolve_goal_target(node_name):
    """Resolve alias: 'carrier;ML' -> 'carrier;DL'."""
    parts = node_name.split(";", 1)
    if len(parts) != 2:
        return node_name
    category, name = parts
    return f"{category};{CARRIER_ALIASES.get(name.upper(), name)}"


def cascade_goals(node):
    """Distribute parent's num delta to children proportionally by num share."""
    children = node.get("children", [])
    if not children:
        return

    parent_baseline_num = node.get("_baseline_num", node["num"])
    parent_goal_num = node.get("_goal_num", node["num"])
    num_delta = parent_goal_num - parent_baseline_num

    for child in children:
        if child.get("_goal_set"):
            continue

        cbn = child["num"]
        cbd = child["den"]
        cbr = cbn / cbd if cbd > 0 else 0
        contribution = cbn / parent_baseline_num if parent_baseline_num > 0 else 0

        child_goal_num = cbn + num_delta * contribution
        child_goal_rate = child_goal_num / cbd if cbd > 0 else 0

        child["_goal_num"] = child_goal_num
        child["_goal_den"] = cbd
        child["_baseline_num"] = cbn
        child["_baseline_den"] = cbd
        child["_stretch"] = (child_goal_rate - cbr) / cbr if cbr > 0 else 0
        child["goal"] = child_goal_rate

        cascade_goals(child)


def apply_goals_from_csv(tree, goals_df):
    """Apply explicit goals from CSV to matching tree nodes."""
    for _, row in goals_df.iterrows():
        node_id = resolve_goal_target(str(row["Node_Name"]).strip())
        target = find_node_by_id(tree, node_id)
        if not target:
            print(f"  WARNING: node '{row['Node_Name']}' not found (resolved: {node_id})")
            continue

        baseline_num = int(str(row["Baseline_Num"]).replace(",", ""))
        baseline_den = int(str(row["Baseline_Den"]).replace(",", ""))
        goal_num = int(str(row["KPI_Num"]).replace(",", ""))
        goal_den = int(str(row["KPI_Den"]).replace(",", ""))
        stretch = float(str(row["Stretch"]).strip().replace("%", "")) / 100.0

        target.update({
            "baseline": float(row["Baseline"]) / 100.0,
            "num": goal_num, "den": goal_den,
            "_goal_num": goal_num, "_goal_den": goal_den,
            "_baseline_num": baseline_num, "_baseline_den": baseline_den,
            "goal": goal_num / goal_den if goal_den > 0 else 0,
            "_goal_set": True, "_stretch": stretch,
        })
        print(f"  Set goal: {target['name']} baseline_num={baseline_num:,} "
              f"goal_num={goal_num:,} stretch={stretch:.2%}")


def propagate_goal_nums(node):
    """Write _goal_num back into num for consistent rollup."""
    if "_goal_num" in node:
        node["num"] = node["_goal_num"]
    for child in node.get("children", []):
        propagate_goal_nums(child)
    # Sync parent with children if not an anchor
    children = node.get("children", [])
    if children and "_goal_num" not in node and not node.get("_goal_set"):
        primary = [c for c in children if not c.get("split")]
        if primary and any("_goal_num" in c for c in primary):
            node["num"] = sum(c.get("num", 0) for c in primary)


def clean_flags(node):
    """Remove internal cascade flags."""
    for key in ("_goal_set", "_parent_baseline", "_stretch",
                "_goal_num", "_goal_den", "_baseline_num", "_baseline_den"):
        node.pop(key, None)
    for child in node.get("children", []):
        clean_flags(child)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def collect_goal_table(node, levels, rows=None, ancestors=None, tier_offset=None):
    """Flatten tree into rows for CSV export."""
    if rows is None:
        rows = []
    if ancestors is None:
        ancestors = {}
    if tier_offset is None:
        tier_offset = node["tier"] - 1

    cat_to_col = {cat: col for col, cat, _, _ in levels}
    current = dict(ancestors)
    if node["category"] in cat_to_col:
        current[cat_to_col[node["category"]]] = node["name"]

    # Compute baseline rate for stretch calc
    bnum = node.get("_baseline_num", node["num"])
    bden = node.get("_baseline_den", node["den"])
    baseline_rate = bnum / bden if bden > 0 else node["baseline"]
    stretch = ((node["goal"] - baseline_rate) / baseline_rate * 100) if baseline_rate > 0 else 0

    row = {"parent": "/".join(current[col] for col, _, _, _ in levels if col in current and col != cat_to_col.get(node["category"], "?")),
           "node": node["name"],
           "tier": node["tier"] - tier_offset}

    for col, _, _, _ in levels:
        row[col] = current.get(col, "")

    row.update({
        "baseline": baseline_rate,
        "baseline_num": bnum, "baseline_den": bden,
        "goal": node["goal"], "stretch": stretch,
        "contribution": node["contribution"],
        "num": node.get("_goal_num", node["num"]),
        "den": node.get("_goal_den", node["den"]),
        "source": "Goal Input" if node.get("_goal_set") else "Cascaded",
    })
    rows.append(row)

    for child in node.get("children", []):
        collect_goal_table(child, levels, rows, current, tier_offset)
    return rows


# ---------------------------------------------------------------------------
# YTD computation
# ---------------------------------------------------------------------------

def compute_ytd(df, levels):
    """Compute cumulative YTD goal expectations by month."""
    month_col = "Mo_Nb"

    # Columns before and after month in the hierarchy
    before_month, after_month = [], []
    found = False
    for col, _, _, _ in levels:
        if col == month_col:
            found = True
            continue
        (after_month if found else before_month).append(col)

    has_month = df[month_col].astype(str).str.strip() != ""

    if not has_month.any():
        df["YTD_Num"] = df["num"]
        df["YTD_Den"] = df["den"]
        return df

    with_month = df[has_month].copy()
    without_month = df[~has_month].copy()

    with_month["_month_int"] = pd.to_numeric(with_month[month_col], errors="coerce").fillna(0).astype(int)
    with_month["_pkey"] = with_month.apply(
        lambda r: "/".join(str(r[c]) for c in before_month if str(r[c]).strip()), axis=1)

    # Month-level = no deeper dimensions filled
    with_month["_is_month"] = with_month.apply(
        lambda r: all(str(r.get(c, "")).strip() == "" for c in after_month), axis=1)

    # Cumulative sum for month-level rows
    ml = with_month[with_month["_is_month"]].sort_values(["_pkey", "_month_int"]).copy()
    ml["YTD_Num"] = ml.groupby("_pkey")["num"].cumsum()
    ml["YTD_Den"] = ml.groupby("_pkey")["den"].cumsum()

    # Below-month rows: YTD = own goal
    bl = with_month[~with_month["_is_month"]].copy()
    bl["YTD_Num"] = bl["num"]
    bl["YTD_Den"] = bl["den"]

    # Without month: YTD = full year goal
    without_month["YTD_Num"] = without_month["num"]
    without_month["YTD_Den"] = without_month["den"]

    result = pd.concat([ml, bl, without_month]).sort_index()
    df["YTD_Num"] = result["YTD_Num"]
    df["YTD_Den"] = result["YTD_Den"]
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def cascade(
    goals_file=GOALS_FILE,
    hierarchy_file=HIERARCHY_FILE,
    cache_file=CACHE_FILE,
    output_file=OUTPUT_FILE
):
    """Run the full cascade pipeline: build tree, apply goals, cascade, export."""

    with open(hierarchy_file, "r", encoding="utf-8") as f:
        hierarchy = json.load(f)

    levels = parse_levels(hierarchy)
    df = pd.read_parquet(cache_file)
    print(f"Loaded {len(df):,} rows from {cache_file}")

    tree = build_tree(df, hierarchy)
    print(f"Built tree: root={tree['name']}")

    goals_df = pd.read_csv(goals_file)
    print(f"\nApplying {len(goals_df)} goal(s):")
    apply_goals_from_csv(tree, goals_df)

    # Cascade top-down by tier
    print("\nCascading...")
    anchors = []
    for _, row in goals_df.iterrows():
        node_id = resolve_goal_target(str(row["Node_Name"]).strip())
        anchor = find_node_by_id(tree, node_id)
        if anchor:
            anchors.append(anchor)
    anchors.sort(key=lambda n: n.get("tier", 0))
    for anchor in anchors:
        cascade_goals(anchor)

    # Export CSV (before cleaning flags)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    kpi_name = goals_df["KPI_Name"].iloc[0]

    top_anchor = anchors[0] if anchors else tree
    rows = collect_goal_table(top_anchor, levels)
    out_df = pd.DataFrame(rows)

    # Sort by tier, then month numerically, then node name
    out_df["_tier_sort"] = out_df["tier"]
    out_df["_month_sort"] = pd.to_numeric(out_df.get("Mo_Nb", ""), errors="coerce").fillna(0).astype(int)
    out_df = out_df.sort_values(["_tier_sort", "parent", "_month_sort", "node"]).reset_index(drop=True)
    out_df.drop(columns=["_tier_sort", "_month_sort"], inplace=True)

    # Add Goal_Yr and compute YTD
    out_df["Goal_Yr"] = 2027
    out_df = compute_ytd(out_df, levels)

    # Format for output
    out_df.insert(0, "KPI_Name", kpi_name)
    out_df["stretch"] = out_df["stretch"].apply(lambda x: f"{x:.2f}%")
    out_df["baseline"] = (out_df["baseline"] * 100).round(2)
    out_df["goal"] = (out_df["goal"] * 100).round(2)
    for c in ("baseline_num", "baseline_den", "num", "den"):
        out_df[c] = out_df[c].round(2)

    out_df = out_df.rename(columns={
        "baseline": "Baseline", "baseline_num": "Baseline_Num", "baseline_den": "Baseline_Den",
        "goal": "Goal", "stretch": "Stretch", "contribution": "Contribution",
        "num": "Goal_Num", "den": "Goal_Den", "tier": "Tier", "source": "Source",
    })

    CASCADED_CSV_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = CASCADED_CSV_DIR / f"{kpi_name}_cascaded.csv"
    out_df.to_csv(csv_path, index=False)
    print(f"Wrote {csv_path}")

    # Write tree JSON
    propagate_goal_nums(tree)
    clean_flags(tree)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(tree, f, indent=4, ensure_ascii=False)
    print(f"Wrote {output_file}")

    # Summary
    print(f"\n{'='*80}\nCASCADED GOALS SUMMARY\n{'='*80}")
    print(out_df[out_df["Tier"] <= 5].head(20).to_string(index=False))
    return tree


if __name__ == "__main__":
    cascade()
