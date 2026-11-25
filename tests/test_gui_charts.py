import tempfile
import unittest
from pathlib import Path

from GUI.app import CaseWindow
from GUI.axis_settings import axis_parameters, axis_ticks
from GUI.charts_view import _segments


class ChartsTests(unittest.TestCase):
    def setUp(self):
        self.window = CaseWindow()
        self.window.withdraw()

    def tearDown(self):
        self.window.update_idletasks()
        self.window.destroy()

    def result_document(self, points, input_case=None):
        return {
            "format": "hmbreach-results",
            "version": 1,
            "input": input_case or self.window.editor.case(),
            "profiles": [{"layer": 1, "points": points}],
        }

    def test_segments_break_at_missing_data_and_connect_adjacent_layers(self):
        profile = {"points": [
            {"x": 0, "z": 0},
            {"x": 1, "z": None},
            {"x": 2, "z": -2},
        ]}
        self.assertEqual(list(_segments(profile, "x", "z")), [[(0, 0)], [(2, -2)]])
        next_profile = {"points": [{"x": 2, "z": -2}, {"x": 3, "z": -3}]}
        self.assertEqual(
            list(_segments(next_profile, "x", "z", previous_point={"x": 1, "z": -1})),
            [[(1, -1), (2, -2), (3, -3)]],
        )

    def test_dual_axes_and_previous_result_overlay(self):
        points = [
            {"x": 0, "z": 0, "h": 0.2, "u": 1, "c": 0.1},
            {"x": 1, "z": -0.5, "h": 0.3, "u": 2, "c": 0.2},
        ]
        chart = self.window.charts_view
        chart.set_results(self.result_document(points))
        self.assertEqual(chart.left_axis.get_ylabel(), "z (m)")
        self.assertEqual(chart.right_axis.get_ylabel(), "Velocity u (m/s)")
        self.assertEqual(len(chart.left_axis.lines), 1)
        self.assertEqual(len(chart.right_axis.lines), 1)

        previous = self.result_document([
            {"x": 0, "z": 0.1, "h": 0.2, "u": 0.5, "c": 0.1},
            {"x": 1, "z": -0.4, "h": 0.3, "u": 1.5, "c": 0.2},
        ])
        chart.set_results(self.result_document(points), previous)
        chart.show_previous_var.set(True)
        chart._redraw()
        self.assertEqual(len(chart.left_axis.lines), 2)
        self.assertEqual(len(chart.right_axis.lines), 2)
        self.assertEqual(chart.left_axis.lines[-1].get_linestyle(), "--")

    def test_initial_slope_overlay_uses_result_snapshot(self):
        chart = self.window.charts_view
        chart.set_results(self.result_document([
            {"x": 0, "z": 0, "h": 0.2, "u": 1, "c": 0.1},
            {"x": 1, "z": -0.5, "h": 0.3, "u": 2, "c": 0.2},
        ]))
        chart.show_initial_var.set(True)
        chart._redraw()
        self.assertTrue(any("Initial slope" in line.get_label() for line in chart.left_axis.lines))
        self.assertIn("input snapshot", chart.status.cget("text"))

    def test_flow_top_view_mirrors_recorded_width(self):
        case = self.window.editor.case()
        case.setdefault("settings", {})["width_model"] = "b_fit"
        chart = self.window.charts_view
        chart.set_results(self.result_document([
            {"x": 0, "z": 0, "h": 0.2, "u": 1, "c": 0.1, "width_m": 2},
            {"x": 1, "z": -0.5, "h": 0.3, "u": 2, "c": 0.2, "width_m": 4},
        ], case))
        chart.plot_type.set("Flow top view")
        chart._redraw()
        self.assertEqual(len(chart.left_axis.lines), 2)
        self.assertEqual(list(chart.left_axis.lines[0].get_ydata()), [1, 2])
        self.assertEqual(list(chart.left_axis.lines[1].get_ydata()), [-1, -2])
        self.assertIn("recorded full width", chart.status.cget("text"))

    def test_axis_ticks_and_image_export(self):
        low, high, interval, label_format = axis_parameters(
            [0, 10], (None, None, None, None)
        )
        self.assertLess(low, 0)
        self.assertGreater(high, 10)
        self.assertTrue(any(value == 0 for _label, value in axis_ticks(
            low, high, interval, label_format
        )))

        chart = self.window.charts_view
        chart.set_results(self.result_document([
            {"x": 0, "z": 0, "h": 0.2, "u": 1, "c": 0.1},
            {"x": 1, "z": -0.5, "h": 0.3, "u": 2, "c": 0.2},
        ]))
        self.assertTrue(chart.lines)
        chart._axis_settings["profile"]["horizontal"] = (0, 2, 0.5, 1)
        chart._redraw()
        self.assertEqual(chart.left_axis.get_xlim(), (0, 2))
        self.assertIn("0.0", [label.get_text() for label in chart.left_axis.get_xticklabels()])
        chart.image_width.set(640)
        chart.image_height.set(480)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "chart.png"
            chart.save_image(target)
            self.assertTrue(target.is_file())
            self.assertEqual(target.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            jpeg = Path(directory) / "chart.jpg"
            chart.save_image(jpeg)
            self.assertEqual(jpeg.read_bytes()[:2], b"\xff\xd8")


if __name__ == "__main__":
    unittest.main()
