import tkinter as tk
from treenode import TreeNode
from treeviewer import TreeViewer
import json

 
# Example usage
if __name__ == "__main__":
    # Create root node
    sys = TreeNode("D0/Sys", 1)

    # Top-level divisions
    domestic = TreeNode("D0/Domestic", 0.5)
    international = TreeNode("D0/International", 0.5)

    sys.add_child(domestic)
    sys.add_child(international)

    # =========================
    # Domestic Regions
    # =========================

    MIDWRegion = TreeNode("D0/Region/MIDWEST", 0.25)
    EASTRegion = TreeNode("D0/Region/EAST", 0.25)
    SOUTHRegion = TreeNode("D0/Region/SOUTH", 0.25)
    WESTRegion = TreeNode("D0/Region/WEST", 0.25)

    domestic.add_child(MIDWRegion)
    domestic.add_child(EASTRegion)
    domestic.add_child(SOUTHRegion)
    domestic.add_child(WESTRegion)

    # Domestic Stations
    JFK = TreeNode("D0/Station/JFK", 0.125, 3)
    ATL = TreeNode("D0/Station/ATL", 0.125, 15)

    MSP = TreeNode("D0/Station/MSP", 0.125, 20)
    POR = TreeNode("D0/Station/POR", 0.125, 6)

    DFW = TreeNode("D0/Station/DFW", 0.125, 12)
    MIA = TreeNode("D0/Station/MIA", 0.125, 10)

    LAX = TreeNode("D0/Station/LAX", 0.125, 18)
    SEA = TreeNode("D0/Station/SEA", 0.125, 8)

    MIDWRegion.add_child(MSP)
    MIDWRegion.add_child(POR)

    EASTRegion.add_child(JFK)
    EASTRegion.add_child(ATL)

    SOUTHRegion.add_child(DFW)
    SOUTHRegion.add_child(MIA)

    WESTRegion.add_child(LAX)
    WESTRegion.add_child(SEA)

    # =========================
    # International Continents
    # =========================

    Europe = TreeNode("D0/Region/EUROPE", 0.25)
    Asia = TreeNode("D0/Region/ASIA", 0.25)
    SouthAmerica = TreeNode("D0/Region/SOUTHAMERICA", 0.25)
    Africa = TreeNode("D0/Region/AFRICA", 0.25)

    international.add_child(Europe)
    international.add_child(Asia)
    international.add_child(SouthAmerica)
    international.add_child(Africa)

    # International Stations
    LHR = TreeNode("D0/Station/LHR", 0.125, 11)
    CDG = TreeNode("D0/Station/CDG", 0.25, 9)

    NRT = TreeNode("D0/Station/NRT", 0.125, 14)
    SIN = TreeNode("D0/Station/SIN", 0.125, 16)

    GRU = TreeNode("D0/Station/GRU", 0.125, 7)
    SCL = TreeNode("D0/Station/SCL", 0.125, 5)

    LOS = TreeNode("D0/Station/LOS", 0.125, 4)
    CAI = TreeNode("D0/Station/CAI", 0.125, 6)

    Europe.add_child(LHR)
    Europe.add_child(CDG)

    Asia.add_child(NRT)
    Asia.add_child(SIN)

    SouthAmerica.add_child(GRU)
    SouthAmerica.add_child(SCL)

    Africa.add_child(LOS)
    Africa.add_child(CAI)


    # Display the tree
    print("Tree Structure:")
    
    # sys.display_tree()

    # render_tree(sys)
    def json_display_tree(filename, node=None, prefix="", is_last=True):

        if node is None:
            with open(filename, "r", encoding="utf-8") as f:
                node = json.load(f)

        connector = "└── " if is_last else "├── "

        print(
            f"{prefix}{connector}"
            f"{node['name']} [{node.get('category', 'Unknown')}] "
            # f"({node['score']})"
        )

        new_prefix = prefix + ("    " if is_last else "│   ")

        children = node.get("children", [])

        for i, child in enumerate(children):
            json_display_tree(
                filename,
                child,
                new_prefix,
                i == len(children) - 1
            )

   

    sys = tk.Tk()

    app = TreeViewer(
        sys
    )

    sys.mainloop()

    



    



