# Imports
import json
from pathlib import Path
import streamlit as st
import networkx as nx
import plotly.graph_objects as go
import pandas as pd


CATEGORIES = [
    "div",
    "director",
    "region",
    "Station",
    "bu",
    "carrier",
    "body type",
    "system",
    "direction",
    "dom_int",
    "dc_carrier",
    "ml_station",
    "enterprise"
    "unknown",
]

TYPES = [
    "Goal",
    "Target"
]

st.set_page_config(
    page_title="KPI Hierarchy",
    page_icon="assets/logo.png",
    layout="wide"
)

st.markdown("""
<style>

/* Main app */
.stApp {
    background-color: #001029;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: #003366;
}

/* ===== Typography ===== */

html,
body,
[class*="css"] {
    font-size: 21px;
}

/* Page title */
h1 {
    font-size: 3.5rem !important;
}

/* Section headers */
h2, h3 {
    font-size: 2.2rem !important;
}

/* ===== Metrics ===== */

[data-testid="stMetric"] {
    padding-top: 0rem;
    padding-bottom: 0rem;
}

[data-testid="stMetricLabel"] {
    font-size: 1rem !important;
    font-weight: 600;
}

[data-testid="stMetricValue"] {
    font-size: 2rem !important;
    font-weight: 700;
}

/* ===== Buttons ===== */

.stButton button {
    font-size: 1.5rem;
    font-weight: 600;
    min-height: 2.5rem;
}

/* ===== Inputs ===== */

.stTextInput label,
.stSelectbox label {
    font-size: 0.95rem;
    font-weight: 600;
}

/* ===== Tabs ===== */

button[data-baseweb="tab"] {
    font-size: 2rem;
    font-weight: 600;
}

/* ===== Expanders ===== */

.streamlit-expanderHeader {
    font-size: 1rem !important;
    font-weight: 600;
}

/* Reduce expander padding */
.streamlit-expanderContent {
    padding-top: 0rem !important;
    padding-bottom: 0rem !important;
}

/* ===== Containers ===== */

/* Reduce vertical spacing between elements */
div[data-testid="stVerticalBlock"] {
    gap: 0.5rem;
}

/* ===== Dataframes ===== */

[data-testid="stDataFrame"] {
    font-size: 0.95rem;
}

/* ===== Inputs Background ===== */

div[data-baseweb="select"] > div {
    background-color: #003366;
    color: white;
}

/* ===== Expander Colors ===== */

div[data-testid="stExpander"] {
    background-color: #003366;
}

/* Tree node buttons */
.stButton button {
    font-size: 1.5rem;
    font-weight: 700;
}

/* Expander headers */
summary {
    font-size: 1.15rem !important;
    font-weight: 700 !important;
}

</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Cached data loading
# ---------------------------------------------------------------------------

@st.cache_data
def load_tree(json_path):
    """Load and cache tree JSON from disk."""
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def load_parquet(parquet_path):
    """Load and cache parquet data."""
    return pd.read_parquet(parquet_path)


@st.cache_data
def load_csv(csv_path):
    """Load and cache CSV data."""
    return pd.read_csv(csv_path)


# ---------------------------------------------------------------------------
# Pre-computed index: flat dict of path -> node reference
# ---------------------------------------------------------------------------

def build_path_index(node, index=None):
    """Build a flat dict mapping path -> node for O(1) lookups."""
    if index is None:
        index = {}

    index[node["path"]] = node

    for child in node.get("children", []):
        build_path_index(child, index)

    return index


def count_nodes_cached(node):
    """Count total nodes (called once, stored in session)."""
    return 1 + sum(
        count_nodes_cached(child)
        for child in node.get("children", [])
    )


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

col1, col2 = st.columns([1, 14])

with col1:
    st.image("assets/logo.png", width=160)

with col2:
    st.markdown(
        """
        <h1 style="
            font-size: 40px;
            font-weight: 600;
            margin-top: 0px;
            margin-bottom: 10px;
            color: white;
            white-space: nowrap;
        ">
            KPI Hierarchy
        </h1>
        """,
        unsafe_allow_html=True
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path("output")

kpis = sorted(
    file.stem
    for file in OUTPUT_DIR.glob("*.json")
)

selected_kpi = st.sidebar.selectbox(
    "Select KPI",
    kpis
)

max_leaf_nodes = st.sidebar.slider(
    "Max Stations",
    1,
    50,
    10
)

# Placeholder — will be set after tree loads
MAX_TREE_DEPTH = 3

json_file = OUTPUT_DIR / f"{selected_kpi}.json"

# Load tree with caching
if ("tree_data" not in st.session_state or st.session_state.get("loaded_kpi") != selected_kpi):
    st.session_state.tree_data = load_tree(str(json_file))
    st.session_state.loaded_kpi = selected_kpi
    # Invalidate index on reload
    st.session_state.pop("path_index", None)
    st.session_state.pop("node_count", None)
    st.session_state.pop("max_depth", None)

root_data = st.session_state.tree_data

# Compute max depth of the tree (once per load)
if "max_depth" not in st.session_state:
    def get_max_depth(node, depth=1):
        children = node.get("children", [])
        if not children:
            return depth
        return max(get_max_depth(c, depth + 1) for c in children)
    st.session_state.max_depth = get_max_depth(root_data)

tree_max_depth = st.session_state.max_depth

MAX_TREE_DEPTH = st.sidebar.slider(
    "Tree Display Depth",
    1,
    tree_max_depth,
    min(3, tree_max_depth)
)

# Build path index (once per tree load)
if "path_index" not in st.session_state:
    st.session_state.path_index = build_path_index(root_data)

if "node_count" not in st.session_state:
    st.session_state.node_count = count_nodes_cached(root_data)

path_index = st.session_state.path_index


# ---------------------------------------------------------------------------
# Utility functions (use path_index for O(1) lookup)
# ---------------------------------------------------------------------------

def find_node(node, path):
    """O(1) node lookup via pre-built index."""
    return path_index.get(path)


def delete_node(parent, path):
    children = parent.get("children", [])

    for i, child in enumerate(children):
        if child["path"] == path:
            del children[i]
            return True
        if delete_node(child, path):
            return True

    return False


def update_paths(node, parent_path=""):
    if parent_path:
        node["path"] = f"{parent_path}/{node['name']}"
    else:
        node["path"] = node["name"]

    for child in node.get("children", []):
        update_paths(child, node["path"])


def rebuild_index():
    """Rebuild path index after tree mutations."""
    st.session_state.path_index = build_path_index(root_data)
    st.session_state.node_count = count_nodes_cached(root_data)


def validate_contributions(node):
    issues = []
    children = node.get("children", [])

    if children:
        total = sum(
            child.get("contribution", 0)
            for child in children
        )
        if abs(total - 1.0) > 0.001:
            issues.append({
                "node": node["name"],
                "total": total
            })

    for child in children:
        issues.extend(validate_contributions(child))

    return issues


# ---------------------------------------------------------------------------
# State initialization
# ---------------------------------------------------------------------------

if "selected_path" not in st.session_state:
    st.session_state.selected_path = (
        root_data.get("path") or root_data["name"]
    )

selected_path = st.session_state.selected_path

if "unsaved_changes" not in st.session_state:
    st.session_state.unsaved_changes = False

selected_node = find_node(root_data, selected_path)

if selected_node is None:
    selected_node = root_data

col1, col2 = st.columns(2)

col1.metric("KPI", selected_kpi)
col2.metric("Nodes", st.session_state.node_count)


# ---------------------------------------------------------------------------
# Lazy tree display — only renders nodes up to MAX_TREE_DEPTH from root,
# and always expands the path to the selected node.
# ---------------------------------------------------------------------------

def get_ancestor_paths(path):
    """Get all ancestor paths for a given node path."""
    parts = path.split("/")
    ancestors = set()
    for i in range(1, len(parts) + 1):
        ancestors.add("/".join(parts[:i]))
    return ancestors


def display_tree(node, depth=0, ancestor_paths=None):
    """Render tree lazily — only expand to MAX_TREE_DEPTH or along selection path."""
    if ancestor_paths is None:
        ancestor_paths = get_ancestor_paths(st.session_state.selected_path)

    children = node.get("children", [])

    is_selected = (node["path"] == st.session_state.selected_path)
    is_ancestor = (node["path"] in ancestor_paths)

    label = (
        f"✅ {node['name']}"
        if is_selected
        else node["name"]
    )

    if children:
        # Only expand if within depth limit OR on the path to selected node
        should_expand = is_ancestor
        should_render_children = (depth < MAX_TREE_DEPTH) or is_ancestor

        with st.expander(label, expanded=should_expand):
            if st.button(
                f"Select {node['name']}",
                key=f"select_{node['path']}"
            ):
                st.session_state.selected_path = node["path"]
                st.rerun()

            if should_render_children:
                for child in children:
                    display_tree(child, depth + 1, ancestor_paths)
            else:
                st.caption(f"({len(children)} children hidden — increase Tree Display Depth)")
    else:
        if st.button(label, key=f"leaf_{node['path']}"):
            st.session_state.selected_path = node["path"]
            st.rerun()


# ---------------------------------------------------------------------------
# Graph building (only when needed)
# ---------------------------------------------------------------------------

def build_graph(node, graph, depth=0, max_depth=4):
    """Build graph with depth limit to avoid rendering thousands of nodes."""
    graph.add_node(
        node["path"],
        name=node["name"],
        category=node.get("category", ""),
        type=node.get("type", "")
    )

    if depth >= max_depth:
        return

    children = node.get("children", [])[:max_leaf_nodes]

    for child in children:
        graph.add_edge(node["path"], child["path"])
        build_graph(child, graph, depth + 1, max_depth)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tree_tab, graph_tab, statistics_tab = st.tabs(
    ["Tree", "Graph", "Statistics"]
)

with tree_tab:
    tree_col, detail_col = st.columns([1, 1])

    with tree_col:
        display_tree(root_data)

    with detail_col:
        if st.session_state.unsaved_changes:
            st.warning("⚠ You have unsaved changes.")

        if "edit_mode" not in st.session_state:
            st.session_state.edit_mode = None

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("Edit", use_container_width=True):
                st.session_state.edit_mode = "edit"

        with col2:
            if st.button("Add Child", use_container_width=True):
                st.session_state.edit_mode = "add"

        with col3:
            if st.button("Delete", use_container_width=True):
                st.session_state.edit_mode = "delete"

        st.subheader("Properties")

        issues = validate_contributions(root_data)

        if issues:
            st.error(f"{len(issues)} contribution issue(s)")
        else:
            st.success("✓ All contribution groups total 100%")

        with st.expander("QA Validation"):
            if not issues:
                st.success("✓ All contributions balance")

            for issue in issues:
                st.warning(
                    f"{issue['node']} = {issue['total']:.1%}"
                )

        st.markdown(f"### {selected_node['name']}")

        st.caption(
            f"{selected_node.get('category', '')}  •  "
            f"`{selected_node.get('path', '')}`"
        )

        col1, col2 = st.columns(2)

        with col1:
            st.metric("Baseline", f"{selected_node['baseline']:.2%}")

        with col2:
            st.metric("Goal", f"{selected_node['goal']:.2%}")

        col1, col2 = st.columns(2)

        with col1:
            st.metric("Num", f"{selected_node['num']:,}")

        with col2:
            st.metric("Den", f"{selected_node['den']:,}")

        st.metric("Contribution", f"{selected_node['contribution']:.2%}")

        # --- Edit Mode ---
        if st.session_state.get("edit_mode") == "edit":
            st.markdown("---")
            st.subheader("Edit Node")

            edit_name = st.text_input(
                "Name", value=selected_node["name"], key="edit_name"
            )

            current_category = selected_node.get("category", CATEGORIES[0])
            edit_category = st.selectbox(
                "Category", CATEGORIES,
                index=(
                    CATEGORIES.index(current_category)
                    if current_category in CATEGORIES else 0
                ),
                key="edit_category"
            )

            edit_type = st.selectbox(
                "Type", TYPES,
                index=TYPES.index(selected_node.get("type", "Goal")),
                key="edit_type"
            )

            edit_contribution = st.number_input(
                "Contribution (%)",
                min_value=0.0, max_value=100.0,
                value=selected_node.get("contribution", 0) * 100,
                step=0.1
            )

            col1, col2 = st.columns(2)

            with col1:
                if st.button("Save Changes", key="save_edit"):
                    selected_node["name"] = edit_name
                    selected_node["category"] = edit_category
                    selected_node["type"] = edit_type
                    selected_node["contribution"] = edit_contribution / 100

                    update_paths(root_data)
                    rebuild_index()

                    st.session_state.selected_path = selected_node["path"]
                    st.session_state.unsaved_changes = True
                    st.session_state.edit_mode = None
                    st.rerun()

            with col2:
                if st.button("Cancel", key="cancel_edit"):
                    st.session_state.edit_mode = None
                    st.rerun()

        # --- Add Child Mode ---
        if st.session_state.get("edit_mode") == "add":
            st.markdown("---")
            st.subheader("Add Child")

            child_name = st.text_input("Child Name", key="add_child_name")
            child_category = st.selectbox(
                "Category", CATEGORIES, key="add_child_category"
            )
            child_type = st.selectbox("Type", TYPES, key="add_child_type")

            col1, col2 = st.columns(2)

            with col1:
                if st.button("Add Child", key="confirm_add_child"):
                    if not child_name.strip():
                        st.error("Child name is required")
                    else:
                        new_child = {
                            "id": child_name,
                            "name": child_name,
                            "path": f"{selected_node['path']}/{child_name}",
                            "category": child_category,
                            "type": child_type,
                            "tier": selected_node.get("tier", 0) + 1,
                            "baseline": 0,
                            "goal": 0,
                            "contribution": 0,
                            "num": 0,
                            "den": 0,
                            "children": []
                        }

                        selected_node.setdefault("children", []).append(new_child)
                        update_paths(root_data)
                        rebuild_index()

                        st.session_state.unsaved_changes = True
                        st.session_state.edit_mode = None
                        st.rerun()

            with col2:
                if st.button("Cancel", key="cancel_add_child"):
                    st.session_state.edit_mode = None
                    st.rerun()

        # --- Delete Mode ---
        if st.session_state.get("edit_mode") == "delete":
            st.markdown("---")
            st.subheader("Delete Node")

            st.warning(f"Are you sure you want to delete '{selected_node['name']}'?")
            st.write("This action cannot be undone.")

            if selected_node["path"] == root_data["path"]:
                st.error("The root node cannot be deleted.")
            else:
                col1, col2 = st.columns(2)

                with col1:
                    if st.button("Confirm Delete", key="confirm_delete", type="primary"):
                        delete_node(root_data, selected_node["path"])
                        update_paths(root_data)
                        rebuild_index()

                        st.session_state.unsaved_changes = True
                        st.session_state.selected_path = root_data["path"]
                        st.session_state.edit_mode = None
                        st.rerun()

                with col2:
                    if st.button("Cancel", key="cancel_delete"):
                        st.session_state.edit_mode = None
                        st.rerun()

        st.markdown("---")

        if st.button("Save Tree", use_container_width=True):
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(
                    st.session_state.tree_data, f,
                    indent=4, ensure_ascii=False
                )
            st.session_state.unsaved_changes = False
            st.success("Tree saved successfully")


# ---------------------------------------------------------------------------
# Graph tab — only builds when viewed
# ---------------------------------------------------------------------------

with graph_tab:
    graph_view = st.radio(
        "View",
        ["Graph", "Hierarchy"],
        horizontal=True,
        key="graph_view_selector"
    )

    if graph_view == "Hierarchy":
        # Visualize hierarchy.json structure using actual field names
        hierarchy_file = Path("hierarchy.json")
        if hierarchy_file.exists():
            with open(hierarchy_file, "r", encoding="utf-8") as f:
                hierarchy_data = json.load(f)

            # Build a networkx graph from the hierarchy definition
            H = nx.DiGraph()

            def build_hierarchy_graph(node, parent_id=None, depth=0):
                node_id = f"{depth}_{node['column']}"
                H.add_node(node_id, column=node["column"], category=node["category"], depth=depth)
                if parent_id:
                    H.add_edge(parent_id, node_id)
                for child in node.get("children", []):
                    build_hierarchy_graph(child, node_id, depth + 1)

            for level in hierarchy_data.get("levels", []):
                build_hierarchy_graph(level)

            # Layout — horizontal staircase with indentation
            pos = {}
            for n in H.nodes():
                d = H.nodes[n]["depth"]
                pos[n] = (d * 0.8, -d)  # x shifts right, y goes down

            edge_x, edge_y = [], []
            for e in H.edges():
                x0, y0 = pos[e[0]]
                x1, y1 = pos[e[1]]
                edge_x += [x0, x1, None]
                edge_y += [y0, y1, None]

            edge_trace = go.Scatter(
                x=edge_x, y=edge_y,
                mode="lines",
                line=dict(width=2, color="#888"),
                hoverinfo="none"
            )

            node_x, node_y, node_labels, node_hover = [], [], [], []
            for n in H.nodes():
                x, y = pos[n]
                node_x.append(x)
                node_y.append(y)
                data = H.nodes[n]
                node_labels.append(data["column"])
                node_hover.append(
                    f"<b>{data['column']}</b><br>"
                    f"Category: {data['category']}<br>"
                    f"Tier: {data['depth'] + 1}"
                )

            node_trace = go.Scatter(
                x=node_x, y=node_y,
                mode="markers+text",
                text=node_labels,
                textposition="middle right",
                textfont=dict(size=14, color="white"),
                hovertext=node_hover,
                hoverinfo="text",
                marker=dict(size=30, color="#003366", line=dict(width=2, color="white"))
            )

            fig = go.Figure(data=[edge_trace, node_trace])
            fig.update_layout(
                showlegend=False,
                hovermode="closest",
                margin=dict(l=40, r=40, t=60, b=40),
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                title="Hierarchy Definition (hierarchy.json)",
                height=500
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("hierarchy.json not found.")

    else:
        # Graph view of the KPI tree
        G = nx.DiGraph()

        # Use selected node as graph root for focused view
        graph_root = selected_node if selected_node else root_data

        build_graph(graph_root, G)

        def hierarchy_pos(G, root, width=1.0, vert_gap=0.2, vert_loc=0, xcenter=0.5):
            children = list(G.successors(root))

            if not children:
                return {root: (xcenter, vert_loc)}

            pos = {root: (xcenter, vert_loc)}
            dx = width / len(children)
            nextx = xcenter - width / 2 - dx / 2

            for child in children:
                nextx += dx
                pos.update(
                    hierarchy_pos(
                        G, child,
                        width=dx, vert_gap=vert_gap,
                        vert_loc=vert_loc - vert_gap,
                        xcenter=nextx
                    )
                )

            return pos

        pos = hierarchy_pos(G, graph_root["path"])

        edge_x = []
        edge_y = []

        for edge in G.edges():
            x0, y0 = pos[edge[0]]
            x1, y1 = pos[edge[1]]
            edge_x += [x0, x1, None]
            edge_y += [y0, y1, None]

        edge_trace = go.Scatter(
            x=edge_x, y=edge_y,
            mode="lines",
            line=dict(width=1, color="#888"),
            hoverinfo="none"
        )

        node_x = []
        node_y = []
        node_text = []
        node_color = []

        colors = {
            "Goal": "#808080",
            "Target": "#003366"
        }

        for node_path in G.nodes():
            x, y = pos[node_path]
            node_x.append(x)
            node_y.append(y)

            data = G.nodes[node_path]
            node_data = find_node(root_data, node_path)

            node_text.append(
                f"<b>{data['name']}</b><br>"
                f"Category: {data.get('category', '')}<br>"
                f"Type: {data.get('type', '')}<br>"
                f"Tier: {node_data.get('tier', '') if node_data else ''}<br>"
                f"<br>"
                f"Baseline: {node_data.get('baseline', 0):.2%}<br>"
                f"Goal: {node_data.get('goal', 0):.2%}<br>"
                f"Contribution: {node_data.get('contribution', 0):.2%}<br>"
                f"<br>"
                f"Num: {node_data.get('num', 0):,}<br>"
                f"Den: {node_data.get('den', 0):,}"
                if node_data else data['name']
            )

            node_color.append(
                colors.get(data.get("type"), "#B0BEC5")
            )

        node_trace = go.Scatter(
            x=node_x, y=node_y,
            mode="markers+text",
            text=[G.nodes[n]["name"] for n in G.nodes()],
            textposition="bottom center",
            hovertext=node_text,
            hoverinfo="text",
            hoverlabel=dict(
                bgcolor="#003366",
                font_size=14,
                font_color="white"
            ),
            marker=dict(
                size=35,
                color=node_color,
                line=dict(width=2, color="black")
            )
        )

        fig = go.Figure(data=[edge_trace, node_trace])

        fig.update_layout(
            showlegend=False,
            hovermode="closest",
            margin=dict(l=20, r=20, t=20, b=20),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False, zeroline=False)
        )

        st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Statistics tab — cached data load
# ---------------------------------------------------------------------------

with statistics_tab:
    st.subheader("Statistics")

    csv_file = Path("output") / f"{selected_kpi}.csv"

    if csv_file.exists():
        # Read fresh each time — this file changes on cascade runs
        df = pd.read_csv(csv_file)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No cascaded output found. Run cascade.py first.")


# ---------------------------------------------------------------------------
# Footer info
# ---------------------------------------------------------------------------

left, right = st.columns([2, 1])

with right:
    st.subheader("KPI Info")
    st.write(f"Root: {root_data['name']}")
    st.write(f"Children: {len(root_data['children'])}")
