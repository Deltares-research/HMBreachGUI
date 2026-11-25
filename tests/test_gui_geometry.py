import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from GUI.app import CaseWindow
from GUI.case_io import load_case, read_json
from GUI.geometry_editor import _x_at_y, preview_profile
from GUI.prototype import ROOT

EXECUTABLE = Path(os.environ.get(
    "HMBREACH_EXECUTABLE", str(ROOT / "build" / "Release" / "HMBreach.exe")
)).resolve()


class GeometryEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = CaseWindow()

    def tearDown(self):
        self.window.editor.dirty = False
        self.window._results_dirty = False
        self.window.close()

    def test_preview_clips_and_interpolates_material_boundaries(self):
        layers = [
            {"thickness": 0.25, "angle": None},
            {"thickness": 0.3, "angle": None},
        ]
        points = [(-0.1, 0.1), (0.2, -0.2), (0.5, -0.55)]
        profile = preview_profile(points, layers)
        self.assertAlmostEqual(profile[0][0], 0.0)
        self.assertEqual(profile[-1], (0.5, -0.55))
        self.assertAlmostEqual(_x_at_y(profile, -0.25), 0.242857142857)
        schematic = preview_profile(None, layers)
        self.assertAlmostEqual(schematic[-1][0], 0.55 / math.tan(math.radians(75)))

    def test_click_drag_remove_and_save_coordinate_geometry(self):
        self.window.load_input(ROOT / "examples" / "coordinate_geometry_input.json")
        self.window.show()
        self.window.tabs.setCurrentWidget(self.window.editor.geometry)
        self.application.processEvents()
        editor = self.window.editor
        geometry = editor.geometry
        canvas = geometry.canvas
        original = load_case(ROOT / "examples" / "coordinate_geometry_input.json")
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen(0.55, -0.6).toPoint())
        self.assertEqual(geometry.table.rowCount(), 4)
        self.assertTrue(editor.dirty)
        position = canvas.to_screen(*canvas.points[-1]).toPoint()
        target = canvas.to_screen(0.58, -0.62).toPoint()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=position)
        QTest.mouseMove(canvas, target, delay=1)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
        self.assertAlmostEqual(float(geometry.table.item(3, 0).text()), 0.58, delta=0.005)
        geometry.remove_point()
        self.assertEqual(geometry.table.rowCount(), 3)
        geometry.table.item(1, 0).setText("0.3")
        with tempfile.TemporaryDirectory() as directory:
            target_file = Path(directory) / "edited.json"
            self.window.save_input(target_file)
            saved = read_json(target_file)
            self.assertEqual(saved["settings"]["slope_geometry"][1]["x_m"], 0.3)
            self.assertEqual(saved["layers"], original["layers"])
            self.window.load_input(target_file)
            self.assertEqual(self.window.editor.case(), saved)

    def test_geometry_ignores_angles_and_keeps_them_in_editor(self):
        editor = self.window.editor
        geometry = editor.geometry
        self.assertFalse(geometry.enabled.isChecked())
        geometry.enabled.setChecked(True)
        geometry.add_point(1, -1)
        self.assertTrue(all("initial_alpha_deg" not in layer for layer in editor.case()["layers"]))
        self.assertEqual(editor.table.item(0, 7).text(), "40.0")
        self.assertFalse(editor.table.item(0, 7).flags() & Qt.ItemFlag.ItemIsEditable)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.json"
            self.window.save_input(path)
            self.assertTrue(all("initial_alpha_deg" not in layer for layer in read_json(path)["layers"]))
            self.assertEqual(editor.table.item(0, 7).text(), "40.0")
            self.assertEqual(editor.table.item(1, 7).text(), "35.0")
        geometry.table.item(1, 0).setText("-1")
        with self.assertRaisesRegex(ValueError, "increasing X"):
            editor.case()
        self.assertIn("increasing X", geometry.message.text())
        self.assertEqual(geometry.table.item(1, 0).text(), "-1")
        geometry.enabled.setChecked(False)
        self.assertTrue(editor.table.item(0, 7).flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertEqual([layer["initial_alpha_deg"] for layer in editor.case()["layers"]], [40, 35])

    def test_new_slope_has_immovable_origin_and_preserves_legacy_cases(self):
        editor = self.window.editor
        geometry = editor.geometry
        geometry.enabled.setChecked(True)
        self.assertEqual(geometry.points(), [{"x_m": 0.0, "y_m": 0.0}])
        self.assertFalse(geometry.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable)
        self.window.show()
        self.window.tabs.setCurrentWidget(geometry)
        self.application.processEvents()
        canvas = geometry.canvas
        origin = canvas.to_screen(0, 0).toPoint()
        target = canvas.to_screen(0.1, -0.1).toPoint()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=origin)
        QTest.mouseMove(canvas, target, delay=1)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
        geometry.remove_point()
        self.assertEqual(geometry.points(), [{"x_m": 0.0, "y_m": 0.0}])
        self.assertIn("fixed", geometry.message.text())
        geometry.add_point(1, -1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new.json"
            self.window.save_input(path)
            self.window.load_input(path)
            self.assertFalse(geometry.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable)
        source = ROOT / "examples" / "coordinate_geometry_input.json"
        self.window.load_input(source)
        self.assertEqual(editor.case(), load_case(source))
        self.assertTrue(geometry.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsEditable)

    def test_mismatch_warning_and_extend_bottom_layer(self):
        self.window.load_input(ROOT / "examples" / "coordinate_geometry_input.json")
        editor = self.window.editor
        geometry = editor.geometry
        self.assertEqual(geometry.depth_warning.text(), "")
        self.assertFalse(geometry.match_button.isEnabled())
        geometry.table.item(2, 1).setText("-1")
        self.assertIn("total layer thickness (0.55 m)", geometry.depth_warning.text())
        self.assertIn("depth 1.0 m", geometry.depth_warning.text())
        self.assertTrue(geometry.match_button.isEnabled())
        with patch("GUI.app.QMessageBox.warning") as warning, \
             patch("GUI.app.QFileDialog.getSaveFileName", return_value=("", "")):
            self.window._save_input()
            warning.assert_called_once()
        geometry.match_button.click()
        self.assertEqual(float(editor.table.item(0, 0).text()), 0.25)
        self.assertEqual(float(editor.table.item(1, 0).text()), 0.75)
        self.assertEqual(geometry.depth_warning.text(), "")
        self.assertFalse(geometry.match_button.isEnabled())
        self.assertTrue(editor.dirty)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "adjusted.json"
            self.window.save_input(target)
            self.window.load_input(target)
            self.assertEqual(self.window.editor.case()["layers"][1]["thickness_m"], 0.75)

    def test_shallow_slope_warns_and_bottom_layer_can_be_reduced(self):
        self.window.load_input(ROOT / "examples" / "coordinate_geometry_input.json")
        editor = self.window.editor
        geometry = editor.geometry
        geometry.table.item(2, 1).setText("-0.4")
        self.assertIn("depth 0.4 m", geometry.depth_warning.text())
        self.assertTrue(geometry.match_button.isEnabled())
        with patch("GUI.app.QMessageBox.warning") as warning:
            self.window.run_calculation()
            warning.assert_called_once()
        self.assertIn("total layer thickness", editor.message.text())
        geometry.match_button.click()
        self.assertEqual(float(editor.table.item(0, 0).text()), 0.25)
        self.assertAlmostEqual(float(editor.table.item(1, 0).text()), 0.15)
        self.assertEqual(geometry.depth_warning.text(), "")
        self.assertAlmostEqual(sum(layer["thickness_m"] for layer in editor.case()["layers"]), 0.4)

    def test_cannot_reduce_bottom_layer_to_zero_or_negative(self):
        self.window.load_input(ROOT / "examples" / "coordinate_geometry_input.json")
        geometry = self.window.editor.geometry
        geometry.table.item(1, 1).setText("-0.1")
        for bottom in ("-0.25", "-0.2"):
            geometry.table.item(2, 1).setText(bottom)
            self.assertFalse(geometry.match_button.isEnabled())
            self.assertIn("below all upper layers", geometry.depth_warning.text())
            self.assertEqual(float(self.window.editor.table.item(1, 0).text()), 0.3)

    def test_rounding_that_makes_slope_too_shallow_is_reported(self):
        self.window.load_input(ROOT / "examples" / "coordinate_geometry_input.json")
        editor = self.window.editor
        editor.table.item(0, 0).setText("0.1")
        editor.table.item(1, 0).setText("0.2")
        editor.geometry.table.item(2, 1).setText("-0.3")
        self.assertIn("0.30000000000000004", editor.geometry.depth_warning.text())
        with self.assertRaisesRegex(ValueError, "total layer thickness"):
            editor.case()
        editor.geometry.match_button.click()
        self.assertEqual(editor.geometry.depth_warning.text(), "")
        self.assertLessEqual(sum(layer["thickness_m"] for layer in editor.case()["layers"]), 0.3)

    def test_layer_changes_update_preview_and_incomplete_geometry(self):
        self.window.load_input(ROOT / "examples" / "coordinate_geometry_input.json")
        editor = self.window.editor
        geometry = editor.geometry
        editor.table.item(0, 0).setText("0.2")
        editor.table.item(0, 1).setText("300")
        self.assertAlmostEqual(geometry.canvas.profile[-1][1], -0.5)
        self.assertIn("D50 300 um", geometry.properties.text())
        geometry.table.selectRow(2)
        geometry.remove_point()
        self.assertIn("total layer thickness", geometry.message.text())
        self.assertEqual(geometry.canvas.profile, [])
        self.assertEqual(geometry.table.rowCount(), 2)
        with self.assertRaisesRegex(ValueError, "total layer thickness"):
            editor.case()

    def test_geometry_rejects_overflowing_layer_depth(self):
        self.window.load_input(ROOT / "examples" / "coordinate_geometry_input.json")
        editor = self.window.editor
        editor.table.item(0, 0).setText("1e308")
        editor.table.item(1, 0).setText("1e308")
        with self.assertRaisesRegex(ValueError, "Total layer thickness must be finite"):
            editor.case()

    @unittest.skipUnless(EXECUTABLE.is_file(), "Build HMBreach or set HMBREACH_EXECUTABLE")
    def test_geometry_runs_with_existing_angles_ignored(self):
        geometry = self.window.editor.geometry
        geometry.enabled.setChecked(True)
        geometry.add_point(0.8, -0.55)
        self.window.executable.setText(str(EXECUTABLE))
        with tempfile.TemporaryDirectory() as directory:
            self.window.output_directory.setText(directory)
            loop = QEventLoop()
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            self.window.resultsFinished.connect(loop.quit)
            self.window.run_calculation()
            timeout.start(30000)
            loop.exec()
            timeout.stop()
            self.assertEqual(
                self.window.status.text(), "Calculation completed.", self.window.output.toPlainText()
            )
            self.assertEqual(
                self.window.results["input"]["settings"]["slope_geometry"][1]["x_m"], 0.8
            )
            self.assertTrue(all(
                "initial_alpha_deg" not in layer for layer in self.window.results["input"]["layers"]
            ))
            self.assertTrue((Path(directory) / "hmbres_turbulence_results_initial_geometry.svg").is_file())


if __name__ == "__main__":
    unittest.main()
