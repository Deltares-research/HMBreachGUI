"""Editable input case, preserving JSON fields not shown in the editor."""

from copy import deepcopy
import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from GUI.case_io import validate_case
from GUI.geometry_editor import GeometryEditor
from GUI.settings_editor import PHYSICAL_FIELDS, SettingsEditor


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


class CaseEditor(QWidget):
    def __init__(self):
        super().__init__()
        self._case = None
        self._layers = []
        self.dirty = False
        self._loading = False
        self.settings = SettingsEditor()
        self.settings.changed.connect(self._settings_changed)
        self.geometry = GeometryEditor()
        self.geometry.changed.connect(self._geometry_changed)
        self.geometry.matchBottomRequested.connect(self._match_bottom_layer)
        layout = QVBoxLayout(self)
        self.mode_label = QLabel("No input case loaded.")
        layout.addWidget(self.mode_label)
        form = QFormLayout()
        self.initial_fields = {}
        for key, label in INITIAL_FIELDS:
            field = QLineEdit()
            field.textChanged.connect(self._layer_changed)
            self.initial_fields[key] = field
            form.addRow(label, field)
        layout.addLayout(form)
        self.angle_notice = QLabel(
            "Layer angles are inactive with coordinate geometry and are omitted from saved "
            "inputs and calculations. They remain available while this case is open."
        )
        self.angle_notice.setWordWrap(True)
        self.angle_notice.hide()
        layout.addWidget(self.angle_notice)
        self.table = QTableWidget(0, len(LAYER_FIELDS) + 1)
        self.table.setHorizontalHeaderLabels(
            [field[1] for field in LAYER_FIELDS] + ["Effective permeability (mm/s)"]
        )
        self.table.horizontalHeader().moveSection(len(LAYER_FIELDS), 5)
        self.table.setColumnWidth(4, 180)
        self.table.setColumnWidth(len(LAYER_FIELDS), 190)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemChanged.connect(self._layer_changed)
        layout.addWidget(self.table)
        permeability_note = QLabel(
            "Effective permeability is a preview; leave the override blank to use the solver's calculated value."
        )
        permeability_note.setWordWrap(True)
        layout.addWidget(permeability_note)
        actions = QHBoxLayout()
        for text, callback in (
            ("Add layer", self.add_layer),
            ("Copy layer", self.copy_layer),
            ("Remove layer", self.remove_layer),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        gradients = QHBoxLayout()
        self.gradient_all = QLineEdit()
        self.gradient_all.setPlaceholderText("Hydraulic gradient (-)")
        apply_gradient = QPushButton("Apply gradient to all layers")
        apply_gradient.clicked.connect(self._apply_gradient)
        gradients.addWidget(self.gradient_all)
        gradients.addWidget(apply_gradient)
        layout.addLayout(gradients)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

    def _mark_dirty(self, *_):
        if not self._loading:
            self.dirty = True

    def set_case(self, case):
        self.settings.set_case(case)
        self.geometry.set_case(case)
        self._loading = True
        try:
            self._case = deepcopy(case)
            self._layers = deepcopy(case["layers"])
            self._update_mode_label()
            for key, field in self.initial_fields.items():
                field.setText(_display(case["initial_conditions"].get(key)))
            self.table.setRowCount(0)
            for layer in self._layers:
                self._append_row(layer)
            self.angle_notice.setVisible(self.geometry.enabled.isChecked())
            self.message.clear()
            self.dirty = False
        finally:
            self._loading = False
        self._refresh_geometry()
        self.geometry.canvas.fit()

    def _layer_changed(self, *_):
        if not self._loading:
            self._mark_dirty()
            self._refresh_geometry()

    def _geometry_changed(self):
        if not self._loading:
            self.angle_notice.setVisible(self.geometry.enabled.isChecked())
            blocked = self.table.blockSignals(True)
            try:
                for row in range(self.table.rowCount()):
                    self._set_angle_state(self.table.item(row, 7))
            finally:
                self.table.blockSignals(blocked)
            self._mark_dirty()
            self._refresh_geometry()

    def _update_mode_label(self):
        mode = self.settings.mode.currentData()
        width = self.settings.width_model.currentData()
        self.mode_label.setText(f"Mode: {mode if mode is not None else 'breach'} | "
                                f"Width model: {width if width is not None else 'b_constant'}")

    def _settings_changed(self):
        if not self._loading:
            self._update_mode_label()
            self._mark_dirty()
            self._refresh_geometry()

    def _apply_gradient(self):
        if not self.table.rowCount():
            self.message.setText("Add a layer before applying a gradient.")
            return
        text = self.gradient_all.text().strip()
        try:
            gradient = _parse_number(text, "Hydraulic gradient")
            if not math.isfinite(gradient):
                raise ValueError("Hydraulic gradient must be finite.")
        except ValueError as error:
            self.message.setText(str(error))
            return
        self._loading = True
        try:
            for row in range(self.table.rowCount()):
                self.table.item(row, 3).setText(text)
        finally:
            self._loading = False
        self._mark_dirty()
        self._refresh_geometry()
        self.message.clear()

    def _refresh_geometry(self):
        if self._case is None:
            return
        self._refresh_permeability()
        layers = []
        error = ""
        thicknesses = []
        for row in range(self.table.rowCount()):
            try:
                thickness = float(self.table.item(row, 0).text())
            except ValueError:
                thicknesses = []
                break
            if not math.isfinite(thickness) or thickness <= 0:
                thicknesses = []
                break
            thicknesses.append(thickness)
        try:
            for row in range(self.table.rowCount()):
                thickness = _parse_number(self.table.item(row, 0).text(), f"Layer {row + 1} thickness")
                d50 = _parse_number(self.table.item(row, 1).text(), f"Layer {row + 1} d50")
                angle_text = ("" if self.geometry.enabled.isChecked()
                              else self.table.item(row, 7).text().strip())
                angle = _parse_number(angle_text, f"Layer {row + 1} angle") if angle_text else None
                if (not math.isfinite(thickness) or thickness <= 0 or
                        not math.isfinite(d50) or d50 <= 0 or
                        (angle is not None and (not math.isfinite(angle) or not 0 < angle < 90))):
                    raise ValueError(f"Layer {row + 1} needs positive thickness and d50, and an angle between 0 and 90 degrees.")
                layers.append({
                    "thickness": thickness, "d50": d50, "angle": angle,
                    "porosity": self.table.item(row, 2).text(),
                    "gradient": self.table.item(row, 3).text(),
                })
        except ValueError as exc:
            layers = []
            error = str(exc)
        if not error:
            try:
                self.case()
            except ValueError as exc:
                error = str(exc)
        self.settings.message.setText(error)
        self.geometry.refresh(layers, error, thicknesses)

    def _refresh_permeability(self):
        blocked = self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, len(LAYER_FIELDS))
                try:
                    value, source = self._permeability(row)
                    item.setText(f"{value:.12g}")
                    item.setToolTip(f"{source}; mm/s. The solver calculates the authoritative value.")
                except (ValueError, OverflowError) as error:
                    item.setText("--")
                    item.setToolTip(f"Permeability unavailable: {error}")
        finally:
            self.table.blockSignals(blocked)

    def _permeability(self, row):
        def finite_number(text, label):
            value = _parse_number(text, label)
            if not math.isfinite(value):
                raise ValueError(f"{label} must be finite.")
            return value

        override = self.table.item(row, 4).text().strip()
        if override:
            value = finite_number(override, "Permeability override")
            if value <= 0:
                raise ValueError("Permeability override must be positive.")
            return value, "User-specified override"

        d50 = finite_number(self.table.item(row, 1).text(), "D50")
        porosity = finite_number(self.table.item(row, 2).text(), "Porosity") / 100
        if d50 <= 0 or not 0 < porosity < 1:
            raise ValueError("D50 must be positive and porosity must be between 0 and 100%.")
        user_d15 = self.table.item(row, 5).text().strip().lower()
        if user_d15 not in ("", "true", "false"):
            raise ValueError("User D15 must be true or false.")
        if user_d15 == "true":
            d15 = finite_number(self.table.item(row, 6).text(), "D15")
            if d15 <= 0:
                raise ValueError("D15 must be positive.")
        else:
            d15 = d50 / 1.75
        constants = self.settings.physical_fields
        gravity = finite_number(constants["g"].text().strip() or PHYSICAL_DEFAULTS["g"], "Gravity")
        temperature = finite_number(
            constants["temperature_c"].text().strip() or PHYSICAL_DEFAULTS["temperature_c"],
            "Temperature",
        )
        if gravity <= 0 or temperature <= -20:
            raise ValueError("Gravity must be positive and temperature must exceed -20°C.")
        # Preview mirrors HMBresCorrected::derive; it is never serialized as an override.
        viscosity = 40.0 / (20.0 + temperature) * 1.0e-6
        d15_metres = d15 * 1.0e-6
        value = (gravity / (160.0 * viscosity) * (porosity**3 / (1 - porosity)**2)
                 * d15_metres**2 * 1000.0)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Calculated permeability must be finite and positive.")
        return value, "Calculated preview"

    def _match_bottom_layer(self, target_depth):
        if not self.table.rowCount() or not math.isfinite(target_depth) or target_depth <= 0:
            return
        upper_thicknesses = [
            float(self.table.item(row, 0).text()) for row in range(self.table.rowCount() - 1)
        ]
        item = self.table.item(self.table.rowCount() - 1, 0)
        thickness = target_depth - sum(upper_thicknesses)
        if not math.isfinite(thickness) or thickness <= 0:
            self.geometry.message.setText("Cannot match the bottom layer to the slope depth.")
            return
        if sum(upper_thicknesses + [thickness]) > target_depth:
            thickness = math.nextafter(thickness, -math.inf)
        if thickness <= 0:
            self.geometry.message.setText("Cannot match the bottom layer to the slope depth.")
            return
        item.setText(repr(thickness))

    def _set_angle_state(self, item):
        if self.geometry.enabled.isChecked():
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setForeground(QBrush(QColor("gray")))
            item.setToolTip("Ignored and omitted from saved input while coordinate geometry is enabled.")
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setForeground(QBrush())
            item.setToolTip("")

    def _append_row(self, layer):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, (key, _, _) in enumerate(LAYER_FIELDS):
            self.table.setItem(row, column, QTableWidgetItem(_display(layer.get(key))))
        permeability = QTableWidgetItem("--")
        permeability.setFlags(permeability.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, len(LAYER_FIELDS), permeability)
        self._set_angle_state(self.table.item(row, 7))

    def mark_saved(self, case):
        self._case = deepcopy(case)
        self._layers = deepcopy(case["layers"])
        self.dirty = False
        self.message.clear()

    def add_layer(self):
        if self._case is None:
            self.message.setText("Open an input case first.")
            return
        layer = {
            "thickness_m": 1.0,
            "d50_micrometre": 250.0,
            "porosity_percent": 40.0,
            "external_gradient": 0.0,
        }
        if self.settings.mode.currentData() == "turbulence" and not self.geometry.enabled.isChecked():
            layer["initial_alpha_deg"] = 45.0
        if self.settings.width_model.currentData() == "b_fit":
            layer["flow_width_m"] = 1.0
        self._loading = True
        try:
            self._layers.append(layer)
            self._append_row(layer)
        finally:
            self._loading = False
        self.table.selectRow(self.table.rowCount() - 1)
        self._mark_dirty()
        self._refresh_geometry()
        self.message.clear()

    def copy_layer(self):
        row = self.table.currentRow()
        if row < 0:
            self.message.setText("Select a layer to copy.")
            return
        layer = deepcopy(self._layers[row])
        self._loading = True
        try:
            self._layers.append(layer)
            self._append_row(layer)
            target = self.table.rowCount() - 1
            for column in range(len(LAYER_FIELDS)):
                self.table.item(target, column).setText(self.table.item(row, column).text())
        finally:
            self._loading = False
        self.table.selectRow(target)
        self._mark_dirty()
        self._refresh_geometry()
        self.message.clear()

    def remove_layer(self):
        row = self.table.currentRow()
        if row < 0:
            self.message.setText("Select a layer to remove.")
            return
        self.table.removeRow(row)
        del self._layers[row]
        self._mark_dirty()
        self._refresh_geometry()
        self.message.clear()

    def case(self):
        if self._case is None:
            raise ValueError("Open an input case first.")
        case = deepcopy(self._case)
        initial = case["initial_conditions"]
        for key, label in INITIAL_FIELDS:
            text = self.initial_fields[key].text().strip()
            if not text and key == "initial_width_m":
                initial.pop(key, None)
            else:
                initial[key] = _parse_number(text, label)
        layers = []
        for row, original in enumerate(self._layers):
            layer = deepcopy(original)
            for column, (key, label, optional) in enumerate(LAYER_FIELDS):
                if key == "initial_alpha_deg" and self.geometry.enabled.isChecked():
                    layer.pop(key, None)
                    continue
                text = self.table.item(row, column).text().strip()
                if optional and not text:
                    if key in ("permeability_mm_s", "initial_alpha_deg") and layer.get(key, "missing") is None:
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
