"""Tkinter case editor and HMBreach solver integration."""

import json
import os
import sys
import tempfile
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk
from latex2mathml.exceptions import (
    DenominatorNotFoundError, DoubleSubscriptsError, DoubleSuperscriptsError,
    ExtraLeftOrMissingRightError, InvalidAlignmentError, InvalidStyleForGenfracError,
    InvalidWidthError, LimitsMustFollowMathOperatorError, MissingEndError,
    MissingSuperScriptOrSubscriptError, NoAvailableTokensError, NumeratorNotFoundError,
)

from GUI.case_editor import CaseEditor
from GUI.case_io import load_case, read_json, results_from_workbook, validate_results, write_json
from GUI.charts_view import ChartsView
from GUI.help_view import render_document
from GUI.prototype import DEFAULT_INPUT, PrototypeWindow, ROOT
from GUI.results_view import ResultsView


GUI_VERSION = "0.1.0"


def _read_workbook(path, case):
    return validate_results(results_from_workbook(path, case))


def _preferences_path():
    base = os.environ.get("APPDATA")
    return (Path(base) if base else Path.home() / ".config") / "HMBreachGUI" / "preferences.json"


class CaseWindow(PrototypeWindow):
    def __init__(self):
        super().__init__()
        self.title("HMBreach")
        self._temporary_input = None
        self._running_case = None
        self._working_directory = None
        self.results = None
        self._results_dirty = False
        self._result_future = None
        self._result_executor = None
        self._result_files = None

        self.tabs.pack_forget()
        header = tk.Frame(self, background="#003b5c")
        header.pack(fill="x")
        self.header_title = tk.Label(
            header, text=f"HMBreach GUI v{GUI_VERSION} (development build)",
            background="#003b5c", foreground="white",
            font=("TkDefaultFont", 14, "bold"),
        )
        self.header_title.pack(side="left", padx=12)
        try:
            with Image.open(ROOT / "Deltares_logo_Wit_RGB.png") as image:
                image.thumbnail((180, 52), Image.Resampling.LANCZOS)
                self._logo = ImageTk.PhotoImage(image, master=self)
        except OSError as error:
            tk.Label(
                header, text=f"Deltares logo unavailable: {error}",
                background="#003b5c", foreground="white",
            ).pack(side="right", padx=8)
        else:
            tk.Label(header, image=self._logo, background="#003b5c").pack(side="right", padx=8)
        self.tabs.pack(fill="both", expand=True)

        self.tabs.forget(self.run_page)
        self.input_page = ttk.Frame(self.tabs, padding=8)
        self.editor = CaseEditor(self.input_page, tabs_parent=self.tabs)
        self.tabs.add(self.input_page, text="Input")
        self.tabs.add(self.editor.geometry, text="Geometry")
        self.tabs.add(self.run_page, text="Run")
        self.results_view = ResultsView(
            self.tabs, on_open_results=self._open_results, on_save_results=self._save_results
        )
        self.tabs.add(self.results_view, text="Results")
        self.charts_view = ChartsView(self.tabs)
        self.tabs.add(self.charts_view, text="Charts")
        self.tabs.add(self.editor.settings, text="Constants")
        self._build_help_page()
        self.result_status = self.results_view.status
        self.input_entry.configure(state="readonly")
        self._build_input_page()
        try:
            self.load_input(DEFAULT_INPUT)
        except (OSError, ValueError) as error:
            self.status.set(f"Could not load sample input: {error}")
        self._restore_working_directory()
        self._size_initial_window()

    def _size_initial_window(self):
        screen_limit = max(
            self.minsize()[1],
            min(self.winfo_screenheight() - 80, (self.winfo_screenwidth() - 80) * 2 // 3),
        )
        height = min(800, screen_limit)
        height -= height % 2
        self.geometry(f"{height * 3 // 2}x{height}")

    def _build_help_page(self):
        page = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(page, text="Help")
        ttk.Button(
            page, text="Open formatted documentation in browser",
            command=self._open_formatted_help,
        ).pack(anchor="w", pady=4)

    def _open_formatted_help(self):
        try:
            path = ROOT / "SCIENTIFICREADME.md"
            html = render_document(path.read_text(encoding="utf-8"), path)
            directory = _preferences_path().parent / "documentation"
            directory.mkdir(parents=True, exist_ok=True)
            output = directory / "scientific-readme.html"
            output.write_text(html, encoding="utf-8")
            if not webbrowser.open(output.as_uri(), new=2):
                raise OSError("No browser could be opened.")
        except (
            OSError, UnicodeError, ValueError, DenominatorNotFoundError,
            DoubleSubscriptsError, DoubleSuperscriptsError, ExtraLeftOrMissingRightError,
            InvalidAlignmentError, InvalidStyleForGenfracError, InvalidWidthError,
            LimitsMustFollowMathOperatorError, MissingEndError,
            MissingSuperScriptOrSubscriptError, NoAvailableTokensError, NumeratorNotFoundError,
        ) as error:
            messagebox.showerror("Unable to display documentation", str(error), parent=self)

    def _restore_working_directory(self):
        path = _preferences_path()
        try:
            with path.open(encoding="utf-8") as stream:
                preferences = json.load(stream)
            directory = preferences["working_directory"]
            if not isinstance(directory, str) or not Path(directory).is_dir():
                raise ValueError("The saved working directory no longer exists.")
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.set(f"Unable to restore working directory: {error}")
            return
        self.output_directory.set(directory)

    def _save_working_directory(self):
        directory = self.output_directory.get().strip()
        if not directory or not Path(directory).is_dir():
            return
        path = _preferences_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"working_directory": str(Path(directory).resolve())}, indent=2),
                encoding="utf-8",
            )
        except OSError as error:
            messagebox.showwarning("Unable to remember working directory", str(error), parent=self)

    def _choose_directory(self):
        super()._choose_directory()
        self._save_working_directory()

    def _build_input_page(self):
        buttons = ttk.Frame(self.input_page)
        buttons.pack(fill="x", pady=(0, 5))
        ttk.Button(buttons, text="Open case JSON...", command=self._choose_input).pack(side="left", padx=3)
        ttk.Button(buttons, text="Save case JSON as...", command=self._save_input).pack(side="left", padx=3)
        ttk.Button(
            buttons, text="Export solver input JSON...", command=self._export_input
        ).pack(side="left", padx=3)
        self.editor.pack(fill="both", expand=True)

    def _busy(self):
        return (
            self._is_running()
            or self._result_future is not None
        )

    def load_input(self, path):
        case = load_case(path)
        results = validate_results(case.pop("results")) if "results" in case else None
        self.editor.set_case(case)
        self.results = results
        self._results_dirty = False
        self.results_view.set_results(results)
        self.results_view.set_files(None, None)
        self.charts_view.set_results(results)
        self.input_file.set(str(Path(path).resolve()))
        self.status.set("Input case loaded.")

    def _choose_input(self):
        if self._busy():
            messagebox.showinfo(
                "Calculation running",
                "Wait for the calculation and results to finish.",
                parent=self,
            )
            return
        self.editor.commit_pending_edits()
        if (self.editor.dirty or self._results_dirty) and not messagebox.askyesno(
            "Discard changes?", "Discard unsaved input edits or calculation results?", parent=self
        ):
            return
        filename = filedialog.askopenfilename(
            parent=self,
            title="Open case JSON",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not filename:
            return
        try:
            self.load_input(Path(filename))
        except (OSError, ValueError) as error:
            messagebox.showerror("Unable to open input", str(error), parent=self)

    def save_input(self, path):
        case = self.editor.case()
        document = dict(case)
        if self.results is not None:
            document["results"] = self.results
        write_json(path, document)
        self.editor.mark_saved(case)
        self._results_dirty = False
        self.input_file.set(str(Path(path).resolve()))
        self.status.set("Input case saved.")

    def _save_input(self):
        try:
            self.editor.case()
        except ValueError as error:
            self.editor.message.configure(text=str(error))
            self._show_depth_warning()
            return
        self._show_depth_warning()
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Save case JSON",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if filename:
            try:
                self.save_input(Path(filename))
            except (OSError, ValueError) as error:
                messagebox.showerror("Unable to save input", str(error), parent=self)

    def _export_input(self):
        try:
            case = self.editor.case()
        except ValueError as error:
            self.editor.message.configure(text=str(error))
            self._show_depth_warning()
            return
        self._show_depth_warning()
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export solver input JSON",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if filename:
            try:
                if Path(filename).resolve() == Path(self.input_file.get()).resolve():
                    raise ValueError("Choose a different file to avoid replacing the open case.")
                write_json(filename, case)
            except (OSError, ValueError) as error:
                messagebox.showerror("Unable to export input", str(error), parent=self)

    def run_calculation(self):
        if self._busy():
            return
        try:
            case = self.editor.case()
        except ValueError as error:
            self.editor.message.configure(text=str(error))
            self.tabs.select(0)
            self._show_depth_warning()
            return
        directory_text = self.output_directory.get().strip()
        directory = Path(directory_text) if directory_text else None
        if directory is None or not directory.is_dir():
            self.status.set("Select an existing working directory.")
            self.tabs.select(self.run_page)
            return
        if not Path(self.executable.get().strip()).is_file():
            self.status.set("Select an existing HMBreach executable.")
            self.tabs.select(self.run_page)
            return
        self._save_working_directory()
        if self._results_dirty and not messagebox.askyesno(
            "Replace results?",
            "Replace calculation results that have not been saved in the case?",
            parent=self,
        ):
            return
        self._show_depth_warning()
        try:
            self._temporary_input = tempfile.TemporaryDirectory(
                prefix="hmbreach-input-", dir=directory
            )
            input_path = Path(self._temporary_input.name) / "input.json"
            write_json(input_path, case)
        except (OSError, ValueError) as error:
            self._cleanup_temporary_input()
            self.status.set(f"Unable to prepare calculation: {error}")
            self.tabs.select(self.run_page)
            return
        self._running_case = case
        self._working_directory = directory.resolve()
        self.results_view.set_files(None, None)
        original_filename = self.input_file.get()
        self.input_file.set(str(input_path.resolve()))
        self.tabs.select(self.run_page)
        try:
            super().run_calculation()
        finally:
            self.input_file.set(original_filename)
        if self.process is None:
            self._cleanup_temporary_input()
            self._running_case = None

    def _show_depth_warning(self):
        warning = self.editor.geometry.depth_warning.cget("text")
        if warning:
            messagebox.showwarning("Layer and slope depth mismatch", warning, parent=self)

    def _cleanup_temporary_input(self):
        if self._temporary_input is not None:
            self._temporary_input.cleanup()
            self._temporary_input = None

    def _process_finished(self, exit_code):
        try:
            if exit_code != 0:
                self.result_status.configure(
                    text="Calculation failed; previously loaded results were not changed."
                )
                self.status.set(f"Calculation failed (exit code {exit_code}).")
                self.run_button.configure(state="normal")
                return
            case = self._running_case
            if case is None:
                raise ValueError("Calculation input snapshot is missing.")
            settings = case.get("settings", {})
            workbook = Path(
                settings.get("workbook_file", settings.get("profile_file", "hmbres_results.xlsx"))
            )
            if not workbook.is_absolute():
                workbook = self._working_directory / workbook
            workbook = workbook.resolve()
            geometry = workbook.with_name(workbook.stem + "_initial_geometry.svg")
            self._result_files = (workbook, geometry)
            self._result_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="hmbreach-results"
            )
            self._result_future = self._result_executor.submit(_read_workbook, workbook, case)
            self.run_button.configure(state="disabled")
            self.status.set("Calculation completed; reading results...")
            self.after(25, self._finish_results_read)
        except (OSError, ValueError) as error:
            self.result_status.configure(text=f"Unable to load calculation results: {error}")
            self.status.set("Calculation finished, but results could not be loaded.")
            self.run_button.configure(state="normal")
        finally:
            self._cleanup_temporary_input()
            self._running_case = None

    def _finish_results_read(self):
        if self._result_future is None or not self._result_future.done():
            if self._result_future is not None:
                self.after(25, self._finish_results_read)
            return
        future = self._result_future
        workbook, geometry = self._result_files
        self._result_future = None
        self._result_files = None
        self._result_executor.shutdown(wait=False)
        self._result_executor = None
        self.run_button.configure(state="normal")
        error = future.exception()
        if error is not None:
            self.result_status.configure(
                text=f"Unable to load calculation results: {type(error).__name__}: {error}"
            )
            self.status.set("Calculation finished, but results could not be loaded.")
            return
        self.set_results(future.result())
        self.results_view.set_files(workbook, geometry if geometry.is_file() else None)
        self.status.set("Calculation completed.")

    def _close(self):
        if self._result_future is not None:
            messagebox.showinfo(
                "Reading results",
                "Wait for results to finish loading before closing.",
                parent=self,
            )
            return
        if self._is_running():
            super()._close()
            return
        self.editor.commit_pending_edits()
        if (self.editor.dirty or self._results_dirty) and not messagebox.askyesno(
            "Discard changes?", "Discard unsaved changes?", parent=self
        ):
            return
        self._save_working_directory()
        self.destroy()

    def set_results(self, results):
        previous = self.results
        self.results = validate_results(results)
        self._results_dirty = True
        self.results_view.set_results(self.results)
        self.results_view.set_files(None, None)
        self.charts_view.set_results(self.results, previous)

    def _open_results(self):
        if self._busy():
            messagebox.showinfo(
                "Calculation running",
                "Wait for the calculation and results to finish.",
                parent=self,
            )
            return
        if self._results_dirty and not messagebox.askyesno(
            "Replace results?",
            "Replace results that have not been saved in the case?",
            parent=self,
        ):
            return
        filename = filedialog.askopenfilename(
            parent=self,
            title="Open results JSON",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if filename:
            try:
                self.set_results(read_json(filename))
            except (OSError, ValueError) as error:
                messagebox.showerror("Unable to open results", str(error), parent=self)

    def save_results(self, path):
        if self.results is None:
            raise ValueError("Run a calculation or open results first.")
        write_json(path, self.results)

    def _save_results(self):
        if self.results is None:
            self.result_status.configure(text="Run a calculation or open results before saving.")
            return
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Save results JSON",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if filename:
            try:
                self.save_results(Path(filename))
            except (OSError, ValueError) as error:
                messagebox.showerror("Unable to save results", str(error), parent=self)


def main():
    window = CaseWindow()
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
