"""PySide6 case editor and solver integration."""

import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from GUI.case_editor import CaseEditor
from GUI.case_io import load_case, read_json, results_from_workbook, validate_results, write_json
from GUI.charts_view import ChartsView
from GUI.prototype import PrototypeWindow
from GUI.results_view import ResultsView


def _read_workbook(path, case):
    return validate_results(results_from_workbook(path, case))


class CaseWindow(PrototypeWindow):
    resultsFinished = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("HMBreach")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._temporary_input = None
        self._running_case = None
        self.results = None
        self._results_dirty = False
        self._result_future = None
        self._result_executor = None
        self._result_files = None
        self._result_timer = QTimer(self)
        self._result_timer.setInterval(25)
        self._result_timer.timeout.connect(self._finish_results_read)
        self.editor = CaseEditor()
        self.input_file.setReadOnly(True)
        run_page = self.takeCentralWidget()
        tabs = QTabWidget()
        self.tabs = tabs
        self.setCentralWidget(tabs)
        tabs.addTab(self._input_page(), "Input")
        tabs.addTab(self.editor.geometry, "Geometry")
        tabs.addTab(run_page, "Run")
        self.results_view = ResultsView()
        self.result_status = self.results_view.status
        self.results_view.openResultsRequested.connect(self._open_results)
        self.results_view.saveResultsRequested.connect(self._save_results)
        tabs.addTab(self.results_view, "Results")
        self.charts_view = ChartsView()
        tabs.addTab(self.charts_view, "Charts")
        tabs.addTab(self.editor.settings, "Constants")
        self.process.finished.connect(self._collect_results)
        self.process.errorOccurred.connect(self._cleanup_failed_start)
        try:
            self.load_input(Path(self.input_file.text()))
        except (OSError, ValueError) as error:
            self.status.setText(f"Could not load sample input: {error}")

    def _input_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        buttons = QHBoxLayout()
        self.open_button = QPushButton("Open case JSON...")
        self.open_button.clicked.connect(self._choose_input)
        self.save_button = QPushButton("Save case JSON as...")
        self.save_button.clicked.connect(self._save_input)
        self.export_input_button = QPushButton("Export solver input JSON...")
        self.export_input_button.clicked.connect(self._export_input)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.export_input_button)
        layout.addLayout(buttons)
        layout.addWidget(self.editor)
        return page

    def load_input(self, path):
        case = load_case(path)
        results = validate_results(case.pop("results")) if "results" in case else None
        self.editor.set_case(case)
        self.results = results
        self._results_dirty = False
        self.results_view.set_results(results)
        self.results_view.set_files(None, None)
        self.charts_view.set_results(results)
        self.input_file.setText(str(Path(path).resolve()))
        self.status.setText("Input case loaded.")

    def _choose_input(self):
        if self.process.state() != QProcess.ProcessState.NotRunning or self._result_future is not None:
            QMessageBox.information(self, "Calculation running", "Wait for the calculation and results to finish.")
            return
        if (self.editor.dirty or self._results_dirty) and QMessageBox.question(
            self, "Discard changes?", "Discard unsaved input edits or calculation results?"
        ) != QMessageBox.StandardButton.Yes:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open case JSON", "", "JSON files (*.json);;All files (*)"
        )
        if not filename:
            return
        try:
            self.load_input(Path(filename))
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Unable to open input", str(error))

    def save_input(self, path):
        case = self.editor.case()
        document = dict(case)
        if self.results is not None:
            document["results"] = self.results
        write_json(path, document)
        self.editor.mark_saved(case)
        self._results_dirty = False
        self.input_file.setText(str(Path(path).resolve()))
        self.status.setText("Input case saved.")

    def _save_input(self):
        try:
            self.editor.case()
        except ValueError as error:
            self.editor.message.setText(str(error))
            self._show_depth_warning()
            return
        self._show_depth_warning()
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save case JSON", "", "JSON files (*.json);;All files (*)"
        )
        if filename:
            try:
                self.save_input(Path(filename))
            except (OSError, ValueError) as error:
                QMessageBox.critical(self, "Unable to save input", str(error))

    def _export_input(self):
        try:
            case = self.editor.case()
        except ValueError as error:
            self.editor.message.setText(str(error))
            self._show_depth_warning()
            return
        self._show_depth_warning()
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export solver input JSON", "", "JSON files (*.json);;All files (*)"
        )
        if filename:
            try:
                if Path(filename).resolve() == Path(self.input_file.text()).resolve():
                    raise ValueError("Choose a different file to avoid replacing the open case.")
                write_json(filename, case)
            except (OSError, ValueError) as error:
                QMessageBox.critical(self, "Unable to export input", str(error))

    def run_calculation(self):
        if self.process.state() != QProcess.ProcessState.NotRunning or self._result_future is not None:
            return
        try:
            case = self.editor.case()
        except ValueError as error:
            self.editor.message.setText(str(error))
            self.tabs.setCurrentIndex(0)
            self._show_depth_warning()
            return
        directory = Path(self.output_directory.text().strip())
        if not self.output_directory.text().strip() or not directory.is_dir():
            self.status.setText("Select an existing working directory.")
            self.tabs.setCurrentIndex(2)
            return
        if not Path(self.executable.text().strip()).is_file():
            self.status.setText("Select an existing HMBreach executable.")
            self.tabs.setCurrentIndex(2)
            return
        if self._results_dirty and QMessageBox.question(
            self, "Replace results?", "Replace calculation results that have not been saved in the case?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self._show_depth_warning()
        try:
            self._temporary_input = tempfile.TemporaryDirectory(
                prefix="hmbreach-input-", dir=directory
            )
            input_path = Path(self._temporary_input.name) / "input.json"
            write_json(input_path, case)
        except (OSError, ValueError) as error:
            self._cleanup_temporary_input()
            self.status.setText(f"Unable to prepare calculation: {error}")
            self.tabs.setCurrentIndex(2)
            return
        self._running_case = case
        self.results_view.set_files(None, None)
        original_filename = self.input_file.text()
        self.input_file.setText(str(input_path.resolve()))
        self.tabs.setCurrentIndex(2)
        try:
            super().run_calculation()
        finally:
            self.input_file.setText(original_filename)

    def _show_depth_warning(self):
        warning = self.editor.geometry.depth_warning.text()
        if warning:
            QMessageBox.warning(self, "Layer and slope depth mismatch", warning)

    def _cleanup_temporary_input(self):
        if self._temporary_input is not None:
            self._temporary_input.cleanup()
            self._temporary_input = None

    def _cleanup_failed_start(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._cleanup_temporary_input()
            self._running_case = None
            self.resultsFinished.emit(False)

    def _collect_results(self, exit_code, exit_status):
        try:
            if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
                self.result_status.setText(
                    "Calculation failed; previously loaded results were not changed."
                )
                self.resultsFinished.emit(False)
                return
            case = self._running_case
            if case is None:
                raise ValueError("Calculation input snapshot is missing.")
            settings = case.get("settings", {})
            workbook = Path(settings.get("workbook_file", settings.get("profile_file", "hmbres_results.xlsx")))
            if not workbook.is_absolute():
                workbook = Path(self.process.workingDirectory()) / workbook
            workbook = workbook.resolve()
            geometry = workbook.with_name(workbook.stem + "_initial_geometry.svg")
            self._result_files = (workbook, geometry)
            self._result_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hmbreach-results")
            self._result_future = self._result_executor.submit(_read_workbook, workbook, case)
            self._result_timer.start()
            self.run_button.setEnabled(False)
            self.status.setText("Calculation completed; reading results...")
        except (OSError, ValueError) as error:
            self.result_status.setText(f"Unable to load calculation results: {error}")
            self.status.setText("Calculation finished, but results could not be loaded.")
            self.resultsFinished.emit(False)
        finally:
            self._cleanup_temporary_input()
            self._running_case = None

    def _finish_results_read(self):
        if self._result_future is None or not self._result_future.done():
            return
        self._result_timer.stop()
        future = self._result_future
        workbook, geometry = self._result_files
        self._result_future = None
        self._result_files = None
        self._result_executor.shutdown(wait=False)
        self._result_executor = None
        self.run_button.setEnabled(True)
        error = future.exception()
        if error is not None:
            self.result_status.setText(f"Unable to load calculation results: {type(error).__name__}: {error}")
            self.status.setText("Calculation finished, but results could not be loaded.")
            self.resultsFinished.emit(False)
            return
        self.set_results(future.result())
        self.results_view.set_files(workbook, geometry if geometry.is_file() else None)
        self.status.setText("Calculation completed.")
        self.resultsFinished.emit(True)

    def closeEvent(self, event):
        if self._result_future is not None:
            QMessageBox.information(self, "Reading results", "Wait for results to finish loading before closing.")
            event.ignore()
            return
        if self.process.state() != QProcess.ProcessState.NotRunning:
            super().closeEvent(event)
            return
        if (self.editor.dirty or self._results_dirty) and QMessageBox.question(
            self, "Discard changes?", "Discard unsaved input edits or calculation results?"
        ) != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        event.accept()

    def set_results(self, results):
        previous = self.results
        self.results = validate_results(results)
        self._results_dirty = True
        self.results_view.set_results(self.results)
        self.results_view.set_files(None, None)
        self.charts_view.set_results(self.results, previous)

    def _open_results(self):
        if self.process.state() != QProcess.ProcessState.NotRunning or self._result_future is not None:
            QMessageBox.information(self, "Calculation running", "Wait for the calculation and results to finish.")
            return
        if self._results_dirty and QMessageBox.question(
            self, "Replace results?", "Replace results that have not been saved in the case?"
        ) != QMessageBox.StandardButton.Yes:
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Open results JSON", "", "JSON files (*.json);;All files (*)"
        )
        if filename:
            try:
                self.set_results(read_json(filename))
            except (OSError, ValueError) as error:
                QMessageBox.critical(self, "Unable to open results", str(error))

    def save_results(self, path):
        if self.results is None:
            raise ValueError("Run a calculation or open results first.")
        write_json(path, self.results)

    def _save_results(self):
        if self.results is None:
            self.result_status.setText("Run a calculation or open results before saving.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save results JSON", "", "JSON files (*.json);;All files (*)"
        )
        if filename:
            try:
                self.save_results(Path(filename))
            except (OSError, ValueError) as error:
                QMessageBox.critical(self, "Unable to save results", str(error))


def main():
    application = QApplication(sys.argv)
    window = CaseWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
