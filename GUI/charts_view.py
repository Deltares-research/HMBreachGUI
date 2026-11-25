"""Charts of recorded profiles and their symmetric flow-width top view."""

import math
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FixedFormatter, FixedLocator

from GUI.axis_settings import AXES, AxisSettingsDialog, axis_parameters, axis_ticks
from GUI.case_io import read_json, validate_case, validate_results
from GUI.geometry_editor import preview_profile
from GUI.results_view import METRICS


LABELS = dict(METRICS)


def _label(key):
    return LABELS.get(key, f"{key} (unit not recorded)")


def _initial_profile(case):
    if (not isinstance(case, dict) or not isinstance(case.get("initial_conditions"), dict)
            or not isinstance(case.get("settings", {}), dict)
            or not isinstance(case.get("layers"), list)
            or any(not isinstance(layer, dict) for layer in case["layers"])):
        raise ValueError("The result's input snapshot is incomplete.")
    validate_case(case)
    geometry = case.get("settings", {}).get("slope_geometry")
    points = None if geometry is None else [(point["x_m"], point["y_m"]) for point in geometry]
    layers = [
        {"thickness": layer["thickness_m"], "angle": layer.get("initial_alpha_deg")}
        for layer in case["layers"]
    ]
    if geometry is None and any(
        math.tan(math.radians(layer["angle"] if layer["angle"] is not None else 75.0)) == 0
        for layer in layers
    ):
        raise ValueError("An initial slope angle is too small to display.")
    profile = preview_profile(points, layers)
    origin = profile[0][0]
    profile = [(x - origin, z) for x, z in profile]
    if any(not math.isfinite(value) for point in profile for value in point):
        raise ValueError("Initial slope coordinates are not finite.")
    schematic = geometry is None and any(layer["angle"] is None for layer in layers)
    return profile, schematic


def _segments(profile, x_key, y_key, width_sign=None, previous_point=None):
    """Split missing data while connecting adjacent computational layers."""
    def coordinates(point):
        x = point.get(x_key)
        y = point.get(y_key)
        if x is None or y is None or (width_sign is not None and y <= 0):
            return None
        return (x, width_sign * y / 2 if width_sign is not None else y)

    segment = []
    if previous_point is not None:
        previous = coordinates(previous_point)
        first = coordinates(profile["points"][0])
        if previous is not None and first is not None and previous != first:
            segment.append(previous)
    for point in profile["points"]:
        values = coordinates(point)
        if values is None:
            if segment:
                yield segment
                segment = []
            continue
        segment.append(values)
    if segment:
        yield segment


class ChartsView(ttk.Frame):
    def __init__(self, master=None):
        super().__init__(master, padding=8)
        self.current = None
        self.previous = None
        self._variables_populated = False
        self._axis_settings = {
            mode: {key: (None, None, None, None) for key, _ in AXES}
            for mode in ("profile", "top")
        }
        self._axis_values = {key: [] for key, _ in AXES}
        self.colors = ["#0072b2", "#d55e00"]
        self.lines = []

        selectors = ttk.Frame(self)
        selectors.pack(fill="x")
        self.plot_type = tk.StringVar(value="Profile chart")
        self.x_variable = tk.StringVar()
        self.left_variable = tk.StringVar()
        self.right_variable = tk.StringVar()
        self._variable_keys = [{}, {}, {}]
        self.plot_combo = ttk.Combobox(
            selectors, textvariable=self.plot_type, values=("Profile chart", "Flow top view"),
            state="readonly", width=16,
        )
        self.plot_combo.pack(side="left", padx=(0, 8))
        self.plot_combo.bind("<<ComboboxSelected>>", self._redraw)
        self.variable_combos = []
        for label, variable in (
            ("Horizontal:", self.x_variable), ("Left:", self.left_variable),
            ("Right:", self.right_variable),
        ):
            ttk.Label(selectors, text=label).pack(side="left")
            combo = ttk.Combobox(selectors, textvariable=variable, state="readonly", width=18)
            combo.pack(side="left", padx=(3, 8))
            combo.bind("<<ComboboxSelected>>", self._redraw)
            self.variable_combos.append(combo)

        comparison = ttk.Frame(self)
        comparison.pack(fill="x", pady=4)
        self.show_initial_var = tk.BooleanVar(value=False)
        self.show_initial = ttk.Checkbutton(
            comparison, text="Show initial slope", variable=self.show_initial_var,
            command=self._redraw,
        )
        self.show_initial.pack(side="left")
        self.show_previous_var = tk.BooleanVar(value=False)
        self.show_previous = ttk.Checkbutton(
            comparison, text="Show previous results", variable=self.show_previous_var,
            command=self._redraw,
        )
        self.show_previous.pack(side="left", padx=8)
        self.load_previous = ttk.Button(
            comparison, text="Load comparison JSON...", command=self._load_previous
        )
        self.load_previous.pack(side="left")
        self.comparison_status = ttk.Label(comparison, text="No previous results.")
        self.comparison_status.pack(side="left", fill="x", expand=True, padx=8)

        appearance = ttk.Frame(self)
        appearance.pack(fill="x", pady=4)
        ttk.Label(appearance, text="Title:").pack(side="left")
        self.title = tk.StringVar(value="HMBreach")
        title_entry = ttk.Entry(appearance, textvariable=self.title)
        title_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.title.trace_add("write", self._redraw)
        ttk.Label(appearance, text="Title size:").pack(side="left")
        self.title_size = tk.IntVar(value=16)
        self.title_size.trace_add("write", self._redraw)
        ttk.Spinbox(
            appearance, from_=8, to=48, textvariable=self.title_size, width=4,
            command=self._redraw,
        ).pack(side="left", padx=4)
        self.color_buttons = []
        for index, label in enumerate(("Left colour...", "Right colour...")):
            button = ttk.Button(
                appearance, text=label, command=lambda item=index: self._choose_color(item)
            )
            button.pack(side="left", padx=3)
            self.color_buttons.append(button)
        self._update_colors()

        self.figure = Figure(figsize=(8, 5), dpi=100, facecolor="white")
        self.left_axis = self.figure.add_subplot(111)
        self.right_axis = self.left_axis.twinx()
        self.figure.subplots_adjust(bottom=0.16, top=0.88, left=0.12, right=0.88)
        self.chart_canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True)

        self.status = ttk.Label(
            self, text="Run a calculation or open results to plot profiles.", wraplength=1000
        )
        self.status.pack(fill="x", pady=3)
        exports = ttk.Frame(self)
        exports.pack(fill="x", pady=3)
        ttk.Label(exports, text="Image width (px):").pack(side="left")
        self.image_width = tk.IntVar(value=1200)
        ttk.Spinbox(exports, from_=320, to=4096, textvariable=self.image_width, width=6).pack(
            side="left", padx=3
        )
        ttk.Label(exports, text="Height (px):").pack(side="left")
        self.image_height = tk.IntVar(value=800)
        ttk.Spinbox(exports, from_=240, to=4096, textvariable=self.image_height, width=6).pack(
            side="left", padx=3
        )
        ttk.Button(exports, text="Axis settings...", command=self._open_axis_settings).pack(
            side="right", padx=3
        )
        ttk.Button(exports, text="Save chart image...", command=self._export_image).pack(
            side="right", padx=3
        )
        self.set_results(None)

    def _choose_color(self, index):
        selected = colorchooser.askcolor(self.colors[index], parent=self.winfo_toplevel())[1]
        if selected:
            self.colors[index] = selected
            self._update_colors()
            self._redraw()

    def _update_colors(self):
        for button, color in zip(self.color_buttons, self.colors):
            button.configure(text=f"{color}  Choose colour...")

    def _validate_axis_settings(self, settings):
        for key, title in AXES:
            try:
                axis_parameters(self._axis_values[key], settings[key])
            except ValueError as error:
                raise ValueError(f"{title} axis: {error}") from error

    def _open_axis_settings(self):
        mode = "top" if self.plot_type.get() == "Flow top view" else "profile"
        dialog = AxisSettingsDialog(
            mode, self._axis_settings[mode], self._validate_axis_settings, self.winfo_toplevel()
        )
        self.wait_window(dialog)
        if dialog.settings is not None:
            self._axis_settings[mode] = dialog.settings
            self._redraw()

    def set_previous(self, results, description=""):
        self.previous = results
        self.show_previous.configure(state="normal" if results is not None else "disabled")
        if results is None:
            self.show_previous_var.set(False)
        self.comparison_status.configure(
            text=description if results is not None else "No previous results."
        )
        self._populate_variables()
        self._redraw()

    def _load_previous(self):
        filename = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="Load comparison results",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not filename:
            return
        try:
            data = read_json(filename)
            if isinstance(data, dict) and "results" in data:
                data = data["results"]
            previous = validate_results(data)
        except (OSError, ValueError) as error:
            messagebox.showerror("Unable to load comparison", str(error), parent=self)
            return
        self.set_previous(previous, f"Comparison: {Path(filename).name}")
        self.show_previous_var.set(True)
        self._redraw()

    def _populate_variables(self):
        keys = set()
        for results in (self.current, self.previous):
            if results is not None:
                for profile in results["profiles"]:
                    for point in profile["points"]:
                        keys.update(point)
        ordered = [key for key, _label_text in METRICS if key in keys]
        ordered.extend(sorted(keys - set(ordered)))
        for index, (combo, variable, default, allow_none) in enumerate((
            (self.variable_combos[0], self.x_variable, "x", False),
            (self.variable_combos[1], self.left_variable, "z", True),
            (self.variable_combos[2], self.right_variable, "u", True),
        )):
            previous_key = self._variable_keys[index].get(variable.get()) if self._variables_populated else default
            display_to_key = {}
            options = []
            if allow_none:
                options.append("None")
                display_to_key["None"] = None
            for key in ordered:
                label_text = _label(key)
                options.append(label_text)
                display_to_key[label_text] = key
            combo.configure(values=tuple(options))
            self._variable_keys[index] = display_to_key
            selected = next(
                (label_text for label_text, key in display_to_key.items() if key == previous_key),
                None,
            )
            if selected is None:
                selected = next(
                    (label_text for label_text, key in display_to_key.items() if key == default),
                    options[0] if options else "",
                )
            variable.set(selected)
        self._variables_populated = bool(ordered)

    def _selected_key(self, index):
        variable = (self.x_variable, self.left_variable, self.right_variable)[index]
        return self._variable_keys[index].get(variable.get())

    def _redraw(self, *_):
        if not self.winfo_exists():
            return
        top = self.plot_type.get() == "Flow top view"
        x_key = self._selected_key(0)
        left_key, right_key = self._selected_key(1), self._selected_key(2)
        for combo in self.variable_combos:
            combo.configure(state="disabled" if top else "readonly")
        self.color_buttons[1].configure(state="disabled" if top else "normal")
        slope_axes = []
        if not top:
            if (x_key, left_key) in (("x", "z"), ("z", "x")):
                slope_axes.append((self.left_axis, left_key))
            if (x_key, right_key) in (("x", "z"), ("z", "x")):
                slope_axes.append((self.right_axis, right_key))
        self.show_initial.configure(state="normal" if slope_axes else "disabled")
        if not slope_axes:
            self.show_initial_var.set(False)

        for legend in self.figure.legends[:]:
            legend.remove()
        self.left_axis.clear()
        self.right_axis.clear()
        self.lines = []
        self.left_axis.set_title(self.title.get(), fontsize=self._safe_title_size())
        self.left_axis.set_facecolor("white")
        self.right_axis.set_facecolor("none")
        if top:
            self.left_axis.set_xlabel("x (m)")
            self.left_axis.set_ylabel("Lateral offset (m)")
            self.right_axis.set_visible(False)
        else:
            self.left_axis.set_xlabel(_label(x_key) if x_key else "")
            self.left_axis.set_ylabel(_label(left_key) if left_key else "")
            self.right_axis.set_ylabel(_label(right_key) if right_key else "")
            self.right_axis.set_visible(True)
            self.right_axis.spines["right"].set_color(self.colors[1])
            self.right_axis.tick_params(axis="y", colors=self.colors[1])
            self.right_axis.yaxis.label.set_color(self.colors[1])
        self.left_axis.spines["left"].set_color(self.colors[0])
        self.left_axis.tick_params(axis="y", colors=self.colors[0])
        self.left_axis.yaxis.label.set_color(self.colors[0])
        self.left_axis.grid(True, color="#dddddd", linewidth=0.7)

        x_values, left_values, right_values = [], [], []
        missing_width = False
        width_notes = []
        slope_note = ""
        sources = [("Current", self.current, False)]
        if self.show_previous_var.get() and self.previous is not None:
            sources.append(("Previous", self.previous, True))
        for source, results, dashed in sources:
            if results is None:
                continue
            if top:
                case = results.get("input", {})
                settings = case.get("settings", {})
                if ("initial_conditions" not in case or "layers" not in case
                        or not isinstance(settings, dict)):
                    width_notes.append(f"{source} width model is not recorded.")
                elif settings.get("width_model", "b_constant") in ("b_constant", "unit_width"):
                    width_notes.append(f"{source} uses unit width, not a physical channel width.")
                elif settings["width_model"] not in ("b_fit", "b_calc", "fanning", "geometry"):
                    width_notes.append(f"{source} width model is not recognized.")
            previous_profile = None
            for profile in results["profiles"]:
                previous_point = (
                    previous_profile["points"][-1]
                    if previous_profile is not None
                    and profile["layer"] == previous_profile["layer"] + 1
                    else None
                )
                if top:
                    for sign, side in ((1, "+ width/2"), (-1, "- width/2")):
                        self._add_segments(
                            profile, "x", "width_m", self.left_axis, self.colors[0],
                            f"{source} L{profile['layer']} {side}", dashed,
                            x_values, left_values, sign, previous_point,
                        )
                    missing_width |= any(
                        point.get("width_m") is None or point["width_m"] <= 0
                        for point in profile["points"]
                    )
                elif x_key is not None:
                    for index, (key, axis, color, values) in enumerate((
                        (left_key, self.left_axis, self.colors[0], left_values),
                        (right_key, self.right_axis, self.colors[1], right_values),
                    )):
                        if key is not None:
                            self._add_segments(
                                profile, x_key, key, axis, color,
                                f"{source} L{profile['layer']} {_label(key)}", dashed,
                                x_values, values, previous_point=previous_point,
                            )
                previous_profile = profile
        if self.show_initial_var.get() and not top:
            if not slope_axes:
                slope_note = "Initial slope requires x and z on the chart axes."
            elif self.current is None:
                slope_note = "Initial slope unavailable: no current results."
            else:
                try:
                    points, schematic = _initial_profile(self.current["input"])
                except (KeyError, ValueError) as error:
                    slope_note = f"Initial slope unavailable: {error}"
                else:
                    profile = {"points": [{"x": x, "z": z} for x, z in points]}
                    name = (
                        "Initial slope (schematic: 75 deg where unspecified)"
                        if schematic else "Initial slope"
                    )
                    for axis, key in slope_axes:
                        values = left_values if axis is self.left_axis else right_values
                        self._add_segments(
                            profile, x_key, key, axis, "#555555", name, False,
                            x_values, values, line_style="-.",
                        )
                    slope_note = "Initial slope uses the current result's input snapshot."
                    if schematic:
                        slope_note += " Unspecified angles are shown schematically at 75 degrees."

        handles, labels = self.left_axis.get_legend_handles_labels()
        right_handles, right_labels = self.right_axis.get_legend_handles_labels()
        if handles or right_handles:
            self.figure.legend(
                handles + right_handles, labels + right_labels, loc="lower center",
                bbox_to_anchor=(0.5, 0.01), ncol=max(1, min(4, len(handles + right_handles))),
                fontsize=8, frameon=False,
            )
        else:
            existing = self.figure.legends[:]
            for legend in existing:
                legend.remove()
        self.figure.subplots_adjust(
            bottom=0.2 if handles or right_handles else 0.14,
            top=0.88, left=0.13, right=0.87 if not top else 0.97,
        )

        self._axis_values = {
            "horizontal": x_values, "left": left_values, "right": right_values,
        }
        settings = self._axis_settings["top" if top else "profile"]
        try:
            self._validate_axis_settings(settings)
            for key, axis, values in (
                ("horizontal", self.left_axis, x_values),
                ("left", self.left_axis, left_values),
                ("right", self.right_axis, right_values),
            ):
                if top and key == "right":
                    continue
                lower, upper, interval, label_format = axis_parameters(values, settings[key])
                ticks = axis_ticks(lower, upper, interval, label_format)
                if not math.isfinite(lower + upper):
                    raise ValueError(f"{key} axis limits are too large for chart display.")
                if key == "horizontal":
                    axis.set_xlim(lower, upper)
                    axis.xaxis.set_major_locator(FixedLocator([value for _label_text, value in ticks]))
                    axis.xaxis.set_major_formatter(FixedFormatter([label_text for label_text, _ in ticks]))
                else:
                    axis.set_ylim(lower, upper)
                    axis.yaxis.set_major_locator(FixedLocator([value for _label_text, value in ticks]))
                    axis.yaxis.set_major_formatter(FixedFormatter([label_text for label_text, _ in ticks]))
        except ValueError as error:
            for line in self.lines:
                line.remove()
            self.lines.clear()
            self.status.configure(text=f"Invalid axis settings: {error}")
            self.chart_canvas.draw_idle()
            return

        if not x_values:
            description = (
                "No recorded positive widths are available for the top view." if top else
                "No recorded points match the selected variables."
            )
        elif missing_width:
            description = (
                "Some points have no recorded positive width and are not shown. "
                "Axes scale independently."
            )
        else:
            description = (
                "Top view uses recorded full width, mirrored around the centreline. "
                "Axes scale independently." if top else
                "Profile curves use recorded points; previous results are dashed."
            )
        axis_note = (
            "Manual axis limits may clip data."
            if any(limits[0] is not None for limits in settings.values()) else ""
        )
        self.status.configure(text=" ".join(
            part for part in (description, *width_notes, slope_note, axis_note) if part
        ))
        self.chart_canvas.draw_idle()

    def _safe_title_size(self):
        try:
            return min(48, max(8, int(self.title_size.get())))
        except (tk.TclError, ValueError):
            return 16

    def _add_segments(
        self, profile, x_key, y_key, axis, color, name, dashed, xs, ys,
        width_sign=None, previous_point=None, line_style=None,
    ):
        count = 0
        for points in _segments(profile, x_key, y_key, width_sign, previous_point):
            line, = axis.plot(
                [point[0] for point in points], [point[1] for point in points],
                color=color, linewidth=1.5, linestyle=line_style or ("--" if dashed else "-"),
                marker="o" if len(points) == 1 else None,
                markersize=4, label=name if count == 0 else "_nolegend_",
            )
            self.lines.append(line)
            for x, y in points:
                for bounds, value in ((xs, x), (ys, y)):
                    if not bounds:
                        bounds.extend((value, value))
                    else:
                        bounds[0] = min(bounds[0], value)
                        bounds[1] = max(bounds[1], value)
            count += 1
        return count

    def set_results(self, results, previous=None):
        self.current = results
        self.set_previous(previous, "Previous result" if previous is not None else "")

    def save_image(self, path):
        path = Path(path)
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise ValueError("Choose a PNG or JPEG filename.")
        if not self.lines:
            raise ValueError("There is no chart data to export.")
        try:
            width = int(self.image_width.get())
            height = int(self.image_height.get())
        except (tk.TclError, ValueError) as error:
            raise ValueError("Image dimensions must be whole numbers.") from error
        if not 320 <= width <= 4096 or not 240 <= height <= 4096:
            raise ValueError("Image dimensions must be between 320x240 and 4096x4096 pixels.")
        size = self.figure.get_size_inches()
        try:
            self.figure.set_size_inches(width / 100, height / 100, forward=False)
            self.figure.savefig(path, dpi=100, facecolor="white")
        except OSError:
            raise
        finally:
            self.figure.set_size_inches(size, forward=False)
            self.chart_canvas.draw_idle()

    def _export_image(self):
        filename = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(),
            title="Save chart image",
            defaultextension=".png",
            filetypes=(("PNG image", "*.png"), ("JPEG image", "*.jpg *.jpeg")),
        )
        if not filename:
            return
        try:
            self.save_image(filename)
        except (OSError, ValueError) as error:
            messagebox.showwarning("Unable to save chart", str(error), parent=self)
