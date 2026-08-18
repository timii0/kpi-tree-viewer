# Imports
import json
from pathlib import Path
import streamlit as st
import networkx as nx
import plotly.graph_objects as go
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("output")
HIERARCHIES_DIR = Path("hierarchies")

# ---------------------------------------------------------------------------
# Page config & styling
# ---------------------------------------------------------------------------

st.set_page_config(page_title="KPI Hierarchy", page_icon="assets/logo.png", layout="wide")

st.markdown("""<style>
.stApp { background-color: #001029; }
[data-testid="stSidebar"] { background-color: #003366; }
html, body, [class*="css"] { font-size: 21px; }
h1 { font-size: 3.5rem !important; }
h2, h3 { font-size: 2.2rem !important; }
[data-testid="stMetric"] { padding: 0; }
[data-testid="stMetricLabel"] { font-size: 1rem !important; font-weight: 600; }
[data-testid="stMetricValue"] { font-size: 2rem !important; font-weight: 700; }
.stButton button { font-size: 1.5rem; font-weight: 700; min-height: 2.5rem; }
.stTextInput label, .stSelectbox label { font-size: 0.95rem; font-weight: 600; }
button[data-baseweb="tab"] { font-size: 2rem; font-weight: 600; }
div[data-testid="stVerticalBlock"] { gap: 0.5rem; }
div[data-baseweb="select"] > div { background-color: #003366; color: white; }
div[data-testid="stExpander"] { background-color: #003366; }
summary { font-size: 1.15rem !important; font-weight: 700 !important; }
</style>""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_tree(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def load_parquet(path):
    return pd.read_parquet(path)


# ---------------------------------------------------------------------------
# Tree utilities
# ---------------------------------------------------------------------------


def build_path_index(node, index=None):
    if index is None:
        index = {}
    index[node["path"]] = node
    for child in node.get("children", []):
        build_path_index(child, index)
    return index


def count_nodes(node):
    return 1 + sum(count_nodes(c) for c in node.get("children", []))


def validate_contributions(node):
    issues = []
    children = node.get("children", [])
    if children:
        for group_name, group in [
            (node["name"], [c for c in children if not c.get("split")]),
            (f"{node['name']} (split)", [c for c in children if c.get("split")]),
        ]:
            if group:
                total = sum(c.get("contribution", 0) for c in group)
                if abs(total - 1.0) > 0.001:
                    issues.append({"node": group_name, "total": total})
    for child in children:
        issues.extend(validate_contributions(child))
    return issues


def validate_rollup(node):
    issues = []
    children = node.get("children", [])
    if children:
        primary = [c for c in children if not c.get("split")]
        if primary:
            child_sum = sum(c.get("num", 0) for c in primary)
            parent_num = node.get("num", 0)
            if parent_num > 0 and abs(child_sum - parent_num) > len(primary):
                issues.append({"type": "num_rollup", "node": node["name"],
                               "parent_num": parent_num, "children_num": child_sum,
                               "diff": child_sum - parent_num})
            ct = sum(c.get("contribution", 0) for c in primary)
            if abs(ct - 1.0) > 0.001:
                issues.append({"type": "contribution_sum", "node": node["name"], "total": ct})
    for child in children:
        issues.extend(validate_rollup(child))
    return issues



# ---------------------------------------------------------------------------
# Build tree from hierarchy (used by Hierarchy Builder)
# ---------------------------------------------------------------------------


def build_tree_from_hierarchy(df, hierarchy_def):
    """Build KPI tree from data + hierarchy definition. Root = first level."""

    def apply_transform(series, transform):
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

    # Collect all columns from hierarchy
    col_map = {}

    def collect(node):
        col_name = f"_lvl_{node['category']}"
        if col_name not in df.columns:
            df[col_name] = apply_transform(df[node["column"]], node.get("transform"))
        col_map[node["category"]] = col_name
        for child in node.get("children", []):
            collect(child)

    for top in hierarchy_def.get("levels", []):
        collect(top)

    # Build root from totals
    total_num = int(df["num"].sum())
    total_den = int(df["den"].sum())
    root = {
        "id": "system;sys", "name": "sys", "category": "system",
        "type": "Goal", "path": "", "tier": 1,
        "num": total_num, "den": total_den,
        "baseline": 0, "goal": 0, "contribution": 1.0, "children": []
    }

    def build_level(parent_node, parent_df, hierarchy_nodes, tier, split_offset=0):
        split_idx = 0
        for h_node in hierarchy_nodes:
            category = h_node["category"]
            col_name = col_map[category]
            is_split = h_node.get("split", False)
            h_children = h_node.get("children", [])

            if is_split:
                split_idx += 1
                node_tier = tier + split_idx * 0.1
                child_offset = split_idx * 0.1
            else:
                node_tier = tier + split_offset
                child_offset = split_offset

            agg = parent_df.groupby(col_name, sort=False).agg(
                num=("num", "sum"), den=("den", "sum")).reset_index()

            for _, row in agg.iterrows():
                name = str(row[col_name])
                if not name or name.lower() == "nan":
                    continue
                node = {
                    "id": f"{category};{name}", "name": name,
                    "category": category, "tier": node_tier,
                    "type": "Goal", "path": "",
                    "num": int(row["num"]), "den": int(row["den"]),
                    "baseline": 0, "goal": 0, "contribution": 1.0, "children": []
                }
                if is_split:
                    node["split"] = True
                parent_node["children"].append(node)
                if h_children:
                    build_level(node, parent_df[parent_df[col_name] == name], h_children, tier + 1, child_offset)

    # Start from the first level's CHILDREN (skip sys level since root IS sys)
    top_levels = hierarchy_def.get("levels", [])
    if top_levels:
        first_level_children = top_levels[0].get("children", [])
        if first_level_children:
            build_level(root, df, first_level_children, 2)
        else:
            # No children under first level — just use the levels as-is
            build_level(root, df, top_levels, 2)

    # Post-processing
    def calc_baselines(n):
        n["baseline"] = n["num"] / n["den"] if n["den"] > 0 else 0
        n["goal"] = n["baseline"]
        for c in n["children"]:
            calc_baselines(c)

    def calc_contributions(n):
        children = n.get("children", [])
        if not children:
            return
        pden = n["den"]
        for c in children:
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


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

col1, col2 = st.columns([1, 14])
with col1:
    st.image("assets/logo.png", width=160)
with col2:
    st.markdown('<h1 style="font-size:40px;font-weight:600;margin:0;color:white;">KPI Hierarchy</h1>',
                unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar & tree loading
# ---------------------------------------------------------------------------

kpis = sorted(f.stem for f in OUTPUT_DIR.glob("*.json"))
default_idx = kpis.index("D0 2.0") if "D0 2.0" in kpis else 0
selected_kpi = st.sidebar.selectbox("Select KPI", kpis, index=default_idx)
max_leaf_nodes = st.sidebar.slider("Max Stations", 1, 50, 10)

json_file = OUTPUT_DIR / f"{selected_kpi}.json"

if "tree_data" not in st.session_state or st.session_state.get("loaded_kpi") != selected_kpi:
    st.session_state.tree_data = load_tree(str(json_file))
    st.session_state.loaded_kpi = selected_kpi
    for k in ("path_index", "node_count", "max_depth", "validation_issues", "rollup_issues"):
        st.session_state.pop(k, None)

root_data = st.session_state.tree_data

if "max_depth" not in st.session_state:
    def _md(n, d=1):
        ch = n.get("children", [])
        return max((_md(c, d+1) for c in ch), default=d) if ch else d
    st.session_state.max_depth = _md(root_data)

MAX_TREE_DEPTH = st.sidebar.slider("Tree Display Depth", 1, st.session_state.max_depth,
                                    min(5, st.session_state.max_depth))

if "path_index" not in st.session_state:
    st.session_state.path_index = build_path_index(root_data)
if "node_count" not in st.session_state:
    st.session_state.node_count = count_nodes(root_data)

path_index = st.session_state.path_index


def find_node(path):
    return path_index.get(path)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

if "selected_path" not in st.session_state:
    st.session_state.selected_path = root_data.get("path") or root_data["name"]

selected_node = find_node(st.session_state.selected_path) or root_data

col1, col2 = st.columns(2)
col1.metric("KPI", selected_kpi)
col2.metric("Nodes", st.session_state.node_count)

# ---------------------------------------------------------------------------
# Tree display
# ---------------------------------------------------------------------------


def get_ancestor_paths(path):
    parts = path.split("/")
    return {"/".join(parts[:i]) for i in range(1, len(parts) + 1)}


def display_tree(node, depth=0, ancestors=None):
    if ancestors is None:
        ancestors = get_ancestor_paths(st.session_state.selected_path)
    children = node.get("children", [])
    is_selected = node["path"] == st.session_state.selected_path
    is_ancestor = node["path"] in ancestors
    is_split = node.get("split", False)
    label = f"{'✅' if is_selected else '⑂' if is_split else ''} {node['name']}".strip()

    if children:
        should_render = depth < MAX_TREE_DEPTH or is_ancestor
        with st.expander(label, expanded=is_ancestor):
            if st.button(f"Select {node['name']}", key=f"sel_{node['path']}"):
                st.session_state.selected_path = node["path"]
                st.rerun()
            if should_render:
                for c in (c for c in children if not c.get("split")):
                    display_tree(c, depth + 1, ancestors)
                splits = [c for c in children if c.get("split")]
                if splits:
                    with st.expander(f"⑂ Split ({len(splits)})", expanded=False):
                        for c in splits:
                            display_tree(c, depth + 1, ancestors)
            else:
                st.caption(f"({len(children)} hidden)")
    else:
        if st.button(label, key=f"leaf_{node['path']}"):
            st.session_state.selected_path = node["path"]
            st.rerun()


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tree_tab, graph_tab, stats_tab, builder_tab = st.tabs(
    ["Tree", "Graph", "Statistics", "Hierarchy Builder"])

# ===== TREE TAB =====
with tree_tab:
    tree_col, detail_col = st.columns([1, 1])

    with tree_col:
        display_tree(root_data)

    with detail_col:
        # Validation
        if "validation_issues" not in st.session_state:
            st.session_state.validation_issues = validate_contributions(root_data)
        if "rollup_issues" not in st.session_state:
            st.session_state.rollup_issues = validate_rollup(root_data)

        issues = st.session_state.validation_issues
        rollup = st.session_state.rollup_issues
        if issues or rollup:
            st.error(f"{len(issues) + len(rollup)} issue(s)")
        else:
            st.success("All valid")

        with st.expander("QA Validation"):
            if not issues:
                st.success("Contributions OK")
            for i in issues:
                st.warning(f"{i['node']} = {i['total']:.1%}")
            num_issues = [r for r in rollup if r["type"] == "num_rollup"]
            if not num_issues:
                st.success("Rollup OK")
            for i in num_issues:
                st.warning(f"{i['node']}: diff {i['diff']:+,}")

        # Properties
        st.markdown(f"### {selected_node['name']}")
        st.caption(f"{selected_node.get('category', '')} \u2022 `{selected_node.get('path', '')}`")
        c1, c2 = st.columns(2)
        c1.metric("Baseline", f"{selected_node['baseline']:.2%}")
        c2.metric("Goal", f"{selected_node['goal']:.2%}")
        c1, c2 = st.columns(2)
        c1.metric("Num", f"{selected_node['num']:,}")
        c2.metric("Den", f"{selected_node['den']:,}")
        st.metric("Contribution", f"{selected_node['contribution']:.2%}")

# ===== GRAPH TAB =====
with graph_tab:
    view = st.radio("View", ["Graph", "Hierarchy"], horizontal=True, key="gv")

    if view == "Hierarchy":
        # Try to find the hierarchy used to build the currently selected KPI
        hier_file = HIERARCHIES_DIR / f"{selected_kpi}.json"
        if not hier_file.exists():
            hier_file = Path("hierarchy.json")
        if hier_file.exists():
            hdata = json.loads(hier_file.read_text(encoding="utf-8"))
            st.caption(f"Hierarchy: `{hier_file.name}`")
            H = nx.DiGraph()

            def _bh(node, pid=None, d=0):
                nid = f"{d}_{node['column']}"
                H.add_node(nid, column=node["column"], category=node["category"],
                           depth=d, split=node.get("split", False))
                if pid:
                    H.add_edge(pid, nid)
                for c in node.get("children", []):
                    _bh(c, nid, d + 1)

            for lv in hdata.get("levels", []):
                _bh(lv)

            # Layout
            pos, xc = {}, [0]

            def _lp(n, d):
                ch = list(H.successors(n))
                if not ch:
                    pos[n] = (xc[0], -d)
                    xc[0] += 1
                else:
                    for c in ch:
                        _lp(c, d + 1)
                    pos[n] = (sum(pos[c][0] for c in ch) / len(ch), -d)

            for r in (n for n in H.nodes() if H.in_degree(n) == 0):
                _lp(r, 0)

            ex, ey = [], []
            for e in H.edges():
                ex += [pos[e[0]][0], pos[e[1]][0], None]
                ey += [pos[e[0]][1], pos[e[1]][1], None]

            nc = ["#6B2D8B" if H.nodes[n].get("split") else "#003366" for n in H.nodes()]
            fig = go.Figure([
                go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=2, color="#888"), hoverinfo="none"),
                go.Scatter(x=[pos[n][0] for n in H.nodes()], y=[pos[n][1] for n in H.nodes()],
                           mode="markers+text", text=[H.nodes[n]["column"] for n in H.nodes()],
                           textposition="middle right", textfont=dict(size=14, color="white"),
                           marker=dict(size=30, color=nc, line=dict(width=2, color="white")),
                           hoverinfo="text",
                           hovertext=[f"{H.nodes[n]['category']} (Tier {H.nodes[n]['depth']+1})" for n in H.nodes()])
            ])
            fig.update_layout(showlegend=False, hovermode="closest", height=500,
                              margin=dict(l=40, r=40, t=60, b=40),
                              xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                              yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                              title="Hierarchy Definition")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"No hierarchy definition found for '{selected_kpi}'.")
    else:
        G = nx.DiGraph()
        graph_root = selected_node or root_data

        def _bg(n, d=0):
            G.add_node(n["path"], name=n["name"], category=n.get("category", ""),
                       type=n.get("type", ""), split=n.get("split", False))
            if d < 4:
                for c in n.get("children", [])[:max_leaf_nodes]:
                    G.add_edge(n["path"], c["path"])
                    _bg(c, d + 1)
        _bg(graph_root)

        def _hp(g, root, w=1.0, vg=0.2, vl=0, xc=0.5):
            ch = list(g.successors(root))
            if not ch:
                return {root: (xc, vl)}
            p = {root: (xc, vl)}
            dx = w / len(ch)
            nx_ = xc - w / 2 - dx / 2
            for c in ch:
                nx_ += dx
                p.update(_hp(g, c, dx, vg, vl - vg, nx_))
            return p

        pos = _hp(G, graph_root["path"])
        ex, ey = [], []
        for e in G.edges():
            ex += [pos[e[0]][0], pos[e[1]][0], None]
            ey += [pos[e[0]][1], pos[e[1]][1], None]

        nc = []
        ht = []
        for np in G.nodes():
            d = G.nodes[np]
            nd = find_node(np)
            ht.append(f"<b>{d['name']}</b><br>Num: {nd['num']:,}<br>Den: {nd['den']:,}<br>"
                      f"Baseline: {nd['baseline']:.2%}<br>Goal: {nd['goal']:.2%}<br>"
                      f"Contribution: {nd['contribution']:.2%}"
                      if nd else d["name"])
            nc.append("#6B2D8B" if d.get("split") else "#808080" if d.get("type") == "Goal" else "#003366")

        fig = go.Figure([
            go.Scatter(x=ex, y=ey, mode="lines", line=dict(width=1, color="#888"), hoverinfo="none"),
            go.Scatter(x=[pos[n][0] for n in G.nodes()], y=[pos[n][1] for n in G.nodes()],
                       mode="markers+text", text=[G.nodes[n]["name"] for n in G.nodes()],
                       textposition="bottom center", hovertext=ht, hoverinfo="text",
                       marker=dict(size=35, color=nc, line=dict(width=2, color="black")))
        ])
        fig.update_layout(showlegend=False, hovermode="closest",
                          margin=dict(l=20, r=20, t=20, b=20),
                          xaxis=dict(showgrid=False, zeroline=False),
                          yaxis=dict(showgrid=False, zeroline=False))
        st.plotly_chart(fig, use_container_width=True)

# ===== STATISTICS TAB =====
with stats_tab:
    csv_file = OUTPUT_DIR / f"{selected_kpi}_cascaded.csv"
    if csv_file.exists():
        st.dataframe(pd.read_csv(csv_file), use_container_width=True, hide_index=True)
    else:
        st.info("No cascaded data. Run the Hierarchy Builder or cascade.py first.")

# ===== HIERARCHY BUILDER TAB =====
with builder_tab:
    st.subheader("Build from Hierarchy")
    st.caption(
        "Select a saved hierarchy (designed in the editor) and build a new KPI tree. "
        "Run `python editor.py` to design hierarchies."
    )

    # List available hierarchies
    hier_files = sorted(f.stem for f in HIERARCHIES_DIR.glob("*.json")) if HIERARCHIES_DIR.exists() else []

    if not hier_files:
        st.info("No hierarchies found. Run `python editor.py` to create one.")
    else:
        selected_hier = st.selectbox("Hierarchy", hier_files, key="bld_hier")
        kpi_name = st.text_input("KPI Name for output", value=selected_hier, key="bld_name")

        if st.button("Build Tree", type="primary", key="bld_go"):
            kn = kpi_name.strip()
            if not kn:
                st.error("Enter a KPI name.")
            elif (OUTPUT_DIR / f"{kn}.json").exists():
                st.error(f"'{kn}' already exists in output/. Pick a different name or delete the old one.")
            else:
                with st.spinner(f"Building '{kn}'..."):
                    cp = Path("teradata_cache.parquet")
                    if not cp.exists():
                        st.error("teradata_cache.parquet not found. Run kpi_statistics.py first.")
                    else:
                        hp = HIERARCHIES_DIR / f"{selected_hier}.json"
                        from cascade import cascade
                        try:
                            op = OUTPUT_DIR / f"{kn}.json"
                            cascade(goals_file=Path("goals.csv"), hierarchy_file=hp,
                                    cache_file=cp, output_file=op)
                            st.success(f"Built '{kn}' — select it from the sidebar.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Build failed: {e}")
