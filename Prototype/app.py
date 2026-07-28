# Imports
import json
from pathlib import Path
from csvtojson import build_stats_rows
import streamlit as st
import networkx as nx
import plotly.graph_objects as go
import pandas as pd
from streamlit_plotly_events import plotly_events
from kpi_statistics import df

CATEGORIES = [
    "div",
    "director",
    "region",
    "Station",
    "bu",
    "Carrier",
    "body type",
    "system",
    "direction",
    "dom_int",
    "DC_Carrier",
    "ML_Station",
    "unknown",
    "Enterprise"
]

TYPES = [
    "Goal",
    "Target"
]

st.set_page_config(
    page_title="KPI Tree Viewer",
    page_icon="assets/logo.png",
    layout="wide"
)

# colors = {
#     "sidebar" : "#C01933",
#     "bg": "#003366",
#     "extras" : "#991933"
# }

st.markdown("""
<style>

/* Sidebar */
[data-testid="stSidebar"] {
    background-color: #003366;
}

/* Expander headers */
.streamlit-expanderHeader {
    background-color: #CC0000;
    color: white;
}

/* Expander body */
div[data-testid="stExpander"] {
    background-color: #003366;
}

/* Selectbox */
div[data-baseweb="select"] > div {
    background-color: #003366;
    color: white;
}

# /* Main page */
# .stApp {
#     background-color: #003366;
# }

</style>
""", unsafe_allow_html=True)


col1, col2 = st.columns([1, 10])

with col1:
    st.image("assets/logo.png", width=100)

with col2:
    st.title("KPI Tree Viewer")


OUTPUT_DIR = Path("output")

kpis = sorted(
    file.stem
    for file in OUTPUT_DIR.glob("*.json")
)

selected_kpi = st.sidebar.selectbox(
    "Select KPI",
    kpis
)

json_file = OUTPUT_DIR / f"{selected_kpi}.json"

with open(json_file, "r", encoding="utf-8") as f:
    root_data = json.load(f)

def find_node(node, path):

    if node["path"] == path:
        return node

    for child in node.get("children", []):

        result = find_node(
            child,
            path
        )

        if result:
            return result

    return None

def delete_node(parent, path):

    children = parent.get("children", [])

    for i, child in enumerate(children):

        if child["path"] == path:
            del children[i]
            return True

        if delete_node(child, path):
            return True

    return False

def count_nodes(node):

    return 1 + sum(
        count_nodes(child)
        for child in node.get("children", [])
    )

def count_leafs(node):

    children = node.get("children", [])

    if not children:
        return 1

    return sum(
        count_leafs(child)
        for child in children
    )

def collect_paths(node, paths=None):

    if paths is None:
        paths = []

    paths.append(node["path"])

    for child in node.get("children", []):
        collect_paths(child, paths)

    return paths

def update_paths(node, parent_path=""):

    if parent_path:

        node["path"] = (
            f"{parent_path}/{node['name']}"
        )

    else:

        node["path"] = node["name"]

    for child in node.get("children", []):

        update_paths(
            child,
            node["path"]
        )

node_paths = collect_paths(root_data)


if "selected_path" not in st.session_state:
    st.session_state.selected_path = (
        root_data.get("path")
        or root_data["name"]
        )

selected_path = st.session_state.selected_path

if "unsaved_changes" not in st.session_state:
    st.session_state.unsaved_changes = False


selected_node = find_node(
    root_data,
    selected_path
)

if selected_node is None:
    selected_node = root_data

col1, col2 = st.columns(2)

col1.metric(
    "Nodes",
    count_nodes(root_data)
)

col2.metric(
    "Leaf Nodes",
    count_leafs(root_data)
)

def display_tree(node):

    children = node.get("children", [])

    is_selected = (
        node["path"]
        == st.session_state.selected_path
    )

    label = (
        f"✅ {node['name']}"
        if is_selected
        else node["name"]
    )

    if children:

        with st.expander(label):

            if st.button(
                f"Select {node['name']}",
                key=f"select_{node['path']}"
            ):
                st.session_state.selected_path = (
                    node["path"]
                )
                st.rerun()

            st.write(
                f"Category: {node.get('category','')}"
            )

            for child in children:
                display_tree(child)

    else:

        label = (
            f"✅ {node['name']}"
            if is_selected
            else node["name"]
        )

        if st.button(
            label,
            key=f"leaf_{node['path']}"
        ):
            st.session_state.selected_path = (
                node["path"]
            )
            st.rerun()



def build_graph(node, graph):

    graph.add_node(
        node["path"],
        name=node["name"],
        category=node.get("category", ""),
        type=node.get("type", "")
    )

    for child in node.get("children", []):

        graph.add_edge(
            node["path"],
            child["path"]
        )

        build_graph(
            child,
            graph
        )

tree_tab, graph_tab, statistics_tab = st.tabs(
    ["Tree", "Graph", "Statistics"]
)

with tree_tab:

    tree_col, detail_col = st.columns(
        [2, 1]
    )

    with tree_col:

        display_tree(root_data)

    with detail_col:
        if st.session_state.unsaved_changes:
            st.warning(
                "⚠ You have unsaved changes."
            )

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

        st.markdown(
            f"### {selected_node['name']}"
        )

        st.caption(
            selected_node.get(
                "category",
                ""
            )
        )

        col1, col2 = st.columns(2)

        with col1:
            st.metric(
                "Baseline",
                f"{selected_node['baseline']:.2%}"
            )

        with col2:
            st.metric(
                "Goal",
                f"{selected_node['goal']:.2%}"
            )

        col1, col2 = st.columns(2)

        with col1:
            st.metric(
                "Num",
                f"{selected_node['num']:,}"
            )

        with col2:
            st.metric(
                "Den",
                f"{selected_node['den']:,}"
            )

        st.metric(
            "Contribution",
            f"{selected_node['contribution']:.2%}"
        )

        new_name = st.text_input(
            "Name",
            value=selected_node["name"]
        )

        new_category = st.selectbox(
            "Category",
            CATEGORIES,
            index=(
                CATEGORIES.index(selected_node.get("category", "unknown")
            )
        )
        )

        new_type = st.selectbox(
            "Type",
            TYPES,
            index=(
                TYPES.index(
                    selected_node.get(
                        "type",
                        "Goal"
                    )
                )
            )
        )

        if st.session_state.get("edit_mode") == "edit":

            st.markdown("---")
            st.subheader("Edit Node")

            edit_name = st.text_input(
                "Name",
                value=selected_node["name"],
                key="edit_name"
            )

            current_category = selected_node.get(
                "category",
                CATEGORIES[0]
            )

            edit_category = st.selectbox(
                "Category",
                CATEGORIES,
                index=(
                    CATEGORIES.index(current_category)
                    if current_category in CATEGORIES
                    else 0
                ),
                key="edit_category"
            )

            edit_type = st.selectbox(
                "Type",
                TYPES,
                index=(
                    TYPES.index(
                        selected_node.get(
                            "type",
                            "Goal"
                        )
                    )
                ),
                key="edit_type"
            )

            col1, col2 = st.columns(2)

            with col1:

                if st.button(
                    "Save Changes",
                    key="save_edit"
                ):

                    old_path = selected_node["path"]
                    selected_node["name"] = edit_name
                    selected_node["category"] = edit_category
                    selected_node["type"] = edit_type

                    update_paths(root_data)

                    st.session_state.selected_path = (
                        selected_node["path"]
                    )

                    st.session_state.unsaved_changes = True

                    st.success("Node updated")

                    st.session_state.edit_mode = None

                    st.rerun()

            with col2:

                if st.button(
                    "Cancel",
                    key="cancel_edit"
                ):

                    st.session_state.edit_mode = None

                    st.rerun()

        if st.session_state.get("edit_mode") == "add":

            st.markdown("---")
            st.subheader("Add Child")

            child_name = st.text_input(
                "Child Name",
                key="add_child_name"
            )

            child_category = st.selectbox(
                "Category",
                CATEGORIES,
                key="add_child_category"
            )

            child_type = st.selectbox(
                "Type",
                TYPES,
                key="add_child_type"
            )

            col1, col2 = st.columns(2)

            with col1:

                if st.button(
                    "Add Child",
                    key="confirm_add_child"
                ):

                    if not child_name.strip():

                        st.error(
                            "Child name is required"
                        )

                    else:

                        new_child = {
                            "id": child_name,
                            "name": child_name,
                            "path": (
                                f"{selected_node['path']}"
                                f"/{child_name}"
                            ),
                            "category": child_category,
                            "type": child_type,

                            "tier": selected_node.get(
                                "tier",
                                0
                            ) + 1,

                            "baseline": 0,
                            "goal": 0,
                            "contribution": 0,

                            "num": 0,
                            "den": 0,

                            "children": []
                        }

                        selected_node.setdefault(
                            "children",
                            []
                        ).append(
                            new_child
                        )

                        update_paths(root_data)
                        st.session_state.unsaved_changes = True

                        st.success(
                            f"Added {child_name}"
                        )

                        st.session_state.edit_mode = None

                        st.rerun()

            with col2:

                if st.button(
                    "Cancel",
                    key="cancel_add_child"
                ):

                    st.session_state.edit_mode = None

                    st.rerun()

        if st.session_state.get("edit_mode") == "delete":
            st.markdown("---")
            st.subheader("Delete Node")

            st.warning(
                f"Are you sure you want to delete "
                f"'{selected_node['name']}'?"
            )

            st.write(
                "This action cannot be undone."
            )

            # Prevent deleting root node
            if selected_node["path"] == root_data["path"]:

                st.error(
                    "The root node cannot be deleted."
                )

            else:

                col1, col2 = st.columns(2)

                with col1:

                    if st.button(
                        "Confirm Delete",
                        key="confirm_delete",
                        type="primary"
                    ):

                        delete_node(
                            root_data,
                            selected_node["path"]
                        )

                        update_paths(root_data)
                        st.session_state.unsaved_changes = True

                        st.success(
                            f"{selected_node['name']} deleted"
                        )

                        st.session_state.selected_path = (
                            root_data["path"]
                        )

                        st.session_state.edit_mode = None

                        st.rerun()

                with col2:

                    if st.button(
                        "Cancel",
                        key="cancel_delete"
                    ):

                        st.session_state.edit_mode = None

                        st.rerun()

        st.markdown("---")

        if st.button(
            "💾 Save Tree",
            use_container_width=True
        ):

            with open(
                json_file,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    root_data,
                    f,
                    indent=4,
                    ensure_ascii=False
                )

            st.session_state.unsaved_changes = False

            st.success(
                "Tree saved successfully"
            )
with graph_tab:

    G = nx.DiGraph()

    build_graph(
        root_data,
        G
    )

    def hierarchy_pos(
    G,
    root,
    width=1.0,
    vert_gap=0.2,
    vert_loc=0,
    xcenter=0.5
):

        children = list(G.successors(root))

        if not children:
            return {root: (xcenter, vert_loc)}

        pos = {
            root: (xcenter, vert_loc)
        }

        dx = width / len(children)

        nextx = xcenter - width / 2 - dx / 2

        for child in children:

            nextx += dx

            pos.update(
                hierarchy_pos(
                    G,
                    child,
                    width=dx,
                    vert_gap=vert_gap,
                    vert_loc=vert_loc - vert_gap,
                    xcenter=nextx
                )
            )

        return pos
    
    pos = hierarchy_pos(
        G,
        root_data["path"]
    )

    edge_x = []
    edge_y = []

    for edge in G.edges():

        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]

        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line=dict(
            width=1,
            color="#888"
        ),
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

    for node in G.nodes():

        x, y = pos[node]

        node_x.append(x)
        node_y.append(y)

        data = G.nodes[node]

        node_text.append(
            f"{data['name']}<br>"
            f"Category: {data['category']}<br>"
            f"Type: {data['type']}"
        )

        node_color.append(
            colors.get(
                data.get("type"),
                "#B0BEC5"
            )
        )

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        text=[
            G.nodes[n]["name"]
            for n in G.nodes()
        ],
        textposition="bottom center",
        hovertext=node_text,
        hoverinfo="text",
        marker=dict(
            size=35,
            color=node_color,
            line=dict(
                width=2,
                color="black"
            )
        )
    )

    fig = go.Figure(
        data=[
            edge_trace,
            node_trace
        ]
    )

    fig.update_layout(
        showlegend=False,
        hovermode="closest",
        margin=dict(
            l=20,
            r=20,
            t=20,
            b=20
        ),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=False, zeroline=False)
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )

with statistics_tab:

    st.subheader("Statistics")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    # csv_file = Path("assets") / f"{selected_kpi}.csv"

    # stats_df = pd.read_csv(
    #     csv_file
    # )

    # st.dataframe(
    #     stats_df,
    #     use_container_width=True,
    #     hide_index=True
    # )

left, right = st.columns([2,1])

with right:

    st.subheader("KPI Info")

    st.write(
        f"Root: {root_data['name']}"
    )

    st.write(
        f"Children: {len(root_data['children'])}"
    )



