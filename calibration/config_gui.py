import os
import shutil
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import xml.etree.ElementTree as ET


def timestamp():
    return time.strftime("%Y%m%d_%H%M%S")


class XmlEditor(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("config.xml Editor (Generic)")
        self.geometry("1000x600")

        self.xml_path = tk.StringVar(value=os.path.join(os.getcwd(), "config.xml"))
        self.tree = None
        self.root_el = None

        # Map Treeview item -> Element
        self.item_to_element = {}

        self._build_ui()

    def _build_ui(self):
        # Top bar
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="XML path:").pack(side="left")
        ttk.Entry(top, textvariable=self.xml_path, width=70).pack(side="left", padx=6)
        ttk.Button(top, text="Browse", command=self.browse).pack(side="left")
        ttk.Button(top, text="Load", command=self.load_xml).pack(side="left", padx=6)
        ttk.Button(top, text="Save", command=self.save_xml).pack(side="left")
        ttk.Button(top, text="Backup", command=self.backup_only).pack(side="left", padx=6)

        # Main split
        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill="both", expand=True, padx=10, pady=8)

        # Left: Tree
        left = ttk.Frame(main)
        main.add(left, weight=1)

        ttk.Label(left, text="XML Structure").pack(anchor="w")

        self.treeview = ttk.Treeview(left, columns=("tag",), show="tree")
        self.treeview.pack(fill="both", expand=True)
        self.treeview.bind("<<TreeviewSelect>>", self.on_select)

        # Right: Editor
        right = ttk.Frame(main)
        main.add(right, weight=2)

        ttk.Label(right, text="Selected Node").pack(anchor="w")
        self.selected_label = ttk.Label(right, text="(none)")
        self.selected_label.pack(anchor="w", pady=(0, 8))

        # Node text value
        ttk.Label(right, text="Text value (between tags)").pack(anchor="w")
        self.text_box = tk.Text(right, height=4)
        self.text_box.pack(fill="x", expand=False)

        # Attributes
        ttk.Label(right, text="Attributes (key=value, one per line)").pack(anchor="w", pady=(10, 0))
        self.attr_box = tk.Text(right, height=10)
        self.attr_box.pack(fill="both", expand=True)

        # Buttons
        btns = ttk.Frame(right)
        btns.pack(fill="x", pady=8)
        ttk.Button(btns, text="Apply Changes to Node", command=self.apply_changes).pack(side="left")
        ttk.Button(btns, text="Reload Node", command=self.reload_node).pack(side="left", padx=8)

        # Status
        self.status = tk.StringVar(value="Load config.xml to begin.")
        ttk.Label(self, textvariable=self.status).pack(anchor="w", padx=10, pady=(0, 8))

    def browse(self):
        p = filedialog.askopenfilename(filetypes=[("XML files", "*.xml"), ("All files", "*.*")])
        if p:
            self.xml_path.set(p)

    def load_xml(self):
        path = self.xml_path.get().strip()
        if not os.path.exists(path):
            messagebox.showerror("Error", f"File not found:\n{path}")
            return

        try:
            self.tree = ET.parse(path)
            self.root_el = self.tree.getroot()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse XML:\n{e}")
            return

        self.treeview.delete(*self.treeview.get_children())
        self.item_to_element.clear()

        root_item = self.treeview.insert("", "end", text=self._node_label(self.root_el))
        self.item_to_element[root_item] = self.root_el
        self._populate_tree(root_item, self.root_el)

        self.status.set(f"Loaded: {path}")

    def _populate_tree(self, parent_item, element):
        for child in list(element):
            item = self.treeview.insert(parent_item, "end", text=self._node_label(child))
            self.item_to_element[item] = child
            self._populate_tree(item, child)

    def _node_label(self, el: ET.Element) -> str:
        # Show tag + important attribute summary (if any)
        if el.attrib:
            attrs = " ".join([f'{k}="{v}"' for k, v in el.attrib.items()])
            return f"<{el.tag} {attrs}>"
        return f"<{el.tag}>"

    def on_select(self, _event=None):
        sel = self.treeview.selection()
        if not sel:
            return
        item = sel[0]
        el = self.item_to_element.get(item)
        if el is None:
            return

        self.selected_label.config(text=f"Tag: {el.tag}")
        self._load_editor_from_element(el)

    def _load_editor_from_element(self, el: ET.Element):
        # Load text value
        self.text_box.delete("1.0", tk.END)
        txt = (el.text or "").strip()
        self.text_box.insert(tk.END, txt)

        # Load attributes
        self.attr_box.delete("1.0", tk.END)
        if el.attrib:
            lines = [f"{k}={v}" for k, v in el.attrib.items()]
            self.attr_box.insert(tk.END, "\n".join(lines))

    def reload_node(self):
        sel = self.treeview.selection()
        if not sel:
            return
        el = self.item_to_element.get(sel[0])
        if el is None:
            return
        self._load_editor_from_element(el)
        self.status.set("Reloaded node values from XML in memory.")

    def apply_changes(self):
        sel = self.treeview.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a node first.")
            return
        item = sel[0]
        el = self.item_to_element.get(item)
        if el is None:
            return

        # Apply text
        new_text = self.text_box.get("1.0", tk.END).strip()
        el.text = new_text if new_text != "" else None

        # Apply attributes
        new_attrib = {}
        attr_lines = [ln.strip() for ln in self.attr_box.get("1.0", tk.END).splitlines() if ln.strip()]
        for ln in attr_lines:
            if "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            new_attrib[k.strip()] = v.strip()
        el.attrib.clear()
        el.attrib.update(new_attrib)

        # Update tree label for that item
        self.treeview.item(item, text=self._node_label(el))

        self.status.set(f"Applied changes to <{el.tag}> (not saved yet).")

    def _backup_path(self, path: str) -> str:
        backup_dir = os.path.join(os.path.dirname(path), "config_backups")
        os.makedirs(backup_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        return os.path.join(backup_dir, f"{base}_{timestamp()}.xml")

    def backup_only(self):
        path = self.xml_path.get().strip()
        if not os.path.exists(path):
            messagebox.showerror("Error", f"File not found:\n{path}")
            return
        bpath = self._backup_path(path)
        shutil.copy2(path, bpath)
        self.status.set(f"Backup created: {bpath}")

    def save_xml(self):
        if self.tree is None or self.root_el is None:
            messagebox.showwarning("Warning", "Load an XML file first.")
            return

        path = self.xml_path.get().strip()
        if not os.path.exists(path):
            messagebox.showerror("Error", f"File not found:\n{path}")
            return

        # Backup first
        bpath = self._backup_path(path)
        shutil.copy2(path, bpath)

        # Atomic save
        tmp_path = path + ".tmp"
        try:
            self.tree.write(tmp_path, encoding="utf-8", xml_declaration=True)
            os.replace(tmp_path, path)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}")
            return

        self.status.set(f"Saved: {path} (backup: {bpath})")
        messagebox.showinfo("Saved", "config.xml saved successfully.\nBackup created automatically.")


if __name__ == "__main__":
    app = XmlEditor()
    app.mainloop()

