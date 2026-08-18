"""
cascade.py - Goal Cascading Engine

Builds a KPI tree, applies goal targets from goals.csv, cascades stretch
proportionally to all descendants, and outputs the enriched tree + CSV.

The cascade distributes a parent's numerator improvement (num delta) to
children proportionally based on each child's num share. This means every
child gets the same percentage stretch as the parent, preserving relative
performance rankings.

Usage (standalone):
    python cascade.py

    Uses default paths: goals.csv, hierarchy.json, teradata_cache.parquet
    Outputs to: output/D0 2.0.json + output/D0 2.0_cascaded.csv

Usage (as library):
    from cascade import cascade
    cascade(goals_file=Path("goals.csv"),
            hierarchy_file=Path("hierarchies/D0 4.0.json"),
            cache_file=Path("teradata_cache.parquet"),
            output_file=Path("output/D0 4.0.json"))
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

CARRIER_ALIASES = {"ML": "DL", "DL": "DL", "DC": "DC"}


# ---------------------------------------------------------------------------
# Hierarchy helpers
# ---------------------------------------------------------------------------

def parse_levels(hierarchy):
    """Flatten hierarchy definition into an ordered list of level tuples.

    Walks the hierarchy tree depth-first and collects each level's metadata
    in the order they appear. Used for CSV column ordering and YTD computation.

    Args:
        hierarchy (dict): Hierarchy JSON with {"levels": [...]} structure.

    Returns:
        list[tuple]: Each tuple is (column, category, transform, split).
            - column (str): DataFrame column name (e.g. "ml_dc_1")
            - category (str): Logical category (e.g. "carrier")
            - transform (dict or None): Value transform spec
            - split (bool): Whether this level is a split branch
    """
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
    """Find a node in the tree by its 'id' field using depth-first search.

    Node IDs follow the format "category;name" (e.g. "carrier;DL", "system;sys").
    This is the primary method for locating goal target nodes.

    Args:
        node (dict): Root of the subtree to search.
        node_id (str): Target node ID to find.

    Returns:
        dict or None: The matching node, or None if not found.
    """
    if node["id"] == node_id:
        return node
    for child in node.get("children", []):
        result = find_node_by_id(child, node_id)
        if result:
            return result
    return None


def resolve_goal_target(node_name):
    """Resolve carrier aliases in goal target node names.

    The goals.csv may reference carriers by operational codes that differ
    from the tree's data values. This function maps them (e.g. "ML" → "DL").

    Args:
        node_name (str): Raw Node_Name from goals.csv (e.g. "carrier;ML").

    Returns:
        str: Resolved node ID (e.g. "carrier;DL"). Returns unchanged if
            no alias exists or format is invalid.
    """
    parts = node_name.split(";", 1)
    if len(parts) != 2:
        return node_name
    category, name = parts
    return f"{category};{CARRIER_ALIASES.get(name.upper(), name)}"


def cascade_goals(node):
    """Distribute a parent's num improvement to children proportionally.

    This is the core cascade algorithm. It takes the num delta (goal_num -
    baseline_num) from the parent and allocates it to each child based on
    that child's num share of the parent's baseline.

    Algorithm per child:
        contribution = child.num / parent._baseline_num
        child_goal_num = child.num + num_delta * contribution
        child.goal = child_goal_num / child.den

    This preserves uniform percentage stretch: if the parent has 5% stretch,
    every child also gets ~5% stretch (exact for num-proportional distribution).

    Args:
        node (dict): Anchor node that has _goal_num and _baseline_num set.
            Typically called on nodes marked via apply_goals_from_csv().

    Side effects:
        Sets on each child: _goal_num, _goal_den, _baseline_num, _baseline_den,
        _stretch, goal. Then recurses into each child.

    Notes:
        - Children with _goal_set=True are skipped (they have their own
          explicit goals and will cascade independently).
        - The contribution used here is NUM-based (child_num / parent_num),
          not the den-based contribution stored on tree nodes.
    """
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

        # IMPORTANT: This is the CASCADE contribution — NUM-BASED.
        # child.num / parent.baseline_num determines what share of the
        # parent's stretch each child receives.
        # This is DIFFERENT from the tree node's "contribution" field which
        # is DEN-BASED (child.den / parent.den) and represents volume share.
        # Num-based means higher-performing children get proportionally more
        # absolute stretch, preserving uniform percentage improvement.
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
    """Apply explicit goal values from the goals CSV to matching tree nodes.

    Iterates through each row in goals_df, resolves the node ID (with carrier
    alias handling), finds the node in the tree, and sets its goal values.

    Args:
        tree (dict): Root node of the KPI tree.
        goals_df (pd.DataFrame): Goals CSV with columns:
            Node_Name, Baseline, Baseline_Num, Baseline_Den, Stretch,
            KPI_Num, KPI_Den, Goal.

    Side effects:
        On each matched node, sets: baseline, num, den, goal, _goal_num,
        _goal_den, _baseline_num, _baseline_den, _goal_set, _stretch.

        Prints warnings for unmatched nodes.

    Notes:
        - Node_Name format: "category;name" (e.g. "carrier;ML")
        - Commas in numeric fields are stripped before parsing
        - Stretch is parsed from percentage string (e.g. "5%" → 0.05)
    """
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
    """Write cascaded goal_num values back into the 'num' field for consistency.

    After cascading, nodes have _goal_num (the target numerator) stored
    separately. This function copies it into 'num' so the final tree JSON
    reflects goal values rather than baseline values.

    Also syncs non-anchor parent nodes: if a parent wasn't an explicit goal
    target, its num is recalculated as the sum of its primary children's num.
    This keeps the tree internally consistent for rollup validation.

    Args:
        node (dict): Root node. Applies recursively to all descendants.
    """
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
    """Remove internal cascade working flags before JSON serialization.

    During cascading, nodes accumulate temporary fields prefixed with '_'
    (e.g. _goal_num, _baseline_num, _goal_set). These are implementation
    details not needed in the output file.

    Args:
        node (dict): Root node. Applies recursively to all descendants.

    Removed keys:
        _goal_set, _parent_baseline, _stretch, _goal_num, _goal_den,
        _baseline_num, _baseline_den.
    """
    for key in ("_goal_set", "_parent_baseline", "_stretch",
                "_goal_num", "_goal_den", "_baseline_num", "_baseline_den"):
        node.pop(key, None)
    for child in node.get("children", []):
        clean_flags(child)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def collect_goal_table(node, levels, rows=None, ancestors=None, tier_offset=None, parent_baseline_num=None):
    """Flatten the tree into a list of row dicts for CSV export.

    Walks the tree depth-first, building one row per node with all ancestor
    dimension values filled in. This produces the cascaded summary table.

    Args:
        node (dict): Current node being processed.
        levels (list): From parse_levels(). Defines column order in output.
        rows (list or None): Accumulator for output rows. Pass None to start.
        ancestors (dict or None): Map of column→value from ancestor nodes.
            Used to fill in parent dimensions for each row.
        tier_offset (float or None): Subtracted from raw tier to produce
            relative tier numbering (auto-set from first node's tier - 1).
        parent_baseline_num (float or None): Parent's baseline numerator.
            Used to compute num-based contribution for each row.

    Returns:
        list[dict]: Flat list of row dicts. Each row contains:
            parent, node, tier, {dimension columns}, baseline, baseline_num,
            baseline_den, goal, stretch, contribution, num, den, source.

    Notes:
        - contribution in the CSV is num-based: child._baseline_num / parent_baseline_num.
          This differs from the tree node's den-based contribution field.
        - stretch is computed as: (goal - baseline_rate) / baseline_rate * 100
        - source is "Goal Input" for anchor nodes, "Cascaded" for derived nodes.
    """
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

    # Num-based contribution: child_baseline_num / parent_baseline_num
    if parent_baseline_num and parent_baseline_num > 0:
        contribution = bnum / parent_baseline_num
    else:
        contribution = node["contribution"]  # root node keeps 1.0

    row = {"parent": "/".join(current[col] for col, _, _, _ in levels if col in current and col != cat_to_col.get(node["category"], "?")),
           "node": node["name"],
           "tier": node["tier"] - tier_offset}

    for col, _, _, _ in levels:
        row[col] = current.get(col, "")

    row.update({
        "baseline": baseline_rate,
        "baseline_num": bnum, "baseline_den": bden,
        "goal": node["goal"], "stretch": stretch,
        "contribution": contribution,
        "num": node.get("_goal_num", node["num"]),
        "den": node.get("_goal_den", node["den"]),
        "source": "Goal Input" if node.get("_goal_set") else "Cascaded",
    })
    rows.append(row)

    for child in node.get("children", []):
        collect_goal_table(child, levels, rows, current, tier_offset, parent_baseline_num=bnum)
    return rows


# ---------------------------------------------------------------------------
# YTD computation
# ---------------------------------------------------------------------------

def compute_ytd(df, levels):
    """Add YTD (year-to-date) cumulative columns to the cascaded output.

    Computes cumulative numerator and denominator through the year for
    month-level rows, enabling YTD rate tracking against goals.

    Args:
        df (pd.DataFrame): Cascaded output table (from collect_goal_table).
        levels (list): From parse_levels(). Used to identify which columns
            come before/after month in the hierarchy.

    Returns:
        pd.DataFrame: Input df with 'YTD_Num' and 'YTD_Den' columns added.

    Logic:
        - Identifies month column (Mo_Nb) position in hierarchy.
        - Month-level rows (no deeper dims filled): cumulative sum of num/den
          grouped by parent key, sorted by month number.
        - Below-month rows (station, dom_int under a month): YTD = own value.
        - Non-month rows (carriers, system): YTD = full year value.
        - If Mo_Nb is not in the hierarchy, all rows get YTD = full year.
    """
    month_col = "Mo_Nb"

    # Columns before and after month in the hierarchy
    before_month, after_month = [], []
    found = False
    for col, _, _, _ in levels:
        if col == month_col:
            found = True
            continue
        (after_month if found else before_month).append(col)

    # If month column doesn't exist in the output, YTD = full year goal
    if month_col not in df.columns:
        df["YTD_Num"] = df["num"]
        df["YTD_Den"] = df["den"]
        return df

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
    """Run the full cascade pipeline: build tree, apply goals, cascade, export.

    This is the main entry point. It orchestrates the entire process from
    raw data to final output files.

    Args:
        goals_file (Path): Path to goals CSV file. Contains explicit goal
            targets for anchor nodes.
        hierarchy_file (Path): Path to hierarchy definition JSON. Defines
            the nesting structure of dimensions.
        cache_file (Path): Path to teradata_cache.parquet. The raw flight
            data used to build the tree.
        output_file (Path): Path for the output tree JSON. The cascaded CSV
            is written alongside it as {stem}_cascaded.csv.

    Returns:
        dict: Root node of the cascaded tree.

    Output files:
        - {output_file}: Tree JSON with cascaded goal values in every node.
        - {output_file.parent}/{output_file.stem}_cascaded.csv: Flat summary
          table with columns: KPI_Name, parent, node, Tier, {dimensions},
          Baseline, Baseline_Num, Baseline_Den, Goal, Stretch, Contribution,
          Goal_Num, Goal_Den, Source, Goal_Yr, YTD_Num, YTD_Den.

    Pipeline steps:
        1. Load hierarchy and parse levels
        2. Load parquet data
        3. build_tree() — construct base tree with baselines
        4. apply_goals_from_csv() — set explicit goals on anchor nodes
        5. cascade_goals() — distribute stretch to all descendants
        6. collect_goal_table() + compute_ytd() — build CSV output
        7. propagate_goal_nums() + clean_flags() — finalize tree
        8. Write JSON and CSV files
    """

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
    if "Mo_Nb" in out_df.columns:
        out_df["_month_sort"] = pd.to_numeric(out_df["Mo_Nb"], errors="coerce").fillna(0).astype(int)
    else:
        out_df["_month_sort"] = 0
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

    csv_dir = output_file.parent
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_path = csv_dir / f"{output_file.stem}_cascaded.csv"
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
