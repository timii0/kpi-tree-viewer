"""
editor.py - Hierarchy Designer

Tkinter desktop app for visually designing hierarchy definitions. Each node
in the hierarchy represents a dimension (column + category) that defines the
nesting order used when building KPI trees. Supports split branches which
provide alternate dimensional views of the same data.

On Save, the editor:
    1. Writes the hierarchy JSON to hierarchies/{name}.json
    2. Calls cascade.py to build the full KPI tree + cascaded CSV
    3. Outputs go to output/{name}.json and output/{name}_cascaded.csv

Output format:
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

# Reserved columns in the parquet that are NOT dimensions.
# Everything else is treated as an available dimension for hierarchy building.
_RESERVED_COLUMNS = {"num", "den", "Yr_Nb", "__index_level_0__"}

# Path to the parquet cache used to discover available dimension columns.
_CACHE_FILE = Path(__file__).parent / "teradata_cache.parquet"


def _load_available_columns():
    """Discover available dimension columns from the parquet cache.

    Reads only the parquet schema (no row data loaded) and returns all
    columns that are not in _RESERVED_COLUMNS. Each column uses its own
    name as both the column and category label.

    Returns:
        list[tuple]: (column_name, category_label) pairs for use in the editor.
            Falls back to a minimal default if the parquet doesn't exist.
    """
    if _CACHE_FILE.exists():
        import pyarrow.parquet as pq
        schema = pq.read_schema(_CACHE_FILE)
        all_cols = schema.names
        return [(col, col) for col in all_cols if col not in _RESERVED_COLUMNS]
    # Fallback if no cache exists yet
    return [("sys", "sys")]


# Dynamically loaded from parquet cache. Format: (column_name, category_label)
# If the query in kpi_statistics.py changes, restart editor.py to pick up new columns.
AVAILABLE_COLUMNS = _load_available_columns()

# Transforms auto-applied when a node with a matching column is added.
# These convert raw data values into human-readable labels during tree building.
# Key = column name (matched against the column, not category).
# To add a new transform: add the column key here and handle the type in
# converter.py → apply_transform_series().
TRANSFORMS = {
    "frst_flt_ind": {"type": "int_flag", "map": {"1": "First Flight", "0": "Not First Flight"}},
}

# Directory where hierarchy definition files are stored.
HIERARCHIES_DIR = Path(__file__).parent / "hierarchies"


# ---------------------------------------------------------------------------
# HierarchyDesigner
# ---------------------------------------------------------------------------

class HierarchyDesigner:
    """Tkinter app for visually designing and saving hierarchy definitions.

    The hierarchy is displayed as a treeview where each node represents a
    dimension level. Users can add, edit, reorder, and delete nodes, toggle
    split branches, and save. Saving triggers a full tree build + cascade.

    Attributes:
        root (tk.Tk): The Tkinter root window.
        node_lookup (dict): Maps treeview item IDs to hierarchy node dicts.
        parent_lookup (dict): Maps treeview item IDs to their parent item IDs.
        json_file (str or None): Path to the currently loaded/saved hierarchy file.
        root_data (dict): In-memory hierarchy wrapped with a virtual root node.
            Structure: {"column": "(root)", "category": "hierarchy", "children": [...]}
            The actual hierarchy levels live under "children".
    """

    def __init__(self, root):
        """Initialize the hierarchy designer window.

        Args:
            root (tk.Tk): The Tkinter root window instance.
        """
        self.root = root
        self.root.title("Hierarchy Designer")
        self.root.geometry("900x600")

        # Maps treeview item_id → hierarchy node dict (for data access)
        self.node_lookup = {}
        # Maps treeview item_id → parent item_id (for tree navigation)
        self.parent_lookup = {}
        # Path to the currently open hierarchy JSON (None if unsaved)
        self.json_file = None
        # In-memory hierarchy data (wrapped with virtual root)
        self.root_data = None

        # Visual settings (unused in current version, reserved for future graph view)
        self.zoom_level = 1.0
        self.NODE_WIDTH = 160
        self.NODE_HEIGHT = 50
        self.LEVEL_HEIGHT = 120
        self.LEAF_SPACING = 180

        self._build_ui()
        self._load_default()

    # -----------------------------------------------------------------------
    # UI Construction
    # -----------------------------------------------------------------------

    def _build_ui(self):
        """Build the complete UI layout: search bar, treeview, details panel, buttons.

        Layout:
            ┌─────────────────────────────────────────────┐
            │ [Search: _______________] [Find]            │
            ├───────────────────────────────┬─────────────┤
            │                               │ Node Details│
            │   Treeview (hierarchy)        │  (JSON)     │
            │                               │             │
            ├───────────────────────────────┼─────────────┤
            │                               │ [Add Child] │
            │                               │ [Edit Node] │
            │                               │ [Toggle]    │
            │                               │ [Delete]    │
            │                               │ [Save]      │
            │                               │ [New]       │
            │                               │ [Open]      │
            │                               │ [Refresh]   │
            │                               │ [Expand]    │
            └───────────────────────────────┴─────────────┘
        """
        # Search bar at the top
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

        # Main frame holds content + button panel side by side
        self.main_frame = ttk.Frame(self.root, padding=(3, 3, 12, 12))
        self.main_frame.pack(fill="both", expand=True)

        # Left side: treeview + details panel
        self.content_frame = ttk.Frame(self.main_frame)
        self.content_frame.pack(side="left", fill="both", expand=True)

        # Treeview widget displays the hierarchy structure
        self.tree = ttk.Treeview(self.content_frame)
        self.tree.pack(side="top", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        # Details panel shows selected node's properties as JSON
        self.details_frame = ttk.Frame(self.content_frame)
        self.details_frame.pack(side="right", fill="both", padx=10)
        ttk.Label(self.details_frame, text="Node Details", font=("Arial", 14, "bold")).pack(anchor="w")
        self.details = tk.Text(self.details_frame, width=40, height=20)
        self.details.pack(fill="both", expand=True)

        # Right side: action buttons
        btn_frame = ttk.Frame(self.main_frame)
        btn_frame.pack(side="left", fill="y", padx=10, pady=10)

        for text, cmd in [
            ("Add Child", self.add_child),      # Add a new dimension under selected node
            ("Edit Node", self.edit_node),       # Modify column/category/split of selected node
            ("Toggle Split", self.toggle_split), # Quick toggle split flag on selected node
            ("Delete", self.delete_node),        # Remove selected node and all its children
            ("Save", self.save_json),            # Save hierarchy + build tree + cascade
            ("New", self.new_tree),              # Create a blank hierarchy
            ("Open", self.open_tree),            # Open an existing hierarchy from file
            ("Refresh", self.refresh_tree),      # Rebuild treeview from in-memory data
            ("Expand All", self.expand_all),     # Expand all treeview nodes
        ]:
            ttk.Button(btn_frame, text=text, command=cmd).pack(fill="x", pady=3)

    # -----------------------------------------------------------------------
    # Data Loading
    # -----------------------------------------------------------------------

    def _load_default(self):
        """Load the default hierarchy.json on startup if it exists.

        Looks for hierarchy.json in the same directory as this script.
        This provides a starting point when opening the editor.
        """
        default = Path(__file__).parent / "hierarchy.json"
        if default.exists():
            self._load_file(str(default))

    def _wrap_as_root(self, levels):
        """Wrap a levels list in a virtual root node for internal use.

        The treeview needs a single root. The virtual root with category
        "hierarchy" is never saved — only its children (the actual levels)
        are written to the JSON file.

        Args:
            levels (list): The "levels" array from a hierarchy JSON.

        Returns:
            dict: Virtual root node with the levels as children.
        """
        return {"column": "(root)", "category": "hierarchy", "children": levels}

    def _load_file(self, filepath):
        """Load a hierarchy JSON file and populate the treeview.

        Args:
            filepath (str): Full path to the hierarchy JSON file.

        Side effects:
            - Sets self.json_file to the loaded path
            - Sets self.root_data to the wrapped hierarchy
            - Rebuilds and expands the treeview
            - Updates the window title
        """
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.json_file = filepath
        self.root_data = self._wrap_as_root(data.get("levels", []))
        self._clear_and_populate()
        self.expand_all()
        self.root.title(f"Hierarchy Designer - {Path(filepath).name}")

    def _clear_and_populate(self):
        """Clear the treeview and repopulate from self.root_data.

        Resets node_lookup and parent_lookup mappings. Called after any
        structural change to the hierarchy data.
        """
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.node_lookup.clear()
        self.parent_lookup.clear()
        self.details.delete("1.0", tk.END)
        self.populate("", self.root_data)

    def _get_save_data(self):
        """Extract the saveable hierarchy data (unwraps the virtual root).

        Returns:
            dict: {"levels": [...]} — the hierarchy definition ready for JSON output.
        """
        return {"levels": self.root_data.get("children", [])}

    # -----------------------------------------------------------------------
    # Treeview Population & Interaction
    # -----------------------------------------------------------------------

    def populate(self, parent, node):
        """Recursively insert a hierarchy node into the treeview.

        Each node is displayed as "category (column)" with a split marker
        (⑂) if the node is a split branch.

        Args:
            parent (str): Treeview item ID of the parent ("" for root level).
            node (dict): Hierarchy node dict with "column", "category",
                optional "split", and optional "children".

        Side effects:
            - Inserts items into self.tree
            - Updates self.node_lookup and self.parent_lookup
        """
        split_mark = " \u2442" if node.get("split") else ""
        label = f"{node.get('category', '?')} ({node.get('column', '?')}){split_mark}"
        item_id = self.tree.insert(parent, "end", text=label)
        self.node_lookup[item_id] = node
        self.parent_lookup[item_id] = parent
        for child in node.get("children", []):
            self.populate(item_id, child)

    def refresh_tree(self):
        """Rebuild the treeview from the current in-memory hierarchy data.

        Preserves expansion state where possible and expands all nodes
        to maintain visibility while editing.
        """
        expanded = self._get_expanded()
        self._clear_and_populate()
        self._restore_expanded(expanded)
        self.expand_all()

    def on_select(self, event):
        """Handle treeview selection: display selected node's details as JSON.

        Shows all node properties except "children" (replaced with a count)
        in the details text panel.

        Args:
            event: Tkinter event (unused, required by bind signature).
        """
        sel = self.tree.selection()
        if not sel:
            return
        node = self.node_lookup[sel[0]]
        self.details.delete("1.0", tk.END)
        display = {k: v for k, v in node.items() if k != "children"}
        display["children_count"] = len(node.get("children", []))
        self.details.insert(tk.END, json.dumps(display, indent=4))

    def search(self):
        """Find and select the first node matching the search text.

        Searches by category or column name (case-insensitive).
        Scrolls the treeview to make the found node visible.
        """
        target = self.search_var.get().lower()
        for item_id, node in self.node_lookup.items():
            if target in node.get("category", "").lower() or target in node.get("column", "").lower():
                self.tree.selection_set(item_id)
                self.tree.focus(item_id)
                self.tree.see(item_id)
                break

    # -----------------------------------------------------------------------
    # Node Actions
    # -----------------------------------------------------------------------

    def add_child(self):
        """Open a dialog to add a new dimension node under the selected parent.

        The dialog offers:
            - Quick Select: dropdown of known columns from AVAILABLE_COLUMNS
            - Custom entry: type any column name and category
            - Split toggle: mark this dimension as a split branch

        If the column has a known transform (in TRANSFORMS dict), it is
        automatically attached to the new node.

        Requires a node to be selected in the treeview first.
        """
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Add Child", "Select a parent node first.")
            return

        parent_node = self.node_lookup[sel[0]]
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Dimension")
        dialog.geometry("350x320")
        dialog.transient(self.root)

        # Quick select from known columns
        ttk.Label(dialog, text="Quick Select:").pack(pady=(10, 2))
        quick_opts = [f"{cat} ({col})" for col, cat in AVAILABLE_COLUMNS]
        quick_var = tk.StringVar()
        combo = ttk.Combobox(dialog, textvariable=quick_var, values=quick_opts)
        combo.pack(fill="x", padx=10)

        ttk.Separator(dialog, orient="horizontal").pack(fill="x", pady=8, padx=10)
        ttk.Label(dialog, text="Or type custom:").pack(pady=2)

        # Manual column/category entry
        ttk.Label(dialog, text="Column").pack(pady=2)
        col_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=col_var).pack(fill="x", padx=10)

        ttk.Label(dialog, text="Category").pack(pady=2)
        cat_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=cat_var).pack(fill="x", padx=10)

        # Split branch toggle
        split_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(dialog, text="Split branch", variable=split_var).pack(pady=5)

        def on_quick(event):
            """Auto-fill column and category fields from quick select."""
            for col, cat in AVAILABLE_COLUMNS:
                if f"{cat} ({col})" == quick_var.get():
                    col_var.set(col)
                    cat_var.set(cat)
                    break

        combo.bind("<<ComboboxSelected>>", on_quick)

        def save():
            """Validate and add the new child node to the hierarchy."""
            col = col_var.get().strip()
            cat = cat_var.get().strip()
            if not col or not cat:
                messagebox.showwarning("Add", "Column and Category required.")
                return
            child = {"column": col, "category": cat}
            # Auto-attach transform if column has one defined
            if col in TRANSFORMS:
                child["transform"] = TRANSFORMS[col]
            if split_var.get():
                child["split"] = True
            parent_node.setdefault("children", []).append(child)
            self.refresh_tree()
            dialog.destroy()

        ttk.Button(dialog, text="Add", command=save).pack(pady=10)

    def edit_node(self):
        """Open a dialog to modify the selected node's column, category, and split flag.

        Cannot edit the virtual root node. If the category changes to one
        with a known transform, the transform is auto-applied. If changed
        away from a transform category, the transform is removed.
        """
        sel = self.tree.selection()
        if not sel:
            return
        node = self.node_lookup[sel[0]]
        # Don't allow editing the virtual root
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
            """Apply edits to the node and refresh the treeview."""
            node["column"] = col_var.get().strip()
            node["category"] = cat_var.get().strip()
            if split_var.get():
                node["split"] = True
            else:
                node.pop("split", None)
            # Auto-manage transforms based on column name
            if node["column"] in TRANSFORMS:
                node["transform"] = TRANSFORMS[node["column"]]
            else:
                node.pop("transform", None)
            self.refresh_tree()
            dialog.destroy()

        ttk.Button(dialog, text="Save", command=save).pack(pady=10)

    def toggle_split(self):
        """Toggle the split flag on the selected node.

        Split branches represent alternate dimensional views of the same data.
        They get tier offsets (.1, .2) in the built tree and don't affect
        the primary branch's rollup.

        Cannot toggle on the virtual root node.
        """
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
        """Delete the selected node and all its children from the hierarchy.

        Prompts for confirmation before deleting. Cannot delete the virtual
        root node. Removes the node from its parent's children list.
        """
        sel = self.tree.selection()
        if not sel:
            return
        node = self.node_lookup[sel[0]]
        if node is self.root_data:
            messagebox.showwarning("Delete", "Cannot delete root.")
            return
        if not messagebox.askyesno("Delete", "Delete this dimension and its children?"):
            return
        # Find parent node and remove this child from its children list
        parent = self.node_lookup[self.parent_lookup[sel[0]]]
        parent["children"].remove(node)
        self.tree.delete(sel[0])

    # -----------------------------------------------------------------------
    # File Operations
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
            5. Cascade produces both the tree JSON and cascaded CSV in output/.
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

        # Write the hierarchy definition JSON
        with open(self.json_file, "w", encoding="utf-8") as f:
            json.dump(hier_data, f, indent=4, ensure_ascii=False)

        # Derive output paths from the hierarchy filename
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

        # Build the KPI tree and run goal cascading
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
        """Create a new blank hierarchy with a user-provided name.

        Prompts for a name (e.g. "D0 4.0"), creates an empty hierarchy,
        and sets the save path to hierarchies/{name}.json.
        """
        name = simpledialog.askstring("New Hierarchy", "Name (e.g. 'D0 4.0'):")
        if not name:
            return
        HIERARCHIES_DIR.mkdir(exist_ok=True)
        self.json_file = str(HIERARCHIES_DIR / f"{name}.json")
        self.root_data = self._wrap_as_root([])
        self._clear_and_populate()
        self.root.title(f"Hierarchy Designer - {name}")

    def open_tree(self):
        """Open an existing hierarchy JSON file via a file dialog.

        Defaults to the hierarchies/ directory. Loads and displays the
        selected hierarchy in the treeview.
        """
        HIERARCHIES_DIR.mkdir(exist_ok=True)
        fp = filedialog.askopenfilename(
            title="Open Hierarchy", filetypes=[("JSON", "*.json")],
            initialdir=str(HIERARCHIES_DIR))
        if fp:
            self._load_file(fp)

    # -----------------------------------------------------------------------
    # View Helpers
    # -----------------------------------------------------------------------

    def expand_all(self):
        """Expand all nodes in the treeview for full visibility."""
        def expand(item):
            self.tree.item(item, open=True)
            for c in self.tree.get_children(item):
                expand(c)
        for item in self.tree.get_children():
            expand(item)

    def _get_expanded(self):
        """Capture which treeview items are currently expanded.

        Uses object identity (id()) of the underlying node dicts to track
        state across treeview rebuilds.

        Returns:
            set[int]: Set of Python object IDs for expanded nodes.
        """
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
        """Restore treeview expansion state from a set of object IDs.

        Args:
            expanded (set[int]): Set from _get_expanded() captured before rebuild.
        """
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
