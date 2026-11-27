import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from GUI.app import CaseWindow
from GUI.case_io import load_case, read_json
from GUI.geometry_editor import _x_at_y, preview_profile
from GUI.prototype import ROOT


class GeometryEditorTests(unittest.TestCase):
    def setUp(self):
        self.window = CaseWindow()
        self.window.withdraw()

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


if __name__ == "__main__":
    unittest.main()
