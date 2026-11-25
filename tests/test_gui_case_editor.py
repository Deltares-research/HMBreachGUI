import os
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from GUI.app import CaseWindow
from GUI.case_io import load_case, read_json, results_from_workbook, validate_results, write_json
from GUI.prototype import ROOT


EXECUTABLE = Path(os.environ.get(
    "HMBREACH_EXECUTABLE", str(ROOT / "build" / "Release" / "HMBreach.exe")
)).resolve()


class CaseEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = CaseWindow()

    def tearDown(self):
        self.window.editor.dirty = False
        self.window._results_dirty = False
        self.window.close()

    def test_round_trip_preserves_geometry_and_other_settings(self):
        source = ROOT / "examples" / "coordinate_geometry_input.json"
        original = load_case(source)
        self.window.load_input(source)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "case.json"
            self.window.save_input(target)
            self.assertEqual(read_json(target), original)

    def test_copy_add_remove_and_validate_without_losing_edits(self):
        editor = self.window.editor
        editor.table.selectRow(0)
        editor.table.item(0, 1).setText("321")
        editor.copy_layer()
        self.assertEqual(editor.case()["layers"][-1]["d50_micrometre"], 321)
        editor.remove_layer()
        editor.add_layer()
        self.assertEqual(len(editor.case()["layers"]), 3)
        editor.table.item(2, 0).setText("-1")
        with self.assertRaisesRegex(ValueError, "Layer 3 thickness"):
            editor.case()
        self.assertEqual(editor.table.item(2, 0).text(), "-1")

    def test_user_d15_and_initial_concentration_validation(self):
        editor = self.window.editor
        editor.table.item(0, 5).setText("true")
        with self.assertRaisesRegex(ValueError, "requires d15"):
            editor.case()
        editor.table.item(0, 6).setText("100")
        editor.initial_fields["initial_concentration_percent"].setText("60")
        with self.assertRaisesRegex(ValueError, "Initial concentration"):
            editor.case()

    def test_permeability_preview_updates_without_creating_overrides(self):
        editor = self.window.editor
        preview = editor.table.item(0, 9)
        initial = float(preview.text())
        self.assertAlmostEqual(initial, 0.19468968254, places=10)
        self.assertIn("Calculated preview", preview.toolTip())
        self.assertIsNone(editor.case()["layers"][0]["permeability_mm_s"])
        self.assertFalse(editor.dirty)
        editor.table.item(0, 1).setText("500")
        self.assertAlmostEqual(float(preview.text()), initial * 4, places=9)
        editor.table.item(0, 5).setText("true")
        editor.table.item(0, 6).setText("100")
        expected = initial * (100 / (250 / 1.75)) ** 2
        self.assertAlmostEqual(float(preview.text()), expected, places=10)
        editor.settings.physical_fields["g"].setText("19.62472")
        editor.settings.physical_fields["temperature_c"].setText("20")
        self.assertAlmostEqual(float(preview.text()), expected * 2 * 40 / 35, places=10)
        editor.table.item(0, 4).setText("0.9")
        self.assertEqual(preview.text(), "0.9")
        self.assertIn("User-specified override", preview.toolTip())
        editor.table.item(0, 4).setText("-1")
        self.assertEqual(preview.text(), "--")
        self.assertIn("must be positive", preview.toolTip())
        editor.table.item(0, 4).setText("")
        self.assertAlmostEqual(float(preview.text()), expected * 2 * 40 / 35, places=10)
        editor.table.item(0, 2).setText("invalid")
        self.assertEqual(preview.text(), "--")
        self.assertIn("Porosity", preview.toolTip())

    def test_invalid_geometry_and_settings_are_reported_before_saving(self):
        self.window.load_input(ROOT / "examples" / "coordinate_geometry_input.json")
        self.window.editor.table.item(0, 0).setText("10")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "case.json"
            with self.assertRaisesRegex(ValueError, "total layer thickness"):
                self.window.save_input(target)
            self.assertFalse(target.exists())
            self.assertEqual(self.window.editor.table.item(0, 0).text(), "10")

        case = load_case(ROOT / "examples" / "turbulence_input.json")
        case["settings"]["model_options"] = {"max_steps": -1}
        self.window.editor.set_case(case)
        with self.assertRaisesRegex(ValueError, "max_steps"):
            self.window.editor.case()

    def test_result_json_validation_rejects_bad_versions_and_points(self):
        for value in (
            {"format": "hmbreach-results", "version": 2, "input": {}, "profiles": []},
            {"format": "hmbreach-results", "version": 1, "input": {},
             "profiles": [{"layer": 1, "points": [{"x": 1}]}]},
            {"format": "hmbreach-results", "version": 1, "input": {},
             "profiles": [{"layer": 1, "points": [
                 {"x": 10**400, "z": 0, "h": 1, "u": 1, "c": 1}]}]},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_results(value)

    @unittest.skipUnless(EXECUTABLE.is_file(), "Build HMBreach or set HMBREACH_EXECUTABLE")
    def test_edited_case_runs_and_results_round_trip(self):
        self.window.executable.setText(str(EXECUTABLE))
        self.window.editor.table.item(0, 1).setText("260")
        with tempfile.TemporaryDirectory() as directory:
            self.window.output_directory.setText(directory)
            loop = QEventLoop()
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            self.window.resultsFinished.connect(loop.quit)
            self.window.run_calculation()
            self.assertFalse(self.window.run_button.isEnabled())
            timeout.start(30000)
            loop.exec()
            timeout.stop()
            self.assertEqual(self.window.status.text(), "Calculation completed.")
            self.assertIsNotNone(self.window.results)
            results = self.window.results
            self.assertEqual(results["input"]["layers"][0]["d50_micrometre"], 260)
            self.assertGreater(len(results["profiles"][0]["points"]), 0)
            workbook = Path(directory) / "hmbres_turbulence_results.xlsx"
            self.assertEqual(results, results_from_workbook(workbook, results["input"]))
            self.assertEqual(self.window.results_view.workbook, workbook.resolve())
            self.assertTrue(self.window.results_view.geometry.is_file())
            direct = Path(directory) / "direct"
            direct.mkdir()
            direct_input = direct / "input.json"
            write_json(direct_input, results["input"])
            completed = subprocess.run(
                [str(EXECUTABLE), "--input", str(direct_input)],
                cwd=direct, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(results, results_from_workbook(direct / workbook.name, results["input"]))
            path = Path(directory) / "results.json"
            self.window.save_results(path)
            self.assertEqual(validate_results(read_json(path)), results)
            case_path = Path(directory) / "case.json"
            self.window.save_input(case_path)
            saved_case = case_path.read_bytes()
            self.window.load_input(case_path)
            self.window.run_calculation()
            timeout.start(30000)
            loop.exec()
            timeout.stop()
            self.assertEqual(self.window.status.text(), "Calculation completed.")
            self.assertEqual(self.window.results, results)
            self.assertNotIn("results", self.window.results["input"])
            self.assertEqual(case_path.read_bytes(), saved_case)
            self.assertFalse(any(Path(directory).glob("hmbreach-input-*")))

    @unittest.skipUnless(EXECUTABLE.is_file(), "Build HMBreach or set HMBREACH_EXECUTABLE")
    def test_preview_matches_solver_calculated_permeability(self):
        editor = self.window.editor
        editor.settings.physical_fields["g"].setText("8.5")
        editor.settings.physical_fields["temperature_c"].setText("20")
        editor.table.item(0, 5).setText("true")
        editor.table.item(0, 6).setText("100")
        self.window.executable.setText(str(EXECUTABLE))
        with tempfile.TemporaryDirectory() as directory:
            self.window.output_directory.setText(directory)

            def run():
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
                self.window.resultsFinished.disconnect(loop.quit)
                self.assertEqual(
                    self.window.status.text(), "Calculation completed.", self.window.output.toPlainText()
                )
                return deepcopy(self.window.results)

            calculated = run()
            for row in range(editor.table.rowCount()):
                editor.table.item(row, 4).setText(editor.table.item(row, 9).text())
            supplied = run()
            for first, second in zip(calculated["profiles"], supplied["profiles"]):
                for name in ("h", "u", "c"):
                    self.assertAlmostEqual(
                        first["points"][-1][name], second["points"][-1][name], delta=1e-8
                    )


if __name__ == "__main__":
    unittest.main()
