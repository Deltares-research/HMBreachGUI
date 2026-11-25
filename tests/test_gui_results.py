import os
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from GUI.app import CaseWindow
from GUI.case_io import read_json, write_json
from GUI.prototype import ROOT


EXECUTABLE = Path(os.environ.get(
    "HMBREACH_EXECUTABLE", str(ROOT / "build" / "Release" / "HMBreach.exe")
)).resolve()


class ResultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = CaseWindow()
        self.results = {
            "format": "hmbreach-results", "version": 1,
            "input": self.window.editor.case(),
            "profiles": [
                {"layer": 2, "points": [
                    {"x": 1, "z": -1, "h": 2, "u": 3, "c": 0.1, "froude": 1.5},
                    {"x": 2, "z": -2, "h": 4, "u": 5, "c": 0.2, "extra_metric": 7},
                ]},
                {"layer": 4, "points": [
                    {"x": 10, "z": -3, "h": 6, "u": 7, "c": 0.3},
                ]},
            ],
        }

    def tearDown(self):
        self.window.editor.dirty = False
        self.window._results_dirty = False
        self.window.close()

    def test_table_selection_optional_columns_and_imported_results(self):
        self.window.set_results(self.results)
        view = self.window.results_view
        self.assertEqual(view.model.rowCount(), 2)
        self.assertEqual(view.layer.itemText(0), "2")
        x = view.model.columns.index("x")
        extra = view.model.columns.index("extra_metric")
        self.assertEqual(view.model.data(view.model.index(0, x)), "1")
        self.assertEqual(view.model.data(view.model.index(0, extra)), "")
        self.assertEqual(view.model.data(view.model.index(1, extra)), "7")
        self.assertIn("Last recorded point: x=2", view.summary.text())
        self.assertFalse(view.open_workbook.isEnabled())
        view.layer.setCurrentIndex(1)
        self.assertEqual(view.model.rowCount(), 1)
        self.assertNotIn("extra_metric", view.model.columns)
        self.assertIn("Layer 4", view.summary.text())
        self.assertIn("input snapshot", view.summary.text())
        self.assertEqual(view.model.headerData(0, Qt.Orientation.Vertical), "1")

    def test_case_embeds_results_manually_and_preserves_input_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.json"
            self.window.save_input(path)
            original = path.read_bytes()
            self.window.set_results(self.results)
            self.window.editor.table.item(0, 1).setText("300")
            self.assertEqual(path.read_bytes(), original)
            self.window.save_input(path)
            saved = read_json(path)
            self.assertEqual(saved["layers"][0]["d50_micrometre"], 300)
            self.assertEqual(saved["results"], self.results)
            self.assertEqual(saved["results"]["input"]["layers"][0]["d50_micrometre"], 250)
            self.window.load_input(path)
            self.assertEqual(self.window.results, self.results)
            self.assertNotIn("results", self.window.editor.case())
            self.assertFalse(self.window._results_dirty)
            self.assertFalse(self.window.results_view.open_workbook.isEnabled())
            self.assertEqual(self.window.results_view.model.rowCount(), 2)
            exported = Path(directory) / "solver-input.json"
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(exported), "")):
                self.window._export_input()
            self.assertEqual(read_json(exported), self.window.editor.case())
            self.assertEqual(read_json(path), saved)
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), "")), \
                    patch.object(QMessageBox, "critical") as error:
                self.window._export_input()
                self.assertIn("different file", error.call_args.args[2])
            self.assertEqual(read_json(path), saved)
            self.window.load_input(ROOT / "examples" / "turbulence_input.json")
            self.assertIsNone(self.window.results)
            self.assertEqual(self.window.results_view.model.rowCount(), 0)

    def test_invalid_embedded_results_do_not_replace_current_case(self):
        self.window.set_results(self.results)
        invalid = deepcopy(self.window.editor.case())
        invalid["results"] = {"format": "hmbreach-results", "version": 2}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            write_json(path, invalid)
            with self.assertRaisesRegex(ValueError, "version"):
                self.window.load_input(path)
        self.assertEqual(self.window.results, self.results)
        self.assertEqual(self.window.editor.case(), self.results["input"])

    def test_opening_another_case_asks_before_discarding_unsaved_results(self):
        self.window.set_results(self.results)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No), \
                patch.object(QFileDialog, "getOpenFileName") as dialog:
            self.window._choose_input()
        dialog.assert_not_called()
        self.assertEqual(self.window.results, self.results)

    def test_output_file_open_reports_missing_and_open_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output.xlsx"
            path.touch()
            self.window.results_view.set_files(path, None)
            with patch.object(QDesktopServices, "openUrl", return_value=True) as open_url:
                self.window.results_view.open_workbook.click()
                self.assertEqual(open_url.call_args.args[0].toLocalFile(), str(path.resolve()).replace("\\", "/"))
            with patch.object(QDesktopServices, "openUrl", return_value=False), \
                    patch.object(QMessageBox, "warning") as warning:
                self.window.results_view.open_workbook.click()
                self.assertIn("Could not open", warning.call_args.args[2])
            path.unlink()
            with patch.object(QMessageBox, "warning") as warning:
                self.window.results_view.open_workbook.click()
                self.assertIn("missing", warning.call_args.args[2])

    @unittest.skipUnless(EXECUTABLE.is_file(), "Build HMBreach or set HMBREACH_EXECUTABLE")
    def test_result_read_failure_preserves_previous_results(self):
        self.window.set_results(self.results)
        self.window.executable.setText(str(EXECUTABLE))
        with tempfile.TemporaryDirectory() as directory:
            self.window.output_directory.setText(directory)
            self.window.results_view.set_files(Path(directory) / "old.xlsx", None)
            loop = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            self.window.resultsFinished.connect(loop.quit)
            ticks = []
            heartbeat = QTimer()
            heartbeat.setInterval(10)
            heartbeat.timeout.connect(
                lambda: ticks.append(1) if self.window._result_future is not None else None
            )

            def slow_failure(*_):
                time.sleep(0.25)
                raise ValueError("broken workbook")

            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
                    patch("GUI.app.results_from_workbook", side_effect=slow_failure):
                heartbeat.start()
                self.window.run_calculation()
                timer.start(30000)
                loop.exec()
                timer.stop()
                heartbeat.stop()
            self.assertEqual(self.window.results, self.results)
            self.assertIn("broken workbook", self.window.result_status.text())
            self.assertGreater(len(ticks), 0)
            self.assertFalse(self.window.results_view.open_workbook.isEnabled())
            self.assertTrue(self.window.run_button.isEnabled())

    @unittest.skipUnless(EXECUTABLE.is_file(), "Build HMBreach or set HMBREACH_EXECUTABLE")
    def test_solver_failure_preserves_previous_results(self):
        self.window.set_results(self.results)
        self.window.executable.setText(str(EXECUTABLE))
        with tempfile.TemporaryDirectory() as directory:
            case = self.window.editor.case()
            case["settings"]["workbook_file"] = str(Path(directory) / "missing" / "output.xlsx")
            self.window.editor.set_case(case)
            self.window.output_directory.setText(directory)
            self.window.results_view.set_files(Path(directory) / "old.xlsx", None)
            loop = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            self.window.resultsFinished.connect(loop.quit)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                self.window.run_calculation()
                timer.start(30000)
                loop.exec()
                timer.stop()
            self.assertIn("failed", self.window.status.text().lower())
            self.assertEqual(self.window.results, self.results)
            self.assertFalse(self.window.results_view.open_workbook.isEnabled())


if __name__ == "__main__":
    unittest.main()
