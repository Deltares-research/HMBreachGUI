import os
import tempfile
import unittest
from pathlib import Path

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
