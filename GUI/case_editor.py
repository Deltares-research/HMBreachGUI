"""Editable input case, preserving JSON fields not shown in the editor."""

from copy import deepcopy
import math
import tkinter as tk
from tkinter import ttk

from GUI.case_io import validate_case
from GUI.geometry_editor import GeometryEditor, preview_profile, split_profile_layers
from GUI.settings_editor import PHYSICAL_FIELDS, SettingsEditor
from GUI.table_edit import TableCellEditor


INITIAL_FIELDS = (
    ("vz_mm_s", "Suction velocity (mm/s)"),
    ("initial_layer_thickness_m", "Initial thickness (m)"),
    ("initial_froude", "Initial Froude (-)"),
    ("initial_concentration_percent", "Initial concentration (%)"),
    ("initial_width_m", "Initial width (m; non-constant width only)"),
)
LAYER_FIELDS = (
    ("thickness_m", "Thickness (m)", False),
    ("d50_micrometre", "D50 (um)", False),
    ("porosity_percent", "Porosity (%)", False),
    ("external_gradient", "Gradient (-)", False),
    ("permeability_mm_s", "Permeability override (mm/s)", True),
    ("user_d15", "User D15 (true/false)", True),
    ("d15_micrometre", "D15 (um; optional)", True),
    ("initial_alpha_deg", "Angle (degrees; optional)", True),
    ("flow_width_m", "Flow width (m; B-Fit only)", True),
)
PHYSICAL_DEFAULTS = {key: default for key, _, default in PHYSICAL_FIELDS}


def _display(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _parse_number(text, label):
    try:
        return float(text)
    except ValueError as error:
        raise ValueError(f"{label} must be a number.") from error


class CaseEditor(ttk.Frame):
    def __init__(self, master=None, tabs_parent=None):
        super().__init__(master)
        self._case = None
        self._layers = []
        self.dirty = False
        self._loading = False
        self._derived_geometry_angles = False
        footer = ttk.Frame(self)
        footer.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        actions = ttk.Frame(footer)
        actions.pack(fill="x", pady=3)
        for text, callback in (
            ("Add layer", self.add_layer),
            ("Copy layer", self.copy_layer),
            ("Remove layer", self.remove_layer),
        ):
            ttk.Button(actions, text=text, command=callback).pack(side="left", padx=(0, 5))
        gradients = ttk.Frame(footer)
        gradients.pack(fill="x", pady=3)
        self.gradient_all = tk.StringVar()
        ttk.Entry(gradients, textvariable=self.gradient_all).pack(side="left", fill="x", expand=True)
        ttk.Button(
            gradients, text="Apply gradient to all layers", command=self._apply_gradient
        ).pack(side="left", padx=(6, 0))
        self.message = ttk.Label(footer, wraplength=650)
        self.message.pack(fill="x", pady=(2, 0))

        viewport = ttk.Frame(self)
        viewport.pack(fill="both", expand=True)
        self.content_canvas = tk.Canvas(viewport, highlightthickness=0)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.content_canvas.yview)
        self.content_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.content_canvas.pack(side="left", fill="both", expand=True)
        self.content = ttk.Frame(self.content_canvas)
        self._content_window = self.content_canvas.create_window(
            (0, 0), window=self.content, anchor="nw"
        )
        self.content.bind("<Configure>", self._update_content_layout)
        self.content_canvas.bind("<Configure>", self._update_content_layout)

        choices = ttk.LabelFrame(self.content, text="Model choices", padding=6)
        choices.pack(fill="x", padx=8, pady=(4, 2))
        self.settings = SettingsEditor(
            tabs_parent or master, on_change=self._settings_changed, model_parent=choices
        )
        self.geometry = GeometryEditor(
            tabs_parent or master,
            on_change=self._geometry_changed,
            on_match_bottom=self._match_bottom_layer,
            on_update_layers=self._update_layers_from_geometry,
        )

        self.mode_label = ttk.Label(self.content, text="No input case loaded.")
        self.mode_label.pack(anchor="w", padx=8, pady=(8, 3))
        form = ttk.Frame(self.content)
        form.pack(fill="x", padx=8, pady=4)
        self.initial_fields = {}
        for row, (key, label) in enumerate(INITIAL_FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
            variable = tk.StringVar()
            variable.trace_add("write", self._initial_changed)
            ttk.Entry(form, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=2)
            self.initial_fields[key] = variable
        form.columnconfigure(1, weight=1)

        self.angle_notice = ttk.Label(
            self.content,
            text=(
                "Layer angles are inactive while coordinate geometry is used. Calculated angles "
                "are shown for reference. To edit angles, "
                "turn off 'Use coordinate slope geometry' on the Geometry tab. Angles are "
                "omitted from saved inputs and calculations while coordinates are enabled."
            ),
            wraplength=900,
        )
        self.angle_notice.pack(fill="x", padx=8, pady=3)

        table_frame = ttk.Frame(self.content)
        table_frame.pack(fill="both", expand=True, padx=8, pady=4)
        columns = tuple(key for key, _, _ in LAYER_FIELDS) + ("effective_permeability",)
        self.table = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="browse", height=10
        )
        self.table.configure(displaycolumns=(
            "thickness_m", "initial_alpha_deg", "d50_micrometre", "user_d15", "d15_micrometre",
            "porosity_percent", "effective_permeability", "external_gradient",
            "permeability_mm_s", "flow_width_m",
        ))
        for key, label, _optional in LAYER_FIELDS:
            self.table.heading(key, text=label)
            self.table.column(key, width=145, minwidth=90, stretch=False)
        self.table.heading("effective_permeability", text="Effective permeability (mm/s)")
        self.table.column("effective_permeability", width=190, minwidth=140, stretch=False)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self._cell_editor = TableCellEditor(self.table)
        self.table.bind("<Button-1>", self._begin_cell_edit)

        self._table_hint = ttk.Label(
            self.content,
            text=(
                "Click an editable cell once to type; press Enter to finish or Escape to cancel. "
                "Effective permeability is a preview; leave the override blank to use "
                "the solver's calculated value. Gradient is the dimensionless external "
                "hydraulic gradient i for each layer."
            ),
            wraplength=900,
        )
        self._table_hint.pack(fill="x", padx=8, pady=2)

    def _update_content_layout(self, _event=None):
        width = max(1, self.content_canvas.winfo_width())
        wraplength = max(1, width - 16)
        for label in (self.angle_notice, self._table_hint):
            if int(label.cget("wraplength")) != wraplength:
                label.configure(wraplength=wraplength)
        self.content_canvas.itemconfigure(self._content_window, width=width)
        self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all"))

    def _mark_dirty(self, *_):
        if not self._loading:
            self.dirty = True

    def set_case(self, case):
        self._cell_editor.cancel()
        self._loading = True
        try:
            self._derived_geometry_angles = False
            self._case = deepcopy(case)
            self._layers = deepcopy(case["layers"])
            self.settings.set_case(case)
            self.geometry.set_case(case)
            self._update_mode_label()
            for key, _label in INITIAL_FIELDS:
                self.initial_fields[key].set(_display(case["initial_conditions"].get(key)))
            self.table.delete(*self.table.get_children())
            for layer in self._layers:
                self._append_row(layer)
            self.angle_notice.pack_forget()
            if self.geometry.enabled_var.get():
                self.angle_notice.pack(fill="x", padx=8, pady=3, before=self.table.master)
            self.message.configure(text="")
            self.dirty = False
        finally:
            self._loading = False
        self._refresh_geometry()
        self._restore_geometry_angles()
        if self.geometry.enabled_var.get():
            self.geometry.capture_reference()
        self.geometry.canvas.fit()

    def _initial_changed(self, *_):
        if not self._loading:
            self._mark_dirty()
            self._refresh_geometry()

    def _layer_changed(self, *_):
        if not self._loading:
            self._clear_derived_geometry_angles()
            self._mark_dirty()
            self._refresh_geometry()
            self.geometry.canvas.fit()

    def _clear_derived_geometry_angles(self):
        if self._derived_geometry_angles and self.geometry.enabled_var.get():
            for row in range(len(self.table.get_children())):
                values = self._row_values(row)
                values[7] = ""
                self._set_row_values(row, values)
        self._derived_geometry_angles = False

    def _geometry_changed(self):
        if not self._loading:
            self._clear_derived_geometry_angles()
            self.angle_notice.pack_forget()
            if self.geometry.enabled_var.get():
                self.angle_notice.pack(fill="x", padx=8, pady=3, before=self.table.master)
            self._mark_dirty()
            self._refresh_geometry()

    def _update_mode_label(self):
        mode = self.settings.selected("mode")
        width = self.settings.selected("width_model")
        self.mode_label.configure(
            text=f"Mode: {mode if mode is not None else 'breach'} | "
                 f"Width model: {width if width is not None else 'b_constant'}"
        )

    def _settings_changed(self):
        if not self._loading:
            self._update_mode_label()
            self._mark_dirty()
            self._refresh_geometry()

    def _row_values(self, row):
        item = self.table.get_children()[row]
        return list(self.table.item(item, "values"))

    def _set_row_values(self, row, values):
        item = self.table.get_children()[row]
        self.table.item(item, values=values)

    def _begin_cell_edit(self, event):
        if self.table.identify_region(event.x, event.y) != "cell":
            return
        row_id = self.table.identify_row(event.y)
        column_id = self.table.identify_column(event.x)
        if not row_id or not column_id.startswith("#"):
            return
        display_index = int(column_id[1:]) - 1
        key = self.table.cget("displaycolumns")[display_index]
        columns = self.table.cget("columns")
        column = columns.index(key)
        if key == "effective_permeability":
            self._cell_editor.commit()
            return
        if key == "initial_alpha_deg" and self.geometry.enabled_var.get():
            self._cell_editor.commit()
            return

        def finish(value):
            values = list(self.table.item(row_id, "values"))
            values[column] = value
            self.table.item(row_id, values=values)
            self._layer_changed()

        return self._cell_editor.begin(
            row_id, column_id, lambda: self.table.item(row_id, "values")[column], finish
        )

    def _apply_gradient(self):
        self._cell_editor.commit()
        if not self.table.get_children():
            self.message.configure(text="Add a layer before applying a gradient.")
            return
        text = self.gradient_all.get().strip()
        try:
            gradient = _parse_number(text, "Hydraulic gradient")
            if not math.isfinite(gradient):
                raise ValueError("Hydraulic gradient must be finite.")
        except ValueError as error:
            self.message.configure(text=str(error))
            return
        self._loading = True
        try:
            for row in range(len(self.table.get_children())):
                values = self._row_values(row)
                values[3] = text
                self._set_row_values(row, values)
        finally:
            self._loading = False
        self._mark_dirty()
        self._refresh_geometry()
        self.geometry.canvas.fit()
        self.message.configure(text="")

    def _refresh_geometry(self):
        if self._case is None:
            return
        self._refresh_permeability()
        layers = []
        error = ""
        thicknesses = []
        for row in range(len(self.table.get_children())):
            try:
                thickness = float(self._row_values(row)[0])
            except ValueError:
                thicknesses = []
                break
            if not math.isfinite(thickness) or thickness <= 0:
                thicknesses = []
                break
            thicknesses.append(thickness)
        try:
            for row in range(len(self.table.get_children())):
                values = self._row_values(row)
                thickness = _parse_number(values[0], f"Layer {row + 1} thickness")
                d50 = _parse_number(values[1], f"Layer {row + 1} d50")
                angle_text = "" if self.geometry.enabled_var.get() else values[7].strip()
                angle = _parse_number(angle_text, f"Layer {row + 1} angle") if angle_text else None
                if (
                    not math.isfinite(thickness) or thickness <= 0
                    or not math.isfinite(d50) or d50 <= 0
                    or (angle is not None and (not math.isfinite(angle) or not 0 < angle < 90))
                ):
                    raise ValueError(
                        f"Layer {row + 1} needs positive thickness and d50, "
                        "and an angle between 0 and 90 degrees."
                    )
                layers.append({
                    "thickness": thickness, "d50": d50, "angle": angle,
                    "porosity": values[2], "gradient": values[3],
                })
        except ValueError as exc:
            layers = []
            error = str(exc)
        if not error:
            try:
                self.case()
            except ValueError as exc:
                error = str(exc)
        self.settings.message.configure(text=error)
        self.geometry.refresh(layers, error, thicknesses)

    def _refresh_permeability(self):
        for row in range(len(self.table.get_children())):
            values = self._row_values(row)
            try:
                value, source = self._permeability(row)
                values[-1] = f"{value:.12g}"
            except (ValueError, OverflowError):
                values[-1] = "--"
            self._set_row_values(row, values)

    def _permeability(self, row):
        def finite_number(text, label):
            value = _parse_number(text, label)
            if not math.isfinite(value):
                raise ValueError(f"{label} must be finite.")
            return value

        values = self._row_values(row)
        override = values[4].strip()
        if override:
            value = finite_number(override, "Permeability override")
            if value <= 0:
                raise ValueError("Permeability override must be positive.")
            return value, "User-specified override"

        d50 = finite_number(values[1], "D50")
        porosity = finite_number(values[2], "Porosity") / 100
        if d50 <= 0 or not 0 < porosity < 1:
            raise ValueError("D50 must be positive and porosity must be between 0 and 100%.")
        user_d15 = values[5].strip().lower()
        if user_d15 not in ("", "true", "false"):
            raise ValueError("User D15 must be true or false.")
        if user_d15 == "true":
            d15 = finite_number(values[6], "D15")
            if d15 <= 0:
                raise ValueError("D15 must be positive.")
        else:
            d15 = d50 / 1.75
        constants = self.settings.physical_fields
        gravity = finite_number(
            constants["g"].get().strip() or PHYSICAL_DEFAULTS["g"], "Gravity"
        )
        temperature = finite_number(
            constants["temperature_c"].get().strip() or PHYSICAL_DEFAULTS["temperature_c"],
            "Temperature",
        )
        if gravity <= 0 or temperature <= -20:
            raise ValueError("Gravity must be positive and temperature must exceed -20°C.")
        # Preview mirrors HMBresCorrected::derive; it is never serialized as an override.
        viscosity = 40.0 / (20.0 + temperature) * 1.0e-6
        d15_metres = d15 * 1.0e-6
        value = (
            gravity / (160.0 * viscosity) * (porosity**3 / (1 - porosity)**2)
            * d15_metres**2 * 1000.0
        )
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Calculated permeability must be finite and positive.")
        return value, "Calculated preview"

    def _match_bottom_layer(self, target_depth):
        self._cell_editor.commit()
        row_count = len(self.table.get_children())
        if row_count == 0 or not math.isfinite(target_depth) or target_depth <= 0:
            return
        upper_thicknesses = [
            float(self._row_values(row)[0]) for row in range(row_count - 1)
        ]
        thickness = target_depth - sum(upper_thicknesses)
        if not math.isfinite(thickness) or thickness <= 0:
            self.geometry.message.configure(text="Cannot match the bottom layer to the slope depth.")
            return
        if sum(upper_thicknesses + [thickness]) > target_depth:
            thickness = math.nextafter(thickness, -math.inf)
        if thickness <= 0:
            self.geometry.message.configure(text="Cannot match the bottom layer to the slope depth.")
            return
        values = self._row_values(row_count - 1)
        values[0] = repr(thickness)
        self._set_row_values(row_count - 1, values)
        self._clear_derived_geometry_angles()
        self._mark_dirty()
        self._refresh_geometry()
        self.geometry.canvas.fit()

    def _restore_geometry_angles(self):
        profile = self.geometry.canvas.profile
        if not self.geometry.enabled_var.get() or not profile:
            return
        thicknesses = [float(self._row_values(row)[0]) for row in range(len(self._layers))]
        try:
            segments = split_profile_layers(profile, thicknesses)
        except ValueError as error:
            self.geometry.message.configure(text=str(error))
            return
        grouped = [[] for _ in thicknesses]
        for material, _thickness, angle in segments:
            grouped[material].append(angle)
        for row, angles in enumerate(grouped):
            if angles and all(math.isclose(angle, angles[0], rel_tol=1e-12) for angle in angles):
                values = self._row_values(row)
                if not values[7]:
                    values[7] = repr(angles[0])
                    self._set_row_values(row, values)
        self._derived_geometry_angles = True

    def _update_layers_from_geometry(self):
        self.commit_pending_edits()
        if not self.geometry.enabled_var.get():
            self.geometry.message.configure(text="Enable coordinate slope geometry first.")
            return
        try:
            rows = [self._row_values(row) for row in range(len(self._layers))]
            thicknesses = [
                _parse_number(values[0], f"Layer {row + 1} thickness")
                for row, values in enumerate(rows)
            ]
            if not thicknesses or any(not math.isfinite(t) or t <= 0 for t in thicknesses):
                raise ValueError("Layer thicknesses must be finite and positive.")
            material_rows = []
            material_thicknesses = []
            material_keys = []
            field_keys = {key for key, _label, _optional in LAYER_FIELDS}
            for index, (layer, values, thickness) in enumerate(zip(self._layers, rows, thicknesses)):
                extras = tuple((key, repr(value)) for key, value in sorted(layer.items())
                               if key not in field_keys)
                key = (tuple(values[1:7] + values[8:9]), extras)
                if material_keys and key == material_keys[-1]:
                    material_thicknesses[-1] += thickness
                else:
                    material_keys.append(key)
                    material_rows.append(index)
                    material_thicknesses.append(thickness)
            points = [(point["x_m"], point["y_m"]) for point in self.geometry.points()]
            if len(points) < 2:
                raise ValueError("Slope geometry must contain at least two points.")
            depth = -points[-1][1]
            profile = preview_profile(points, [{"thickness": depth}])
            segments = split_profile_layers(profile, material_thicknesses)
            upper_depth = sum(segment[1] for segment in segments[:-1])
            final_thickness = depth - upper_depth
            if upper_depth + final_thickness > depth:
                final_thickness = math.nextafter(final_thickness, -math.inf)
            if final_thickness <= 0:
                raise ValueError("The slope produced an invalid bottom layer thickness.")
            material, _thickness, angle = segments[-1]
            segments[-1] = (material, final_thickness, angle)
        except ValueError as error:
            self.geometry.message.configure(text=str(error))
            return

        layers = []
        new_rows = []
        for material, thickness, angle in segments:
            source_row = material_rows[material]
            layer = deepcopy(self._layers[source_row])
            layer["thickness_m"] = thickness
            layer["initial_alpha_deg"] = angle
            values = list(rows[source_row])
            values[0] = repr(thickness)
            values[7] = repr(angle)
            layers.append(layer)
            new_rows.append(values)
        self._loading = True
        try:
            self._layers = layers
            self.table.delete(*self.table.get_children())
            for layer, values in zip(layers, new_rows):
                self.table.item(self._append_row(layer), values=values)
        finally:
            self._loading = False
        self._derived_geometry_angles = True
        self._mark_dirty()
        self._refresh_geometry()
        self.geometry.canvas.fit()
        if self.geometry.message.cget("text") == "Input geometry; not calculated output.":
            self.geometry.message.configure(
                text="Input layers updated. Angles are shown for reference; coordinates are saved."
            )
        if any(angle > 45 for _material, _thickness, angle in segments):
            self.geometry.message.configure(
                text=f"{self.geometry.message.cget('text')} Warning: the supplied solver "
                     "rejects slope angles above 45 degrees."
            )

    def _append_row(self, layer):
        values = [_display(layer.get(key)) for key, _, _ in LAYER_FIELDS] + ["--"]
        return self.table.insert("", "end", values=values)

    def mark_saved(self, case):
        self._case = deepcopy(case)
        self._layers = deepcopy(case["layers"])
        self.dirty = False
        self.message.configure(text="")

    def commit_pending_edits(self):
        self._cell_editor.commit()
        self.settings._width_cell_editor.commit()
        self.geometry._cell_editor.commit()

    def add_layer(self):
        self._cell_editor.commit()
        if self._case is None:
            self.message.configure(text="Open an input case first.")
            return
        self._clear_derived_geometry_angles()
        layer = {
            "thickness_m": 1.0,
            "d50_micrometre": 250.0,
            "porosity_percent": 40.0,
            "external_gradient": 0.0,
        }
        if self.settings.selected("mode") == "turbulence" and not self.geometry.enabled_var.get():
            layer["initial_alpha_deg"] = 45.0
        if self.settings.selected("width_model") == "b_fit":
            layer["flow_width_m"] = 1.0
        self._loading = True
        try:
            self._layers.append(layer)
            self._append_row(layer)
        finally:
            self._loading = False
        children = self.table.get_children()
        self.table.selection_set(children[-1])
        self._mark_dirty()
        self._refresh_geometry()
        self.geometry.canvas.fit()
        self.message.configure(text="")

    def copy_layer(self):
        self._cell_editor.commit()
        selection = self.table.selection()
        if not selection:
            self.message.configure(text="Select a layer to copy.")
            return
        self._clear_derived_geometry_angles()
        row = self.table.index(selection[0])
        layer = deepcopy(self._layers[row])
        self._loading = True
        try:
            self._layers.append(layer)
            new_item = self._append_row(layer)
            values = self._row_values(row)
            self.table.item(new_item, values=values)
        finally:
            self._loading = False
        self.table.selection_set(new_item)
        self._mark_dirty()
        self._refresh_geometry()
        self.geometry.canvas.fit()
        self.message.configure(text="")

    def remove_layer(self):
        self._cell_editor.commit()
        selection = self.table.selection()
        if not selection:
            self.message.configure(text="Select a layer to remove.")
            return
        self._clear_derived_geometry_angles()
        item = selection[0]
        row = self.table.index(item)
        self.table.delete(item)
        del self._layers[row]
        self._mark_dirty()
        self._refresh_geometry()
        self.geometry.canvas.fit()
        self.message.configure(text="")

    def case(self):
        self._cell_editor.commit()
        if self._case is None:
            raise ValueError("Open an input case first.")
        case = deepcopy(self._case)
        initial = case["initial_conditions"]
        for key, label in INITIAL_FIELDS:
            text = self.initial_fields[key].get().strip()
            if not text and key == "initial_width_m":
                initial.pop(key, None)
            else:
                initial[key] = _parse_number(text, label)
        layers = []
        for row, original in enumerate(self._layers):
            values = self._row_values(row)
            layer = deepcopy(original)
            for column, (key, label, optional) in enumerate(LAYER_FIELDS):
                if key == "initial_alpha_deg" and self.geometry.enabled_var.get():
                    layer.pop(key, None)
                    continue
                text = values[column].strip()
                if optional and not text:
                    if key in ("permeability_mm_s", "initial_alpha_deg") and layer.get(
                        key, "missing"
                    ) is None:
                        layer[key] = None
                    else:
                        layer.pop(key, None)
                elif key == "user_d15":
                    if text.lower() not in ("true", "false"):
                        raise ValueError(f"Layer {row + 1} {label} must be true or false.")
                    layer[key] = text.lower() == "true"
                else:
                    layer[key] = _parse_number(text, f"Layer {row + 1} {label}")
            layers.append(layer)
        case["layers"] = layers
        self.settings.apply_to_case(case)
        self.geometry.apply_to_case(case)
        validate_case(case)
        return case
