import json
import pandas as pd
from pathlib import Path


INPUT_FILE = Path("assets/D0.csv")
OUTPUT_FILE = Path("output/D0.json")


def clean_number(value):

    if pd.isna(value):
        return 0

    return int(
        str(value)
        .replace(",", "")
        .strip()
    )


def clean_percent(value):

    if pd.isna(value) or value == "":
        return 0

    return (
        float(
            str(value)
            .replace("%", "")
            .strip()
        ) / 100
    )


# =====================================================
# CREATE NODE
# =====================================================

def create_node(row):

    num = clean_number(row["D0_Num"])
    den = clean_number(row["D0_Den"])

    baseline = (
        num / den
        if den > 0
        else 0
    )

    return {
        "id": row["Node_Name"].strip(),
        "name": row["Node_Name"].strip(),
        "category": row["Category"],
        "type": "Goal",

        "tier": int(row["Tier"]),

        "num": num,
        "den": den,

        "baseline": baseline,
        "goal": baseline,

        "contribution": clean_percent(
            row["Contribution"]
        ),

        "path": "",
        "children": []
    }


# =====================================================
# LOAD CSV
# =====================================================

df = pd.read_csv(INPUT_FILE)

df = pd.read_csv(INPUT_FILE)

df = df[
    [
        "Baseline",
        "Category",
        "Tier",
        "Parent_Node",
        "Node_Name",
        "D0_Num",
        "D0_Den",
        "Baseline",
        "Stretch",
        "Contribution",
        "Goal D0 Num",
        "Goal D0 Den",
        "Goal"
    ]
]

df.columns = (
    df.columns
    .str.strip()
)

# =====================================================
# CREATE ALL NODES
# =====================================================

nodes = {}

for _, row in df.iterrows():

    node_name = row["Node_Name"].strip()

    nodes[node_name] = create_node(row)

# =====================================================
# BUILD TREE
# =====================================================

root = nodes["Nwk Sys"]

for _, row in df.iterrows():

    node_name = row["Node_Name"].strip()

    parent_name = str(
        row["Parent_Node"]
    ).strip()

    if (
        pd.isna(row["Parent_Node"])
        or parent_name == ""
        or node_name == "Nwk Sys"
    ):
        continue

    parent = nodes[parent_name]

    parent["children"].append(
        nodes[node_name]
    )

# =====================================================
# BUILD PATHS
# =====================================================

def update_paths(
    node,
    parent_path=""
):

    if parent_path:

        node["path"] = (
            f"{parent_path}/"
            f"{node['name']}"
        )

    else:

        node["path"] = node["name"]

    for child in node["children"]:

        update_paths(
            child,
            node["path"]
        )


# =====================================================
# GOAL CASCADE
# =====================================================

def cascade_goals(
    node,
    inherited_gap=None
):

    # Enterprise node

    if inherited_gap is None:

        node["goal"] = (
            node["baseline"]
            * 1.03
        )

        inherited_gap = (
            node["goal"]
            - node["baseline"]
        )

    for child in node["children"]:

        child_gap = (
            inherited_gap
            * child["contribution"]
        )

        child["goal"] = (
            child["baseline"]
            + child_gap
        )

        cascade_goals(
            child,
            child_gap
        )

# =====================================================
# EXECUTE
# =====================================================

update_paths(root)

cascade_goals(root)

# =====================================================
# SAVE
# =====================================================

with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        root,
        f,
        indent=4
    )

print(
    f"Created {OUTPUT_FILE}"
)