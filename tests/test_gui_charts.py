import os
import math
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QColorDialog, QDialog, QFileDialog, QMessageBox

from GUI.app import CaseWindow
from GUI.axis_settings import AxisSettingsDialog, axis_parameters, axis_ticks
from GUI.case_io import load_case, write_json
from GUI.prototype import ROOT


EXECUTABLE = Path(os.environ.get(
    "HMBREACH_EXECUTABLE", str(ROOT / "build" / "Release" / "HMBreach.exe")
)).resolve()


def results():
    return {
        "format": "hmbreach-results", "version": 1, "input": {},
        "profiles": [
            {"layer": 1, "points": [
                {"x": 0, "z": 0, "h": 1, "u": 2, "c": 0.1, "width_m": 2, "custom": 9},
                {"x": 1, "z": -1, "h": 2, "u": 4, "c": 0.2, "width_m": 4},
                {"x": 2, "z": -2, "h": 3, "u": 6, "c": 0.3, "width_m": 6, "custom": 7},
            ]},
            {"layer": 2, "points": [
                {"x": 2, "z": -2, "h": 3, "u": 6, "c": 0.3, "width_m": 6},
                {"x": 3, "z": -3, "h": 4, "u": 8, "c": 0.4, "width_m": 8},
            ]},
        ],
    }


def select(combo, value):
    index = combo.findData(value)
    if index < 0:
        raise AssertionError(f"Missing selection: {value!r}")
    combo.setCurrentIndex(index)


def xy(series):
    x, y = series.getData()
    return list(zip(x, y))


def rendered_ticks(view, axis):
    axis = {"horizontal": view.x_axis, "left": view.left_axis, "right": view.right_axis}[axis]
    axis.picture = None
    with patch.object(axis, "drawPicture", wraps=axis.drawPicture) as draw:
        view.chart_view.grab()
    if not draw.called:
        return []
    return [text for _, _, text in draw.call_args.args[3]]


def tick_values(axis):
    return [value for value, _ in axis._tickLevels[0]]


class ChartsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = CaseWindow()
        self.view = self.window.charts_view
        self.window.resize(1200, 800)
        self.window.show()
        self.window.tabs.setCurrentWidget(self.view)
        self.application.processEvents()

    def tearDown(self):
        self.window.editor.dirty = False
        self.window._results_dirty = False
        self.window.close()
        self.application.processEvents()

    def test_dual_axes_data_legends_and_missing_points(self):
        self.window.set_results(results())
        view = self.view
        self.assertEqual(view.x_variable.currentData(), "x")
        self.assertEqual(view.left_variable.currentData(), "z")
        self.assertEqual(view.right_variable.currentData(), "u")
        self.assertEqual(view.x_axis.labelText, "x (m)")
        self.assertEqual(view.left_axis.labelText, "z (m)")
        self.assertEqual(view.right_axis.labelText, "Velocity u (m/s)")
        series = view.series
        self.assertEqual(len(series), 4)
        self.assertEqual(xy(series[0]), [(0, 0), (1, -1), (2, -2)])
        self.assertIs(series[0].getViewBox(), view.left_view)
        self.assertIs(series[1].getViewBox(), view.right_view)
        self.assertEqual(view.left_view.viewRange()[0], view.right_view.viewRange()[0])
        self.assertIn("Current L1 z (m)", series[0].name())
        self.assertIsNotNone(view.legend.getLabel(series[0]))
        select(view.left_variable, None)
        self.assertFalse(view.left_axis.isVisible())
        self.assertTrue(view.right_axis.isVisible())
        self.assertEqual(len(view.series), 2)
        select(view.left_variable, "custom")
        select(view.right_variable, None)
        series = view.series
        self.assertEqual([xy(s) for s in series], [[(0, 9)], [(2, 7)]])
        self.assertEqual(view.left_axis.labelText, "custom (unit not recorded)")
        self.assertFalse(view.right_axis.isVisible())
        self.assertIsNone(view.legend.getLabel(series[1]))
        select(view.left_variable, None)
        self.assertFalse(view.series)
        self.assertIn("No recorded points", view.status.text())

    def test_automatic_ticks_show_zero_and_use_round_intervals(self):
        data = results()
        for profile in data["profiles"]:
            for point in profile["points"]:
                point["x"] /= 5
                point["z"] /= 5
        self.window.set_results(data)
        self.application.processEvents()
        self.assertAlmostEqual(tick_values(self.view.x_axis)[1] - tick_values(self.view.x_axis)[0], 0.2)
        self.assertIn(0, tick_values(self.view.x_axis))
        self.assertIn(0, tick_values(self.view.left_axis))
        self.assertIn("0.0", rendered_ticks(self.view, "horizontal"))
        self.assertIn("0.2", rendered_ticks(self.view, "horizontal"))
        self.assertIn("0.4", rendered_ticks(self.view, "horizontal"))
        self.assertIn("0.0", rendered_ticks(self.view, "left"))
        select(self.view.plot_type, "top")
        self.application.processEvents()
        self.assertTrue(any(float(tick) == 0 for tick in rendered_ticks(self.view, "horizontal")))
        self.assertTrue(any(float(tick) == 0 for tick in rendered_ticks(self.view, "left")))

    def test_right_axis_stays_aligned_when_resizing_and_switching_views(self):
        self.window.set_results(results())
        self.window.resize(1000, 900)
        self.application.processEvents()
        self.assertEqual(self.view.right_view.geometry(), self.view.left_view.sceneBoundingRect())
        self.assertEqual(self.view.left_view.viewRange()[0], self.view.right_view.viewRange()[0])
        select(self.view.plot_type, "top")
        select(self.view.plot_type, "profile")
        self.application.processEvents()
        self.assertEqual(self.view.right_view.geometry(), self.view.left_view.sceneBoundingRect())
        self.assertEqual(self.view.left_view.viewRange()[0], self.view.right_view.viewRange()[0])
        self.assertIs(self.view.series[1].getViewBox(), self.view.right_view)

    def test_multi_layer_legend_reflows_without_hiding_plot(self):
        data = results()
        data["profiles"] = [
            {"layer": layer, "points": deepcopy(data["profiles"][0]["points"])}
            for layer in range(1, 11)
        ]
        self.window.set_results(data)
        self.application.processEvents()
        self.assertEqual(len(self.view.legend.items), 20)
        wide_columns = self.view.legend.columnCount
        self.assertGreater(wide_columns, 2)
        self.assertGreater(self.view.left_view.height(), 150)
        self.window.resize(800, 800)
        self.application.processEvents()
        self.assertLess(self.view.legend.columnCount, wide_columns)
        self.assertGreater(self.view.left_view.height(), 150)

    def test_unsupported_extreme_plot_range_is_reported(self):
        self.window.set_results(results())
        settings = self.view._axis_settings["profile"].copy()
        for limits in (
            (1.6e308, 1.7e308, 2e306, None),
            (1.0, 1.000000000000002, 1e-15, None),
        ):
            settings["horizontal"] = limits
            self.view._axis_settings["profile"] = settings
            self.view._redraw()
            self.assertIn("axis", self.view.status.text())
            self.assertIn("chart display", self.view.status.text())
            self.assertFalse(self.view.series)

    def test_automatic_range_does_not_force_zero_and_keeps_small_scales(self):
        lower, upper, interval, fmt = axis_parameters([-3, -2], (None, None, None, None))
        self.assertLess(upper, 0)
        self.assertLess(lower, -3)
        self.assertEqual(interval, 0.5)
        self.assertEqual(fmt, "%.1f")
        lower, upper, interval, fmt = axis_parameters([1e-8, 1e-8], (None, None, None, None))
        self.assertGreater(lower, 0)
        self.assertLess(upper, 2e-8)
        self.assertGreater(interval, 0)
        self.assertIn("g", fmt)

    def test_axis_settings_apply_separately_and_reset(self):
        self.window.set_results(results())
        view = self.view

        def configure(dialog):
            for field, value in zip(dialog.fields["horizontal"], ("-1", "1", "0.2")):
                field.setText(value)
            for field, value in zip(dialog.fields["right"], ("1", "9", "2")):
                field.setText(value)
            select(dialog.decimals["horizontal"], 2)
            select(dialog.decimals["left"], 1)
            select(dialog.decimals["right"], 3)
            dialog.accept()
            return dialog.result()

        with patch.object(AxisSettingsDialog, "exec", configure):
            view.axis_button.click()
        self.assertEqual(view.x_axis.range, [-1, 1])
        self.assertEqual(view.right_axis.range, [1, 9])
        self.assertAlmostEqual(tick_values(view.x_axis)[1] - tick_values(view.x_axis)[0], 0.2)
        self.assertEqual(tick_values(view.right_axis)[1] - tick_values(view.right_axis)[0], 2)
        self.application.processEvents()
        self.assertIn("0.00", rendered_ticks(view, "horizontal"))
        self.assertIn("0.20", rendered_ticks(view, "horizontal"))
        self.assertIn("0.0", rendered_ticks(view, "left"))
        self.assertIn("2.000", rendered_ticks(view, "right"))
        select(view.plot_type, "top")
        self.assertNotEqual(view.x_axis.range[1], 1)
        self.assertIsNone(view._axis_settings["top"]["horizontal"][3])
        select(view.plot_type, "profile")
        self.assertEqual(view.x_axis.range[1], 1)
        self.application.processEvents()
        self.assertIn("0.00", rendered_ticks(view, "horizontal"))

        def reset(dialog):
            dialog._reset()
            dialog.accept()
            return dialog.result()

        with patch.object(AxisSettingsDialog, "exec", reset):
            view.axis_button.click()
        self.assertGreater(view.x_axis.range[1], 3)
        self.assertEqual(view._axis_settings["profile"]["horizontal"], (None, None, None, None))
        self.assertEqual(view._axis_settings["profile"]["right"], (None, None, None, None))

    def test_axis_settings_reject_invalid_values_and_support_tick_only(self):
        self.window.set_results(results())
        view = self.view
        dialog = AxisSettingsDialog("profile", view._axis_settings["profile"], view._validate_axis_settings, view)
        minimum, maximum, interval = dialog.fields["horizontal"]
        with patch.object(QMessageBox, "warning") as warning:
            for low, high, step, expected in (
                ("0", "", "", "both minimum and maximum"),
                ("2", "1", "", "minimum less than maximum"),
                ("0", "1", "0", "positive finite"),
                ("0", "1", "0.0001", "200 major ticks"),
                ("nan", "1", "", "finite"),
            ):
                minimum.setText(low)
                maximum.setText(high)
                interval.setText(step)
                dialog.accept()
                self.assertIn(expected, warning.call_args.args[2])
                self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        minimum.clear()
        maximum.clear()
        interval.setText("0.2")
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        view._axis_settings["profile"] = dialog.settings
        view._redraw()
        self.assertAlmostEqual(tick_values(view.x_axis)[1] - tick_values(view.x_axis)[0], 0.2)
        self.assertLess(view.x_axis.range[0], 0)
        self.assertGreater(view.x_axis.range[1], 3)

    def test_precision_rejects_indistinguishable_and_rounded_zero_ticks(self):
        self.window.set_results(results())
        dialog = AxisSettingsDialog(
            "profile", self.view._axis_settings["profile"], self.view._validate_axis_settings, self.view
        )
        select(dialog.decimals["horizontal"], 1)
        with patch.object(QMessageBox, "warning") as warning:
            for values in (("0.1", "0.3", "0.06"), ("1e-10", "1.1e-10", "1e-10")):
                for field, value in zip(dialog.fields["horizontal"], values):
                    field.setText(value)
                dialog.accept()
                self.assertIn("cannot be distinguished", warning.call_args.args[2])
                self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        select(dialog.decimals["horizontal"], None)
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.view._axis_settings["profile"] = dialog.settings
        self.view._redraw()
        self.assertTrue(self.view.series)
        self.assertIn("e", rendered_ticks(self.view, "horizontal")[0])

    def test_precision_error_is_reported_when_data_changes(self):
        self.window.set_results(results())
        settings = self.view._axis_settings["profile"].copy()
        settings["horizontal"] = (None, None, None, 1)
        self.view._validate_axis_settings(settings)
        self.view._axis_settings["profile"] = settings
        data = results()
        for profile in data["profiles"]:
            for point in profile["points"]:
                point["x"] /= 1000
        self.window.set_results(data)
        self.assertIn("cannot be distinguished", self.view.status.text())
        self.assertFalse(self.view.series)
        self.view._axis_settings["profile"]["horizontal"] = (None, None, None, None)
        self.view._redraw()
        self.assertTrue(self.view.series)

    def test_manual_range_can_exclude_zero(self):
        self.window.set_results(results())
        settings = self.view._axis_settings["profile"].copy()
        settings["horizontal"] = (1.0, 3.0, 0.5, None)
        self.view._validate_axis_settings(settings)
        self.view._axis_settings["profile"] = settings
        self.view._redraw()
        self.application.processEvents()
        self.assertEqual(self.view.x_axis.range, [1, 3])
        self.assertFalse(any(float(tick) == 0 for tick in rendered_ticks(self.view, "horizontal")))
        self.assertIn("may clip data", self.view.status.text())

    def test_fractional_manual_ticks_are_precise_and_include_zero(self):
        parameters = axis_parameters([], (-0.3, 0.3, 0.125, None))
        ticks = axis_ticks(*parameters)
        self.assertEqual(
            ticks,
            [("-0.250", -0.25), ("-0.125", -0.125), ("0.000", 0.0),
             ("0.125", 0.125), ("0.250", 0.25)],
        )

    def test_zero_label_on_all_axes_and_exact_boundary(self):
        self.window.set_results(results())
        settings = self.view._axis_settings["profile"].copy()
        settings["horizontal"] = (-0.8, 0.6, 0.2, None)
        settings["left"] = (-0.4, 0.4, 0.1, None)
        settings["right"] = (-0.8, 0.6, 0.2, None)
        self.view._validate_axis_settings(settings)
        self.view._axis_settings["profile"] = settings
        self.view._redraw()
        self.application.processEvents()
        for axis in ("horizontal", "left", "right"):
            self.assertIn("0.0", rendered_ticks(self.view, axis))
            self.assertNotIn("-0.0", rendered_ticks(self.view, axis))
        settings["horizontal"] = (0.0, 1.0, 0.2, None)
        self.view._axis_settings["profile"] = settings
        self.view._redraw()
        self.application.processEvents()
        self.assertIn("0.0", rendered_ticks(self.view, "horizontal"))

    def test_manual_tick_spacing_error_is_reported_when_data_changes(self):
        self.window.set_results(results())
        settings = self.view._axis_settings["profile"].copy()
        settings["horizontal"] = (None, None, 0.2, None)
        self.view._validate_axis_settings(settings)
        self.view._axis_settings["profile"] = settings
        data = results()
        for profile in data["profiles"]:
            for point in profile["points"]:
                point["x"] *= 1000
        self.window.set_results(data)
        self.assertIn("200 major ticks", self.view.status.text())
        self.assertFalse(self.view.series)
        self.assertEqual(self.view._axis_settings["profile"]["horizontal"], (None, None, 0.2, None))
        self.view._axis_settings["profile"]["horizontal"] = (None, None, None, None)
        self.view._redraw()
        self.assertTrue(self.view.series)

    def test_small_constant_values_have_a_meaningful_scale(self):
        data = results()
        for profile in data["profiles"]:
            for point in profile["points"]:
                point["u"] = 1e-8
        self.window.set_results(data)
        self.assertLess(self.view.right_axis.range[0], 1e-8)
        self.assertGreater(self.view.right_axis.range[1], 1e-8)
        self.assertLess(self.view.right_axis.range[1], 2e-8)

    def test_initial_slope_uses_snapshot_and_follows_selected_axes(self):
        data = results()
        data["input"] = load_case(ROOT / "examples" / "coordinate_geometry_input.json")
        for point in data["input"]["settings"]["slope_geometry"]:
            point["x_m"] += 5
        self.window.set_results(data)
        self.view.show_initial.setChecked(True)
        slope = self.view.series[-1]
        self.assertEqual(slope.name(), "Initial slope")
        self.assertEqual(slope.opts["pen"].style(), Qt.PenStyle.DashDotLine)
        self.assertIs(slope.getViewBox(), self.view.left_view)
        self.assertEqual(xy(slope)[0], (0, 0))
        self.assertAlmostEqual(xy(slope)[-1][0], 0.5)
        self.assertAlmostEqual(xy(slope)[-1][1], -0.55)
        self.assertIn("input snapshot", self.view.status.text())
        self.window.editor.table.item(0, 0).setText("0.4")
        self.view.show_initial.setChecked(False)
        self.view.show_initial.setChecked(True)
        self.assertAlmostEqual(xy(self.view.series[-1])[-1][1], -0.55)
        select(self.view.left_variable, "u")
        select(self.view.right_variable, "z")
        self.assertIs(self.view.series[-1].getViewBox(), self.view.right_view)
        select(self.view.x_variable, "z")
        select(self.view.left_variable, "x")
        select(self.view.right_variable, None)
        slope = self.view.series[-1]
        self.assertAlmostEqual(xy(slope)[-1][0], -0.55)
        self.assertAlmostEqual(xy(slope)[-1][1], 0.5)
        select(self.view.plot_type, "top")
        self.assertFalse(self.view.show_initial.isEnabled())
        self.assertFalse(any(line.name().startswith("Initial slope") for line in self.view.series))
        select(self.view.plot_type, "profile")
        self.assertTrue(self.view.show_initial.isEnabled())
        self.assertTrue(any(line.name().startswith("Initial slope") for line in self.view.series))

    def test_initial_slope_marks_schematic_and_reports_missing_snapshot(self):
        data = results()
        case = load_case(ROOT / "examples" / "turbulence_input.json")
        case["settings"]["mode"] = "breach"
        for layer in case["layers"]:
            layer.pop("initial_alpha_deg", None)
        data["input"] = case
        self.window.set_results(data)
        self.view.show_initial.setChecked(True)
        slope = self.view.series[-1]
        self.assertIn("schematic", slope.name())
        self.assertIn("75 degrees", self.view.status.text())
        self.assertAlmostEqual(xy(slope)[-1][0], 0.55 / math.tan(math.radians(75)))
        tiny_angle = deepcopy(case)
        tiny_angle["layers"][0]["initial_alpha_deg"] = 5e-324
        data["input"] = tiny_angle
        self.window.set_results(data)
        self.assertIn("angle is too small", self.view.status.text())
        self.assertFalse(any(line.name().startswith("Initial slope") for line in self.view.series))
        data = results()
        self.window.set_results(data)
        self.assertFalse(any(line.name().startswith("Initial slope") for line in self.view.series))
        self.assertIn("input snapshot is incomplete", self.view.status.text())
        select(self.view.left_variable, "u")
        self.assertFalse(self.view.show_initial.isEnabled())
        self.assertIn("requires x and z", self.view.status.text())

    def test_top_view_mirrors_recorded_width_and_reports_gaps(self):
        data = results()
        del data["profiles"][0]["points"][1]["width_m"]
        self.window.set_results(data)
        select(self.view.plot_type, "top")
        series = self.view.series
        self.assertEqual(
            [xy(s) for s in series],
            [[(0, 1)], [(2, 3)], [(0, -1)], [(2, -3)],
             [(2, 3), (3, 4)], [(2, -3), (3, -4)]],
        )
        self.assertEqual(self.view.left_axis.labelText, "Lateral offset (m)")
        self.assertIn("not shown", self.view.status.text())
        self.assertIn("width model is not recorded", self.view.status.text())
        self.assertFalse(self.view.right_axis.isVisible())
        for profile in data["profiles"]:
            for point in profile["points"]:
                point.pop("width_m", None)
        self.window.set_results(data)
        self.assertFalse(self.view.series)
        self.assertIn("No recorded positive widths", self.view.status.text())

    def test_unit_width_is_not_presented_as_physical_channel_width(self):
        data = results()
        data["input"] = {"initial_conditions": {}, "layers": []}
        self.window.set_results(data)
        select(self.view.plot_type, "top")
        self.assertIn("uses unit width, not a physical channel width", self.view.status.text())

    def test_adjacent_layers_connect_without_bridging_missing_fields(self):
        data = results()
        data["profiles"][1]["points"][0]["x"] = 2.5
        self.window.set_results(data)
        lines = self.view.series
        self.assertEqual(xy(lines[2])[:2], [(2, -2), (2.5, -2)])
        select(self.view.plot_type, "top")
        lines = self.view.series
        self.assertEqual(xy(lines[2])[:2], [(2, 3), (2.5, 3)])
        del data["profiles"][1]["points"][0]["width_m"]
        self.window.set_results(data)
        self.assertEqual(xy(self.view.series[2]), [(3, 4)])

    def test_previous_results_overlay_and_load_from_case(self):
        first = results()
        second = deepcopy(first)
        second["profiles"][0]["points"][0]["z"] = 10
        self.window.set_results(first)
        self.window.set_results(second)
        self.assertIs(self.view.previous, first)
        self.assertFalse(self.view.show_previous.isChecked())
        self.view.show_previous.setChecked(True)
        lines = self.view.series
        previous = [line for line in lines if line.name().startswith("Previous")]
        self.assertEqual(len(previous), 4)
        self.assertEqual(previous[0].opts["pen"].style(), Qt.PenStyle.DashLine)
        self.assertEqual(xy(previous[0])[0], (0, 0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old-case.json"
            write_json(path, {"results": first})
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(path), "")):
                self.view._load_previous()
            self.assertEqual(self.view.previous, first)
            self.assertIn(path.name, self.view.comparison_status.text())
            bad = Path(directory) / "bad.json"
            write_json(bad, {"results": {"version": 2}})
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(bad), "")), \
                    patch.object(QMessageBox, "critical") as error:
                self.view._load_previous()
            error.assert_called_once()
            self.assertEqual(self.view.previous, first)
        self.window.load_input(ROOT / "examples" / "turbulence_input.json")
        self.assertIsNone(self.view.current)
        self.assertIsNone(self.view.previous)
        self.assertFalse(self.view.show_previous.isEnabled())

    def test_appearance_and_export_png_jpeg_at_requested_size(self):
        self.window.set_results(results())
        view = self.view
        view.title.setText("Slope results")
        view.title_size.setValue(20)
        with patch.object(QColorDialog, "getColor", return_value=QColor("#228833")):
            view.left_color.click()
        self.assertEqual(view.chart.titleLabel.text, "Slope results")
        self.assertEqual(view.chart.titleLabel.opts["size"], "20pt")
        self.assertEqual(view.series[0].opts["pen"].color().name(), "#228833")
        self.assertTrue(view.series[0].opts["pen"].isCosmetic())
        view.image_width.setValue(640)
        view.image_height.setValue(480)
        self.application.processEvents()
        with tempfile.TemporaryDirectory() as directory:
            for extension in ("png", "jpg"):
                path = Path(directory) / f"chart.{extension}"
                view.save_image(path)
                image = QImage(str(path))
                self.assertFalse(image.isNull())
                self.assertEqual((image.width(), image.height()), (640, 480))
                colored = sum(
                    1 for y in range(0, 480, 4) for x in range(0, 640, 4)
                    if min(image.pixelColor(x, y).getRgb()[:3]) < 200
                )
                self.assertGreater(colored, 100)
                hues = [0, 0]
                for y in range(480):
                    for x in range(640):
                        red, green, blue, _ = image.pixelColor(x, y).getRgb()
                        hues[0] += green > red + 25 and green > blue + 25
                        hues[1] += red > green + 40 and red > blue + 40
                self.assertGreater(min(hues), 10)
                self.assertLess(max(hues), 640 * 480 * 0.1)
            with self.assertRaisesRegex(ValueError, "PNG or JPEG"):
                view.save_image(Path(directory) / "chart.svg")
        select(view.plot_type, "top")
        self.application.processEvents()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "top.png"
            view.save_image(path)
            self.assertFalse(QImage(str(path)).isNull())

    @unittest.skipUnless(EXECUTABLE.is_file(), "Build HMBreach or set HMBREACH_EXECUTABLE")
    def test_real_calculations_update_charts_and_previous_overlay(self):
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
                self.assertEqual(self.window.status.text(), "Calculation completed.")
                self.window.tabs.setCurrentWidget(self.view)
                self.application.processEvents()
                return self.window.results

            first = run()
            point = first["profiles"][0]["points"][0]
            self.assertEqual(xy(self.view.series[0])[0], (point["x"], point["z"]))
            self.view.show_initial.setChecked(True)
            initial = xy(self.view.series[-1])
            self.assertEqual(initial[0], (0, 0))
            self.assertAlmostEqual(initial[1][0], 0.25 / math.tan(math.radians(40)))
            self.assertEqual(initial[1][1], -0.25)
            self.view.show_initial.setChecked(False)
            self.window.editor.table.item(0, 1).setText("260")
            second = run()
            self.assertEqual(self.view.previous, first)
            self.assertEqual(self.view.current, second)
            self.view.show_previous.setChecked(True)
            self.assertTrue(any(line.name().startswith("Previous") for line in self.view.series))
            select(self.view.plot_type, "top")
            point = second["profiles"][0]["points"][0]
            self.assertEqual(xy(self.view.series[0])[0], (point["x"], point["width_m"] / 2))
            self.assertIn("unit width", self.view.status.text())
            case = self.window.editor.case()
            case["settings"]["width_model"] = "b_calc"
            case["initial_conditions"]["initial_width_m"] = 1.0
            self.window.editor.set_case(case)
            fanning = run()
            first_width = fanning["profiles"][0]["points"][0]["width_m"]
            last_width = fanning["profiles"][-1]["points"][-1]["width_m"]
            self.assertNotEqual(first_width, last_width)
            self.view.show_previous.setChecked(False)
            positive = xy(self.view.series[0])
            negative = xy(self.view.series[1])
            self.assertEqual(positive[0][1], first_width / 2)
            self.assertEqual(negative[0][1], -first_width / 2)
            self.assertNotIn("unit width", self.view.status.text())


if __name__ == "__main__":
    unittest.main()
