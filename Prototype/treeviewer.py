import tkinter as tk
from tkinter import ttk
from tkinter import simpledialog
from tkinter import messagebox
from tkinter import filedialog
import json
import treenode






class TreeViewer:
    def __init__(self, root, json_file=None):
        self.root = root
        self.root.title("Tree Viewer")
        self.root.geometry("600x400")
        self.node_lookup = {}
        self.parent_lookup = {}
        self.json_file = json_file
        self.zoom_level = 1.0
        self.NODE_WIDTH = 140
        self.NODE_HEIGHT = 60
        self.LEVEL_HEIGHT = 150
        self.LEAF_SPACING = 175

        search_frame = ttk.Frame(root)
        search_frame.pack(fill="x", padx=5, pady=5)

        self.search_var = tk.StringVar()

        ttk.Label(search_frame, text="Search:").pack(side="left")

        search_entry = ttk.Entry(
            search_frame,
            textvariable=self.search_var
        )
        search_entry.pack(side="left", fill="x", expand=True)

        ttk.Button(
            search_frame,
            text="Find",
            command=self.search
        ).pack(side="left", padx=5)

        search_entry.bind("<Return>", lambda e: self.search())

        # Store node data
        self.node_lookup = {}

        # Layout

        style = ttk.Style()

        style.configure(
            "Main.TFrame",
            background="#003366"
        )

        self.main_frame = ttk.Frame(root, padding=(3, 3, 12, 12), style="Main.TFrame")
        self.main_frame.pack(fill="both", expand=True)

        self.content_frame = ttk.Frame(self.main_frame)
        self.content_frame.pack(side="left", fill="both", expand=True)

        # Tree panel
        self.tree = ttk.Treeview(self.content_frame)
        self.tree.pack(side="top", fill="both", expand=True)

        # Details panel
        self.details_frame = ttk.Frame(self.content_frame)
        self.details_frame.pack(side="right", fill="both", padx=10)

        #Button panel
        
        self.button_frame = ttk.Frame(self.main_frame, style="Main.TFrame")
        self.button_frame.pack(side="left", fill="y", padx=10, pady=10)


        self.graph_frame = ttk.Frame(self.content_frame)

        self.canvas = tk.Canvas(
            self.graph_frame,
            bg="white"
        )

        self.v_scroll = ttk.Scrollbar(
            self.graph_frame,
            orient="vertical",
            command=self.canvas.yview
        )

        self.h_scroll = ttk.Scrollbar(
            self.graph_frame,
            orient="horizontal",
            command=self.canvas.xview
        )

        self.canvas.configure(
            xscrollcommand=self.h_scroll.set,
            yscrollcommand=self.v_scroll.set
        )

        self.v_scroll.pack(side="right", fill="y")
        self.h_scroll.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.canvas.bind(
            "<ButtonPress-1>",
            self.pan_start
        )

        self.canvas.bind(
            "<B1-Motion>",
            self.pan_move
        )

        
        ttk.Label(
            self.details_frame,
            text="Node Details",
            font=("Arial", 14, "bold")
        ).pack(anchor="w")

        self.details = tk.Text(
            self.details_frame,
            width=40,
            height=20
        )
        self.details.pack(fill="both", expand=True)
        
        add_button_frame = ttk.Frame(root)
        add_button_frame.pack(fill="x")

        ttk.Button(
            self.button_frame,
            text="Tree View",
            command=self.show_tree_view
        ).pack(fill="x", pady=5)

        ttk.Button(
            self.button_frame,
            text="Graph View",
            command=self.show_graph_view
        ).pack(fill="x", pady=5)

        ttk.Button(
            self.button_frame,
            text="Add Child",
            command=self.add_child
        ).pack(fill="x", pady=5)

        ttk.Button(
            self.button_frame,
            text="Save",
            command=self.save_json
        ).pack(fill="x", pady=5)

        ttk.Button(
            self.button_frame,
            text="Delete Selected",
            command=self.delete_node
        ).pack(fill="x", pady=5)

        ttk.Button(
            self.button_frame,
            text="Edit Node",
            command=self.edit_node
        ).pack(fill="x", pady=5)

        ttk.Button(
            self.button_frame,
            text="New Tree",
            command=self.new_tree
        ).pack(fill="x", pady=5)

        ttk.Button(
            self.button_frame,
            text="Open Tree",
            command=self.open_tree
        ).pack(fill="x", pady=5)

        ttk.Button(
            self.button_frame,
            text="Refresh",
            command=self.refresh_tree
        ).pack(fill="x", pady=5)

        ttk.Button(
            self.button_frame,
            text="Expand All",
            command=self.expand_all
        ).pack(fill="x", pady=5)

        ttk.Button(
            self.button_frame,
            text="Zoom +",
            command=self.zoom_in
        ).pack(fill="x", pady=5)

        ttk.Button(
            self.button_frame,
            text="Zoom -",
            command=self.zoom_out
        ).pack(fill="x", pady=5)

        # Load JSON
        # with open(json_file, "r", encoding="utf-8") as f:
        #    self.root_data  = json.load(f)

        # self.populate("", self.root_data)

        # Click event
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

    CATEGORIES = [
    "div",
    "director",
    "region",
    "station",
    "bu",
    "carrier",
    "body_type",
    "system"
    ]

    TYPES = [
        "Goal",
        "Target"
    ]


    def zoom_in(self):
        self.zoom_level *= 1.1
        self.draw_graph()

    def zoom_out(self):
        self.zoom_level *= 0.9
        self.draw_graph()

    def pan_start(self, event):
        self.canvas.scan_mark(
            event.x,
            event.y
        )

    def pan_move(self, event):
        self.canvas.scan_dragto(
            event.x,
            event.y,
            gain=1
        )

    def refresh_tree(self):
        expanded = self.get_expanded_nodes()

        for item in self.tree.get_children():
            self.tree.delete(item)

        self.node_lookup.clear()
        self.parent_lookup.clear()

        self.populate("", self.root_data)

        self.reopen_nodes(expanded)

    def populate(self, parent, node):
        """
        Recursively populate tree.
        """

        item_id = self.tree.insert(
            parent,
            "end",
            text=f"{node.get('name', node.get('id', 'Unknown'))} ({node.get('category', node.get('id', 'Unknown'))})"
        )

        self.node_lookup[item_id] = node
        self.parent_lookup[item_id] = parent

        for child in node.get("children", []):
            self.populate(item_id, child)

    def on_select(self, event):
        selection = self.tree.selection()

        if not selection:
            return

        item_id = selection[0]
        node = self.node_lookup[item_id]

        self.details.delete("1.0", tk.END)

        self.details.insert(
            tk.END,
            json.dumps(node, indent=4)
        )


    def update_metrics(self, node):
        children = node.get("children", [])

        if not children:
            return node["score"]

        child_scores = [
            self.update_metrics(child)
            for child in children
        ]

        node["score"] = sum(child_scores) / len(child_scores)

        return node["score"]
    
    def update_tiers(self, node, tier=0):
            node["tier"] = tier

            for child in node.get("children", []):
                 self.update_tiers(child, tier + 1)

    def search(self):
        target = self.search_var.get().lower()

        for item_id, node in self.node_lookup.items():
            if target in node["name"].lower():
                self.tree.selection_set(item_id)
                self.tree.focus(item_id)
                self.tree.see(item_id)
                break

    def add_child(self):
        selection = self.tree.selection()

        if not selection:
            return

        parent_item = selection[0]

        dialog = tk.Toplevel(self.root)
        dialog.title("Add Child")
        dialog.geometry("300x450")

        # Name
        ttk.Label(dialog, text="Name").pack(pady=2)

        name_var = tk.StringVar()

        name_entry = ttk.Entry(
            dialog,
            textvariable=name_var
        )
        name_entry.pack(fill="x", padx=10)

        # Category
        ttk.Label(dialog, text="Category").pack(pady=2)
        category_var = tk.StringVar()

        category_combo = ttk.Combobox(
            dialog,
            textvariable=category_var,
            values=self.CATEGORIES,
            state="readonly"
        )

        category_combo.pack(fill="x", padx=10)

        # Type
        ttk.Label(dialog, text="Type").pack(pady=2)
        type_var = tk.StringVar()

        type_combo = ttk.Combobox(
            dialog,
            textvariable=type_var,
            values=self.TYPES,
            state="readonly"
        )

        type_combo.pack(fill="x", padx=10)

        # Score
        ttk.Label(dialog, text="Score").pack(pady=2)

        score_var = tk.DoubleVar(value=0)

        score_entry = ttk.Entry(
            dialog,
            textvariable=score_var
        )
        score_entry.pack(fill="x", padx=10)

        def save_child():

            child_name = name_var.get().strip()

            if not child_name:
                return
            
            parent_node = self.node_lookup[parent_item]

            child_node = {
                "id": child_name,
                "name": child_name,
                "type": type_var.get(),
                "category": category_var.get(),
                "tier": 0,
                "score": score_var.get(),
                "contribution": 1,
                "children": []
            }

            parent_node.setdefault(
                "children",
                []
            ).append(child_node)

            child_item = self.tree.insert(
                parent_item,
                "end",
                text=child_name
            )

            self.node_lookup[child_item] = child_node
            self.parent_lookup[child_item] = parent_item

            self.tree.item(parent_item, open=True)

            self.update_tiers(self.root_data)
            self.update_metrics(self.root_data)
            self.refresh_tree()

            with open(self.json_file, "w", encoding="utf-8") as f:
                json.dump(
                    self.root_data,
                    f,
                    indent=4,
                    ensure_ascii=False
                )

            dialog.destroy()

        ttk.Button(
            dialog,
            text="Add",
            command=save_child
        ).pack(pady=10)

    def remove_lookup_entries(self, item_id):

        for child in self.tree.get_children(item_id):
            self.remove_lookup_entries(child)

        self.node_lookup.pop(item_id, None)
        self.parent_lookup.pop(item_id, None)
    
    def delete_node(self):
        selection = self.tree.selection()

        if not selection:
            return

        item_id = selection[0]

        # Prevent deleting root
        if item_id == self.tree.get_children("")[0]:
            messagebox.showwarning(
                "Delete Node",
                "Cannot delete the root node."
            )
            return
        
        confirm = messagebox.askyesno(
            "Delete Node",
            "Are you sure you want to delete this node and all of its children?"
        )
        
        if not confirm:
            return

        parent_item = self.parent_lookup[item_id]

        parent_node = self.node_lookup[parent_item]
        node_to_delete = self.node_lookup[item_id]

        # Remove from JSON structure
        parent_node["children"].remove(node_to_delete)

        # Remove from TreeView
        self.tree.delete(item_id)

        # Remove references
        self.remove_lookup_entries(item_id)
        self.update_metrics(self.root_data)

        print("Node deleted.")

    def edit_node(self):
        selection = self.tree.selection()
        
        if not selection:
            return

        item_id = selection[0]
        node = self.node_lookup[item_id]

        is_leaf = len(node.get("children", [])) == 0

        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Node")
        dialog.geometry("300x450")

        # Name
        ttk.Label(dialog, text="Name").pack(pady=2)

        name_var = tk.StringVar(
            value=node.get("name", "")
        )

        name_entry = ttk.Entry(
            dialog,
            textvariable=name_var
        )

        name_entry.pack(fill="x", padx=10)

        # Score
        ttk.Label(dialog, text="Score").pack(pady=2)

        score_var = tk.DoubleVar(
            value=node.get("score", 0)
        )

        score_entry = ttk.Entry(
            dialog,
            textvariable=score_var
        )
        score_entry.pack(fill="x", padx=10)

        # category
        ttk.Label(dialog, text="Category").pack(pady=2)

        category_var = tk.StringVar(
        value=node.get("category", "Unknown")
    )

        category_combo = ttk.Combobox(
            dialog,
            textvariable=category_var,
            values=self.CATEGORIES,
            state="readonly"
        )

        category_combo.pack(fill="x", padx=10)

        # type
        ttk.Label(dialog, text="Type").pack(pady=2)

        type_var = tk.StringVar(
        value=node.get("Type", "Unknown")
    )

        type_combo = ttk.Combobox(
            dialog,
            textvariable=type_var,
            values=self.TYPES,
            state="readonly"
        )

        type_combo.pack(fill="x", padx=10)

        # contribution
        ttk.Label(dialog, text="contribution").pack(pady=2)

        contribution_var = tk.DoubleVar(
            value=node.get("contribution", 0)
        )

        contribution_entry = ttk.Entry(
            dialog,
            textvariable=contribution_var
        )
        contribution_entry.pack(fill="x", padx=10)

        if not is_leaf:
            score_entry.config(state="disabled")
            contribution_entry.config(state="disabled")

        def save_changes():

            node["name"] = name_var.get()
            node["score"] = score_var.get()
            node["contribution"] = contribution_var.get()
            node["category"] = category_var.get()

            # Update tree display
            self.tree.item(
                item_id,
                text=f"{node['name']} [{node.get('category', 'Unknown')}]"
                
            )

            dialog.destroy()

            with open(self.json_file, "w", encoding="utf-8") as f:
                json.dump(
                    self.root_data,
                    f,
                    indent=4,
                    ensure_ascii=False
                )

        ttk.Button(
            dialog,
            text="Save",
            command=save_changes
        ).pack(pady=10)
        
        self.update_metrics(self.root_data)


   
    def save_json(self):
        with open(self.json_file, "w", encoding="utf-8") as f:
            json.dump(
                self.root_data,
                f,
                indent=4,
                ensure_ascii=False
            )

        print(f"Saved to {self.json_file}")

    def new_tree(self):
        filename = simpledialog.askstring(
            "New Tree",
            "Enter JSON filename:"        
            )
        
        if not filename:
            return
    

        if not filename.endswith(".json"):
            filename += ".json"

        root_name = simpledialog.askstring(
            "Root Node",
            "Enter root node name:" 
        )

        if not root_name:
            root_name = "Root"

        self.root_data = {
            "id": root_name,
            "name": root_name,
            "category": "unknown",
            "contribution": 1,
            "children": []
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(
                self.root_data,
                f,
                indent=4,
                ensure_ascii=False
            )

        self.json_file = filename

        #Clear treeview
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.node_lookup.clear()
        self.parent_lookup.clear()

        #Load new tree into GUI
        self.populate("", self.root_data)

        messagebox.showinfo(
            "Tree Created",
            f"Created {filename}"
        )

    def open_tree(self):

        filename = filedialog.askopenfilename(
            title="Open Tree",
            filetypes=[("JSON Files", "*.json")]
        )

        if not filename:
            return

        with open(filename, "r", encoding="utf-8") as f:
            self.root_data = json.load(f)

        self.json_file = filename

        # Clear existing tree
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.node_lookup.clear()
        self.parent_lookup.clear()

        self.details.delete("1.0", tk.END)

        # Load new tree
        self.populate("", self.root_data)

        self.root.title(
            f"Tree Viewer - {filename}"
        )

    def expand_all(self):

        def expand(item):
            self.tree.item(item, open=True)

            for child in self.tree.get_children(item):
                expand(child)

        for item in self.tree.get_children():
            expand(item)


    def update_score_by_tier_and_category(
    self,
    node,
    target_tier,
    target_category,
    new_score
):
        if (
            node.get("tier") == target_tier and
            node.get("category") == target_category
        ):
            node["score"] = new_score

        for child in node.get("children", []):
            self.update_score_by_tier_and_category(
                child,
                target_tier,
                target_category,
                new_score
            )

    def get_expanded_nodes(self):
        expanded = set()

        def recurse(item):
            if self.tree.item(item, "open"):
                node = self.node_lookup[item]
                expanded.add(node.get("path", node["name"]))

            for child in self.tree.get_children(item):
                recurse(child)

        for item in self.tree.get_children():
            recurse(item)

        return expanded
    
    def reopen_nodes(self, expanded):
        def recurse(item):
            node = self.node_lookup[item]

            if node.get("path", node["name"]) in expanded:
                self.tree.item(item, open=True)

            for child in self.tree.get_children(item):
                recurse(child)

        for item in self.tree.get_children():
            recurse(item)

    def leaf_count(self, node):

        children = node.get("children", [])

        if not children:
            return 1

        return sum(
            self.leaf_count(child)
            for child in children
        )
    

    def show_tree_view(self):
        self.graph_frame.pack_forget()

        self.tree.pack(
            side="top", fill="both", expand=True
        )

        self.details_frame.pack(
           side="right", fill="both", padx=10
        )



    def show_graph_view(self):
        self.details_frame.pack_forget()
        self.tree.pack_forget()

        self.graph_frame.pack(
            fill="both",
            expand=True
        )

        self.draw_graph()

    def draw_graph(self):
        leafs = self.leaf_count(self.root_data)
        tree_width = leafs * self.LEAF_SPACING * self.zoom_level

        self.canvas.delete("all")
        self.canvas.update_idletasks()
        width = self.canvas.winfo_width()
        self.draw_tree(
            self.root_data,
            tree_width // 2,
            100,
            tree_width
        )

        self.canvas.update_idletasks()

        self.canvas.configure(
            scrollregion=self.canvas.bbox("all")
        )
       
    def draw_node(self, x, y, node):
        colors = {
            "Target": "#003366",      # Delta Blue
            "Goal": "#808080"    # Grey
        }

        color = colors.get(
            node.get("type"),
            "#B0BEC5"  # Default gray
        )

        radius = 25    

        # circle = self.canvas.create_oval(
        #     x - radius,
        #     y - radius,
        #     x + radius,
        #     y + radius,
        #     fill=color,
        #     outline="black"
        # )

        node_width = self.NODE_WIDTH * self.zoom_level
        node_height = self.NODE_HEIGHT * self.zoom_level

        left = x - node_width / 2
        right = x + node_width / 2

        top = y - node_height / 2
        bottom = y + node_height / 2

        rect = self.canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            fill=color,
            outline="black",
            width=2
        )

        # self.canvas.create_text(
        #     x,
        #     y + 35,
        #     text=f"{node["name"]}    C:{node["category"]}"
        # )

        text = self.canvas.create_text(
            x,
            y,
            text=(
                f"{node['name']}\n"
                f"[{node.get('category', '')}]"
            ),
            justify="center"
        )

        self.canvas.tag_bind(
            rect,
            "<Button-1>",
            lambda e, n=node: self.node_clicked(n)
        )

        self.canvas.tag_bind(
            text,
            "<Button-1>",
            lambda f, n=node: self.node_clicked(n)
        )
    
    def draw_tree(self, node, x, y, width):
        # Draw current node
        self.draw_node(
            x,
            y,
            node
        )

        children = node.get("children", [])

        if not children:
            return

        # Total size of all child subtrees
        total_size = sum(
            self.subtree_size(child)
            for child in children
        )

        # Left edge of available space
        current_x = x - width / 2

        # Line colors by category
        colors = {
            "Target": "#003366",      # Delta Blue
            "Goal": "#808080"    # Grey
        }

        for child in children:

            child_size = self.subtree_size(child)

            # Give each child a proportional amount of width
            child_width = (
                width * child_size / total_size
            )

            child_x = current_x + child_width / 2
            child_y = y + self.LEVEL_HEIGHT * self.zoom_level

            line_color = colors.get(
                child.get("type"),
                "gray"
            )

            # self.canvas.create_line(
            #     x,
            #     y + 20,
            #     child_x,
            #     child_y - 20,
            #     fill=line_color,
            #     width=2
            # )

            NODE_HEIGHT = 50

            self.canvas.create_line(
                x,
                y + NODE_HEIGHT/2,
                child_x,
                child_y - NODE_HEIGHT/2,
                fill=line_color,
                width=2
            )

            self.draw_tree(
                child,
                child_x,
                child_y,
                child_width
            )

            current_x += child_width  
    
    def subtree_size(self, node):
        children = node.get("children", [])

        if not children:
            return 1

        return sum(
            self.subtree_size(child)
            for child in children
        )

#     self.update_score_by_tier_and_category(
#         self.root_data,
#         target_tier=3,
#         target_category="Station",
#         new_score=90
# )

#     self.update_metrics(self.root_data)
#     self.refresh_tree()