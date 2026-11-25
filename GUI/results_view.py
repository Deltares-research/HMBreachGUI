"""Read-only, virtualized display of recorded computational-layer profiles."""

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableView,
    QVBoxLayout, QWidget,
)


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


class ProfileTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = []
        self.columns = []

    def set_points(self, points):
        keys = set()
        for point in points:
            keys.update(point)
        known = [key for key, _ in METRICS if key in keys]
        columns = known + sorted(keys - set(known))
        self.beginResetModel()
        self.points = points
        self.columns = columns
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.points)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.points[index.row()].get(self.columns[index.column()])
        if role == Qt.ItemDataRole.DisplayRole:
            return "" if value is None else f"{value:.12g}"
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        if 0 <= section < len(self.columns):
            key = self.columns[section]
            return dict(METRICS).get(key, key)
        return None


class ResultsView(QWidget):
    openResultsRequested = Signal()
    saveResultsRequested = Signal()

    def __init__(self):
        super().__init__()
        self._profiles = []
        self.workbook = None
        self.geometry = None
        layout = QVBoxLayout(self)
        self.status = QLabel("No results loaded.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.open_results = QPushButton("Open results JSON...")
        self.open_results.clicked.connect(self.openResultsRequested.emit)
        self.save_results = QPushButton("Save results JSON as...")
        self.save_results.clicked.connect(self.saveResultsRequested.emit)
        self.open_workbook = QPushButton("Open results workbook")
        self.open_workbook.clicked.connect(lambda: self._open_file(self.workbook))
        self.open_geometry = QPushButton("Open initial geometry SVG")
        self.open_geometry.clicked.connect(lambda: self._open_file(self.geometry))
        for button in (self.open_results, self.save_results, self.open_workbook, self.open_geometry):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.file_status = QLabel()
        self.file_status.setWordWrap(True)
        layout.addWidget(self.file_status)
        row = QHBoxLayout()
        row.addWidget(QLabel("Computational layer:"))
        self.layer = QComboBox()
        self.layer.currentIndexChanged.connect(self._select_layer)
        row.addWidget(self.layer)
        row.addStretch()
        layout.addLayout(row)
        self.summary = QLabel("Run a calculation or open results to see recorded profile data.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableView()
        self.model = ProfileTableModel(self.table)
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)
        note = QLabel("Values are recorded profile points. Full solver diagnostics are on the Run tab.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.set_files(None, None)

    def set_files(self, workbook, geometry):
        self.workbook = Path(workbook) if workbook is not None else None
        self.geometry = Path(geometry) if geometry is not None else None
        self.open_workbook.setEnabled(self.workbook is not None)
        self.open_geometry.setEnabled(self.geometry is not None)
        if self.workbook is None and self.geometry is None:
            self.file_status.setText("No output files associated with these results.")
        else:
            self.file_status.setText(
                f"Workbook: {self.workbook if self.workbook is not None else 'unavailable'}\n"
                f"Initial geometry: {self.geometry if self.geometry is not None else 'unavailable'}"
            )

    def set_results(self, results):
        self._profiles = results["profiles"] if results is not None else []
        blocked = self.layer.blockSignals(True)
        try:
            self.layer.clear()
            for profile in self._profiles:
                self.layer.addItem(str(profile["layer"]))
        finally:
            self.layer.blockSignals(blocked)
        if results is None:
            self.status.setText("No results loaded.")
            self.summary.setText("Run a calculation or open results to see recorded profile data.")
            self.model.set_points([])
            return
        count = sum(len(profile["points"]) for profile in self._profiles)
        self.status.setText(f"Loaded {len(self._profiles)} computational layers and {count} profile points.")
        self._select_layer()

    def _select_layer(self, *_):
        index = self.layer.currentIndex()
        if index < 0:
            self.model.set_points([])
            return
        profile = self._profiles[index]
        points = profile["points"]
        self.model.set_points(points)
        last = points[-1]
        self.summary.setText(
            f"Layer {profile['layer']}: {len(points)} points. Last recorded point: "
            f"x={last['x']:.6g} m, z={last['z']:.6g} m, h={last['h']:.6g} m, "
            f"u={last['u']:.6g} m/s, c={last['c']:.6g} (-). "
            "Results refer to their stored input snapshot, which may differ from the current input."
        )

    def _open_file(self, path):
        if path is None or not path.is_file():
            QMessageBox.warning(self, "Output unavailable", f"Output file is missing: {path}")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            QMessageBox.warning(self, "Unable to open output", f"Could not open: {path}")
