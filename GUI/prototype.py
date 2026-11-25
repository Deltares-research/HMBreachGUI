"""Feasibility prototype: run the existing HMBreach CLI from a Qt window."""

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment
from PySide6.QtGui import QCloseEvent, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


ROOT = Path(__file__).resolve().parents[1]


def default_executable():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().with_name("HMBreach.exe")
    return ROOT / "build" / "Release" / "HMBreach.exe"


class PrototypeWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HMBreach - PySide6 feasibility prototype")
        self.resize(900, 600)

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._process_finished)

        self.executable = QLineEdit(str(default_executable()))
        self.input_file = QLineEdit(str(ROOT / "examples" / "turbulence_input.json"))
        self.output_directory = QLineEdit()
        self.run_button = QPushButton("Run calculation")
        self.run_button.clicked.connect(self.run_calculation)
        self.status = QLabel("Select an output working directory to begin.")
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)

        form = QFormLayout()
        form.addRow("HMBreach executable", self._path_row(self.executable, self._choose_executable))
        form.addRow("Input JSON", self._path_row(self.input_file, self._choose_input))
        form.addRow("Working directory", self._path_row(self.output_directory, self._choose_directory))
        warning = QLabel(
            "The solver writes output files using paths from the JSON. "
            "Existing files at those paths may be overwritten; absolute paths "
            "are not restricted to the working directory."
        )
        warning.setWordWrap(True)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addLayout(form)
        layout.addWidget(warning)
        layout.addWidget(self.run_button)
        layout.addWidget(self.status)
        layout.addWidget(self.output)
        self.setCentralWidget(page)

    def _path_row(self, field, callback):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field)
        button = QPushButton("Browse...")
        button.clicked.connect(callback)
        layout.addWidget(button)
        return row

    def _choose_executable(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select HMBreach executable", "", "Executable files (*.exe);;All files (*)"
        )
        if filename:
            self.executable.setText(filename)

    def _choose_input(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select input JSON", "", "JSON files (*.json);;All files (*)"
        )
        if filename:
            self.input_file.setText(filename)

    def _choose_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select working directory")
        if directory:
            self.output_directory.setText(directory)

    def run_calculation(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        executable_text = self.executable.text().strip()
        input_text = self.input_file.text().strip()
        directory_text = self.output_directory.text().strip()
        if not executable_text or not Path(executable_text).is_file():
            self.status.setText("Select an existing HMBreach executable.")
            return
        if not input_text or not Path(input_text).is_file():
            self.status.setText("Select an existing input JSON file.")
            return
        if not directory_text or not Path(directory_text).is_dir():
            self.status.setText("Select an existing working directory.")
            return

        self.output.clear()
        self.status.setText("Calculation running...")
        self.run_button.setEnabled(False)
        self.process.setProcessEnvironment(QProcessEnvironment.systemEnvironment())
        self.process.setWorkingDirectory(str(Path(directory_text).resolve()))
        self.process.start(
            str(Path(executable_text).resolve()),
            ["--input", str(Path(input_text).resolve())],
        )

    def _append_output(self, data):
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.insertPlainText(bytes(data).decode("utf-8", errors="replace"))
        self.output.moveCursor(QTextCursor.MoveOperation.End)

    def _read_stdout(self):
        self._append_output(self.process.readAllStandardOutput())

    def _read_stderr(self):
        self._append_output(self.process.readAllStandardError())

    def _process_error(self, error):
        self._append_output(f"\nProcess error: {self.process.errorString()}\n".encode())
        if error == QProcess.ProcessError.FailedToStart:
            self.status.setText("Failed to start calculation.")
            self.run_button.setEnabled(True)

    def _process_finished(self, exit_code, exit_status):
        self._read_stdout()
        self._read_stderr()
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            self.status.setText("Calculation completed.")
        else:
            self.status.setText(f"Calculation failed (exit code {exit_code}).")
        self.run_button.setEnabled(True)

    def closeEvent(self, event: QCloseEvent):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.information(
                self, "Calculation running", "Wait for the calculation to finish before closing."
            )
            event.ignore()
            return
        event.accept()


def main():
    application = QApplication(sys.argv)
    window = PrototypeWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
