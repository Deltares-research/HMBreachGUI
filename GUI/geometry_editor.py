"""Interactive slope coordinates and initial material-layer preview."""

import math
import tkinter as tk
from copy import deepcopy
from tkinter import ttk


def _interpolate(a, b, y):
    return a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1])


def preview_profile(points, layers):
    """Return the input slope clipped to the datum and total material depth."""
    depth = sum(layer["thickness"] for layer in layers)
    if not math.isfinite(depth) or depth <= 0:
        raise ValueError("Layer thicknesses must have a finite positive total.")
    if points is None:
        profile = [(0.0, 0.0)]
        for layer in layers:
            angle = layer["angle"] if layer["angle"] is not None else 75.0
            x, y = profile[-1]
            profile.append((x + layer["thickness"] / math.tan(math.radians(angle)),
                            y - layer["thickness"]))
        return profile

    if len(points) < 2:
        raise ValueError("Slope geometry must contain at least two points.")
    for a, b in zip(points, points[1:]):
        if b[0] <= a[0] or b[1] > a[1]:
            raise ValueError("Slope geometry must have increasing X and non-increasing Y.")
        if b[1] == a[1] and b[1] < 0 and a[1] > -depth:
            raise ValueError("Slope geometry segments within the layers must descend.")
    if points[-1][1] > -depth:
        raise ValueError("Slope geometry must cover the total layer thickness.")

    if points[0][1] < 0:
        if points[1][1] >= points[0][1]:
            raise ValueError("Slope geometry must descend below y=0.")
        clipped = [(_interpolate(points[0], points[1], 0), 0.0)]
        start = 0
    else:
        for index, point in enumerate(points):
            if point[1] == 0:
                clipped = [point]
                start = index + 1
                break
            if index + 1 < len(points) and point[1] > 0 > points[index + 1][1]:
                clipped = [(_interpolate(point, points[index + 1], 0), 0.0)]
                start = index + 1
                break
        else:
            raise ValueError("Slope geometry must cross or reach y=0.")
    for point in points[start:]:
        if point[1] >= 0:
            continue
        if point[1] > -depth:
            clipped.append(point)
        else:
            clipped.append((_interpolate(clipped[-1], point, -depth), -depth))
            break
    if len(clipped) < 2 or clipped[-1][1] > -depth:
        raise ValueError("Slope geometry must cover the total layer thickness.")
    return clipped


def _x_at_y(profile, y):
    for a, b in zip(profile, profile[1:]):
        if b[1] <= y:
            return _interpolate(a, b, y)
    return profile[-1][0]


class SlopeCanvas(ttk.Frame):
    def __init__(self, master=None):
        super().__init__(master)
        self.widget = tk.Canvas(self, background="white", highlightthickness=0, height=280)
        self.widget.pack(fill="both", expand=True)
        self.points = []
        self.profile = []
        self.layers = []
        self.selected = -1
        self.editable = False
        self.lock_origin = False
        self.bounds = (-0.1, 1.1, -1.1, 0.1)
        self._dragging = False
        self.on_add = None
        self.on_move = None
        self.on_select = None
        self.widget.bind("<Configure>", lambda _event: self.redraw())
        self.widget.bind("<ButtonPress-1>", self._mouse_down)
        self.widget.bind("<B1-Motion>", self._mouse_drag)
        self.widget.bind("<ButtonRelease-1>", self._mouse_up)

    def set_data(self, points, profile, layers, editable):
        self.points = points
        self.profile = profile
        self.layers = layers
        self.editable = editable
        self.redraw()

    def fit(self):
        values = self.points + self.profile
        if not values:
            values = [(0.0, 0.0), (1.0, -1.0)]
        xs = [p[0] for p in values]
        ys = [p[1] for p in values] + [0.0]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        width = max(max_x - min_x, 0.5)
        height = max(max_y - min_y, 0.5)
        self.bounds = (min_x - width * 0.15, max_x + width * 0.15,
                       min_y - height * 0.15, max_y + height * 0.15)
        self.redraw()

    def plot_rect(self):
        width = max(1, self.widget.winfo_width())
        height = max(1, self.widget.winfo_height())
        return 62, 18, max(1, width - 82), max(1, height - 60)

    def to_screen(self, x, y):
        left, right, bottom, top = self.bounds
        rect_left, rect_top, rect_width, rect_height = self.plot_rect()
        return (rect_left + (x - left) / (right - left) * rect_width,
                rect_top + rect_height - (y - bottom) / (top - bottom) * rect_height)

    def to_world(self, x, y):
        left, right, bottom, top = self.bounds
        rect_left, rect_top, rect_width, rect_height = self.plot_rect()
        return (left + (x - rect_left) / rect_width * (right - left),
                bottom + (rect_top + rect_height - y) / rect_height * (top - bottom))

    def redraw(self):
        canvas = self.widget
        canvas.delete("all")
        rect_left, rect_top, rect_width, rect_height = self.plot_rect()
        rect_right, rect_bottom = rect_left + rect_width, rect_top + rect_height
        for tick in range(6):
            x = rect_left + rect_width * tick / 5
            y = rect_top + rect_height * tick / 5
            canvas.create_line(x, rect_top, x, rect_bottom, fill="#dddddd")
            canvas.create_line(rect_left, y, rect_right, y, fill="#dddddd")
            wx, _ = self.to_world(x, rect_bottom)
            _, wy = self.to_world(rect_left, y)
            canvas.create_text(x, rect_bottom + 13, text=f"{wx:.2f}", fill="#333333")
            canvas.create_text(rect_left - 8, y, text=f"{wy:.2f}", fill="#333333", anchor="e")
        canvas.create_rectangle(rect_left, rect_top, rect_right, rect_bottom, outline="#333333")
        canvas.create_text((rect_left + rect_right) / 2, rect_bottom + 31, text="X (m)")
        canvas.create_text(20, 12, text="Y (m)")
        if self.profile:
            grains = sorted(set(layer["d50"] for layer in self.layers))
            depth = 0.0
            for index, layer in enumerate(self.layers, 1):
                top = -depth
                depth += layer["thickness"]
                bottom = -depth
                fraction = grains.index(layer["d50"]) / max(1, len(grains) - 1)
                color = "#{:02x}{:02x}{:02x}".format(
                    round(253 - 113 * fraction),
                    round(231 - 150 * fraction),
                    round(37 - 27 * fraction),
                )
                left = self.profile[0][0]
                polygon = [(left, top), (_x_at_y(self.profile, top), top)]
                polygon.extend(p for p in self.profile if bottom < p[1] < top)
                polygon.extend([(_x_at_y(self.profile, bottom), bottom), (left, bottom)])
                flat_points = [coordinate for point in polygon for coordinate in self.to_screen(*point)]
                canvas.create_polygon(
                    *flat_points, fill=color, outline="#806b47", width=1, tags="plot"
                )
                middle = (top + bottom) / 2
                label_x = (left + _x_at_y(self.profile, middle)) / 2
                canvas.create_text(*self.to_screen(label_x, middle), text=str(index), fill="#333333")
            profile_points = [
                coordinate for point in self.profile for coordinate in self.to_screen(*point)
            ]
            canvas.create_line(*profile_points, fill="#0072b2", width=3, tags="plot")
        if self.editable and self.points:
            point_coords = [
                coordinate for point in self.points for coordinate in self.to_screen(*point)
            ]
            canvas.create_line(
                *point_coords, fill="#006198", width=2, dash=(5, 3), tags="plot"
            )
            for index, point in enumerate(self.points):
                x, y = self.to_screen(*point)
                color = "#d62728" if index == self.selected else "#0072b2"
                canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill=color, outline=color)

    def _mouse_down(self, event):
        if not self.editable:
            return
        x, y = event.x, event.y
        left, top, width, height = self.plot_rect()
        if not left <= x <= left + width or not top <= y <= top + height:
            return
        distances = [
            math.hypot(self.to_screen(*point)[0] - x, self.to_screen(*point)[1] - y)
            for point in self.points
        ]
        if distances and min(distances) <= 12:
            self.selected = distances.index(min(distances))
            self._dragging = not (self.lock_origin and self.selected == 0)
            if self.on_select is not None:
                self.on_select(self.selected)
            self.redraw()
        else:
            if self.on_add is not None:
                self.on_add(*self.to_world(x, y))

    def _mouse_drag(self, event):
        if self._dragging and self.selected >= 0 and self.on_move is not None:
            self.on_move(self.selected, *self.to_world(event.x, event.y))

    def _mouse_up(self, _event):
        self._dragging = False


class GeometryEditor(ttk.Frame):
    def __init__(self, master=None, on_change=None, on_match_bottom=None):
        super().__init__(master)
        self.on_change = on_change
        self.on_match_bottom = on_match_bottom
        self._loading = False
        self._original_points = []
        self._lock_origin = False
        self._target_depth = None
        self.enabled_var = tk.BooleanVar(value=False)
        self.enabled = ttk.Checkbutton(
            self, text="Use coordinate slope geometry", variable=self.enabled_var,
            command=self._toggle_geometry,
        )
        self.enabled.pack(anchor="w", padx=8, pady=(8, 2))
        hint = ttk.Label(
            self,
            text=(
            "New slopes start at (0, 0). Click to append points; drag a point to move it. "
            "Edit exact coordinates in the table. "
            "Coordinates must descend from left to right and cover all layers. "
            "Layer angles are ignored and omitted from saved input while coordinates are used."
            ),
            wraplength=900,
        )
        hint.pack(fill="x", padx=8, pady=4)
        content = ttk.Frame(self)
        content.pack(fill="both", expand=True, padx=8, pady=4)
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)
        self.canvas = SlopeCanvas(content)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.canvas.on_add = self.add_point
        self.canvas.on_move = self.move_point
        self.canvas.on_select = self._select_row
        controls = ttk.Frame(content)
        controls.grid(row=0, column=1, sticky="nsew")
        self.table = ttk.Treeview(controls, columns=("x", "y"), show="headings", height=8)
        self.table.heading("x", text="X (m)")
        self.table.heading("y", text="Y (m)")
        self.table.column("x", width=100, anchor="e")
        self.table.column("y", width=100, anchor="e")
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self._selection_changed)
        self.table.bind("<Double-1>", self._begin_cell_edit)
        actions = ttk.Frame(controls)
        actions.pack(fill="x", pady=4)
        self.remove_button = ttk.Button(actions, text="Remove selected point", command=self.remove_point)
        self.remove_button.pack(fill="x", pady=2)
        self.match_button = ttk.Button(
            actions, text="Match bottom layer to slope bottom", command=self._match_bottom
        )
        self.match_button.pack(fill="x", pady=2)
        ttk.Button(actions, text="Fit view", command=self.canvas.fit).pack(fill="x", pady=2)
        self.properties = ttk.Label(controls, wraplength=300)
        self.properties.pack(fill="x", pady=4)
        self.message = ttk.Label(self, wraplength=900)
        self.message.pack(fill="x", padx=8, pady=2)
        self.depth_warning = ttk.Label(self, wraplength=900, foreground="#a54b00")
        self.depth_warning.pack(fill="x", padx=8, pady=(2, 8))

    def set_case(self, case):
        settings = case.get("settings", {})
        has_geometry = "slope_geometry" in settings
        geometry = settings.get("slope_geometry")
        if has_geometry and (
            not isinstance(geometry, list) or any(not isinstance(point, dict) for point in geometry)
        ):
            raise ValueError("Slope geometry must be an array of point objects.")
        self._loading = True
        try:
            self._original_points = deepcopy(geometry or [])
            self._lock_origin = bool(
                self._original_points and
                self._original_points[0].get("x_m") == 0 and
                self._original_points[0].get("y_m") == 0
            )
            self.enabled_var.set(has_geometry)
            self.table.delete(*self.table.get_children())
            for point in self._original_points:
                self._append(point.get("x_m", ""), point.get("y_m", ""))
            if has_geometry and not self._original_points:
                self._insert_origin()
            self.canvas.selected = -1
        finally:
            self._loading = False

    def _append(self, x, y):
        self.table.insert("", "end", values=(x, y))

    def _insert_origin(self):
        self._lock_origin = True
        self._original_points.append({"x_m": 0.0, "y_m": 0.0})
        self._append(0, 0)

    def _toggle_geometry(self):
        if self._loading:
            return
        if self.enabled_var.get() and not self._original_points:
            self._loading = True
            try:
                self._insert_origin()
            finally:
                self._loading = False
        self._changed()

    def _changed(self):
        if self.on_change is not None and not self._loading:
            self.on_change()

    def _begin_cell_edit(self, event):
        if not self.enabled_var.get():
            return
        row = self.table.identify_row(event.y)
        column = self.table.identify_column(event.x)
        if not row or column not in ("#1", "#2"):
            return
        if self._lock_origin and row == self.table.get_children()[0]:
            return
        box = self.table.bbox(row, column)
        if not box:
            return
        x, y, width, height = box
        old_value = self.table.set(row, column)
        editor = ttk.Entry(self.table)
        editor.insert(0, old_value)
        editor.select_range(0, "end")
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()

        def finish(_event=None):
            if not editor.winfo_exists():
                return
            value = editor.get()
            editor.destroy()
            self.table.set(row, column, value)
            self._changed()

        editor.bind("<Return>", finish)
        editor.bind("<FocusOut>", finish)
        editor.bind("<Escape>", lambda _event: editor.destroy())

    def _selection_changed(self):
        selection = self.table.selection()
        self.canvas.selected = self.table.index(selection[0]) if selection else -1
        self.canvas.redraw()

    def _select_row(self, index):
        rows = self.table.get_children()
        if 0 <= index < len(rows):
            self.table.selection_set(rows[index])
            self.table.see(rows[index])

    def add_point(self, x, y):
        self._loading = True
        try:
            if not self._original_points:
                self._insert_origin()
            self._original_points.append({})
            self._append(f"{x:.6g}", f"{y:.6g}")
            last = self.table.get_children()[-1]
            self.table.selection_set(last)
        finally:
            self._loading = False
        self._changed()

    def move_point(self, row, x, y):
        if row == 0 and self._lock_origin:
            return
        self._loading = True
        try:
            item = self.table.get_children()[row]
            self.table.item(item, values=(f"{x:.6g}", f"{y:.6g}"))
        finally:
            self._loading = False
        self._changed()

    def remove_point(self):
        selection = self.table.selection()
        if not selection:
            self.message.configure(text="Select a point to remove.")
            return
        item = selection[0]
        row = self.table.index(item)
        if row == 0 and self._lock_origin:
            self.message.configure(text="The first point of this slope is fixed at (0, 0).")
            return
        self._loading = True
        try:
            self.table.delete(item)
            del self._original_points[row]
            self.canvas.selected = -1
        finally:
            self._loading = False
        self._changed()

    def points(self):
        points = []
        for row, (original, item) in enumerate(zip(self._original_points, self.table.get_children())):
            point = deepcopy(original)
            values = self.table.item(item, "values")
            for column, key in enumerate(("x_m", "y_m")):
                try:
                    value = float(values[column])
                except ValueError as error:
                    raise ValueError(f"Slope point {row + 1} {key} must be a number.") from error
                if not math.isfinite(value):
                    raise ValueError(f"Slope point {row + 1} {key} must be finite.")
                point[key] = value
            points.append(point)
        return points

    def apply_to_case(self, case):
        if self.enabled_var.get():
            case.setdefault("settings", {})["slope_geometry"] = self.points()
        elif "settings" in case:
            case["settings"].pop("slope_geometry", None)

    def _match_bottom(self):
        if self._target_depth is not None and self.on_match_bottom is not None:
            self.on_match_bottom(self._target_depth)

    def refresh(self, layers, error="", thicknesses=None):
        points = []
        profile = []
        try:
            if self.enabled_var.get():
                points = [(point["x_m"], point["y_m"]) for point in self.points()]
                profile = preview_profile(points, layers)
            else:
                profile = preview_profile(None, layers)
        except ValueError as exc:
            if not error:
                error = str(exc)
        self.canvas.set_data(points, profile, layers, self.enabled_var.get())
        self.canvas.lock_origin = self._lock_origin
        state = "normal" if self.enabled_var.get() else "disabled"
        self.table.configure(selectmode="browse")
        self.remove_button.configure(state=state)
        if self.enabled_var.get():
            self.table.state(["!disabled"])
        else:
            self.table.state(["disabled"])
        self._target_depth = None
        warning = ""
        if self.enabled_var.get() and len(points) >= 2 and thicknesses:
            total_depth = sum(thicknesses)
            slope_depth = -min(y for _, y in points)
            if (math.isfinite(total_depth) and
                    (slope_depth < total_depth or not math.isclose(
                        total_depth, slope_depth, rel_tol=1e-12, abs_tol=1e-12
                    ))):
                warning = (
                    f"Warning: total layer thickness ({total_depth!r} m) does not match "
                    f"the lowest slope point (depth {slope_depth!r} m)."
                )
                if slope_depth > sum(thicknesses[:-1]):
                    self._target_depth = slope_depth
                else:
                    warning += " The slope bottom must be below all upper layers to adjust the bottom layer."
        self.depth_warning.configure(text=warning)
        self.match_button.configure(state="normal" if self._target_depth is not None else "disabled")
        self.properties.configure(text="\n".join(
            f"Layer {index}: {layer['thickness']:g} m; D50 {layer['d50']:g} um; "
            f"porosity {layer['porosity']}%; gradient {layer['gradient']}"
            for index, layer in enumerate(layers, 1)
        ))
        if not error:
            error = ("Input geometry; not calculated output." if self.enabled_var.get() else
                     "Layer profile; unspecified angles use 75 degrees (schematic).")
        self.message.configure(text=error)
