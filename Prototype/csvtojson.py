import json
import pandas as pd


def create_node(name, category):

    return {
        "id": name,
        "name": name,
        "category": category,
        "type": "Goal",
        "path": "",
        "tier": 0,
        "num": 0,
        "den": 0,
        "baseline": 0,
        "contribution": 0,

        "children": []
    }


def find_or_create(parent, name, category):

    for child in parent["children"]:

        if (
            child["name"] == name and
            child["category"] == category
        ):
            return child

    node = create_node(
        name,
        category
    )

    parent["children"].append(node)

    return node


def update_tree(node, tier=0, parent_path=""):
    node["tier"] = tier
    if parent_path:

        node["path"] = (
            f"{parent_path}/{node['name']}"
        )

    else:

        node["path"] = node["name"]

    for child in node["children"]:

        update_tree(
            child,
            tier + 1,
            node["path"]
        )


# ==========================
# LOAD CSV
# ==========================

df = pd.read_csv(
    "assets/A0.csv"
)

# ==========================
# ROOT
# ==========================

kpi_code = df["KPI"].iloc[0]

root = {
    "id": kpi_code,
    "name": kpi_code,

    "category": "Root",
    "type": "Goal",

    "path": "",
    "tier": 0,

    "num": 0,
    "den": 0,

    "baseline": 0,
    "contribution": 100,

    "children": []
}

# ==========================
# BUILD TREE
# ==========================

for _, row in df.iterrows():

    hierarchy = row["Recommended Grp_Comb"]

    if pd.isna(hierarchy):
        continue

    category_path, value_path = hierarchy.split(";")

    categories = category_path.split("/")
    values = value_path.split("/")

    current = root

    for category, value in zip(
        categories,
        values
    ):

        current = find_or_create(
            current,
            value,
            category
        )

    # ----------------------
    # Metrics live on the
    # final node
    # ----------------------

    current["tier"] = int(
        row["Tier"]
    )

    current["num"] = (
        0 if pd.isna(row["Num"])
        else int(row["Num"])
    )

    current["den"] = (
        0 if pd.isna(row["Den"])
        else int(row["Den"])
    )

    current["baseline"] = float(
        str(row["A0"])
        .replace("%", "")
    )

    current["contribution"] = float(
        str(row["Contribution"])
        .replace("%", "")
    )

update_tree(root)

# ==========================
# SAVE JSON
# ==========================

filename = f"{kpi_code}.json"

with open(
    filename,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        root,
        f,
        indent=4,
        ensure_ascii=False
    )

print(
    f"Created {filename}"
)

def build_stats_rows(node, level=1, parent_den=None):

    rows = []

    hierarchy_name = (
        "YE"
        if level == 1
        else node.get("category", "")
    )

    num = node.get("num", 0)
    den = node.get("den", 0)

    goal = (
        num / den
        if den > 0
        else 0
    )

    proportion = (
        1.0
        if parent_den is None
        else den / parent_den
        if parent_den > 0
        else 0
    )

    rows.append({
        "Hierarchy": f"{level} {hierarchy_name}",
        "Drill Down": (
            ""
            if level == 1
            else node["name"]
        ),
        "Num": num,
        "Den": den,
        "Goal": goal,
        "Proportion": proportion
    })

    for child in node.get("children", []):

        rows.extend(
            build_stats_rows(
                child,
                level + 1,
                den
            )
        )

    return rows

# year_node = root.children["2026"]

# rows = build_stats_rows(year_node)

# stats_df = pd.DataFrame(rows)

# print(stats_df)

# stats_df["Goal"] = stats_df["Goal"].map(
#     lambda x: f"{x:.2%}"
# )

# stats_df["Proportion"] = stats_df["Proportion"].map(
#     lambda x: f"{x:.1%}"
# )

# print(stats_df)

def get_stats(node):

    rows = [{
        "Hierarchy": f"{node.level}",
        "Drill Down": node.name,
        "Goal": node.performance,
        "Proportion": 1.0,
        "Num": node.num,
        "Den": node.den
    }]

    for child in node.children.values():

        rows.append({
            "Hierarchy": child.level,
            "Drill Down": child.name,
            "Goal": child.performance,
            "Proportion": child.den / node.den,
            "Num": child.num,
            "Den": child.den
        })

    return pd.DataFrame(rows)