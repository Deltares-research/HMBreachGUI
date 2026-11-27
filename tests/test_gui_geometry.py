import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from GUI.app import CaseWindow
from GUI.case_io import load_case, read_json
from GUI.geometry_editor import _x_at_y, preview_profile
from GUI.prototype import ROOT


class GeometryEditorTests(unittest.TestCase):
    def setUp(self):
        self.window = CaseWindow()
        self.window.withdraw()
        self.window.load_input(ROOT / "examples" / "turbulence_input.json")

    def tearDown(self):
        self.window.update_idletasks()
        self.window.destroy()

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

    def test_coordinate_geometry_edit_round_trip(self):
        source = ROOT / "examples" / "coordinate_geometry_input.json"
        self.window.load_input(source)
        geometry = self.window.editor.geometry
        geometry.add_point(0.8, -1.0)
        case = self.window.editor.case()
        self.assertEqual(case["settings"]["slope_geometry"][-1], {"x_m": 0.8, "y_m": -1.0})

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "edited.json"
            self.window.save_input(target)
            saved = read_json(target)
            self.assertEqual(saved["layers"], load_case(source)["layers"])
            self.window.load_input(target)
            self.assertEqual(self.window.editor.case(), saved)

    def test_invalid_geometry_remains_visible_and_is_rejected(self):
        self.window.load_input(ROOT / "examples" / "coordinate_geometry_input.json")
        geometry = self.window.editor.geometry
        rows = geometry.table.get_children()
        geometry.table.item(rows[1], values=("-0.2", "-0.2"))
        with self.assertRaisesRegex(ValueError, "increasing X"):
            self.window.editor.case()
        self.assertEqual(geometry.table.item(rows[1], "values"), ("-0.2", "-0.2"))

    def test_drawing_rejects_negative_x_and_positive_y(self):
        canvas = self.window.editor.geometry.canvas
        canvas.widget.configure(width=500, height=300)
        self.window.update_idletasks()
        canvas.editable = True
        canvas.points = []
        canvas.bounds = (-1, 1, -1, 1)
        added = []
        canvas.on_add = lambda x, y: added.append((x, y))
        for point in ((-0.5, -0.5), (0.5, 0.5), (0.5, -0.5)):
            x, y = canvas.to_screen(*point)
            canvas._mouse_down(SimpleNamespace(x=x, y=y))
        self.assertEqual(len(added), 1)
        self.assertAlmostEqual(added[0][0], 0.5)
        self.assertAlmostEqual(added[0][1], -0.5)

    def test_fit_always_includes_origin_for_existing_geometry(self):
        canvas = self.window.editor.geometry.canvas
        canvas.points = [(2, -2), (3, -3)]
        canvas.profile = []
        canvas.fit()
        left, right, bottom, top = canvas.bounds
        self.assertLess(left, 0)
        self.assertGreater(right, 0)
        self.assertLess(bottom, 0)
        self.assertGreater(top, 0)

    def test_new_coordinate_geometry_displays_single_origin(self):
        geometry = self.window.editor.geometry
        geometry.enabled_var.set(True)
        geometry._toggle_geometry()
        self.assertEqual(geometry.points(), [{"x_m": 0.0, "y_m": 0.0}])
        self.assertEqual(geometry.canvas.points, [(0.0, 0.0)])

    def test_single_click_edits_coordinates_but_not_locked_origin(self):
        geometry = self.window.editor.geometry
        geometry.enabled_var.set(True)
        geometry._toggle_geometry()
        geometry.add_point(0.5, -0.55)
        self.window.deiconify()
        self.window.tabs.select(geometry)
        self.window.update()
        table = geometry.table

        def click(row, column):
            x, y, width, height = table.bbox(row, column)
            table.event_generate("<Button-1>", x=x + width // 2, y=y + height // 2)
            self.window.update()

        origin, point = table.get_children()
        click(origin, "#1")
        self.assertIsNone(geometry._cell_editor.entry)
        click(point, "#1")
        entry = geometry._cell_editor.entry
        self.assertTrue(entry.selection_present())
        entry.delete(0, "end")
        entry.insert(0, "0.75")
        case = self.window.editor.case()
        self.assertEqual(case["settings"]["slope_geometry"][1]["x_m"], 0.75)
        self.assertEqual(table.selection(), (point,))

    def test_existing_slope_remains_visible_while_drawing(self):
        geometry = self.window.editor.geometry
        original = list(geometry.canvas.profile)
        geometry.enabled_var.set(True)
        geometry._toggle_geometry()
        self.assertEqual(geometry.canvas.reference_profile, original)
        self.assertEqual(geometry.canvas.points, [(0.0, 0.0)])
        self.assertTrue(geometry.canvas.widget.find_withtag("reference-slope"))
        geometry.add_point(0.1, -0.1)
        self.assertEqual(geometry.canvas.reference_profile, original)

    def test_loaded_coordinate_slope_is_kept_as_reference(self):
        self.window.load_input(ROOT / "examples" / "coordinate_geometry_input.json")
        geometry = self.window.editor.geometry
        original = list(geometry.canvas.profile)
        geometry.move_point(1, 0.3, -0.2)
        self.assertEqual(geometry.canvas.reference_profile, original)
        self.assertTrue(geometry.canvas.widget.find_withtag("reference-slope"))

    def test_adjusting_input_layers_fits_view(self):
        editor = self.window.editor
        with patch.object(editor.geometry.canvas, "fit") as fit:
            row = editor.table.get_children()[0]
            values = list(editor.table.item(row, "values"))
            values[0] = "2"
            editor.table.item(row, values=values)
            editor._layer_changed()
        fit.assert_called()
        self.assertLess(editor.geometry.canvas.profile[-1][1], -2)

    def test_update_layers_splits_at_bends_and_material_boundaries(self):
        editor = self.window.editor
        row = editor.table.get_children()[0]
        values = list(editor.table.item(row, "values"))
        values[3:7] = ["0.12", "3", "true", "120"]
        editor.table.item(row, values=values)
        editor._layer_changed()
        geometry = editor.geometry
        geometry.enabled_var.set(True)
        geometry._toggle_geometry()
        for point in ((0.2, -0.1), (0.4, -0.4), (0.8, -0.8)):
            geometry.add_point(*point)
        geometry.update_layers_button.invoke()
        self.assertIn("above 45 degrees", geometry.message.cget("text"))
        case = editor.case()
        layers = case["layers"]
        self.assertEqual(len(layers), 4)
        for layer, thickness, d50 in zip(
            layers, (0.1, 0.15, 0.15, 0.4), (250, 250, 200, 200)
        ):
            self.assertAlmostEqual(layer["thickness_m"], thickness)
            self.assertEqual(layer["d50_micrometre"], d50)
            self.assertNotIn("initial_alpha_deg", layer)
        for layer in layers[:2]:
            self.assertEqual(layer["external_gradient"], 0.12)
            self.assertEqual(layer["permeability_mm_s"], 3)
            self.assertTrue(layer["user_d15"])
            self.assertEqual(layer["d15_micrometre"], 120)
        displayed = [editor._row_values(i) for i in range(4)]
        for row, angle in zip(displayed, (26.565051177, 56.309932474, 56.309932474, 45)):
            self.assertAlmostEqual(float(row[7]), angle, places=6)
        self.assertIn("slope_geometry", case["settings"])
        polygons = geometry.canvas.widget.find_withtag("material-layer")
        fills = [geometry.canvas.widget.itemcget(item, "fill") for item in polygons]
        self.assertEqual(fills[0], fills[1])
        self.assertEqual(fills[2], fills[3])

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "converted.json"
            self.window.save_input(target)
            self.window.load_input(target)
            rows = [editor._row_values(i) for i in range(4)]
            for row, angle in zip(rows, (26.565051177, 56.309932474, 56.309932474, 45)):
                self.assertAlmostEqual(float(row[7]), angle, places=6)

    def test_repeated_update_removes_obsolete_slope_breaks(self):
        editor = self.window.editor
        geometry = editor.geometry
        geometry.enabled_var.set(True)
        geometry._toggle_geometry()
        for point in ((0.2, -0.1), (0.4, -0.4), (0.8, -0.8)):
            geometry.add_point(*point)
        geometry.update_layers_button.invoke()
        geometry.move_point(1, 0.2, -0.18)
        self.assertTrue(all(not editor._row_values(i)[7] for i in range(4)))
        geometry.update_layers_button.invoke()
        case = editor.case()
        self.assertEqual(len(case["layers"]), 4)
        for layer, thickness in zip(case["layers"], (0.18, 0.07, 0.15, 0.4)):
            self.assertAlmostEqual(layer["thickness_m"], thickness)

    def test_update_layers_truncates_to_shallow_slope_and_rejects_invalid_geometry(self):
        editor = self.window.editor
        geometry = editor.geometry
        initial_fill = geometry.canvas._grain_colors[250]
        geometry.enabled_var.set(True)
        geometry._toggle_geometry()
        before = [editor._row_values(i) for i in range(2)]
        geometry.update_layers_button.invoke()
        self.assertEqual([editor._row_values(i) for i in range(2)], before)
        self.assertIn("at least two points", geometry.message.cget("text"))
        geometry.add_point(0.2, -0.2)
        geometry.update_layers_button.invoke()
        case = editor.case()
        self.assertEqual(len(case["layers"]), 1)
        self.assertAlmostEqual(case["layers"][0]["thickness_m"], 0.2)
        self.assertEqual(case["layers"][0]["d50_micrometre"], 250)
        polygon = geometry.canvas.widget.find_withtag("material-layer")[0]
        self.assertEqual(geometry.canvas.widget.itemcget(polygon, "fill"), initial_fill)


if __name__ == "__main__":
    unittest.main()
