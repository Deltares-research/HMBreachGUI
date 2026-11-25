"""Read-only display of recorded computational-layer profiles."""

import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


METRICS = (
    ("step", "Step"), ("s", "s (m)"), ("x", "x (m)"), ("z", "z (m)"),
    ("width_m", "Width (m)"), ("water_level", "Water level (m)"),
    ("h", "Depth h (m)"), ("u", "Velocity u (m/s)"),
    ("c", "Concentration c (-)"), ("froude", "Froude (-)"),
    ("erosion_velocity", "Erosion velocity (m/s)"), ("q", "q (m²/s)"),
    ("total_discharge", "Discharge (m³/s)"),
    ("sediment_transport", "Sediment transport (kg/s/m)"),
    ("total_sediment_transport", "Total sediment transport (kg/s)"),
    ("sedimentation_velocity", "Sedimentation (m/s)"),
    ("entrainment_velocity", "Entrainment (m/s)"), ("ds", "ds (m)"),
    ("local_error_h", "Local error h (m)"), ("local_error_u", "Local error u (m/s)"),
    ("local_error_c", "Local error c (-)"), ("local_error_width", "Local error width (m)"),
    ("error_norm", "Error norm (-)"), ("rejected_steps", "Rejected steps"),
    ("v_wal", "Wall retreat (m/s)"),
    ("initial_sediment_transport", "Initial sediment transport (kg/s/m)"),
    ("sediment_transport_amplification", "Transport amplification (-)"),
    ("maximum_transport_ratio", "Maximum transport ratio (-)"),
    ("breach_flow_criterion_met", "Breach-flow criterion met (0/1)"),
)


class ResultsView(ttk.Frame):
    def __init__(self, master=None, on_open_results=None, on_save_results=None):
        super().__init__(master, padding=8)
        self.on_open_results = on_open_results
        self.on_save_results = on_save_results
        self._profiles = []
        self.workbook = None
        self.geometry = None

        self.status = ttk.Label(self, text="No results loaded.", wraplength=1000)
        self.status.pack(fill="x", pady=(0, 5))
        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=3)
        self.open_results = ttk.Button(
            actions, text="Open results JSON...", command=self._open_results
        )
        self.save_results = ttk.Button(
            actions, text="Save results JSON as...", command=self._save_results
        )
        self.open_workbook = ttk.Button(
            actions, text="Open results workbook", command=lambda: self._open_file(self.workbook)
        )
        self.open_geometry = ttk.Button(
            actions, text="Open initial geometry SVG", command=lambda: self._open_file(self.geometry)
        )
        for button in (self.open_results, self.save_results, self.open_workbook, self.open_geometry):
            button.pack(side="left", padx=(0, 5))
        self.file_status = ttk.Label(self, wraplength=1000)
        self.file_status.pack(fill="x", pady=3)
        selector = ttk.Frame(self)
        selector.pack(fill="x", pady=3)
        ttk.Label(selector, text="Computational layer:").pack(side="left")
        self.layer_value = tk.StringVar()
        self.layer = ttk.Combobox(selector, textvariable=self.layer_value, state="readonly", width=12)
        self.layer.pack(side="left", padx=5)
        self.layer.bind("<<ComboboxSelected>>", self._select_layer)
        self.summary = ttk.Label(
            self, text="Run a calculation or open results to see recorded profile data.",
            wraplength=1000,
        )
        self.summary.pack(fill="x", pady=4)
        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True, pady=4)
        self.table = ttk.Treeview(table_frame, show="headings")
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self, text="Values are recorded profile points. Full solver diagnostics are on the Run tab.",
            wraplength=1000,
        ).pack(fill="x", pady=(3, 0))
        self.set_files(None, None)

    def _open_results(self):
        if self.on_open_results is not None:
            self.on_open_results()

    def _save_results(self):
        if self.on_save_results is not None:
            self.on_save_results()

    def set_files(self, workbook, geometry):
        self.workbook = Path(workbook) if workbook is not None else None
        self.geometry = Path(geometry) if geometry is not None else None
        self.open_workbook.configure(state="normal" if self.workbook is not None else "disabled")
        self.open_geometry.configure(state="normal" if self.geometry is not None else "disabled")
        if self.workbook is None and self.geometry is None:
            text = "No output files associated with these results."
        else:
            text = (
                f"Workbook: {self.workbook if self.workbook is not None else 'unavailable'}\n"
                f"Initial geometry: {self.geometry if self.geometry is not None else 'unavailable'}"
            )
        self.file_status.configure(text=text)

    def set_results(self, results):
        self._profiles = results["profiles"] if results is not None else []
        self.layer.configure(values=tuple(str(profile["layer"]) for profile in self._profiles))
        if results is None:
            self.layer_value.set("")
            self.status.configure(text="No results loaded.")
            self.summary.configure(text="Run a calculation or open results to see recorded profile data.")
            self._set_points([])
            return
        count = sum(len(profile["points"]) for profile in self._profiles)
        self.status.configure(
            text=f"Loaded {len(self._profiles)} computational layers and {count} profile points."
        )
        if self._profiles:
            self.layer.current(0)
            self._select_layer()

    def _select_layer(self, _event=None):
        index = self.layer.current()
        if index < 0:
            self._set_points([])
            return
        profile = self._profiles[index]
        points = profile["points"]
        self._set_points(points)
        last = points[-1]
        self.summary.configure(
            text=(
                f"Layer {profile['layer']}: {len(points)} points. Last recorded point: "
                f"x={last['x']:.6g} m, z={last['z']:.6g} m, h={last['h']:.6g} m, "
                f"u={last['u']:.6g} m/s, c={last['c']:.6g} (-). "
                "Results refer to their stored input snapshot, which may differ from the current input."
            )
        )

    def _set_points(self, points):
        keys = set()
        for point in points:
            keys.update(point)
        known = [key for key, _label in METRICS if key in keys]
        columns = known + sorted(keys - set(known))
        self.table.configure(columns=columns)
        labels = dict(METRICS)
        for key in columns:
            self.table.heading(key, text=labels.get(key, key))
            self.table.column(key, width=max(100, min(220, len(labels.get(key, key)) * 9)))
        self.table.delete(*self.table.get_children())
        for point in points:
            self.table.insert(
                "", "end",
                values=tuple("" if point.get(key) is None else f"{point[key]:.12g}" for key in columns),
            )

    def _open_file(self, path):
        if path is None or not path.is_file():
            messagebox.showwarning("Output unavailable", f"Output file is missing: {path}", parent=self)
            return
        try:
            os.startfile(str(path.resolve()))
        except OSError as error:
            messagebox.showwarning("Unable to open output", str(error), parent=self)
