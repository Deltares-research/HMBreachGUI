"""Editable solver settings and model-default overrides."""

import math
import tkinter as tk
from copy import deepcopy
from tkinter import messagebox, ttk

from GUI.table_edit import TableCellEditor


PHYSICAL_FIELDS = (
    ("g", "Gravity (m/s²)", "9.81236"),
    ("rho_w", "Water density (kg/m³)", "1000"),
    ("rho_s", "Sediment density (kg/m³)", "2650"),
    ("temperature_c", "Water temperature (°C)", "15"),
    ("f0", "Bed friction coefficient f0 (-)", "0.05"),
    ("fki", "Friction coefficient fki (-)", "0.333"),
    ("rk3", "Roughness coefficient rk3 (-)", "0.0015"),
    ("phi_deg", "Friction angle (degrees)", "variant-dependent"),
    ("erosion_a", "Erosion coefficient A (-)", "0.018"),
    ("erosion_b", "Erosion coefficient B (-)", "variant-dependent"),
    ("delta_n", "Dilatancy delta n (-)", "0.04"),
)
OPTION_FIELDS = (
    ("max_angle_iterations", "Maximum angle iterations", "80", True),
    ("max_steps", "Maximum calculation steps", "2000000", True),
    ("alpha_min_deg", "Minimum angle (degrees)", "5", False),
    ("alpha_max_deg", "Maximum angle (degrees)", "89.9", False),
    ("angle_tolerance_deg", "Angle tolerance (degrees)", "1e-8", False),
    ("equilibrium_relative_tolerance", "Equilibrium relative tolerance (-)", "0.01", False),
    ("critical_froude_guard", "Critical Froude guard (-)", "1e-8", False),
    ("minimum_ds_factor", "Minimum step factor (-)", "1e-8", False),
    ("concentration_margin", "Concentration margin (-)", "1e-10", False),
    ("adaptive_relative_tolerance", "Adaptive relative tolerance (-)", "1e-3", False),
    ("adaptive_absolute_tolerance", "Adaptive absolute tolerance", "1e-8", False),
)


def _number(text, label, integer=False):
    try:
        value = float(text)
    except ValueError as error:
        raise ValueError(f"{label} must be a number.") from error
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite.")
    if integer:
        if not value.is_integer() or not -2147483648 <= value <= 2147483647:
            raise ValueError(f"{label} must be an integer.")
        return int(value)
    return value


class SettingsEditor(ttk.Frame):
    def __init__(self, master=None, on_change=None, model_parent=None):
        super().__init__(master)
        self.on_change = on_change
        self._loading = False
        self._width_points = []
        self._width_geometry_present = False

        self.canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        contents = ttk.Frame(self.canvas, padding=8)
        self._contents_window = self.canvas.create_window((0, 0), window=contents, anchor="nw")
        contents.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_contents)
        self._contents = contents

        intro = ttk.Label(
            contents,
            text=(
                "Blank fields use solver defaults. Changing a width model may require changes "
                "to initial width and layer flow widths on the Input tab. Layer angles and "
                "hydraulic gradients are edited on the Input tab. Legacy alfa_reset, a_1_n0 "
                "and d50d15 overrides are not supported by the current solver."
            ),
            wraplength=950,
        )
        intro.pack(fill="x", pady=(0, 6))

        if model_parent is None:
            choices = ttk.LabelFrame(contents, text="Model choices", padding=6)
            choices.pack(fill="x", pady=4)
        else:
            choices = model_parent
        self.mode = self._combo(choices, "Calculation mode", (
            ("Default (breach)", None), ("Breach", "breach"), ("Turbulence", "turbulence"),
        ))
        self.width_model = self._combo(choices, "Flow-width model", (
            ("Default (B-Constant)", None), ("B-Constant", "b_constant"),
            ("Unit width (B-Constant alias)", "unit_width"), ("B-Fit", "b_fit"),
            ("B-Calc / fanning", "b_calc"), ("Fanning (B-Calc alias)", "fanning"),
            ("Width geometry", "geometry"),
        ))
        self.erosion_variant = self._combo(choices, "Erosion formulation", (
            ("Default (Variant 2)", None), ("Variant 1", "variant_1"),
            ("Variant 2", "variant_2"),
        ))
        self.erosion_variant.bind("<<ComboboxSelected>>", self._variant_changed, add="+")

        model = ttk.LabelFrame(contents, text="Flow-width settings", padding=6)
        model.pack(fill="x", pady=4)
        self.fit_type = self._combo(model, "B-Fit function", (
            ("Default (Poly4)", None), ("Straight line", "straight_line"),
            ("Poly2", "poly2"), ("Poly3", "poly3"), ("Poly4", "poly4"),
            ("Exponential", "exp"), ("Power", "power"), ("Logarithmic", "log"),
            ("Rodbard", "rodbard"), ("Gamma variate", "gamma_variate"),
        ))
        self.fit_iterations = self._field(model, "B-Fit iteration limit", "1000")
        ttk.Label(
            model, text="B-Fit settings apply only in B-Fit mode; clear them when switching modes.",
            wraplength=900,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Label(model, text="Width geometry points").grid(row=3, column=0, sticky="nw", pady=3)
        table_frame = ttk.Frame(model)
        table_frame.grid(row=3, column=1, sticky="ew", pady=3)
        self.width_table = ttk.Treeview(table_frame, columns=("s_m", "width_m"), show="headings", height=5)
        self.width_table.heading("s_m", text="Distance s (m)")
        self.width_table.heading("width_m", text="Width (m)")
        for column in ("s_m", "width_m"):
            self.width_table.column(column, width=130, anchor="e")
        self.width_table.pack(fill="x")
        self._width_cell_editor = TableCellEditor(self.width_table)
        self.width_table.bind("<Button-1>", self._begin_width_cell_edit)
        width_actions = ttk.Frame(table_frame)
        width_actions.pack(fill="x", pady=3)
        ttk.Button(width_actions, text="Add width point", command=self.add_width_point).pack(side="left")
        ttk.Button(width_actions, text="Remove width point", command=self.remove_width_point).pack(
            side="left", padx=5
        )
        ttk.Label(
            model, text="Width geometry points are valid only in width-geometry mode.",
            wraplength=900,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=3)
        model.columnconfigure(1, weight=1)

        physical = ttk.LabelFrame(contents, text="Physical constants", padding=6)
        physical.pack(fill="x", pady=4)
        ttk.Label(physical, text="Constant").grid(row=0, column=0, sticky="w")
        ttk.Label(physical, text="Default").grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(physical, text="Override").grid(row=0, column=2, sticky="w")
        self.physical_fields = {}
        self._physical_labels = {}
        for key, label, default in PHYSICAL_FIELDS:
            row = len(self.physical_fields) + 1
            ttk.Label(physical, text=label).grid(row=row, column=0, sticky="w", pady=2)
            label_widget = ttk.Label(physical, text=default)
            label_widget.grid(row=row, column=1, sticky="w", padx=8, pady=2)
            variable = tk.StringVar()
            variable.trace_add("write", self._edited)
            ttk.Entry(physical, textvariable=variable).grid(row=row, column=2, sticky="ew", pady=2)
            self.physical_fields[key] = variable
            self._physical_labels[key] = label_widget
        physical.columnconfigure(2, weight=1)

        numerical = ttk.LabelFrame(contents, text="Numerical options", padding=6)
        numerical.pack(fill="x", pady=4)
        self.option_fields = {}
        for key, label, default, _integer in OPTION_FIELDS:
            self.option_fields[key] = self._field(numerical, label, default)
        self.adaptive = self._combo(numerical, "Adaptive step sizing", (
            ("Default (off)", None), ("Off", False), ("On", True),
        ))
        ttk.Button(
            contents, text="Reset physical and numerical overrides", command=self._confirm_reset
        ).pack(anchor="w", pady=4)
        self.message = ttk.Label(contents, wraplength=950)
        self.message.pack(fill="x", pady=4)
        self._variant_changed()

    def _update_scroll_region(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_contents(self, event):
        self.canvas.itemconfigure(self._contents_window, width=event.width)

    def _field(self, parent, label, default, return_label=False):
        row = sum(1 for child in parent.winfo_children() if isinstance(child, ttk.Label))
        label_widget = ttk.Label(parent, text=f"{label}  (default: {default})")
        label_widget.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        variable = tk.StringVar()
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=2)
        variable.trace_add("write", self._edited)
        parent.columnconfigure(1, weight=1)
        return (variable, label_widget) if return_label else variable

    def _combo(self, parent, label, values):
        row = sum(1 for child in parent.winfo_children() if isinstance(child, ttk.Label))
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        variable = tk.StringVar()
        combo = ttk.Combobox(
            parent, textvariable=variable, values=tuple(title for title, _value in values),
            state="readonly",
        )
        combo._choice_values = list(values)
        combo.grid(row=row, column=1, sticky="ew", pady=2)
        combo.bind("<<ComboboxSelected>>", self._edited, add="+")
        parent.columnconfigure(1, weight=1)
        return combo

    def selected(self, key):
        combo = {
            "mode": self.mode,
            "width_model": self.width_model,
            "width_fit_type": self.fit_type,
            "erosion_variant": self.erosion_variant,
            "adaptive_step_sizing": self.adaptive,
        }[key]
        index = combo.current()
        return combo._choice_values[index][1] if 0 <= index < len(combo._choice_values) else None

    def _set_combo(self, combo, value):
        for index, (_label, current) in enumerate(combo._choice_values):
            if type(current) is type(value) and current == value:
                combo.current(index)
                return
        combo._choice_values.append((f"Unsupported: {value}", value))
        combo.configure(values=tuple(label for label, _value in combo._choice_values))
        combo.current(len(combo._choice_values) - 1)

    def _edited(self, *_):
        if not self._loading and self.on_change is not None:
            self.on_change()

    def _variant_changed(self, *_):
        variant = self.selected("erosion_variant")
        if variant is None or variant == "variant_2":
            phi, erosion_b = "29", "0.3"
        elif variant == "variant_1":
            phi, erosion_b = "32", "0.06"
        else:
            phi, erosion_b = "variant-dependent", "variant-dependent"
        for key, default in (("phi_deg", phi), ("erosion_b", erosion_b)):
            self._physical_labels[key].configure(text=default)

    def set_case(self, case):
        self._width_cell_editor.cancel()
        settings = case.get("settings", {})
        constants = settings.get("physical_constants", {})
        options = settings.get("model_options", {})
        width_points = settings.get("width_geometry", [])
        if not isinstance(constants, dict) or not isinstance(options, dict):
            raise ValueError("Physical constants and model options must be objects.")
        if not isinstance(width_points, list) or any(not isinstance(point, dict) for point in width_points):
            raise ValueError("Width geometry must be an array of point objects.")
        for index, point in enumerate(width_points, 1):
            for key in ("s_m", "width_m"):
                if key in point and (
                    isinstance(point[key], bool) or not isinstance(point[key], (int, float))
                ):
                    raise ValueError(f"Width point {index} {key} must be a number.")
        for container, keys in (
            (settings, ("mode", "width_model", "width_fit_type")),
            (constants, ("erosion_variant",)),
            (options, ("adaptive_step_sizing",)),
        ):
            for key in keys:
                if key in container and container[key] is None:
                    raise ValueError(f"{key} cannot be null.")
        for container, keys in (
            (settings, ("width_fit_max_iterations",)),
            (constants, tuple(key for key, _, _ in PHYSICAL_FIELDS)),
            (options, tuple(key for key, _, _, _ in OPTION_FIELDS)),
        ):
            for key in keys:
                if key in container and (
                    isinstance(container[key], bool) or not isinstance(container[key], (int, float))
                ):
                    raise ValueError(f"{key} must be a number.")
        self._loading = True
        try:
            for combo, value in (
                (self.mode, settings.get("mode")),
                (self.width_model, settings.get("width_model")),
                (self.fit_type, settings.get("width_fit_type")),
                (self.erosion_variant, constants.get("erosion_variant")),
                (self.adaptive, options.get("adaptive_step_sizing")),
            ):
                unsupported = [
                    index for index, (label, _value) in enumerate(combo._choice_values)
                    if label.startswith("Unsupported: ")
                ]
                for index in reversed(unsupported):
                    combo._choice_values.pop(index)
                combo.configure(values=tuple(label for label, _value in combo._choice_values))
                self._set_combo(combo, value)
            self.fit_iterations.set(
                str(settings["width_fit_max_iterations"])
                if "width_fit_max_iterations" in settings else ""
            )
            for key, variable in self.physical_fields.items():
                variable.set(str(constants[key]) if key in constants else "")
            for key, variable in self.option_fields.items():
                variable.set(str(options[key]) if key in options else "")
            self._width_points = deepcopy(width_points)
            self._width_geometry_present = "width_geometry" in settings
            self.width_table.delete(*self.width_table.get_children())
            for point in self._width_points:
                self._append_point(point)
            self.message.configure(text="")
        finally:
            self._loading = False
        self._variant_changed()

    def _append_point(self, point):
        return self.width_table.insert(
            "", "end", values=(point.get("s_m", ""), point.get("width_m", ""))
        )

    def _begin_width_cell_edit(self, event):
        if self.width_table.identify_region(event.x, event.y) != "cell":
            return
        row = self.width_table.identify_row(event.y)
        column = self.width_table.identify_column(event.x)
        if not row or column not in ("#1", "#2"):
            return
        def finish(value):
            self.width_table.set(row, column, value)
            self._edited()

        return self._width_cell_editor.begin(
            row, column, lambda: self.width_table.set(row, column), finish
        )

    def add_width_point(self):
        self._width_cell_editor.commit()
        self._loading = True
        try:
            self._width_geometry_present = True
            self._width_points.append({})
            item = self._append_point({})
            self.width_table.selection_set(item)
        finally:
            self._loading = False
        self._edited()

    def remove_width_point(self):
        self._width_cell_editor.commit()
        selection = self.width_table.selection()
        if not selection:
            self.message.configure(text="Select a width point to remove.")
            return
        row = self.width_table.index(selection[0])
        self._loading = True
        try:
            self.width_table.delete(selection[0])
            del self._width_points[row]
            self._width_geometry_present = bool(self._width_points)
        finally:
            self._loading = False
        self._edited()

    def _confirm_reset(self):
        if not messagebox.askyesno(
            "Reset overrides?",
            "Reset all physical constants and numerical options to the solver defaults?",
            parent=self,
        ):
            return
        self._loading = True
        try:
            self.erosion_variant.current(0)
            self.adaptive.current(0)
            for variable in (*self.physical_fields.values(), *self.option_fields.values()):
                variable.set("")
        finally:
            self._loading = False
        self._variant_changed()
        self._edited()

    def apply_to_case(self, case):
        self._width_cell_editor.commit()
        had_settings = "settings" in case
        settings = case.setdefault("settings", {})
        for key, combo in (
            ("mode", self.mode), ("width_model", self.width_model),
            ("width_fit_type", self.fit_type),
        ):
            value = self.selected(key)
            if value is None:
                settings.pop(key, None)
            else:
                settings[key] = value
        iterations = self.fit_iterations.get().strip()
        if iterations:
            settings["width_fit_max_iterations"] = _number(
                iterations, "B-Fit iteration limit", True
            )
        else:
            settings.pop("width_fit_max_iterations", None)
        constants = deepcopy(settings.get("physical_constants", {}))
        options = deepcopy(settings.get("model_options", {}))
        variant = self.selected("erosion_variant")
        if variant is None:
            constants.pop("erosion_variant", None)
        else:
            constants["erosion_variant"] = variant
        for key, label, _default in PHYSICAL_FIELDS:
            text = self.physical_fields[key].get().strip()
            if text:
                constants[key] = _number(text, label)
            else:
                constants.pop(key, None)
        for key, label, _default, integer in OPTION_FIELDS:
            text = self.option_fields[key].get().strip()
            if text:
                options[key] = _number(text, label, integer)
            else:
                options.pop(key, None)
        adaptive = self.selected("adaptive_step_sizing")
        if adaptive is None:
            options.pop("adaptive_step_sizing", None)
        else:
            options["adaptive_step_sizing"] = adaptive
        for key, value in (("physical_constants", constants), ("model_options", options)):
            if value or key in settings:
                settings[key] = value
        if self._width_geometry_present:
            points = []
            rows = self.width_table.get_children()
            for row, original in enumerate(self._width_points):
                point = deepcopy(original)
                values = self.width_table.item(rows[row], "values")
                for column, key in enumerate(("s_m", "width_m")):
                    point[key] = _number(
                        values[column].strip(), f"Width point {row + 1} {key}"
                    )
                points.append(point)
            settings["width_geometry"] = points
        else:
            settings.pop("width_geometry", None)
        if not had_settings and not settings:
            case.pop("settings")
