"""
editor.py - Hierarchy Designer

Tkinter app for visually designing hierarchy definitions. Nodes represent
dimensions (column + category) that define the nesting order for KPI tree
construction. Supports split branches (rendered in purple).

Output format matches hierarchy.json:
    {"levels": [{"column": "sys", "category": "system", "children": [...]}]}

Usage:
    python editor.py
"""

import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, filedialog
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AVAILABLE_COLUMNS = [
    ("sys", "system"),
    ("ml_dc_1", "carrier"),
    ("ml_dc_2", "dc_carrier"),
    ("Mo_Nb", "month"),
    ("frst_flt_ind", "first_flt"),
    ("dom_int", "dom_int"),
    ("vendor", "vendor"),
    ("station", "station"),
    ("fleet", "fleet"),
]

TRANSFORMS = {
    "first_flt": {"type": "int_flag", "map": {"1": "First Flight", "0": "Not First Flight"}},
}

HIERARCHIES_DIR = Path(__file__).parent / "hierarchies"


# ---------------------------------------------------------------------------
# HierarchyDesigner
# ---------------------------------------------------------------------------

class HierarchyDesigner:
    """TreeViewer-style app for designing hierarchy definitions."""

    def __init__(self, root):
        self.root = root
        self.root.title("Hierarchy Designer")
        self.root.geometry("900x600")
        self.node_lookup = {}
        self.parent_lookup = {}
        self.json_file = None
        self.root_data = None
        self.zoom_level = 1.0
        self.NODE_WIDTH = 160
        self.NODE_HEIGHT = 50
        self.LEVEL_HEIGHT = 120
        self.LEAF_SPACING = 180

        self._build_ui()
        self._load_default()

    def _build_ui(self):
        # Search bar
        search_frame = ttk.Frame(self.root)
        search_frame.pack(fill="x", padx=5, pady=5)

        self.search_var = tk.StringVar()
        ttk.Label(search_frame, text="Search:").pack(side="left")
        entry = ttk.Entry(search_frame, textvariable=self.search_var)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(search_frame, text="Find", command=self.search).pack(side="left", padx=5)
        entry.bind("<Return>", lambda e: self.search())

        # Styling
        style = ttk.Style()

        # Main frame
        self.main_frame = ttk.Frame(self.root, padding=(3, 3, 12, 12))
        self.main_frame.pack(fill="both", expand=True)

        # Content (tree + details + graph)
        self.content_frame = ttk.Frame(self.main_frame)
        self.content_frame.pack(side="left", fill="both", expand=True)

        self.tree = ttk.Treeview(self.content_frame)
        self.tree.pack(side="top", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # Details panel
        self.details_frame = ttk.Frame(self.content_frame)
        self.details_frame.pack(side="right", fill="both", padx=10)
        ttk.Label(self.details_frame, text="Node Details", font=("Arial", 14, "bold")).pack(anchor="w")
        self.details = tk.Text(self.details_frame, width=40, height=20)
        self.details.pack(fill="both", expand=True)

        # Button panel
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.pack(side="left", fill="y", padx=10, pady=10)

        for text, cmd in [
            ("Add Child", self.add_child),
            ("Edit Node", self.edit_node),
            ("Toggle Split", self.toggle_split),
            ("Delete", self.delete_node),
            ("Save", self.save_json),
            ("New", self.new_tree),
            ("Open", self.open_tree),
            ("Refresh", self.refresh_tree),
            ("Expand All", self.expand_all),
        ]:
            ttk.Button(btn_frame, text=text, command=cmd).pack(fill="x", pady=3)

    def _load_default(self):
        default = Path(__file__).parent / "hierarchy.json"
        if default.exists():
            self._load_file(str(default))

    # -----------------------------------------------------------------------
    # Data
    # -----------------------------------------------------------------------

    def _wrap_as_root(self, levels):
        return {"column": "(root)", "category": "hierarchy", "children": levels}

    def _load_file(self, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.json_file = filepath
        self.root_data = self._wrap_as_root(data.get("levels", []))
        self._clear_and_populate()
        self.expand_all()
        self.root.title(f"Hierarchy Designer - {Path(filepath).name}")

    def _clear_and_populate(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.node_lookup.clear()
        self.parent_lookup.clear()
        self.details.delete("1.0", tk.END)
        self.populate("", self.root_data)

    def _get_save_data(self):
        return {"levels": self.root_data.get("children", [])}

    # -----------------------------------------------------------------------
    # Tree
    # -----------------------------------------------------------------------

    def populate(self, parent, node):
        split_mark = " \u2442" if node.get("split") else ""
        label = f"{node.get('category', '?')} ({node.get('column', '?')}){split_mark}"
        item_id = self.tree.insert(parent, "end", text=label)
        self.node_lookup[item_id] = node
        self.parent_lookup[item_id] = parent
        for child in node.get("children", []):
            self.populate(item_id, child)

    def refresh_tree(self):
        expanded = self._get_expanded()
        self._clear_and_populate()
        self._restore_expanded(expanded)
        # Keep tree expanded while working
        self.expand_all()

    def on_select(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        node = self.node_lookup[sel[0]]
        self.details.delete("1.0", tk.END)
        display = {k: v for k, v in node.items() if k != "children"}
        display["children_count"] = len(node.get("children", []))
        self.details.insert(tk.END, json.dumps(display, indent=4))

    def search(self):
        target = self.search_var.get().lower()
        for item_id, node in self.node_lookup.items():
            if target in node.get("category", "").lower() or target in node.get("column", "").lower():
                self.tree.selection_set(item_id)
                self.tree.focus(item_id)
                self.tree.see(item_id)
                break

    # -----------------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------------

    def add_child(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Add Child", "Select a parent node first.")
            return

        parent_node = self.node_lookup[sel[0]]
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Dimension")
        dialog.geometry("350x320")
        dialog.transient(self.root)

        # Quick select
        ttk.Label(dialog, text="Quick Select:").pack(pady=(10, 2))
        quick_opts = [f"{cat} ({col})" for col, cat in AVAILABLE_COLUMNS]
        quick_var = tk.StringVar()
        combo = ttk.Combobox(dialog, textvariable=quick_var, values=quick_opts)
        combo.pack(fill="x", padx=10)

        ttk.Separator(dialog, orient="horizontal").pack(fill="x", pady=8, padx=10)
        ttk.Label(dialog, text="Or type custom:").pack(pady=2)

        ttk.Label(dialog, text="Column").pack(pady=2)
        col_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=col_var).pack(fill="x", padx=10)

        ttk.Label(dialog, text="Category").pack(pady=2)
        cat_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=cat_var).pack(fill="x", padx=10)

        split_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(dialog, text="Split branch", variable=split_var).pack(pady=5)

        def on_quick(event):
            for col, cat in AVAILABLE_COLUMNS:
                if f"{cat} ({col})" == quick_var.get():
                    col_var.set(col)
                    cat_var.set(cat)
                    break

        combo.bind("<<ComboboxSelected>>", on_quick)

        def save():
            col = col_var.get().strip()
            cat = cat_var.get().strip()
            if not col or not cat:
                messagebox.showwarning("Add", "Column and Category required.")
                return
            child = {"column": col, "category": cat}
            if cat in TRANSFORMS:
                child["transform"] = TRANSFORMS[cat]
            if split_var.get():
                child["split"] = True
            parent_node.setdefault("children", []).append(child)
            self.refresh_tree()
            dialog.destroy()

        ttk.Button(dialog, text="Add", command=save).pack(pady=10)

    def edit_node(self):
        sel = self.tree.selection()
        if not sel:
            return
        node = self.node_lookup[sel[0]]
        if node is self.root_data:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Dimension")
        dialog.geometry("350x220")
        dialog.transient(self.root)

        ttk.Label(dialog, text="Column").pack(pady=2)
        col_var = tk.StringVar(value=node.get("column", ""))
        ttk.Entry(dialog, textvariable=col_var).pack(fill="x", padx=10)

        ttk.Label(dialog, text="Category").pack(pady=2)
        cat_var = tk.StringVar(value=node.get("category", ""))
        ttk.Entry(dialog, textvariable=cat_var).pack(fill="x", padx=10)

        split_var = tk.BooleanVar(value=node.get("split", False))
        ttk.Checkbutton(dialog, text="Split branch", variable=split_var).pack(pady=5)

        def save():
            node["column"] = col_var.get().strip()
            node["category"] = cat_var.get().strip()
            if split_var.get():
                node["split"] = True
            else:
                node.pop("split", None)
            if node["category"] in TRANSFORMS:
                node["transform"] = TRANSFORMS[node["category"]]
            else:
                node.pop("transform", None)
            self.refresh_tree()
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).pack(pady=10)

    def toggle_split(self):
        sel = self.tree.selection()
        if not sel:
            return
        node = self.node_lookup[sel[0]]
        if node is self.root_data:
            return
        if node.get("split"):
            node.pop("split")
        else:
            node["split"] = True
        self.refresh_tree()

    def delete_node(self):
        sel = self.tree.selection()
        if not sel:
            return
        node = self.node_lookup[sel[0]]
        if node is self.root_data:
            messagebox.showwarning("Delete", "Cannot delete root.")
            return
        if not messagebox.askyesno("Delete", "Delete this dimension and its children?"):
            return
        parent = self.node_lookup[self.parent_lookup[sel[0]]]
        parent["children"].remove(node)
        self.tree.delete(sel[0])

    # -----------------------------------------------------------------------
    # File operations
    # -----------------------------------------------------------------------

    def save_json(self):
        """Save hierarchy definition to JSON, then build tree and run cascade.

        Full workflow on Save:
            1. Prompts for file path if not previously saved (saves to hierarchies/).
            2. Writes the hierarchy JSON ({"levels": [...]}).
            3. Derives KPI name from the filename stem.
            4. Calls cascade() with:
               - goals_file = ./goals.csv
               - hierarchy_file = the saved hierarchy JSON
               - cache_file = ./teradata_cache.parquet
               - output_file = ./output/{kpi_name}.json
            5. Cascade produces both the tree JSON and cascaded CSV.
            6. Shows success/warning dialog.

        If teradata_cache.parquet doesn't exist, saves the hierarchy but
        skips tree building.
        """
        if not self.json_file:
            HIERARCHIES_DIR.mkdir(exist_ok=True)
            self.json_file = filedialog.asksaveasfilename(
                title="Save Hierarchy", defaultextension=".json",
                filetypes=[("JSON", "*.json")], initialdir=str(HIERARCHIES_DIR))
        if not self.json_file:
            return

        hier_data = self._get_save_data()

        # Save hierarchy definition
        with open(self.json_file, "w", encoding="utf-8") as f:
            json.dump(hier_data, f, indent=4, ensure_ascii=False)

        # Derive KPI name from filename
        kpi_name = Path(self.json_file).stem
        base_dir = Path(__file__).parent
        cache_file = base_dir / "teradata_cache.parquet"
        output_dir = base_dir / "output"
        output_dir.mkdir(exist_ok=True)
        output_json = output_dir / f"{kpi_name}.json"
        goals_file = base_dir / "goals.csv"

        if not cache_file.exists():
            messagebox.showwarning("Build", "teradata_cache.parquet not found. Hierarchy saved but tree not built.")
            return

        # Build tree + cascade
        try:
            import sys
            sys.path.insert(0, str(base_dir))
            from cascade import cascade

            cascade(
                goals_file=goals_file,
                hierarchy_file=Path(self.json_file),
                cache_file=cache_file,
                output_file=output_json
            )

            messagebox.showinfo(
                "Saved & Built",
                f"Hierarchy saved to: {Path(self.json_file).name}\n"
                f"Tree built: output/{kpi_name}.json\n"
                f"CSV: output/{kpi_name}_cascaded.csv\n\n"
                f"Open in Streamlit to view."
            )
        except Exception as e:
            messagebox.showwarning(
                "Build Warning",
                f"Hierarchy saved. Tree build had an issue:\n{e}\n\n"
                f"The hierarchy file is still saved."
            )

    def new_tree(self):
        name = simpledialog.askstring("New Hierarchy", "Name (e.g. 'D0 4.0'):")
        if not name:
            return
        HIERARCHIES_DIR.mkdir(exist_ok=True)
        self.json_file = str(HIERARCHIES_DIR / f"{name}.json")
        self.root_data = self._wrap_as_root([])
        self._clear_and_populate()
        self.root.title(f"Hierarchy Designer - {name}")

    def open_tree(self):
        HIERARCHIES_DIR.mkdir(exist_ok=True)
        fp = filedialog.askopenfilename(
            title="Open Hierarchy", filetypes=[("JSON", "*.json")],
            initialdir=str(HIERARCHIES_DIR))
        if fp:
            self._load_file(fp)

    # -----------------------------------------------------------------------
    # View helpers
    # -----------------------------------------------------------------------

    def expand_all(self):
        def expand(item):
            self.tree.item(item, open=True)
            for c in self.tree.get_children(item):
                expand(c)
        for item in self.tree.get_children():
            expand(item)

    def _get_expanded(self):
        out = set()

        def recurse(item):
            if self.tree.item(item, "open"):
                out.add(id(self.node_lookup.get(item)))
            for c in self.tree.get_children(item):
                recurse(c)

        for item in self.tree.get_children():
            recurse(item)
        return out

    def _restore_expanded(self, expanded):
        def recurse(item):
            if id(self.node_lookup.get(item)) in expanded:
                self.tree.item(item, open=True)
            for c in self.tree.get_children(item):
                recurse(c)

        for item in self.tree.get_children():
            recurse(item)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    HierarchyDesigner(root)
    root.mainloop()
