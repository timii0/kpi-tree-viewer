import json
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="KPI Tree Viewer",
    layout="wide"
)

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

tab1, tab2, tab3 = st.tabs(
    ["Tree", "Graph", "Statistics"]
)

with tab1:
    display_tree(root_data)

with tab2:
    st.write("Graph coming soon")

with tab3:
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