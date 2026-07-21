import teradatasql
import pandas as pd
import json
import getpass as gp
import os
import csv
import random
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


TD_HOST = os.getenv('TD_HOST', 'dwprod')
TD_USER = os.getenv('TD_USER') or input('Teradata username (TD_USER): ').strip()
TD_PASS = os.getenv('TD_PASS') or gp.getpass('Teradata password (TD_PASS): ')
TD_LOGMECH = os.getenv('TD_LOGMECH', 'LDAP')
 

def td_connect():
    return teradatasql.connect(host=TD_HOST, user=TD_USER, password=TD_PASS, logmech=TD_LOGMECH)
 
# def td_query(sql: str) -> pd.DataFrame:
#     with td_connect() as conn:
#         return  pd.read_sql(
#             """
#         SELECT 
#             DISTINCT grp_comb,
#             goal_owner,
#             kpi_code
#         FROM zods_kpi.ref_kpi_goals
#         WHERE goal_year = 2026
#         AND kpi_code = 'MSI'
#         ORDER BY goal_owner, grp_comb;

#         """
#             , conn)



def assign_contributions(node):

    children = node.get("children", [])

    if not children:
        return

    # Generate random weights
    weights = [random.random() for _ in children]

    total = sum(weights)

    contributions = [
        round((w / total) * 100, 2)
        for w in weights
    ]

    # Fix rounding so total is exactly 100
    contributions[-1] += round(
        100 - sum(contributions),
        2
    )

    for child, contribution in zip(
        children,
        contributions
    ):
        child["contribution"] = contribution

    for child in children:
        assign_contributions(child)       


with td_connect() as conn:

    df = pd.read_sql(
        """
        SELECT 
            DISTINCT grp_comb,
            goal_owner,
            kpi_code
        FROM zods_kpi.ref_kpi_goals
        WHERE goal_year = 2026
        --AND kpi_code = 'MSI'
        ORDER BY goal_owner, grp_comb;

        """,
        conn
    )

def create_node(name, category):
    return {
        "id": name,
        "name": name,
        "category": category,
        "path": "",
        "tier": 0,
        "contribution": 1,
        "type": "Goal",
        "children": []
    }   

def find_or_create(parent, name, category):

    for child in parent["children"]:
        if child["name"] == name:
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


def export_to_csv(root, kpi_code):

    rows = []

    def walk(
        node,
        parent_name="",
        category_path="",
        node_path=""
    ):

        current_category_path = (
            node.get("category", "")
            if not category_path
            else f"{category_path}/{node.get('category', '')}"
        )

        current_node_path = (
            node["name"]
            if not node_path
            else f"{node_path}/{node['name']}"
        )

        children = node.get("children", [])

        child_count = len(children)

        is_leaf = child_count == 0

        rows.append({
            "KPI": kpi_code,
            "Node Name": node["name"],
            "Parent": parent_name,
            "Category": node.get("category", ""),
            "Tier": node.get("tier", 0),
            "Contribution": node.get("contribution", 100),
            "Target/Goal": node.get("type", "Goal"),
            "Category Path": current_category_path,
            "Node Path": current_node_path,
            "Child Count": child_count,
            "Leaf": "Yes" if is_leaf else "No"
        })

        for child in children:
            walk(
                child,
                node["name"],
                current_category_path,
                current_node_path
            )

    walk(root)

    csv_filename = OUTPUT_DIR/f"{kpi_code}.csv"

    with open(
        csv_filename,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "KPI",
                "Node Name",
                "Parent",
                "Category",
                "Tier",
                "Contribution",
                "Target/Goal",
                "Category Path",
                "Node Path",
                "Child Count",
                "Leaf"
            ]
        )

        writer.writeheader()
        writer.writerows(rows)

    print(f"Created {csv_filename}")

for kpi_code, group in df.groupby("kpi_code"):

    root = {
        "id": f"{kpi_code}",
        "name": f"{kpi_code}",
        "category": "Root",
        "tier": 0,
        "path": "",
        "score": 0,
        "contribution": 1,
        "children": []
    }

    for _, row in group.iterrows():

        hierarchy = row["grp_comb"]

        category_path, value_path = hierarchy.split(";")

        categories = category_path.split("/")
        values = value_path.split("/")

        current = root

        for category, value in zip(categories, values):

            current = find_or_create(
                current,
                value,
                category
            )

    assign_contributions(root)
    update_tree(root)

    json_filename = OUTPUT_DIR/f"{kpi_code}.json"

    with open(
        json_filename,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            root,
            f,
            indent=4,
            ensure_ascii=False
        )

    
    export_to_csv(
        root,
        kpi_code
    )

    print(f"Created {json_filename}")


