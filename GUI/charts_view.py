"""Charts of recorded profiles and their symmetric flow-width top view."""

import math
from html import escape
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
import pyqtgraph as pg

if pg.Qt.QT_LIB != "PySide6":
    raise ImportError("The chart requires PyQtGraph to use the PySide6 Qt binding.")

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
            segment.append(QPointF(*previous))
    for point in profile["points"]:
        values = coordinates(point)
        if values is None:
            if segment:
                yield segment
                segment = []
            continue
        segment.append(QPointF(*values))
    if segment:
        yield segment


class ChartWidget(pg.GraphicsLayoutWidget):
    resized = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class ChartsView(QWidget):
    def __init__(self):
        super().__init__()
        self.current = None
        self.previous = None
        self._variables_populated = False
        self._data_changed = False
        self._axis_settings = {
            mode: {key: (None, None, None, None) for key, _ in AXES}
            for mode in ("profile", "top")
        }
        self._axis_values = {key: [] for key, _ in AXES}
        self.colors = [QColor("#0072b2"), QColor("#d55e00")]
        layout = QVBoxLayout(self)

        selectors = QHBoxLayout()
        self.plot_type = QComboBox()
        self.plot_type.addItem("Profile chart", "profile")
        self.plot_type.addItem("Flow top view", "top")
        self.x_variable = QComboBox()
        self.left_variable = QComboBox()
        self.right_variable = QComboBox()
        for label, control in (
            ("Plot:", self.plot_type), ("Horizontal:", self.x_variable),
            ("Left:", self.left_variable), ("Right:", self.right_variable),
        ):
            selectors.addWidget(QLabel(label))
            selectors.addWidget(control, 1)
        layout.addLayout(selectors)

        comparison = QHBoxLayout()
        self.show_initial = QCheckBox("Show initial slope")
        self.show_initial.setToolTip(
            "Uses the current result's input snapshot. Available when plotting x against z."
        )
        self.show_previous = QCheckBox("Show previous results")
        self.show_previous.setEnabled(False)
        self.load_previous = QPushButton("Load comparison JSON...")
        self.load_previous.clicked.connect(self._load_previous)
        self.comparison_status = QLabel("No previous results.")
        comparison.addWidget(self.show_initial)
        comparison.addWidget(self.show_previous)
        comparison.addWidget(self.load_previous)
        comparison.addWidget(self.comparison_status, 1)
        layout.addLayout(comparison)

        appearance = QHBoxLayout()
        self.title = QLineEdit("HMBreach")
        self.title_size = QSpinBox()
        self.title_size.setRange(8, 48)
        self.title_size.setValue(16)
        self.left_color = QPushButton("Left colour...")
        self.right_color = QPushButton("Right colour...")
        self.left_color.clicked.connect(lambda: self._choose_color(0))
        self.right_color.clicked.connect(lambda: self._choose_color(1))
        appearance.addWidget(QLabel("Title:"))
        appearance.addWidget(self.title, 1)
        appearance.addWidget(QLabel("Title size:"))
        appearance.addWidget(self.title_size)
        appearance.addWidget(self.left_color)
        appearance.addWidget(self.right_color)
        layout.addLayout(appearance)

        self.chart_view = ChartWidget()
        self.chart_view.setBackground("w")
        self.chart = self.chart_view.addPlot(row=0, col=0)
        self.chart.setMenuEnabled(False)
        self.left_view = self.chart.getViewBox()
        self.left_view.setMouseEnabled(x=False, y=False)
        self.right_view = pg.ViewBox(enableMenu=False)
        self.right_view.setMouseEnabled(x=False, y=False)
        self.chart.scene().addItem(self.right_view)
        self.right_view.setXLink(self.left_view)
        self.left_view.sigResized.connect(self._sync_right_view)
        self.x_axis = self.chart.getAxis("bottom")
        self.left_axis = self.chart.getAxis("left")
        self.right_axis = self.chart.getAxis("right")
        self.right_axis.linkToView(self.right_view)
        for axis in (self.x_axis, self.left_axis, self.right_axis):
            axis.setPen("k")
            axis.setTextPen("k")
            axis.enableAutoSIPrefix(False)
        self.legend = pg.LegendItem(colCount=2, labelTextColor="k", frame=False)
        self.chart_view.addItem(self.legend, row=1, col=0)
        self.chart_view.resized.connect(self._layout_legend)
        self.series = []
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setMinimumSize(400, 280)
        layout.addWidget(self.chart_view, 1)

        self.status = QLabel("Run a calculation or open results to plot profiles.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        exports = QHBoxLayout()
        self.image_width = QSpinBox()
        self.image_width.setRange(320, 4096)
        self.image_width.setValue(1200)
        self.image_height = QSpinBox()
        self.image_height.setRange(240, 4096)
        self.image_height.setValue(800)
        export_button = QPushButton("Save chart image...")
        export_button.clicked.connect(self._export_image)
        self.axis_button = QPushButton("Axis settings...")
        self.axis_button.clicked.connect(self._open_axis_settings)
        exports.addWidget(QLabel("Image width (px):"))
        exports.addWidget(self.image_width)
        exports.addWidget(QLabel("Height (px):"))
        exports.addWidget(self.image_height)
        exports.addStretch()
        exports.addWidget(self.axis_button)
        exports.addWidget(export_button)
        layout.addLayout(exports)
        for control in (self.plot_type, self.x_variable, self.left_variable, self.right_variable):
            control.currentIndexChanged.connect(self._redraw)
        self.show_previous.toggled.connect(self._redraw)
        self.show_initial.toggled.connect(self._redraw)
        self.title.textChanged.connect(self._set_title)
        self.title_size.valueChanged.connect(self._set_title)
        self._set_title()
        self._update_colors()
        self.set_results(None)

    def _set_title(self, *_):
        self.chart.setTitle(escape(self.title.text()), color="#000000", size=f"{self.title_size.value()}pt")

    def _sync_right_view(self):
        self.right_view.setGeometry(self.left_view.sceneBoundingRect())
        self.right_view.linkedViewChanged(self.left_view, self.right_view.XAxis)

    def _layout_legend(self):
        if self.legend.items:
            metrics = QFontMetrics(self.font())
            entry_width = max(metrics.horizontalAdvance(label.text) for _, label in self.legend.items) + 45
            columns = max(1, min(len(self.legend.items), (self.chart_view.width() - 20) // entry_width))
            self.legend.setColumnCount(columns)

    def _clear_series(self):
        self.legend.clear()
        for item in self.series:
            item.getViewBox().removeItem(item)
        self.series.clear()

    def _choose_color(self, index):
        color = QColorDialog.getColor(self.colors[index], self, "Choose chart colour")
        if color.isValid():
            self.colors[index] = color
            self._update_colors()
            self._redraw()

    def _update_colors(self):
        for button, color in zip((self.left_color, self.right_color), self.colors):
            button.setStyleSheet(f"border-bottom: 4px solid {color.name()};")

    def _validate_axis_settings(self, settings):
        for key, title in AXES:
            try:
                axis_parameters(self._axis_values[key], settings[key])
            except ValueError as error:
                raise ValueError(f"{title} axis: {error}") from error

    def _open_axis_settings(self):
        mode = self.plot_type.currentData()
        dialog = AxisSettingsDialog(
            mode, self._axis_settings[mode], self._validate_axis_settings, self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._axis_settings[mode] = dialog.settings
            self._redraw()

    def set_results(self, results, previous=None):
        self.current = results
        self.set_previous(previous, "Previous result" if previous is not None else "")

    def set_previous(self, results, description=""):
        self.previous = results
        self.show_previous.setEnabled(results is not None)
        if results is None:
            self.show_previous.setChecked(False)
        self.comparison_status.setText(description if results is not None else "No previous results.")
        self._data_changed = True
        if self.isVisible():
            self._refresh_data()

    def showEvent(self, event):
        super().showEvent(event)
        if self._data_changed:
            self._refresh_data()

    def _refresh_data(self):
        self._data_changed = False
        self._populate_variables()
        self._redraw()

    def _load_previous(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load comparison results", "", "JSON files (*.json);;All files (*)"
        )
        if not filename:
            return
        try:
            data = read_json(filename)
            if isinstance(data, dict) and "results" in data:
                data = data["results"]
            previous = validate_results(data)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Unable to load comparison", str(error))
            return
        self.set_previous(previous, f"Comparison: {Path(filename).name}")
        self.show_previous.setChecked(True)

    def _populate_variables(self):
        keys = set()
        for result in (self.current, self.previous):
            if result is not None:
                for profile in result["profiles"]:
                    for point in profile["points"]:
                        keys.update(point)
        ordered = [key for key, _ in METRICS if key in keys]
        ordered.extend(sorted(keys - set(ordered)))
        for combo, default, allow_none in (
            (self.x_variable, "x", False),
            (self.left_variable, "z", True),
            (self.right_variable, "u", True),
        ):
            old = combo.currentData() if self._variables_populated else default
            blocked = combo.blockSignals(True)
            try:
                combo.clear()
                if allow_none:
                    combo.addItem("None", None)
                for key in ordered:
                    combo.addItem(_label(key), key)
                index = combo.findData(old)
                if index < 0:
                    index = combo.findData(default)
                combo.setCurrentIndex(index if index >= 0 else (0 if combo.count() else -1))
            finally:
                combo.blockSignals(blocked)
        self._variables_populated = bool(ordered)

    def _redraw(self, *_):
        if not self.isVisible():
            return
        top = self.plot_type.currentData() == "top"
        x_key = self.x_variable.currentData()
        slope_axes = [
            (combo, axis)
            for combo, axis in (
                (self.left_variable, self.left_axis),
                (self.right_variable, self.right_axis),
            )
            if (x_key, combo.currentData()) in (("x", "z"), ("z", "x"))
        ]
        self.show_initial.setEnabled(not top and bool(slope_axes))
        for control in (self.x_variable, self.left_variable, self.right_variable, self.right_color):
            control.setEnabled(not top)
        self._clear_series()
        self.x_axis.setLabel(escape("x (m)" if top else _label(self.x_variable.currentData() or "x")), color="#000000")
        self.left_axis.setLabel(escape("Lateral offset (m)" if top else (
            _label(self.left_variable.currentData()) if self.left_variable.currentData() else ""
        )), color="#000000")
        self.right_axis.setLabel(escape(
            _label(self.right_variable.currentData()) if not top and self.right_variable.currentData() else ""
        ), color="#000000")
        x_values, left_values, right_values = [], [], []
        missing_width = False
        width_notes = []
        slope_note = ""
        sources = [("Current", self.current, False)]
        if self.show_previous.isChecked() and self.previous is not None:
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
                else:
                    x_key = self.x_variable.currentData()
                    if x_key is None:
                        continue
                    for combo, axis, color, values in (
                        (self.left_variable, self.left_axis, self.colors[0], left_values),
                        (self.right_variable, self.right_axis, self.colors[1], right_values),
                    ):
                        key = combo.currentData()
                        if key is not None:
                            self._add_segments(
                                profile, x_key, key, axis, color,
                                f"{source} L{profile['layer']} {_label(key)}", dashed,
                                x_values, values, previous_point=previous_point,
                            )
                previous_profile = profile
        if self.show_initial.isChecked() and not top:
            if not slope_axes:
                slope_note = "Initial slope requires x and z on the chart axes."
            elif self.current is None:
                slope_note = "Initial slope unavailable: no current results."
            else:
                try:
                    points, schematic = _initial_profile(self.current["input"])
                except ValueError as error:
                    slope_note = f"Initial slope unavailable: {error}"
                else:
                    profile = {"points": [{"x": x, "z": z} for x, z in points]}
                    name = "Initial slope (schematic: 75 deg where unspecified)" if schematic else "Initial slope"
                    for combo, axis in slope_axes:
                        values = left_values if axis is self.left_axis else right_values
                        self._add_segments(
                            profile, x_key, combo.currentData(), axis, QColor("#555555"),
                            name, False, x_values, values, line_style=Qt.PenStyle.DashDotLine,
                        )
                    slope_note = "Initial slope uses the current result's input snapshot."
                    if schematic:
                        slope_note += " Unspecified angles are shown schematically at 75 degrees."
        self._layout_legend()
        self.chart.showAxis("left", bool(left_values))
        self.chart.showAxis("right", bool(right_values))
        self._axis_values = {
            "horizontal": x_values, "left": left_values, "right": right_values,
        }
        settings = self._axis_settings[self.plot_type.currentData()]
        try:
            self._validate_axis_settings(settings)
            for key, axis, view in (
                ("horizontal", self.x_axis, self.left_view),
                ("left", self.left_axis, self.left_view),
                ("right", self.right_axis, self.right_view),
            ):
                lower, upper, interval, label_format = axis_parameters(self._axis_values[key], settings[key])
                ticks = axis_ticks(lower, upper, interval, label_format)
                if not math.isfinite(lower + upper):
                    raise ValueError(f"{key} axis limits are too large for chart display.")
                if key == "horizontal":
                    view.setXRange(lower, upper, padding=0)
                    actual_range = view.viewRange()[0]
                else:
                    view.setYRange(lower, upper, padding=0)
                    actual_range = view.viewRange()[1]
                if actual_range != [lower, upper]:
                    raise ValueError(f"{key} axis range is too narrow for chart display.")
                metrics = QFontMetrics(axis.style["tickFont"] or self.font())
                margin = (
                    max(metrics.horizontalAdvance(label) for label, _ in ticks) / 2
                    if key == "horizontal" else metrics.height() / 2
                )
                axis.setStyle(hideOverlappingLabels=max(15, math.ceil(margin) + 2))
                axis.setTicks([[(value, label) for label, value in ticks]])
        except ValueError as error:
            self._clear_series()
            self.status.setText(f"Invalid axis settings: {error}")
            return
        if not x_values:
            description = (
                "No recorded positive widths are available for the top view." if top else
                "No recorded points match the selected variables."
            )
        elif missing_width:
            description = ("Some points have no recorded positive width and are not shown. "
                           "Axes scale independently.")
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
        self.status.setText(" ".join(
            part for part in (description, *width_notes, slope_note, axis_note) if part
        ))

    def _add_segments(
        self, profile, x_key, y_key, axis, color, name, dashed, xs, ys,
        width_sign=None, previous_point=None, line_style=None,
    ):
        count = 0
        for points in _segments(profile, x_key, y_key, width_sign, previous_point):
            pen = QPen(color, 2)
            pen.setCosmetic(True)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            if line_style is not None:
                pen.setStyle(line_style)
            series = pg.PlotDataItem(
                x=[point.x() for point in points], y=[point.y() for point in points],
                name=name, pen=pen, symbol="o" if len(points) == 1 else None,
                symbolSize=5, symbolBrush=color,
            )
            (self.right_view if axis is self.right_axis else self.left_view).addItem(series)
            self.series.append(series)
            if count == 0:
                self.legend.addItem(series, escape(name))
            for point in points:
                for bounds, value in ((xs, point.x()), (ys, point.y())):
                    if not bounds:
                        bounds.extend((value, value))
                    else:
                        bounds[0] = min(bounds[0], value)
                        bounds[1] = max(bounds[1], value)
            count += 1
        return count

    def save_image(self, path):
        path = Path(path)
        image_format = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}.get(path.suffix.lower())
        if image_format is None:
            raise ValueError("Choose a PNG or JPEG filename.")
        if not self.series:
            raise ValueError("There is no chart data to export.")
        image = QImage(self.image_width.value(), self.image_height.value(), QImage.Format.Format_RGB32)
        if image.isNull():
            raise OSError("Unable to allocate the chart image.")
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.chart_view.render(
                painter, QRectF(0, 0, image.width(), image.height()),
                self.chart_view.viewport().rect(), Qt.AspectRatioMode.IgnoreAspectRatio,
            )
        finally:
            painter.end()
        if not image.save(str(path), image_format):
            raise OSError(f"Could not save chart image: {path}")

    def _export_image(self):
        filename, selected = QFileDialog.getSaveFileName(
            self, "Save chart image", "", "PNG image (*.png);;JPEG image (*.jpg *.jpeg)"
        )
        if not filename:
            return
        path = Path(filename)
        if not path.suffix:
            path = path.with_suffix(".jpg" if selected.startswith("JPEG") else ".png")
        try:
            self.save_image(path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Unable to save chart", str(error))
