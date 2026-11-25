import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from GUI.prototype import PrototypeWindow, ROOT, default_executable


EXECUTABLE = Path(os.environ.get(
    "HMBREACH_EXECUTABLE", str(ROOT / "build" / "Release" / "HMBreach.exe")
)).resolve()


class ExecutableLocationTests(unittest.TestCase):
    def test_packaged_solver_is_next_to_gui_executable(self):
        executable = ROOT / "some-package" / "HMBreachGUI.exe"
        with patch("sys.frozen", True, create=True), patch("sys.executable", str(executable)):
            self.assertEqual(default_executable(), executable.resolve().with_name("HMBreach.exe"))

    def test_source_default_remains_in_build_release(self):
        with patch("sys.frozen", False, create=True):
            self.assertEqual(default_executable(), ROOT / "build" / "Release" / "HMBreach.exe")


@unittest.skipUnless(EXECUTABLE.is_file(), "Build HMBreach or set HMBREACH_EXECUTABLE")
class PySidePrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = PrototypeWindow()
        self.window.executable.setText(str(EXECUTABLE))
        self.window.show()

    def tearDown(self):
        self.window.close()

    def run_process(self):
        loop = QEventLoop()
        timed_out = []
        heartbeat = []
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: (timed_out.append(True), loop.quit()))
        self.window.process.finished.connect(loop.quit)
        self.window.run_calculation()
        QTimer.singleShot(
            0,
            lambda: heartbeat.append(self.window.status.text()),
        )
        timer.start(30000)
        loop.exec()
        timer.stop()
        if timed_out:
            self.window.process.kill()
            self.window.process.waitForFinished(5000)
        self.assertFalse(timed_out, "The calculation did not finish in 30 seconds.")
        return heartbeat

    def test_sample_calculation_and_responsive_event_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(self.window.input_file.text())
            original_input = input_path.read_bytes()
            self.window.output_directory.setText(directory)
            heartbeat = self.run_process()
            self.assertEqual(heartbeat, ["Calculation running..."])
            self.assertEqual(self.window.status.text(), "Calculation completed.")
            self.assertTrue(self.window.run_button.isEnabled())
            self.assertIn("Calculation completed.", self.window.output.toPlainText())
            self.assertTrue((Path(directory) / "hmbres_turbulence_results.xlsx").is_file())
            self.assertTrue(
                (Path(directory) / "hmbres_turbulence_results_initial_geometry.svg").is_file()
            )
            self.assertEqual(input_path.read_bytes(), original_input)

    def test_solver_error_is_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.json"
            invalid.write_text("{", encoding="utf-8")
            self.window.input_file.setText(str(invalid))
            self.window.output_directory.setText(directory)
            self.run_process()
            self.assertIn("Calculation failed", self.window.status.text())
            self.assertIn("HMBRES ERROR:", self.window.output.toPlainText())
            self.assertTrue(self.window.run_button.isEnabled())

    def test_invalid_executable_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / "invalid.exe"
            invalid.write_text("not an executable", encoding="utf-8")
            self.window.executable.setText(str(invalid))
            self.window.output_directory.setText(directory)
            loop = QEventLoop()
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            self.window.process.errorOccurred.connect(loop.quit)
            self.window.run_calculation()
            if self.window.status.text() == "Calculation running...":
                timer.start(5000)
                loop.exec()
                timer.stop()
            self.assertEqual(self.window.status.text(), "Failed to start calculation.")
            self.assertIn("Process error:", self.window.output.toPlainText())
            self.assertTrue(self.window.run_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
