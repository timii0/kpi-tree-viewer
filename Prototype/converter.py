"""
converter2.0.py - Build KPI tree from parquet data + hierarchy definition.

Usage:
    python converter2.0.py

Reads:  teradata_cache.parquet, hierarchy.json
Writes: output/D0 2.0.json
"""

import pandas as pd
import json
from pathlib import Path
import time

OUTPUT_FILE = Path("output") / "D0 2.0.json"
HIERARCHY_FILE = Path("hierarchy.json")
CACHE_FILE = Path("teradata_cache.parquet")


def apply_transform_series(series, transform):
    """Vectorized transform on a pandas Series."""
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
    """Build KPI tree from dataframe + hierarchy definition.
    Root = sys (first hierarchy level). Children built from level's children."""

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

    def build_level(parent, parent_df, h_nodes, tier):
        split_idx = 0
        for h_node in h_nodes:
            cat = h_node["category"]
            col = col_map[cat]
            is_split = h_node.get("split", False)
            h_children = h_node.get("children", [])

            node_tier = tier + (split_idx := split_idx + 1) * 0.1 if is_split else tier

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
                    build_level(node, parent_df[parent_df[col] == name], h_children, tier + 1)

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
    start = time.time()
    df = pd.read_parquet(CACHE_FILE)
    print(f"Loaded {len(df):,} rows in {time.time() - start:.2f}s")

    with open(HIERARCHY_FILE, "r", encoding="utf-8") as f:
        hierarchy = json.load(f)

    t0 = time.time()
    root = build_tree(df, hierarchy)
    print(f"Tree built in {time.time() - t0:.2f}s")

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(root, f, indent=4, ensure_ascii=False)
    print(f"Wrote {OUTPUT_FILE}")
