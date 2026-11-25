"""Interactive slope coordinates and initial material-layer preview."""

import math
from copy import deepcopy

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)


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


class SlopeCanvas(QWidget):
    pointAdded = Signal(float, float)
    pointMoved = Signal(int, float, float)
    pointSelected = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 280)
        self.points = []
        self.profile = []
        self.layers = []
        self.selected = -1
        self.editable = False
        self.lock_origin = False
        self.bounds = (-0.1, 1.1, -1.1, 0.1)
        self._dragging = False

    def set_data(self, points, profile, layers, editable):
        self.points = points
        self.profile = profile
        self.layers = layers
        self.editable = editable
        self.update()

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
        self.update()

    def plot_rect(self):
        return QRectF(62, 18, max(1, self.width() - 82), max(1, self.height() - 60))

    def to_screen(self, x, y):
        left, right, bottom, top = self.bounds
        rect = self.plot_rect()
        return QPointF(rect.left() + (x - left) / (right - left) * rect.width(),
                       rect.bottom() - (y - bottom) / (top - bottom) * rect.height())

    def to_world(self, point):
        left, right, bottom, top = self.bounds
        rect = self.plot_rect()
        return (left + (point.x() - rect.left()) / rect.width() * (right - left),
                bottom + (rect.bottom() - point.y()) / rect.height() * (top - bottom))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        rect = self.plot_rect()
        for tick in range(6):
            x = rect.left() + rect.width() * tick / 5
            y = rect.top() + rect.height() * tick / 5
            painter.setPen(QPen(QColor("#dddddd"), 1))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            wx, _ = self.to_world(QPointF(x, rect.bottom()))
            _, wy = self.to_world(QPointF(rect.left(), y))
            painter.setPen(QColor("#333333"))
            painter.drawText(QRectF(x - 35, rect.bottom() + 4, 70, 18),
                             Qt.AlignmentFlag.AlignHCenter, f"{wx:.2f}")
            painter.drawText(QRectF(0, y - 9, 56, 18),
                             Qt.AlignmentFlag.AlignRight, f"{wy:.2f}")
        painter.save()
        painter.setClipRect(rect)
        if self.profile:
            grains = sorted(set(layer["d50"] for layer in self.layers))
            depth = 0.0
            for index, layer in enumerate(self.layers, 1):
                top = -depth
                depth += layer["thickness"]
                bottom = -depth
                fraction = grains.index(layer["d50"]) / max(1, len(grains) - 1)
                color = QColor(round(253 - 113 * fraction), round(231 - 150 * fraction),
                               round(37 - 27 * fraction))
                left = self.profile[0][0]
                polygon = [(left, top), (_x_at_y(self.profile, top), top)]
                polygon.extend(p for p in self.profile if bottom < p[1] < top)
                polygon.extend([(_x_at_y(self.profile, bottom), bottom), (left, bottom)])
                painter.setPen(QPen(QColor("#806b47"), 1))
                painter.setBrush(color)
                painter.drawPolygon(QPolygonF([self.to_screen(*p) for p in polygon]))
                middle = (top + bottom) / 2
                label_x = (left + _x_at_y(self.profile, middle)) / 2
                painter.setPen(QColor("#333333"))
                painter.drawText(self.to_screen(label_x, middle), str(index))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#0072b2"), 3))
            painter.drawPolyline(QPolygonF([self.to_screen(*p) for p in self.profile]))
        if self.editable and self.points:
            painter.setPen(QPen(QColor("#006198"), 2, Qt.PenStyle.DashLine))
            painter.drawPolyline(QPolygonF([self.to_screen(*p) for p in self.points]))
            for index, point in enumerate(self.points):
                painter.setBrush(QColor("#d62728") if index == self.selected else QColor("#0072b2"))
                painter.drawEllipse(self.to_screen(*point), 5, 5)
        painter.restore()
        painter.setPen(QColor("#333333"))
        painter.drawRect(rect)
        painter.drawText(QRectF(rect.left(), rect.bottom() + 23, rect.width(), 18),
                         Qt.AlignmentFlag.AlignHCenter, "X (m)")
        painter.drawText(4, 14, "Y (m)")

    def mousePressEvent(self, event):
        if not self.editable or event.button() != Qt.MouseButton.LeftButton:
            return
        position = event.position()
        if not self.plot_rect().contains(position):
            return
        distances = [(self.to_screen(*point) - position).manhattanLength()
                     for point in self.points]
        if distances and min(distances) <= 12:
            self.selected = distances.index(min(distances))
            self._dragging = not (self.lock_origin and self.selected == 0)
            self.pointSelected.emit(self.selected)
            self.update()
        else:
            self.pointAdded.emit(*self.to_world(position))

    def mouseMoveEvent(self, event):
        if self._dragging and self.selected >= 0:
            self.pointMoved.emit(self.selected, *self.to_world(event.position()))

    def mouseReleaseEvent(self, event):
        self._dragging = False


class GeometryEditor(QWidget):
    changed = Signal()
    matchBottomRequested = Signal(float)

    def __init__(self):
        super().__init__()
        self._loading = False
        self._original_points = []
        self._lock_origin = False
        self._target_depth = None
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox("Use coordinate slope geometry")
        self.enabled.toggled.connect(self._toggle_geometry)
        layout.addWidget(self.enabled)
        hint = QLabel(
            "New slopes start at (0, 0). Click to append points; drag a point to move it. "
            "Edit exact coordinates in the table. "
            "Coordinates must descend from left to right and cover all layers. "
            "Layer angles are ignored and omitted from saved input while coordinates are used."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        content = QHBoxLayout()
        self.canvas = SlopeCanvas()
        content.addWidget(self.canvas, 3)
        controls = QVBoxLayout()
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["X (m)", "Y (m)"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._edited)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        controls.addWidget(self.table)
        self.remove_button = QPushButton("Remove selected point")
        self.remove_button.clicked.connect(self.remove_point)
        controls.addWidget(self.remove_button)
        self.match_button = QPushButton("Match bottom layer to slope bottom")
        self.match_button.clicked.connect(self._match_bottom)
        controls.addWidget(self.match_button)
        fit = QPushButton("Fit view")
        fit.clicked.connect(self.canvas.fit)
        controls.addWidget(fit)
        self.properties = QLabel()
        self.properties.setWordWrap(True)
        controls.addWidget(self.properties)
        content.addLayout(controls, 2)
        layout.addLayout(content, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.depth_warning = QLabel()
        self.depth_warning.setWordWrap(True)
        self.depth_warning.setStyleSheet("color: #a54b00;")
        layout.addWidget(self.depth_warning)
        self.canvas.pointAdded.connect(self.add_point)
        self.canvas.pointMoved.connect(self.move_point)
        self.canvas.pointSelected.connect(self.table.selectRow)

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
            self.enabled.setChecked(has_geometry)
            self.table.setRowCount(0)
            for point in self._original_points:
                self._append(point.get("x_m", ""), point.get("y_m", ""))
            if has_geometry and not self._original_points:
                self._insert_origin()
            self.canvas.selected = -1
        finally:
            self._loading = False

    def _append(self, x, y):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, value in enumerate((x, y)):
            item = QTableWidgetItem(str(value))
            if row == 0 and self._lock_origin:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, column, item)

    def _insert_origin(self):
        self._lock_origin = True
        self._original_points.append({"x_m": 0.0, "y_m": 0.0})
        self._append(0, 0)

    def _toggle_geometry(self, checked):
        if self._loading:
            return
        if checked and not self._original_points:
            self._loading = True
            try:
                self._insert_origin()
            finally:
                self._loading = False
        self.changed.emit()

    def _edited(self, *_):
        if not self._loading:
            self.changed.emit()

    def _selection_changed(self):
        self.canvas.selected = self.table.currentRow()
        self.canvas.update()

    def add_point(self, x, y):
        self._loading = True
        try:
            if not self._original_points:
                self._insert_origin()
            self._original_points.append({})
            self._append(f"{x:.6g}", f"{y:.6g}")
            self.table.selectRow(self.table.rowCount() - 1)
        finally:
            self._loading = False
        self.changed.emit()

    def move_point(self, row, x, y):
        if row == 0 and self._lock_origin:
            return
        self._loading = True
        try:
            self.table.item(row, 0).setText(f"{x:.6g}")
            self.table.item(row, 1).setText(f"{y:.6g}")
        finally:
            self._loading = False
        self.changed.emit()

    def remove_point(self):
        row = self.table.currentRow()
        if row < 0:
            self.message.setText("Select a point to remove.")
            return
        if row == 0 and self._lock_origin:
            self.message.setText("The first point of this slope is fixed at (0, 0).")
            return
        self._loading = True
        try:
            self.table.removeRow(row)
            del self._original_points[row]
            self.canvas.selected = self.table.currentRow()
        finally:
            self._loading = False
        self.changed.emit()

    def points(self):
        points = []
        for row, original in enumerate(self._original_points):
            point = deepcopy(original)
            for column, key in enumerate(("x_m", "y_m")):
                try:
                    value = float(self.table.item(row, column).text())
                except ValueError as error:
                    raise ValueError(f"Slope point {row + 1} {key} must be a number.") from error
                if not math.isfinite(value):
                    raise ValueError(f"Slope point {row + 1} {key} must be finite.")
                point[key] = value
            points.append(point)
        return points

    def apply_to_case(self, case):
        if self.enabled.isChecked():
            case.setdefault("settings", {})["slope_geometry"] = self.points()
        elif "settings" in case:
            case["settings"].pop("slope_geometry", None)

    def _match_bottom(self):
        if self._target_depth is not None:
            self.matchBottomRequested.emit(self._target_depth)

    def refresh(self, layers, error="", thicknesses=None):
        points = []
        profile = []
        try:
            if self.enabled.isChecked():
                points = [(point["x_m"], point["y_m"]) for point in self.points()]
                profile = preview_profile(points, layers)
            else:
                profile = preview_profile(None, layers)
        except ValueError as exc:
            if not error:
                error = str(exc)
        self.canvas.set_data(points, profile, layers, self.enabled.isChecked())
        self.canvas.lock_origin = self._lock_origin
        self.table.setEnabled(self.enabled.isChecked())
        self.remove_button.setEnabled(self.enabled.isChecked())
        self._target_depth = None
        warning = ""
        if self.enabled.isChecked() and len(points) >= 2 and thicknesses:
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
        self.depth_warning.setText(warning)
        self.match_button.setEnabled(self._target_depth is not None)
        self.properties.setText("\n".join(
            f"Layer {index}: {layer['thickness']:g} m; D50 {layer['d50']:g} um; "
            f"porosity {layer['porosity']}%; gradient {layer['gradient']}"
            for index, layer in enumerate(layers, 1)
        ))
        if not error:
            error = ("Input geometry; not calculated output." if self.enabled.isChecked() else
                     "Layer profile; unspecified angles use 75 degrees (schematic).")
        self.message.setText(error)
