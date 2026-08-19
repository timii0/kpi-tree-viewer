"""
converter.py - Build KPI tree from parquet data + hierarchy definition.

This module provides the core tree-building logic used by cascade.py.
It reads a flat DataFrame (from teradata_cache.parquet) and a hierarchy
definition (JSON), then constructs a nested tree where each level groups
data by a dimension column.

Usage (standalone):
    python converter.py --hierarchy hierarchy.json --output output/my_kpi.json

When imported:
    from converter import build_tree, apply_transform_series
"""

import pandas as pd
import json
from pathlib import Path
import time

OUTPUT_FILE = Path("output") / "output.json"
HIERARCHY_FILE = Path("hierarchy.json")
CACHE_FILE = Path("teradata_cache.parquet")


def apply_transform_series(series, transform):
    """Apply a value transform to a pandas Series before tree grouping.

    Transforms convert raw column values into display-friendly labels.
    Called once per hierarchy column during tree construction.

    Args:
        series (pd.Series): Raw column data from the DataFrame.
        transform (dict or None): Transform specification. If None, simply
            strips whitespace and casts to string.

    Transform types:
        - "int_flag": Casts to int then maps via {"1": "Label", "0": "Label"}.
          Used for binary indicators like first_flt_ind.
        - "map": Direct string-to-string mapping via a dict.
          Unmapped values pass through unchanged.

    Returns:
        pd.Series: Transformed string values ready for groupby.

    Example:
        >>> transform = {"type": "int_flag", "map": {"1": "First Flight", "0": "Not First Flight"}}
        >>> apply_transform_series(df["frst_flt_ind"], transform)
    """
    if not transform:
        return series.astype(str).str.strip()
    kind = transform.get("type")
    if kind == "int_flag":
        m = transform.get("map", {})
        return pd.to_numeric(series, errors="coerce").fillna(-1).astype(int).astype(str).map(m).fillna(series.astype(str).str.strip())
    if kind == "map":
        m = transform.get("map", {})
        return series.astype(str).str.strip().map(m).fillna(series.astype(str).str.strip())
    return series.astype(str).str.strip()


def build_tree(df, hierarchy):
    """Build a complete KPI tree from a DataFrame and hierarchy definition.

    This is the primary tree construction function. It creates a nested dict
    structure where each level corresponds to a hierarchy dimension. The root
    node represents the system total (sum of all num/den).

    Args:
        df (pd.DataFrame): Flat data with at minimum 'num' and 'den' columns,
            plus all dimension columns referenced in the hierarchy (e.g. sys,
            ml_dc_1, ml_dc_2, station, fleet, etc.).
        hierarchy (dict): Hierarchy definition with structure:
            {"levels": [{"column": "sys", "category": "system", "children": [...]}]}

    Returns:
        dict: Root node of the tree. Structure per node:
            {
                "id": "category;name",
                "name": str,
                "category": str,
                "type": "Goal",
                "tier": float,          # Integer for primary, X.1/X.2 for splits
                "num": int,
                "den": int,
                "baseline": float,      # num/den
                "goal": float,          # Same as baseline (no goals applied here)
                "contribution": float,  # child.den / parent.den
                "path": str,            # Slash-separated from root
                "children": list,
                "split": bool           # Only present if True
            }

    Processing steps:
        1. prepare_columns: Pre-transforms all hierarchy columns on the DataFrame
        2. build_level: Recursive groupby at each hierarchy depth
        3. calc_baselines: Sets baseline = num/den for every node
        4. calc_contributions: Sets contribution = child.den / parent.den
        5. set_paths: Builds slash-separated path strings

    Notes:
        - The first hierarchy level is treated as the root (sys). Its children
          define the actual tree branching starting at tier 2.
        - Split branches get tier offsets (.1, .2, etc.) that propagate to
          all descendants of that split.
        - contribution is den-based. To change to num-based, modify
          calc_contributions() (see DEVELOPER_GUIDE.MD).
    """

    # Pre-transform all columns referenced in the hierarchy
    col_map = {}  # category -> transformed column name

    def prepare_columns(node):
        col_name = f"_lvl_{node['category']}"
        if col_name not in df.columns:
            df[col_name] = apply_transform_series(df[node["column"]], node.get("transform"))
        col_map[node["category"]] = col_name
        for child in node.get("children", []):
            prepare_columns(child)

    for top in hierarchy.get("levels", []):
        prepare_columns(top)

    # Root = totals (sys level)
    root = {
        "id": "system;sys", "name": "sys", "category": "system",
        "type": "Goal", "path": "", "tier": 1,
        "num": int(df["num"].sum()), "den": int(df["den"].sum()),
        "baseline": 0, "goal": 0, "contribution": 1.0, "children": []
    }

    def build_level(parent, parent_df, h_nodes, tier, split_offset=0):
        split_idx = 0
        for h_node in h_nodes:
            cat = h_node["category"]
            col = col_map[cat]
            is_split = h_node.get("split", False)
            h_children = h_node.get("children", [])

            if is_split:
                split_idx += 1
                node_tier = tier + split_idx * 0.1
                child_offset = split_idx * 0.1
            else:
                node_tier = tier + split_offset
                child_offset = split_offset

            agg = parent_df.groupby(col, sort=False).agg(
                num=("num", "sum"), den=("den", "sum")).reset_index()

            for _, row in agg.iterrows():
                name = str(row[col])
                if not name or name.lower() == "nan":
                    continue
                node = {
                    "id": f"{cat};{name}", "name": name, "category": cat,
                    "tier": node_tier, "type": "Goal", "path": "",
                    "num": int(row["num"]), "den": int(row["den"]),
                    "baseline": 0, "goal": 0, "contribution": 1.0, "children": []
                }
                if is_split:
                    node["split"] = True
                parent["children"].append(node)
                if h_children:
                    build_level(node, parent_df[parent_df[col] == name], h_children, tier + 1, child_offset)

    # Start from first level's children (root IS the first level)
    top = hierarchy.get("levels", [])
    if top and top[0].get("children"):
        build_level(root, df, top[0]["children"], 2)

    # Post-processing
    def calc_baselines(n):
        n["baseline"] = n["num"] / n["den"] if n["den"] > 0 else 0
        n["goal"] = n["baseline"]
        for c in n["children"]:
            calc_baselines(c)

    def calc_contributions(n):
        # IMPORTANT: This sets the DISPLAY contribution on tree nodes.
        # It is DEN-BASED: child.den / parent.den (volume share).
        # This is DIFFERENT from the cascade's stretch allocation which
        # uses NUM-BASED: child.num / parent.num (performance share).
        # See cascade.py → cascade_goals() for the other calculation.
        if not n.get("children"):
            return
        pden = n["den"]
        for c in n["children"]:
            c["contribution"] = c["den"] / pden if pden > 0 else 0
            calc_contributions(c)

    def set_paths(n, pp=""):
        n["path"] = f"{pp}/{n['name']}" if pp else n["name"]
        for c in n["children"]:
            set_paths(c, n["path"])

    calc_baselines(root)
    calc_contributions(root)
    set_paths(root)
    return root


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build KPI tree from parquet + hierarchy")
    parser.add_argument("--hierarchy", type=Path, default=HIERARCHY_FILE,
                        help="Path to hierarchy JSON (default: hierarchy.json)")
    parser.add_argument("--cache", type=Path, default=CACHE_FILE,
                        help="Path to parquet cache (default: teradata_cache.parquet)")
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE,
                        help="Path for output tree JSON (default: output/output.json)")
    args = parser.parse_args()

    start = time.time()
    df = pd.read_parquet(args.cache)
    print(f"Loaded {len(df):,} rows in {time.time() - start:.2f}s")

    with open(args.hierarchy, "r", encoding="utf-8") as f:
        hierarchy = json.load(f)

    t0 = time.time()
    root = build_tree(df, hierarchy)
    print(f"Tree built in {time.time() - t0:.2f}s")

    args.output.parent.mkdir(exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(root, f, indent=4, ensure_ascii=False)
    print(f"Wrote {args.output}")
