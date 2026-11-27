import unittest
from pathlib import Path
from unittest.mock import patch

from GUI.prototype import PrototypeWindow, ROOT, default_executable


class ExecutableLocationTests(unittest.TestCase):
    def test_packaged_solver_is_next_to_gui_executable(self):
        executable = ROOT / "some-package" / "HMBreachGUI.exe"
        with patch("sys.frozen", True, create=True), patch("sys.executable", str(executable)):
            self.assertEqual(default_executable(), executable.resolve().with_name("HMBreach.exe"))

    def test_source_default_remains_in_build_release(self):
        with patch("sys.frozen", False, create=True):
            self.assertEqual(default_executable(), ROOT / "build" / "Release" / "HMBreach.exe")

    def test_run_page_has_editable_path_fields(self):
        window = PrototypeWindow()
        try:
            window.withdraw()
            self.assertEqual(window.input_entry.get(), str(ROOT / "examples" / "default_input.json"))
            self.assertEqual(str(window.input_entry.cget("state")), "normal")
        finally:
            window.destroy()


if __name__ == "__main__":
    unittest.main()
