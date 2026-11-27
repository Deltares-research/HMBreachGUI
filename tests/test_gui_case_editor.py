import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from GUI.app import CaseWindow
from GUI.case_io import load_case, read_json, validate_results
from GUI.prototype import ROOT


EXECUTABLE = Path(os.environ.get(
    "HMBREACH_EXECUTABLE", str(ROOT.parent / "Release" / "HMBreach.exe")
)).resolve()


class CaseEditorTests(unittest.TestCase):
    def setUp(self):
        self.window = CaseWindow()
        self.window.withdraw()

    def tearDown(self):
        self.window.update_idletasks()
        self.window.destroy()

    def test_case_editor_is_contained_in_input_tab(self):
        self.assertIs(self.window.editor.master, self.window.input_page)
        self.assertIn(self.window.editor, self.window.input_page.winfo_children())

    def test_layer_display_order_and_model_choices(self):
        editor = self.window.editor
        columns = list(editor.table.cget("displaycolumns"))
        self.assertEqual(columns[1:6], [
            "d50_micrometre", "user_d15", "d15_micrometre",
            "porosity_percent", "effective_permeability",
        ])
        self.assertIs(editor.settings.mode.master.master, editor)
        self.assertIs(editor.settings.width_model.master, editor.settings.mode.master)
        self.assertIs(editor.settings.erosion_variant.master, editor.settings.mode.master)

    def test_editing_reordered_layer_column_updates_correct_field(self):
        editor = self.window.editor
        self.window.deiconify()
        self.window.update()
        row = editor.table.get_children()[0]
        x, y, width, height = editor.table.bbox(row, "#3")
        editor._begin_cell_edit(SimpleNamespace(x=x + width // 2, y=y + height // 2))
        entry = editor.table.winfo_children()[-1]
        entry.delete(0, "end")
        entry.insert(0, "true")
        entry.focus_force()
        self.window.update()
        entry.event_generate("<Return>")
        self.window.update()
        self.assertEqual(editor.table.item(row, "values")[5], "true")

    def test_working_directory_is_remembered_and_help_loads_selected_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            preferences = path / "settings" / "preferences.json"
            document = path / "scientific.md"
            document.write_text("# Scientific model\nEquations", encoding="utf-8")
            with patch("GUI.app._preferences_path", return_value=preferences):
                self.window.output_directory.set(directory)
                self.window._save_working_directory()
                self.window.output_directory.set("")
                self.window._restore_working_directory()
                self.assertEqual(self.window.output_directory.get(), str(path.resolve()))
            with patch("GUI.app.filedialog.askopenfilename", return_value=str(document)):
                self.window._open_scientific_readme()
            self.assertEqual(self.window.help_text.get("1.0", "end-1c"), "# Scientific model\nEquations")
            self.assertIn(str(document), self.window.help_status.cget("text"))

    def test_round_trip_preserves_geometry_and_other_settings(self):
        source = ROOT / "examples" / "coordinate_geometry_input.json"
        original = load_case(source)
        self.window.load_input(source)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "case.json"
            self.window.save_input(target)
            self.assertEqual(read_json(target), original)

    def test_layer_actions_and_validation_preserve_edits(self):
        editor = self.window.editor
        first = editor.table.get_children()[0]
        values = list(editor.table.item(first, "values"))
        values[1] = "321"
        editor.table.item(first, values=values)
        editor.table.selection_set(first)
        editor.copy_layer()
        self.assertEqual(editor.case()["layers"][-1]["d50_micrometre"], 321)
        editor.remove_layer()
        editor.add_layer()
        self.assertEqual(len(editor.case()["layers"]), 3)

        last = editor.table.get_children()[-1]
        values = list(editor.table.item(last, "values"))
        values[0] = "-1"
        editor.table.item(last, values=values)
        with self.assertRaisesRegex(ValueError, "Layer 3 thickness"):
            editor.case()
        self.assertEqual(editor.table.item(last, "values")[0], "-1")

    def test_initial_concentration_and_embedded_results_validation(self):
        self.window.editor.initial_fields["initial_concentration_percent"].set("60")
        with self.assertRaisesRegex(ValueError, "Initial concentration"):
            self.window.editor.case()

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
    def test_solver_run_loads_results_without_blocking_tk(self):
        self.window.executable.set(str(EXECUTABLE))
        with tempfile.TemporaryDirectory() as directory:
            self.window.output_directory.set(directory)

            def wait_for_results():
                if self.window.process is None and self.window._result_future is None:
                    self.window.quit()
                    return
                self.window.after(25, wait_for_results)

            self.window.run_calculation()
            self.window.after(25, wait_for_results)
            self.window.mainloop()

            self.assertEqual(self.window.status.get(), "Calculation completed.")
            self.assertIsNotNone(self.window.results)
            self.assertGreater(len(self.window.results["profiles"][0]["points"]), 0)
            self.assertTrue(self.window.results_view.workbook.is_file())


if __name__ == "__main__":
    unittest.main()
