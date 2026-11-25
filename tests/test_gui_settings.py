import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from GUI.app import CaseWindow
from GUI.case_io import load_case, read_json
from GUI.prototype import ROOT


EXECUTABLE = Path(os.environ.get(
    "HMBREACH_EXECUTABLE", str(ROOT / "build" / "Release" / "HMBreach.exe")
)).resolve()


def select(combo, value):
    index = combo.findData(value)
    if index < 0:
        raise AssertionError(f"Missing selection: {value!r}")
    combo.setCurrentIndex(index)


class SettingsEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = CaseWindow()

    def tearDown(self):
        self.window.editor.dirty = False
        self.window._results_dirty = False
        self.window.close()

    def test_round_trip_explicit_settings_and_width_geometry(self):
        original = load_case(ROOT / "examples" / "turbulence_input.json")
        original["initial_conditions"]["initial_width_m"] = 1.0
        original["settings"].update({
            "width_model": "geometry",
            "width_geometry": [{"s_m": 1.0, "width_m": 1.5}],
            "physical_constants": {"g": 9.7, "erosion_variant": "variant_1", "phi_deg": 31},
            "model_options": {"max_steps": 100000, "adaptive_step_sizing": True},
        })
        self.window.editor.set_case(original)
        self.assertEqual(self.window.editor.case(), original)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.json"
            self.window.save_input(path)
            self.window.load_input(path)
            self.assertEqual(read_json(path), original)
            self.assertEqual(self.window.editor.case(), original)

    def test_absent_settings_and_explicit_alias_defaults_are_preserved(self):
        case = load_case(ROOT / "examples" / "turbulence_input.json")
        case.pop("settings")
        self.window.editor.set_case(case)
        self.assertEqual(self.window.editor.case(), case)
        case["settings"] = {
            "width_model": "unit_width",
            "model_options": {"adaptive_step_sizing": False},
            "physical_constants": {"erosion_variant": "variant_1"},
        }
        self.window.editor.set_case(case)
        self.assertEqual(self.window.editor.case(), case)
        self.assertEqual(self.window.editor.settings.physical_fields["phi_deg"].placeholderText(),
                         "Default: 32")
        self.assertEqual(self.window.editor.settings.physical_fields["erosion_b"].placeholderText(),
                         "Default: 0.06")

    def test_width_settings_and_mode_are_used_and_validated(self):
        editor = self.window.editor
        settings = editor.settings
        select(settings.mode, "breach")
        select(settings.width_model, "b_fit")
        select(settings.fit_type, "poly2")
        settings.fit_iterations.setText("120")
        editor.initial_fields["initial_width_m"].setText("1")
        editor.table.item(0, 8).setText("1.2")
        editor.table.item(1, 8).setText("1.4")
        case = editor.case()
        self.assertEqual(case["settings"]["mode"], "breach")
        self.assertEqual(case["settings"]["width_fit_type"], "poly2")
        self.assertEqual(case["settings"]["width_fit_max_iterations"], 120)
        self.assertEqual([layer["flow_width_m"] for layer in case["layers"]], [1.2, 1.4])
        editor.add_layer()
        self.assertNotIn("initial_alpha_deg", editor.case()["layers"][-1])

        select(settings.width_model, "b_constant")
        editor.initial_fields["initial_width_m"].clear()
        for row in range(editor.table.rowCount()):
            editor.table.item(row, 8).setText("")
        with self.assertRaisesRegex(ValueError, "Width-fit settings"):
            editor.case()
        settings.fit_type.setCurrentIndex(0)
        settings.fit_iterations.clear()
        self.assertEqual(editor.case()["settings"]["width_model"], "b_constant")

    def test_width_points_and_invalid_values_preserve_edits(self):
        editor = self.window.editor
        settings = editor.settings
        select(settings.width_model, "geometry")
        editor.initial_fields["initial_width_m"].setText("1")
        settings.add_width_point()
        settings.width_table.item(0, 0).setText("1")
        settings.width_table.item(0, 1).setText("2")
        self.assertEqual(editor.case()["settings"]["width_geometry"], [{"s_m": 1.0, "width_m": 2.0}])
        settings.physical_fields["g"].setText("bad")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            with self.assertRaisesRegex(ValueError, "Gravity"):
                self.window.save_input(path)
            self.assertFalse(path.exists())
        self.assertEqual(settings.physical_fields["g"].text(), "bad")
        self.assertIn("Gravity", settings.message.text())
        settings.physical_fields["g"].clear()
        settings.option_fields["max_steps"].setText("1.5")
        with self.assertRaisesRegex(ValueError, "integer"):
            editor.case()

    def test_reset_overrides_and_apply_gradient(self):
        editor = self.window.editor
        settings = editor.settings
        settings.physical_fields["g"].setText("8")
        settings.option_fields["max_steps"].setText("1000")
        select(settings.erosion_variant, "variant_1")
        with patch("GUI.settings_editor.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.No):
            settings._confirm_reset()
        self.assertEqual(settings.physical_fields["g"].text(), "8")
        with patch("GUI.settings_editor.QMessageBox.question",
                   return_value=QMessageBox.StandardButton.Yes):
            settings._confirm_reset()
        self.assertNotIn("physical_constants", editor.case()["settings"])
        self.assertNotIn("model_options", editor.case()["settings"])
        self.assertEqual(editor.case()["settings"]["mode"], "turbulence")
        editor.gradient_all.setText("0.12")
        editor._apply_gradient()
        self.assertEqual([layer["external_gradient"] for layer in editor.case()["layers"]], [0.12, 0.12])
        editor.gradient_all.setText("not a number")
        editor._apply_gradient()
        self.assertIn("must be a number", editor.message.text())
        self.assertEqual([layer["external_gradient"] for layer in editor.case()["layers"]], [0.12, 0.12])

    @unittest.skipUnless(EXECUTABLE.is_file(), "Build HMBreach or set HMBREACH_EXECUTABLE")
    def test_changed_constant_reaches_solver_and_changes_results(self):
        self.window.executable.setText(str(EXECUTABLE))
        with tempfile.TemporaryDirectory() as directory:
            self.window.output_directory.setText(directory)

            def run():
                loop = QEventLoop()
                timeout = QTimer()
                timeout.setSingleShot(True)
                timeout.timeout.connect(loop.quit)
                self.window.resultsFinished.connect(loop.quit)
                with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                    self.window.run_calculation()
                timeout.start(30000)
                loop.exec()
                timeout.stop()
                self.window.resultsFinished.disconnect(loop.quit)
                self.assertEqual(
                    self.window.status.text(), "Calculation completed.", self.window.output.toPlainText()
                )
                return deepcopy(self.window.results)

            baseline = run()
            self.window.editor.settings.physical_fields["g"].setText("8")
            changed = run()
            self.assertEqual(changed["input"]["settings"]["physical_constants"]["g"], 8)
            self.assertNotEqual(baseline["profiles"], changed["profiles"])


if __name__ == "__main__":
    unittest.main()
