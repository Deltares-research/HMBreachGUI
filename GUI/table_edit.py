"""Single-click editing for Treeview cells."""

from tkinter import ttk


class TableCellEditor:
    def __init__(self, table):
        self.table = table
        self.entry = None
        self.on_commit = None
        self.original_value = None

    def begin(self, row, column, get_value, on_commit):
        self.commit()
        box = self.table.bbox(row, column)
        if not box:
            return None
        x, y, width, height = box
        self.table.selection_set(row)
        self.table.focus(row)
        self.entry = ttk.Entry(self.table)
        self.on_commit = on_commit
        self.original_value = get_value()
        self.entry.insert(0, self.original_value)
        self.entry.select_range(0, "end")
        self.entry.place(x=x, y=y, width=width, height=height)
        self.entry.bind("<Return>", self.commit)
        self.entry.bind("<FocusOut>", self.commit)
        self.entry.bind("<Escape>", self.cancel)
        self.entry.focus_set()
        return "break"

    def commit(self, _event=None):
        if self.entry is None:
            return
        entry, on_commit, original_value = self.entry, self.on_commit, self.original_value
        self.entry = None
        self.on_commit = None
        self.original_value = None
        value = entry.get()
        entry.destroy()
        if value != original_value:
            on_commit(value)

    def cancel(self, _event=None):
        if self.entry is not None:
            entry = self.entry
            self.entry = None
            self.on_commit = None
            self.original_value = None
            entry.destroy()
