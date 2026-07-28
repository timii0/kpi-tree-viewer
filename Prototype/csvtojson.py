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
def normalize_grp_comb(grp_comb):

    category_path, value_path = grp_comb.split(";")

    cats = category_path.split("/")
    vals = value_path.split("/")

    # Remove SYS/DIV because we already start at DL/ACS

    if (
        len(cats) >= 2
        and cats[0].lower() == "sys"
        and cats[1].lower() == "div"
    ):
        cats = cats[2:]
        vals = vals[2:]

    return f"{'/'.join(cats)};{'/'.join(vals)}"


dl_node = find_or_create(
    root,
    "DL",
    "sys"
)

acs_node = find_or_create(
    dl_node,
    "ACS",
    "div"
)

# ==========================
# BUILD TREE
# ==========================

for _, row in df.iterrows():

    hierarchy  = normalize_grp_comb(
    row["Grp_Comb"]
)

    if pd.isna(hierarchy):
        continue

    category_path, value_path = hierarchy.split(";")

    categories = category_path.split("/")
    values = value_path.split("/")

    current = acs_node

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

    current["num"] += int(row["Num"])
    current["den"] += int(row["Den"])

    current["baseline"] = float(
        str(row["A0"])
        .replace("%", "")
    )

    current["contribution"] = float(
        str(row["Contribution"])
        .replace("%", "")
    )

def rollup(node):

    children = node.get("children", [])

    for child in children:
        rollup(child)

    if children:

        node["num"] = sum(
            child["num"]
            for child in children
        )

        node["den"] = sum(
            child["den"]
            for child in children
        )

    node["goal"] = (
        node["num"] / node["den"]
        if node["den"] > 0
        else 0
    )

def calculate_contributions(
    node,
    parent_den=None
):

    node["contribution"] = (
        1.0
        if parent_den is None
        else (
            node["den"] / parent_den
            if parent_den > 0
            else 0
        )
    )

    for child in node.get("children", []):

        calculate_contributions(
            child,
            node["den"]
        )


rollup(root)
calculate_contributions(root)
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