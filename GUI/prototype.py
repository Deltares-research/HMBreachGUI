"""Tkinter shell for running the existing HMBreach command-line solver."""

import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "examples" / "default_input.json"


def default_executable():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().with_name("HMBreach.exe")
    return ROOT / "build" / "Release" / "HMBreach.exe"


class PrototypeWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HMBreach")
        self.geometry("900x600")
        self.minsize(720, 480)
        self.process = None
        self._output_queue = queue.Queue()
        self._stdout_thread = None
        self._stdout_finished = False

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True)
        self.run_page = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.run_page, text="Run")

        self.executable = tk.StringVar(value=str(default_executable()))
        self.input_file = tk.StringVar(value=str(DEFAULT_INPUT))
        self.output_directory = tk.StringVar()
        self.status = tk.StringVar(value="Select an output working directory to begin.")

        form = ttk.Frame(self.run_page)
        form.pack(fill="x")
        self.executable_entry = self._path_row(
            form, 0, "HMBreach executable", self.executable, self._choose_executable
        )
        self.input_entry = self._path_row(
            form, 1, "Input JSON", self.input_file, self._choose_input
        )
        self.output_directory_entry = self._path_row(
            form, 2, "Working directory", self.output_directory, self._choose_directory
        )
        ttk.Label(
            self.run_page,
            text=(
                "The solver writes output files using paths from the JSON. Existing files at "
                "those paths may be overwritten; absolute paths are not restricted to the "
                "working directory."
            ),
            wraplength=850,
        ).pack(fill="x", pady=6)
        self.run_button = ttk.Button(
            self.run_page, text="Run calculation", command=self.run_calculation
        )
        self.run_button.pack(anchor="w", pady=4)
        ttk.Label(self.run_page, textvariable=self.status, wraplength=850).pack(fill="x", pady=3)
        output_frame = ttk.Frame(self.run_page)
        output_frame.pack(fill="both", expand=True, pady=4)
        self.output = tk.Text(output_frame, wrap="none", state="disabled")
        yscroll = ttk.Scrollbar(output_frame, orient="vertical", command=self.output.yview)
        xscroll = ttk.Scrollbar(output_frame, orient="horizontal", command=self.output.xview)
        self.output.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.output.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        output_frame.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)
        self.protocol("WM_DELETE_WINDOW", self._close)

    @staticmethod
    def _path_row(parent, row, label, variable, callback):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        ttk.Button(parent, text="Browse...", command=callback).grid(
            row=row, column=2, sticky="e", padx=(6, 0), pady=3
        )
        parent.columnconfigure(1, weight=1)
        return entry

    def _choose_executable(self):
        filename = filedialog.askopenfilename(
            parent=self,
            title="Select HMBreach executable",
            filetypes=(("Executable files", "*.exe"), ("All files", "*.*")),
        )
        if filename:
            self.executable.set(filename)

    def _choose_input(self):
        filename = filedialog.askopenfilename(
            parent=self,
            title="Select input JSON",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if filename:
            self.input_file.set(filename)

    def _choose_directory(self):
        directory = filedialog.askdirectory(parent=self, title="Select working directory")
        if directory:
            self.output_directory.set(directory)

    def run_calculation(self):
        if self.process is not None and self.process.poll() is None:
            return
        executable_text = self.executable.get().strip()
        input_text = self.input_file.get().strip()
        directory_text = self.output_directory.get().strip()
        if not executable_text or not Path(executable_text).is_file():
            self.status.set("Select an existing HMBreach executable.")
            return
        if not input_text or not Path(input_text).is_file():
            self.status.set("Select an existing input JSON file.")
            return
        if not directory_text or not Path(directory_text).is_dir():
            self.status.set("Select an existing working directory.")
            return

        self._set_output("")
        self._stdout_finished = False
        self.status.set("Calculation running...")
        self.run_button.configure(state="disabled")
        try:
            self.process = subprocess.Popen(
                [str(Path(executable_text).resolve()), "--input", str(Path(input_text).resolve())],
                cwd=str(Path(directory_text).resolve()),
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as error:
            self._append_output(f"Process error: {error}\n")
            self.status.set("Failed to start calculation.")
            self.run_button.configure(state="normal")
            self.process = None
            return
        self._stdout_thread = threading.Thread(target=self._read_output, daemon=True)
        self._stdout_thread.start()
        self.after(30, self._poll_process)

    def _read_output(self):
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                self._output_queue.put(line)
        finally:
            process.stdout.close()
            self._output_queue.put(None)

    def _drain_output(self):
        while True:
            try:
                text = self._output_queue.get_nowait()
            except queue.Empty:
                break
            if text is None:
                self._stdout_finished = True
            else:
                self._append_output(text)
        return self._stdout_finished

    def _poll_process(self):
        output_finished = self._drain_output()
        if self.process is None:
            return
        exit_code = self.process.poll()
        if exit_code is None or not output_finished:
            self.after(30, self._poll_process)
            return
        self.process = None
        self._stdout_thread = None
        self._process_finished(exit_code)

    def _set_output(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        if text:
            self.output.insert("end", text)
        self.output.configure(state="disabled")

    def _append_output(self, text):
        self.output.configure(state="normal")
        self.output.insert("end", text)
        self.output.see("end")
        self.output.configure(state="disabled")

    def _process_finished(self, exit_code):
        if exit_code == 0:
            self.status.set("Calculation completed.")
        else:
            self.status.set(f"Calculation failed (exit code {exit_code}).")
        self.run_button.configure(state="normal")

    def _is_running(self):
        return self.process is not None and self.process.poll() is None

    def _close(self):
        if self._is_running():
            messagebox.showinfo(
                "Calculation running", "Wait for the calculation to finish before closing.",
                parent=self,
            )
            return
        self.destroy()


def main():
    window = PrototypeWindow()
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
