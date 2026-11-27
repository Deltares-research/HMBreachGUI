import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import Mock, patch

from GUI.app import CaseWindow
from GUI.case_io import load_case, read_json, validate_results
from GUI.help_view import render_document
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

    def test_startup_case_has_requested_five_layers(self):
        layers = self.window.editor.case()["layers"]
        self.assertEqual(len(layers), 5)
        self.assertEqual([layer["thickness_m"] for layer in layers], [2] * 5)
        self.assertEqual([layer["initial_alpha_deg"] for layer in layers], [32, 28, 24, 20, 16])
        self.assertEqual([layer["d50_micrometre"] for layer in layers], [180, 205, 220, 235, 250])
        self.assertEqual([layer["porosity_percent"] for layer in layers], [40] * 5)

    def test_input_actions_remain_visible_when_window_is_resized(self):
        def buttons_in(widget):
            found = []
            for child in widget.winfo_children():
                if isinstance(child, ttk.Button):
                    found.append(child)
                found.extend(buttons_in(child))
            return found

        wanted = {"Add layer", "Copy layer", "Remove layer", "Apply gradient to all layers"}
        self.window.deiconify()
        for coordinate_geometry in (False, True):
            if coordinate_geometry:
                self.window.editor.geometry.enabled_var.set(True)
                self.window.editor.geometry._toggle_geometry()
            for size in ("900x600", "720x480"):
                self.window.geometry(size)
                self.window.update()
                buttons = {button.cget("text"): button for button in buttons_in(self.window.editor)}
                self.assertTrue(wanted <= buttons.keys())
                for name in wanted:
                    button = buttons[name]
                    self.assertTrue(button.winfo_ismapped(), f"{name} not mapped at {size}")
                    left, top = button.winfo_rootx(), button.winfo_rooty()
                    right, bottom = left + button.winfo_width(), top + button.winfo_height()
                    parent = button.master
                    while parent is not None and not isinstance(parent, tk.Tk):
                        self.assertGreaterEqual(left, parent.winfo_rootx(), (name, size))
                        self.assertGreaterEqual(top, parent.winfo_rooty(), (name, size))
                        self.assertLessEqual(right, parent.winfo_rootx() + parent.winfo_width(), (name, size))
                        self.assertLessEqual(bottom, parent.winfo_rooty() + parent.winfo_height(), (name, size))
                        parent = parent.master

    def test_startup_has_room_for_ten_visible_layer_rows(self):
        self.window.deiconify()
        self.window.update()
        editor = self.window.editor
        for _ in range(5):
            editor.add_layer()
        self.window.update()
        canvas = editor.content_canvas
        table = editor.table
        for geometry_enabled in (False, True):
            if geometry_enabled:
                editor.geometry.enabled_var.set(True)
                editor.geometry._toggle_geometry()
                self.window.update()
            needed = self.window.winfo_height() + max(
                0, editor.content.winfo_reqheight() - canvas.winfo_height()
            )
            screen_limit = max(
                self.window.minsize()[1],
                min(self.window.winfo_screenheight() - 80,
                    (self.window.winfo_screenwidth() - 80) * 2 // 3),
            )
            if needed > screen_limit:
                self.skipTest("Screen is too short to show all ten rows without scrolling")
            for row in (table.get_children()[0], table.get_children()[9]):
                box = table.bbox(row, "#1")
                self.assertTrue(box, "Layer row is not visible in the table")
                top = table.winfo_rooty() + box[1]
                self.assertGreaterEqual(top, canvas.winfo_rooty())
                self.assertLessEqual(top + box[3], canvas.winfo_rooty() + canvas.winfo_height())

        editor.add_layer()
        table.see(table.get_children()[-1])
        self.window.update()
        self.assertTrue(table.bbox(table.get_children()[-1], "#1"))

    def test_startup_keeps_original_window_proportions(self):
        self.window.deiconify()
        self.window.update()
        self.assertEqual(self.window.winfo_width() * 2, self.window.winfo_height() * 3)

    def test_initial_window_height_is_limited_on_a_small_screen(self):
        self.window.deiconify()
        self.window.update()
        with patch.object(self.window, "winfo_screenheight", return_value=650):
            self.window._size_initial_window()
        self.window.update()
        self.assertLessEqual(self.window.winfo_height(), 570)
        self.assertEqual(self.window.winfo_width() * 2, self.window.winfo_height() * 3)
        self.assertEqual(int(self.window.editor.table.cget("height")), 10)
        self.assertLess(self.window.editor.content_canvas.yview()[1], 1)

    def test_initial_window_width_is_limited_on_a_narrow_screen(self):
        self.window.deiconify()
        self.window.update()
        with patch.object(self.window, "winfo_screenwidth", return_value=850):
            self.window._size_initial_window()
        self.window.update()
        self.assertLessEqual(self.window.winfo_width(), 770)
        self.assertEqual(self.window.winfo_width() * 2, self.window.winfo_height() * 3)

    def test_scrolling_reaches_layer_table_at_minimum_window_size(self):
        self.window.deiconify()
        self.window.geometry("720x480")
        self.window.focus_force()
        self.window.update()
        editor = self.window.editor
        canvas = editor.content_canvas
        self.assertLess(canvas.yview()[1], 1)
        canvas.yview_moveto(1)
        self.window.update()
        row = editor.table.get_children()[-1]
        x, y, width, height = editor.table.bbox(row, "#1")
        top = editor.table.winfo_rooty() + y
        self.assertGreaterEqual(top, canvas.winfo_rooty())
        self.assertLessEqual(top + height, canvas.winfo_rooty() + canvas.winfo_height())
        editor.table.event_generate("<Button-1>", x=x + width // 2, y=y + height // 2)
        self.window.update()
        entry = editor._cell_editor.entry
        self.assertIsNotNone(entry)
        entry.delete(0, "end")
        entry.insert(0, "2.5")
        self.assertEqual(editor.case()["layers"][-1]["thickness_m"], 2.5)

    def test_header_identifies_gui_development_version(self):
        self.assertEqual(
            self.window.header_title.cget("text"), "HMBreach GUI v0.1.0 (development build)"
        )

    @unittest.skipUnless((ROOT / "Deltares_logo_Wit_RGB.png").is_file(), "Logo not provided")
    def test_header_displays_provided_logo(self):
        self.assertGreater(self.window._logo.width(), 0)
        self.assertLessEqual(self.window._logo.width(), 180)

    def test_layer_display_order_and_model_choices(self):
        editor = self.window.editor
        columns = list(editor.table.cget("displaycolumns"))
        self.assertEqual(columns[2:7], [
            "d50_micrometre", "user_d15", "d15_micrometre",
            "porosity_percent", "effective_permeability",
        ])
        self.assertIs(editor.settings.mode.master.master, editor.content)
        self.assertIs(editor.settings.width_model.master, editor.settings.mode.master)
        self.assertIs(editor.settings.erosion_variant.master, editor.settings.mode.master)

    def test_editing_reordered_layer_column_updates_correct_field(self):
        editor = self.window.editor
        self.window.deiconify()
        self.window.update()
        row = editor.table.get_children()[0]
        x, y, width, height = editor.table.bbox(row, "#4")
        editor._begin_cell_edit(SimpleNamespace(x=x + width // 2, y=y + height // 2))
        entry = editor.table.winfo_children()[-1]
        entry.delete(0, "end")
        entry.insert(0, "true")
        entry.focus_force()
        self.window.update()
        entry.event_generate("<Return>")
        self.window.update()
        self.assertEqual(editor.table.item(row, "values")[5], "true")

    def test_single_click_edits_angle_and_commits_when_case_is_read(self):
        editor = self.window.editor
        self.window.deiconify()
        self.window.focus_force()
        self.window.update()
        table = editor.table
        row = table.get_children()[0]
        columns = list(table.cget("displaycolumns"))
        column = f"#{columns.index('initial_alpha_deg') + 1}"
        x, y, width, height = table.bbox(row, column)
        table.event_generate("<Button-1>", x=x + width // 2, y=y + height // 2)
        self.window.update()
        entry = table.winfo_children()[-1]
        self.assertEqual(str(entry), str(self.window.focus_get()))
        self.assertEqual(entry.selection_present(), True)
        entry.event_generate("<KeyPress-5>")
        self.window.update()
        self.assertEqual(entry.get(), "5")
        entry.insert("end", "1")
        self.assertEqual(editor.case()["layers"][0]["initial_alpha_deg"], 51)
        self.assertEqual(table.selection(), (row,))

    def test_single_click_switches_cells_and_escape_cancels(self):
        editor = self.window.editor
        self.window.deiconify()
        self.window.focus_force()
        self.window.update()
        table = editor.table
        row = table.get_children()[0]

        def click(column):
            x, y, width, height = table.bbox(row, column)
            table.event_generate("<Button-1>", x=x + width // 2, y=y + height // 2)
            self.window.update()

        click("#2")
        entry = table.winfo_children()[-1]
        entry.delete(0, "end")
        entry.insert(0, "55")
        click("#1")
        entry = table.winfo_children()[-1]
        entry.delete(0, "end")
        entry.insert(0, "99")
        entry.event_generate("<Escape>")
        self.window.update()
        case = editor.case()
        self.assertEqual(case["layers"][0]["initial_alpha_deg"], 55)
        self.assertEqual(case["layers"][0]["thickness_m"], 2)

    def test_coordinate_geometry_locks_angle_until_disabled(self):
        self.window.load_input(ROOT / "examples" / "coordinate_geometry_input.json")
        self.window.deiconify()
        self.window.update()
        editor = self.window.editor
        table = editor.table
        row = table.get_children()[0]
        x, y, width, height = table.bbox(row, "#2")
        table.event_generate("<Button-1>", x=x + width // 2, y=y + height // 2)
        self.window.update()
        self.assertIsNone(editor._cell_editor.entry)
        self.assertIn("turn off", editor.angle_notice.cget("text"))
        editor.geometry.enabled_var.set(False)
        editor.geometry._toggle_geometry()
        for row in table.get_children():
            x, y, width, height = table.bbox(row, "#2")
            table.event_generate("<Button-1>", x=x + width // 2, y=y + height // 2)
            self.window.update()
            entry = editor._cell_editor.entry
            entry.delete(0, "end")
            entry.insert(0, "45")
            entry.event_generate("<Return>")
            self.window.update()
        case = editor.case()
        self.assertNotIn("slope_geometry", case["settings"])
        self.assertEqual([layer["initial_alpha_deg"] for layer in case["layers"]], [45, 45])

    def test_pending_cell_edit_is_not_discarded_without_confirmation(self):
        self.window.deiconify()
        self.window.update()
        editor = self.window.editor
        table = editor.table
        row = table.get_children()[0]
        x, y, width, height = table.bbox(row, "#2")
        table.event_generate("<Button-1>", x=x + width // 2, y=y + height // 2)
        self.window.update()
        entry = editor._cell_editor.entry
        entry.delete(0, "end")
        entry.insert(0, "55")
        with patch("GUI.app.messagebox.askyesno", return_value=False) as confirm, \
                patch("GUI.app.filedialog.askopenfilename") as choose:
            self.window._choose_input()
        confirm.assert_called_once()
        choose.assert_not_called()
        self.assertEqual(editor.case()["layers"][0]["initial_alpha_deg"], 55)

    def test_preview_cell_is_read_only_and_unchanged_click_is_not_dirty(self):
        editor = self.window.editor
        self.window.deiconify()
        self.window.update()
        table = editor.table
        row = table.get_children()[0]
        x, y, width, height = table.bbox(row, "#2")
        table.event_generate("<Button-1>", x=x + width // 2, y=y + height // 2)
        self.window.update()
        editor.commit_pending_edits()
        self.assertFalse(editor.dirty)
        table.xview_moveto(1)
        self.window.update()
        columns = list(table.cget("displaycolumns"))
        column = f"#{columns.index('effective_permeability') + 1}"
        x, y, width, height = table.bbox(row, column)
        table.event_generate("<Button-1>", x=x + width // 2, y=y + height // 2)
        self.window.update()
        self.assertIsNone(editor._cell_editor.entry)
        self.assertFalse(editor.dirty)

    def test_single_click_edits_width_geometry_cells(self):
        settings = self.window.editor.settings
        settings.add_width_point()
        self.window.deiconify()
        self.window.tabs.select(settings)
        self.window.update()
        table = settings.width_table
        row = table.get_children()[0]
        for column, value in (("#1", "1.5"), ("#2", "3")):
            x, y, width, height = table.bbox(row, column)
            table.event_generate("<Button-1>", x=x + width // 2, y=y + height // 2)
            self.window.update()
            entry = settings._width_cell_editor.entry
            entry.insert(0, value)
        case = {"settings": {}}
        settings.apply_to_case(case)
        self.assertEqual(case["settings"]["width_geometry"], [{"s_m": 1.5, "width_m": 3.0}])
        self.assertEqual(table.selection(), (row,))

    def test_working_directory_is_remembered(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            preferences = path / "settings" / "preferences.json"
            with patch("GUI.app._preferences_path", return_value=preferences):
                self.window.output_directory.set(directory)
                self.window._save_working_directory()
                self.window.output_directory.set("")
                self.window._restore_working_directory()
                self.assertEqual(self.window.output_directory.get(), str(path.resolve()))

    def test_help_tab_contains_only_browser_button(self):
        page = self.window.nametowidget(self.window.tabs.tabs()[-1])
        widgets = page.winfo_children()
        self.assertEqual(len(widgets), 1)
        self.assertEqual(widgets[0].cget("text"), "Open formatted documentation in browser")

    def test_formatted_help_opens_offline_browser_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SCIENTIFICREADME.md"
            path.write_text("# Model\n\n$x=\\frac{1}{2}$", encoding="utf-8")
            page = Path(directory) / "documentation" / "scientific-readme.html"
            with patch("GUI.app.ROOT", Path(directory)), \
                    patch("GUI.app._preferences_path", return_value=Path(directory) / "prefs.json"), \
                    patch("GUI.app.webbrowser.open", return_value=True) as browser:
                self.window._open_formatted_help()
            browser.assert_called_once_with(page.as_uri(), new=2)
            html = page.read_text(encoding="utf-8")
            self.assertIn("<h1>Model</h1>", html)
            self.assertIn("<mfrac>", html)
            self.assertIn(path.parent.as_uri() + "/", html)
            self.assertNotIn("<script", html)

    def test_formatted_help_reports_browser_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "SCIENTIFICREADME.md"
            path.write_text("# Model", encoding="utf-8")
            with patch("GUI.app.ROOT", Path(directory)), \
                    patch("GUI.app._preferences_path", return_value=Path(directory) / "prefs.json"), \
                    patch("GUI.app.webbrowser.open", return_value=False), \
                    patch("GUI.app.messagebox.showerror") as show_error:
                self.window._open_formatted_help()
        show_error.assert_called_once()

    def test_formatted_help_reports_missing_document(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("GUI.app.ROOT", Path(directory)), \
                    patch("GUI.app.webbrowser.open") as browser, \
                    patch("GUI.app.messagebox.showerror") as show_error:
                self.window._open_formatted_help()
        show_error.assert_called_once()
        browser.assert_not_called()

    @unittest.skipUnless((ROOT / "SCIENTIFICREADME.md").is_file(), "Scientific README not provided")
    def test_scientific_document_renders_equations_and_diagram(self):
        source = ROOT / "SCIENTIFICREADME.md"
        html = render_document(source.read_text(encoding="utf-8"), source)
        self.assertIn("<h1>HMBreach scientific model</h1>", html)
        self.assertIn("<mfrac>", html)
        self.assertIn("<msqrt>", html)
        self.assertIn("examples/initial_conditions_geometry.svg", html)
        self.assertNotIn("$$", html)
        self.assertTrue((source.parent / "examples" / "initial_conditions_geometry.svg").is_file())

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
        self.assertEqual(len(editor.case()["layers"]), 6)

        last = editor.table.get_children()[-1]
        values = list(editor.table.item(last, "values"))
        values[0] = "-1"
        editor.table.item(last, values=values)
        with self.assertRaisesRegex(ValueError, "Layer 6 thickness"):
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

    def test_failed_calculation_can_be_rerun_after_editing(self):
        self.window.executable.set(sys.executable)
        previous_results = object()
        self.window.results = previous_results
        with tempfile.TemporaryDirectory() as directory, patch.object(
            self.window, "_save_working_directory"
        ):
            self.window.output_directory.set(directory)

            def wait_for_finish():
                deadline = time.monotonic() + 10
                while (
                    (self.window.process is not None or self.window._result_future is not None)
                    and time.monotonic() < deadline
                ):
                    self.window.update()
                    time.sleep(0.01)
                self.assertIsNone(self.window.process, "Calculation did not finish")
                self.assertIsNone(self.window._result_future, "Results did not finish loading")

            self.window.run_calculation()
            wait_for_finish()
            self.assertIn("Calculation failed", self.window.status.get())
            self.assertEqual(str(self.window.run_button.cget("state")), "normal")
            self.assertIs(self.window.results, previous_results)
            self.window.editor.initial_fields["vz_mm_s"].set("2")
            self.window.run_button.invoke()
            self.assertEqual(self.window._running_case["initial_conditions"]["vz_mm_s"], 2)
            wait_for_finish()
            self.assertEqual(str(self.window.run_button.cget("state")), "normal")
            self.assertIs(self.window.results, previous_results)
            if EXECUTABLE.is_file():
                self.window.results = None
                self.window.executable.set(str(EXECUTABLE))
                self.window.run_button.invoke()
                wait_for_finish()
                self.assertEqual(self.window.status.get(), "Calculation completed.")
                self.assertIsNotNone(self.window.results)

    def test_stdout_eof_before_exit_does_not_stall_completion(self):
        process = Mock()
        process.poll.side_effect = [None, 1]
        self.window.process = process
        self.window._output_queue.put(None)
        with patch.object(self.window, "after"), patch.object(
            self.window, "_process_finished"
        ) as finished:
            self.window._poll_process()
            self.window._poll_process()
        finished.assert_called_once_with(1)
        self.assertIsNone(self.window.process)

    @unittest.skipUnless(EXECUTABLE.is_file(), "Build HMBreach or set HMBREACH_EXECUTABLE")
    def test_solver_accepts_layers_updated_from_geometry(self):
        geometry = self.window.editor.geometry
        geometry.enabled_var.set(True)
        geometry._toggle_geometry()
        for point in ((0.2, -0.1), (0.6, -0.4), (1.2, -0.8)):
            geometry.add_point(*point)
        geometry.update_layers_button.invoke()
        self.window.executable.set(str(EXECUTABLE))
        with tempfile.TemporaryDirectory() as directory:
            self.window.output_directory.set(directory)
            self.window.run_calculation()
            deadline = time.monotonic() + 15
            while (
                (self.window.process is not None or self.window._result_future is not None)
                and time.monotonic() < deadline
            ):
                self.window.update()
                time.sleep(0.01)
            self.assertIsNone(self.window.process)
            self.assertIsNone(self.window._result_future)
            self.assertEqual(
                self.window.status.get(), "Calculation completed.",
                self.window.output.get("1.0", "end"),
            )
            self.assertIsNotNone(self.window.results)

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
