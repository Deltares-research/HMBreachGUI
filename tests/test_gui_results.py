import tempfile
import unittest
from pathlib import Path

from GUI.app import CaseWindow
from GUI.case_io import read_json


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.window = CaseWindow()
        self.window.withdraw()
        self.results = {
            "format": "hmbreach-results",
            "version": 1,
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
        self.window.update_idletasks()
        self.window.destroy()

    def test_layer_selection_and_optional_columns(self):
        self.window.set_results(self.results)
        view = self.window.results_view
        rows = view.table.get_children()
        columns = view.table["columns"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(view.layer.get(), "2")
        self.assertEqual(view.table.set(rows[0], "x"), "1")
        self.assertEqual(view.table.set(rows[0], "extra_metric"), "")
        self.assertEqual(view.table.set(rows[1], "extra_metric"), "7")
        self.assertIn("Last recorded point: x=2", view.summary.cget("text"))
        self.assertIn("extra_metric", columns)

        view.layer.current(1)
        view._select_layer()
        self.assertEqual(len(view.table.get_children()), 1)
        self.assertNotIn("extra_metric", view.table["columns"])
        self.assertIn("Layer 4", view.summary.cget("text"))

    def test_output_buttons_only_enable_for_associated_files(self):
        view = self.window.results_view
        view.set_files(None, None)
        self.assertEqual(str(view.open_workbook["state"]), "disabled")
        self.assertEqual(str(view.open_geometry["state"]), "disabled")

    def test_saved_case_keeps_result_input_snapshot_separate(self):
        original_velocity = self.results["input"]["initial_conditions"]["vz_mm_s"]
        self.window.set_results(self.results)
        self.window.editor.initial_fields["vz_mm_s"].set("2")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.json"
            self.window.save_input(path)
            saved = read_json(path)
            self.assertEqual(saved["initial_conditions"]["vz_mm_s"], 2)
            self.assertEqual(
                saved["results"]["input"]["initial_conditions"]["vz_mm_s"], original_velocity
            )
            self.window.load_input(path)
            self.assertEqual(self.window.results, self.results)
            self.assertNotIn("results", self.window.editor.case())


if __name__ == "__main__":
    unittest.main()
