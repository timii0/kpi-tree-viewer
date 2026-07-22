# Imports
import json
from pathlib import Path
import streamlit as st
import networkx as nx
import plotly.graph_objects as go

CATEGORIES = [
    "Div",
    "Director",
    "Region",
    "Station",
    "BU",
    "Carrier",
    "Body Type",
    "System"
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

node_paths = collect_paths(root_data)

selected_path = st.sidebar.selectbox(
    "Select Node",
    node_paths
)

selected_node = find_node(
    root_data,
    selected_path
)

# =====================================================
# Edit Node
# =====================================================

st.sidebar.header("Edit Node")

new_name = st.sidebar.text_input(
    "Name",
    value=selected_node["name"]
)

current_category = selected_node.get(
    "category",
    "Div"
)

new_category = st.sidebar.selectbox(
    "Category",
    CATEGORIES,
    index=(
        CATEGORIES.index(current_category)
        if current_category in CATEGORIES
        else 0
    )
)

new_type = st.sidebar.selectbox(
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

if st.sidebar.button("Save Changes"):

    selected_node["name"] = new_name
    selected_node["category"] = new_category
    selected_node["type"] = new_type

    st.success("Node updated")

# =====================================================
# Add Child
# =====================================================

st.sidebar.header("Add Child")

child_name = st.sidebar.text_input(
    "Child Name"
)

child_category = st.sidebar.selectbox(
    "Child Category",
    CATEGORIES,
    key="child_category"
)

child_type = st.sidebar.selectbox(
    "Child Type",
    TYPES,
    key="child_type"
)

if st.sidebar.button("Add Child"):

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
            "score": 0,
            "contribution": 0,
            "children": []
        }

        selected_node.setdefault(
            "children",
            []
        ).append(
            new_child
        )

        st.success(
            "Child added"
        )

# =====================================================
# Delete Node
# ====================================================

if selected_node["path"] != root_data["path"]:

    if st.sidebar.button(
        "Delete Node",
        type="primary"
    ):

        delete_node(
            root_data,
            selected_node["path"]
        )

        st.success(
            "Node deleted"
        )

col1, col2 = st.columns(2)

if st.sidebar.button(
    "Save Tree"
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

    st.success(
        "Tree saved"
    )

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

    if children:

        with st.expander(node["name"]):

            st.write(
                f"Category: {node.get('category','')}"
            )

            for child in children:
                display_tree(child)

    else:

        st.write(
            f"• {node['name']}"
        )

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
    display_tree(root_data)

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
    st.write("Statistics")

left, right = st.columns([2,1])

with right:

    st.subheader("KPI Info")

    st.write(
        f"Root: {root_data['name']}"
    )

    st.write(
        f"Children: {len(root_data['children'])}"
    )



