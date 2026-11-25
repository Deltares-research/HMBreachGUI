"""Editable solver settings and model-default overrides."""

import math
from copy import deepcopy

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)


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


class SettingsEditor(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._loading = False
        self._width_points = []
        self._width_geometry_present = False
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Blank fields use solver defaults. Changing a width model may require changes "
            "to initial width and layer flow widths on the Input tab. Layer angles and "
            "hydraulic gradients are edited on the Input tab. Legacy alfa_reset, a_1_n0 "
            "and d50d15 overrides are not supported by the current solver."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        groups = QVBoxLayout(contents)

        model = QGroupBox("Model and flow width")
        form = QFormLayout(model)
        self.mode = self._combo((
            ("Default (breach)", None), ("Breach", "breach"), ("Turbulence", "turbulence"),
        ))
        self.width_model = self._combo((
            ("Default (B-Constant)", None), ("B-Constant", "b_constant"),
            ("Unit width (B-Constant alias)", "unit_width"), ("B-Fit", "b_fit"),
            ("B-Calc / fanning", "b_calc"), ("Fanning (B-Calc alias)", "fanning"),
            ("Width geometry", "geometry"),
        ))
        self.fit_type = self._combo((
            ("Default (Poly4)", None), ("Straight line", "straight_line"),
            ("Poly2", "poly2"), ("Poly3", "poly3"), ("Poly4", "poly4"),
            ("Exponential", "exp"), ("Power", "power"), ("Logarithmic", "log"),
            ("Rodbard", "rodbard"), ("Gamma variate", "gamma_variate"),
        ))
        self.fit_iterations = self._field("1000")
        form.addRow("Calculation mode", self.mode)
        form.addRow("Flow-width model", self.width_model)
        form.addRow("B-Fit function", self.fit_type)
        form.addRow("B-Fit iteration limit", self.fit_iterations)
        note = QLabel("B-Fit settings are valid only in B-Fit mode; clear them when switching modes.")
        note.setWordWrap(True)
        form.addRow(note)
        self.width_table = QTableWidget(0, 2)
        self.width_table.setHorizontalHeaderLabels(["Distance s (m)", "Width (m)"])
        self.width_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.width_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.width_table.setMinimumHeight(130)
        self.width_table.setMaximumHeight(150)
        self.width_table.itemChanged.connect(self._edited)
        form.addRow("Width geometry points", self.width_table)
        buttons = QHBoxLayout()
        add = QPushButton("Add width point")
        add.clicked.connect(self.add_width_point)
        remove = QPushButton("Remove width point")
        remove.clicked.connect(self.remove_width_point)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        form.addRow(buttons)
        width_note = QLabel("Width geometry points are valid only in width-geometry mode.")
        width_note.setWordWrap(True)
        form.addRow(width_note)
        groups.addWidget(model)

        physical = QGroupBox("Physical constants")
        form = QFormLayout(physical)
        self.erosion_variant = self._combo((
            ("Default (Variant 2)", None), ("Variant 1", "variant_1"),
            ("Variant 2", "variant_2"),
        ))
        self.erosion_variant.currentIndexChanged.connect(self._variant_changed)
        form.addRow("Erosion formulation", self.erosion_variant)
        self.physical_fields = {}
        for key, label, default in PHYSICAL_FIELDS:
            field = self._field(default)
            field.setToolTip(f"{label}. Leave blank for the solver default: {default}.")
            self.physical_fields[key] = field
            form.addRow(label, field)
        groups.addWidget(physical)

        numerical = QGroupBox("Numerical options")
        form = QFormLayout(numerical)
        self.option_fields = {}
        for key, label, default, _ in OPTION_FIELDS:
            field = self._field(default)
            field.setToolTip(f"{label}. Leave blank for the solver default: {default}.")
            self.option_fields[key] = field
            form.addRow(label, field)
        self.adaptive = self._combo((
            ("Default (off)", None), ("Off", False), ("On", True),
        ))
        form.addRow("Adaptive step sizing", self.adaptive)
        groups.addWidget(numerical)
        reset = QPushButton("Reset physical and numerical overrides")
        reset.clicked.connect(self._confirm_reset)
        groups.addWidget(reset)
        groups.addStretch()
        scroll.setWidget(contents)
        layout.addWidget(scroll, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self._variant_changed()

    def _field(self, default):
        field = QLineEdit()
        field.setPlaceholderText(f"Default: {default}")
        field.textChanged.connect(self._edited)
        return field

    def _combo(self, values):
        combo = QComboBox()
        for label, value in values:
            combo.addItem(label, value)
        combo.currentIndexChanged.connect(self._edited)
        return combo

    def _edited(self, *_):
        if not self._loading:
            self.changed.emit()

    def _variant_changed(self, *_):
        variant = self.erosion_variant.currentData()
        if variant is None or variant == "variant_2":
            phi, erosion_b = "29", "0.3"
        elif variant == "variant_1":
            phi, erosion_b = "32", "0.06"
        else:
            phi, erosion_b = "variant-dependent", "variant-dependent"
        for key, default in (("phi_deg", phi), ("erosion_b", erosion_b)):
            self.physical_fields[key].setPlaceholderText(f"Default: {default}")
            self.physical_fields[key].setToolTip(f"Leave blank for the selected variant's default: {default}.")

    def _set_combo(self, combo, value):
        # bools and integers compare equal in Python; only exact types are interchangeable here.
        index = next(
            (i for i in range(combo.count())
             if type(combo.itemData(i)) is type(value) and combo.itemData(i) == value),
            -1,
        )
        if index < 0:
            combo.addItem(f"Unsupported: {value}", value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def set_case(self, case):
        settings = case.get("settings", {})
        constants = settings.get("physical_constants", {})
        options = settings.get("model_options", {})
        width_points = settings.get("width_geometry", [])
        if not isinstance(constants, dict) or not isinstance(options, dict):
            raise ValueError("Physical constants and model options must be objects.")
        if not isinstance(width_points, list) or any(not isinstance(p, dict) for p in width_points):
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
                while combo.count() and combo.itemText(combo.count() - 1).startswith("Unsupported: "):
                    combo.removeItem(combo.count() - 1)
                self._set_combo(combo, value)
            self.fit_iterations.setText(str(settings["width_fit_max_iterations"])
                                        if "width_fit_max_iterations" in settings else "")
            for key, field in self.physical_fields.items():
                field.setText(str(constants[key]) if key in constants else "")
            for key, field in self.option_fields.items():
                field.setText(str(options[key]) if key in options else "")
            self._width_points = deepcopy(width_points)
            self._width_geometry_present = "width_geometry" in settings
            self.width_table.setRowCount(0)
            for point in self._width_points:
                self._append_point(point)
            self.message.clear()
        finally:
            self._loading = False

    def _append_point(self, point):
        row = self.width_table.rowCount()
        self.width_table.insertRow(row)
        for column, key in enumerate(("s_m", "width_m")):
            self.width_table.setItem(row, column, QTableWidgetItem(str(point.get(key, ""))))

    def add_width_point(self):
        self._loading = True
        try:
            self._width_geometry_present = True
            self._width_points.append({})
            self._append_point({})
            self.width_table.selectRow(self.width_table.rowCount() - 1)
        finally:
            self._loading = False
        self.changed.emit()

    def remove_width_point(self):
        row = self.width_table.currentRow()
        if row < 0:
            self.message.setText("Select a width point to remove.")
            return
        self._loading = True
        try:
            self.width_table.removeRow(row)
            del self._width_points[row]
            self._width_geometry_present = bool(self._width_points)
        finally:
            self._loading = False
        self.changed.emit()

    def _confirm_reset(self):
        if QMessageBox.question(
            self, "Reset overrides?",
            "Reset all physical constants and numerical options to the solver defaults?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._loading = True
        try:
            self.erosion_variant.setCurrentIndex(0)
            self.adaptive.setCurrentIndex(0)
            for field in (*self.physical_fields.values(), *self.option_fields.values()):
                field.clear()
        finally:
            self._loading = False
        self.changed.emit()

    def apply_to_case(self, case):
        had_settings = "settings" in case
        settings = case.setdefault("settings", {})
        for key, combo in (
            ("mode", self.mode), ("width_model", self.width_model),
            ("width_fit_type", self.fit_type),
        ):
            value = combo.currentData()
            if value is None:
                settings.pop(key, None)
            else:
                settings[key] = value
        iterations = self.fit_iterations.text().strip()
        if iterations:
            settings["width_fit_max_iterations"] = _number(iterations, "B-Fit iteration limit", True)
        else:
            settings.pop("width_fit_max_iterations", None)
        constants = deepcopy(settings.get("physical_constants", {}))
        options = deepcopy(settings.get("model_options", {}))
        variant = self.erosion_variant.currentData()
        if variant is None:
            constants.pop("erosion_variant", None)
        else:
            constants["erosion_variant"] = variant
        for key, label, _ in PHYSICAL_FIELDS:
            text = self.physical_fields[key].text().strip()
            if text:
                constants[key] = _number(text, label)
            else:
                constants.pop(key, None)
        for key, label, _, integer in OPTION_FIELDS:
            text = self.option_fields[key].text().strip()
            if text:
                options[key] = _number(text, label, integer)
            else:
                options.pop(key, None)
        adaptive = self.adaptive.currentData()
        if adaptive is None:
            options.pop("adaptive_step_sizing", None)
        else:
            options["adaptive_step_sizing"] = adaptive
        for key, value in (("physical_constants", constants), ("model_options", options)):
            if value or key in settings:
                settings[key] = value
        if self._width_geometry_present:
            points = []
            for row, original in enumerate(self._width_points):
                point = deepcopy(original)
                for column, key in enumerate(("s_m", "width_m")):
                    point[key] = _number(
                        self.width_table.item(row, column).text().strip(),
                        f"Width point {row + 1} {key}",
                    )
                points.append(point)
            settings["width_geometry"] = points
        else:
            settings.pop("width_geometry", None)
        if not had_settings and not settings:
            case.pop("settings")
