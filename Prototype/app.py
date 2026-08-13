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
    "enterprise",
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

def load_tree(json_path):
    """Load tree JSON from disk (no cache — always reads fresh)."""
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

# Default to "D0 2.0" if available
default_kpi_index = 0
if "D0 2.0" in kpis:
    default_kpi_index = kpis.index("D0 2.0")

selected_kpi = st.sidebar.selectbox(
    "Select KPI",
    kpis,
    index=default_kpi_index
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
    st.session_state.pop("validation_issues", None)

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
    min(5, tree_max_depth)
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
    st.session_state.pop("validation_issues", None)
    st.session_state.pop("rollup_issues", None)


def validate_contributions(node):
    issues = []
    children = node.get("children", [])

    if children:
        # Primary children and split children are independent groups —
        # each should sum to 100% of the parent separately.
        primary_children = [c for c in children if not c.get("split")]
        split_children = [c for c in children if c.get("split")]

        if primary_children:
            total = sum(
                child.get("contribution", 0)
                for child in primary_children
            )
            if abs(total - 1.0) > 0.001:
                issues.append({
                    "node": node["name"],
                    "total": total
                })

        if split_children:
            split_total = sum(
                child.get("contribution", 0)
                for child in split_children
            )
            if abs(split_total - 1.0) > 0.001:
                issues.append({
                    "node": f"{node['name']} (split)",
                    "total": split_total
                })

    for child in children:
        issues.extend(validate_contributions(child))

    return issues


def validate_rollup(node):
    """Validate that children's num sums to parent's num and contributions
    sum to 1.0 at every level. Returns a list of issue dicts.
    Allows a small rounding tolerance for proportional distribution."""
    issues = []
    children = node.get("children", [])

    if children:
        primary_children = [c for c in children if not c.get("split")]
        split_children = [c for c in children if c.get("split")]

        # Check num rollup for primary branch
        if primary_children:
            children_num_total = sum(c.get("num", 0) for c in primary_children)
            parent_num = node.get("num", 0)
            # Allow rounding tolerance: 1 per child (proportional distribution rounding)
            tolerance = len(primary_children)
            if parent_num > 0 and abs(children_num_total - parent_num) > tolerance:
                issues.append({
                    "type": "num_rollup",
                    "node": node["name"],
                    "parent_num": parent_num,
                    "children_num": children_num_total,
                    "diff": children_num_total - parent_num,
                })

            # Check contribution sum
            contribution_total = sum(
                c.get("contribution", 0) for c in primary_children
            )
            if abs(contribution_total - 1.0) > 0.001:
                issues.append({
                    "type": "contribution_sum",
                    "node": node["name"],
                    "total": contribution_total,
                })

        # Same checks for split branch (split children share parent den/num
        # independently so their contributions should also sum to 1.0)
        if split_children:
            split_contribution_total = sum(
                c.get("contribution", 0) for c in split_children
            )
            if abs(split_contribution_total - 1.0) > 0.001:
                issues.append({
                    "type": "contribution_sum",
                    "node": f"{node['name']} (split)",
                    "total": split_contribution_total,
                })

    for child in children:
        issues.extend(validate_rollup(child))

    return issues


def find_parent_node(root, target_path):
    """Find the parent of a node by its path."""
    if "/" not in target_path:
        return None  # root has no parent
    parent_path = target_path.rsplit("/", 1)[0]
    return path_index.get(parent_path)


def reallocate_num(parent_node, source_name, dest_name, amount):
    """Move `amount` of num from source sibling to dest sibling within the
    same parent. Recalculates baselines and contributions for affected children.

    Args:
        parent_node: The parent node whose children are being reallocated
        source_name: Name of the child giving up num
        dest_name: Name of the child receiving num
        amount: Integer amount of num to transfer

    Returns:
        (success: bool, message: str)
    """
    children = parent_node.get("children", [])
    primary_children = [c for c in children if not c.get("split")]

    source = next((c for c in primary_children if c["name"] == source_name), None)
    dest = next((c for c in primary_children if c["name"] == dest_name), None)

    if not source or not dest:
        return False, "Source or destination node not found among siblings."

    if amount <= 0:
        return False, "Amount must be greater than zero."

    if amount > source.get("num", 0):
        return False, (
            f"Cannot transfer {amount:,} — {source_name} only has "
            f"{source['num']:,} num available."
        )

    # Transfer the num
    source["num"] -= amount
    dest["num"] += amount

    # Parent num stays the same (it's a redistribution within the tier)
    parent_num = parent_node.get("num", 0)

    # Recalculate baseline (num/den) for source and dest
    if source.get("den", 0) > 0:
        source["baseline"] = source["num"] / source["den"]
    if dest.get("den", 0) > 0:
        dest["baseline"] = dest["num"] / dest["den"]

    # Recalculate contributions for ALL primary children
    # Contribution = child_num / parent_num (reflects new num distribution)
    for child in primary_children:
        if parent_num > 0:
            child["contribution"] = child["num"] / parent_num
        else:
            child["contribution"] = 0

    return True, (
        f"Moved {amount:,} num from {source_name} to {dest_name}. "
        f"Parent {parent_node['name']} num unchanged at {parent_num:,}."
    )


# ---------------------------------------------------------------------------
# Tree-to-CSV export (regenerates the statistics CSV from tree state)
# ---------------------------------------------------------------------------

# Hierarchy column order used in the CSV output
_HIERARCHY_COLUMNS = ["sys", "ml_dc_1", "ml_dc_2", "Mo_Nb", "frst_flt_ind",
                      "dom_int", "vendor", "station", "fleet"]

# Map category -> column name for placing node names in the right column
_CATEGORY_TO_COLUMN = {
    "system": "sys",
    "carrier": "ml_dc_1",
    "dc_carrier": "ml_dc_2",
    "month": "Mo_Nb",
    "first_flt": "frst_flt_ind",
    "dom_int": "dom_int",
    "vendor": "vendor",
    "station": "station",
    "fleet": "fleet",
}


def tree_to_csv(root_node, kpi_name):
    """Flatten tree into a DataFrame matching the statistics CSV format."""
    rows = []

    def walk(node, ancestors):
        # Build the hierarchy column values from ancestors
        current = dict(ancestors)
        col = _CATEGORY_TO_COLUMN.get(node.get("category", ""))
        if col:
            current[col] = node["name"]

        # Determine parent path and node name from the path field
        path = node.get("path", "")
        if "/" in path:
            parent_path = path.rsplit("/", 1)[0]
            # Strip the root prefix for display
            parts = parent_path.split("/")
            parent_display = "/".join(parts[1:]) if len(parts) > 1 else ""
        else:
            parent_display = ""

        node_name = node["name"]
        # For root enterprise node, skip it (start from first real level)
        if node.get("category") == "Enterprise":
            for child in node.get("children", []):
                walk(child, current)
            return

        den = node.get("den", 0)
        num = node.get("num", 0)
        baseline = node.get("baseline", 0)
        goal = node.get("goal", 0)

        # Stretch as percentage
        if baseline > 0:
            stretch = ((goal - baseline) / baseline) * 100
        else:
            stretch = 0

        row = {"KPI_Name": kpi_name, "parent": parent_display, "node": node_name}
        row["Tier"] = node.get("tier", 1) - 1  # offset tier to start at 1

        # Fill hierarchy columns
        for hcol in _HIERARCHY_COLUMNS:
            row[hcol] = current.get(hcol, "")

        row["Baseline"] = round(baseline * 100, 2)
        row["Baseline_Num"] = num  # after reallocation, num IS the current state
        row["Baseline_Den"] = den
        row["Goal"] = round(goal * 100, 2)
        row["Stretch"] = f"{stretch:.2f}%"
        row["Contribution"] = node.get("contribution", 0)
        row["KPI_Num"] = num
        row["KPI_Den"] = den
        row["Goal_Yr"] = 2027
        row["YTD_Yr"] = 2026
        row["YTD_Num"] = ""
        row["YTD_Den"] = ""

        if node.get("split"):
            row["Split"] = True
        else:
            row["Split"] = False

        rows.append(row)

        for child in node.get("children", []):
            walk(child, current)

    walk(root_node, {})
    return pd.DataFrame(rows)


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
    """Render tree lazily — only expand to MAX_TREE_DEPTH or along selection path.
    Split branches are collapsed by default to reduce widget count."""
    if ancestor_paths is None:
        ancestor_paths = get_ancestor_paths(st.session_state.selected_path)

    children = node.get("children", [])

    is_selected = (node["path"] == st.session_state.selected_path)
    is_ancestor = (node["path"] in ancestor_paths)
    is_split = node.get("split", False)

    label = (
        f"✅ {node['name']}"
        if is_selected
        else f"⑂ {node['name']}" if is_split
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
                # Render primary children first, then split children
                primary = [c for c in children if not c.get("split")]
                splits = [c for c in children if c.get("split")]

                for child in primary:
                    display_tree(child, depth + 1, ancestor_paths)

                if splits:
                    with st.expander(f"⑂ Split branches ({len(splits)})", expanded=False):
                        for child in splits:
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
        type=node.get("type", ""),
        split=node.get("split", False)
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

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            if st.button("Edit", use_container_width=True):
                st.session_state.edit_mode = "edit"

        with col2:
            if st.button("Add Child", use_container_width=True):
                st.session_state.edit_mode = "add"

        with col3:
            if st.button("Reallocate", use_container_width=True):
                st.session_state.edit_mode = "reallocate"

        with col4:
            if st.button("Delete", use_container_width=True):
                st.session_state.edit_mode = "delete"

        st.subheader("Properties")

        # Cache validation to avoid re-walking the tree on every rerun
        if "validation_issues" not in st.session_state:
            st.session_state.validation_issues = validate_contributions(root_data)

        if "rollup_issues" not in st.session_state:
            st.session_state.rollup_issues = validate_rollup(root_data)

        issues = st.session_state.validation_issues
        rollup_issues = st.session_state.rollup_issues

        total_issues = len(issues) + len(rollup_issues)
        if total_issues:
            st.error(f"{total_issues} validation issue(s)")
        else:
            st.success("✓ All contributions and rollups valid")

        with st.expander("QA Validation"):
            # Contribution validation
            st.markdown("**Contribution Sum Check**")
            if not issues:
                st.success("✓ All contribution groups total 100%")

            for issue in issues:
                st.warning(
                    f"{issue['node']} = {issue['total']:.1%}"
                )

            # Rollup validation
            st.markdown("**Num Rollup Check**")
            num_issues = [i for i in rollup_issues if i["type"] == "num_rollup"]
            contrib_issues = [i for i in rollup_issues if i["type"] == "contribution_sum"]

            if not num_issues:
                st.success("✓ Children num sums match parent at all levels")
            for issue in num_issues:
                st.warning(
                    f"{issue['node']}: children num = {issue['children_num']:,}, "
                    f"parent num = {issue['parent_num']:,} "
                    f"(diff: {issue['diff']:+,})"
                )

            if not contrib_issues:
                st.success("✓ Contributions sum to 100% at all levels")
            for issue in contrib_issues:
                st.warning(
                    f"{issue['node']}: contributions sum = {issue['total']:.4f} "
                    f"(expected 1.0)"
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

        # --- Reallocate Mode ---
        if st.session_state.get("edit_mode") == "reallocate":
            st.markdown("---")
            st.subheader("Reallocate Num")

            # Find the parent of the selected node to get siblings
            parent_node = find_parent_node(root_data, selected_node["path"])

            if parent_node is None:
                st.error("Cannot reallocate from the root node. Select a child node.")
            else:
                # Get primary siblings (same tier, same parent)
                siblings = [
                    c for c in parent_node.get("children", [])
                    if not c.get("split")
                ]

                if len(siblings) < 2:
                    st.error("Need at least 2 siblings to reallocate between.")
                else:
                    sibling_names = [c["name"] for c in siblings]

                    st.caption(
                        f"Moving num between children of **{parent_node['name']}** "
                        f"(Tier {selected_node.get('tier', '?')})"
                    )

                    # Show current state of siblings
                    sibling_data = []
                    for sib in siblings:
                        sibling_data.append({
                            "Name": sib["name"],
                            "Num": f"{sib['num']:,}",
                            "Den": f"{sib['den']:,}",
                            "Baseline": f"{sib.get('baseline', 0):.2%}",
                            "Contribution": f"{sib.get('contribution', 0):.2%}",
                        })
                    st.dataframe(
                        pd.DataFrame(sibling_data),
                        use_container_width=True,
                        hide_index=True
                    )

                    # Default source to currently selected node
                    default_source_idx = (
                        sibling_names.index(selected_node["name"])
                        if selected_node["name"] in sibling_names
                        else 0
                    )

                    source_name = st.selectbox(
                        "Source (giving num)",
                        sibling_names,
                        index=default_source_idx,
                        key="realloc_source"
                    )

                    # Destination defaults to next sibling
                    dest_options = [n for n in sibling_names if n != source_name]
                    dest_name = st.selectbox(
                        "Destination (receiving num)",
                        dest_options,
                        key="realloc_dest"
                    )

                    source_node = next(
                        (c for c in siblings if c["name"] == source_name), None
                    )
                    max_amount = source_node["num"] if source_node else 0

                    amount = st.number_input(
                        f"Amount to transfer (max {max_amount:,})",
                        min_value=0,
                        max_value=max_amount,
                        value=0,
                        step=100,
                        key="realloc_amount"
                    )

                    # Preview what would happen
                    if amount > 0 and source_node:
                        dest_node_ref = next(
                            (c for c in siblings if c["name"] == dest_name), None
                        )
                        if dest_node_ref:
                            new_source_num = source_node["num"] - amount
                            new_dest_num = dest_node_ref["num"] + amount
                            new_source_baseline = (
                                new_source_num / source_node["den"]
                                if source_node["den"] > 0 else 0
                            )
                            new_dest_baseline = (
                                new_dest_num / dest_node_ref["den"]
                                if dest_node_ref["den"] > 0 else 0
                            )
                            st.info(
                                f"Preview: {source_name} num {source_node['num']:,} → "
                                f"{new_source_num:,} "
                                f"({new_source_baseline:.2%}), "
                                f"{dest_name} num {dest_node_ref['num']:,} → "
                                f"{new_dest_num:,} "
                                f"({new_dest_baseline:.2%})"
                            )

                    col1, col2 = st.columns(2)

                    with col1:
                        if st.button("Apply Reallocation", key="confirm_realloc"):
                            if amount <= 0:
                                st.error("Enter an amount greater than 0.")
                            else:
                                success, msg = reallocate_num(
                                    parent_node, source_name, dest_name, amount
                                )
                                if success:
                                    rebuild_index()
                                    st.session_state.unsaved_changes = True
                                    st.session_state.edit_mode = None
                                    st.rerun()
                                else:
                                    st.error(msg)

                    with col2:
                        if st.button("Cancel", key="cancel_realloc"):
                            st.session_state.edit_mode = None
                            st.rerun()

        st.markdown("---")

        if st.button("Save Tree", use_container_width=True):
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(
                    st.session_state.tree_data, f,
                    indent=4, ensure_ascii=False
                )
            # Also regenerate the statistics CSV from the tree
            csv_output = OUTPUT_DIR / f"{selected_kpi}.csv"
            stats_df = tree_to_csv(st.session_state.tree_data, selected_kpi)
            stats_df.to_csv(csv_output, index=False)

            st.session_state.unsaved_changes = False
            st.success("Tree and statistics saved")


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
                H.add_node(node_id, column=node["column"], category=node["category"],
                           depth=depth, split=node.get("split", False))
                if parent_id:
                    H.add_edge(parent_id, node_id)
                for child in node.get("children", []):
                    build_hierarchy_graph(child, node_id, depth + 1)

            for level in hierarchy_data.get("levels", []):
                build_hierarchy_graph(level)

            # Layout — top-down tree with branching support
            def hierarchy_layout(G):
                """Assign positions using a top-down tree layout."""
                # Find root nodes (no predecessors)
                roots = [n for n in G.nodes() if G.in_degree(n) == 0]

                positions = {}
                x_counter = [0]  # mutable counter for leaf x-positions

                def assign_pos(node, depth):
                    children = list(G.successors(node))
                    if not children:
                        # Leaf node — assign next x slot
                        positions[node] = (x_counter[0], -depth)
                        x_counter[0] += 1
                    else:
                        # Recurse children first, then center parent above them
                        for child in children:
                            assign_pos(child, depth + 1)
                        child_xs = [positions[c][0] for c in children]
                        positions[node] = (sum(child_xs) / len(child_xs), -depth)

                for root in roots:
                    assign_pos(root, 0)

                return positions

            pos = hierarchy_layout(H)

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

            node_x, node_y, node_labels, node_hover, node_colors = [], [], [], [], []
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
                # Delta purple for split branches, default blue otherwise
                if data.get("split"):
                    node_colors.append("#6B2D8B")
                else:
                    node_colors.append("#003366")

            node_trace = go.Scatter(
                x=node_x, y=node_y,
                mode="markers+text",
                text=node_labels,
                textposition="middle right",
                textfont=dict(size=14, color="white"),
                hovertext=node_hover,
                hoverinfo="text",
                marker=dict(size=30, color=node_colors, line=dict(width=2, color="white"))
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
        SPLIT_COLOR = "#6B2D8B"  # Delta purple for split branches

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

            # Split branches get Delta purple; otherwise color by type
            if data.get("split"):
                node_color.append(SPLIT_COLOR)
            else:
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
