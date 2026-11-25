"""Build a local portable Windows package containing the GUI and solver."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", required=True, help="Path to a compatible HMBreach.exe")
    arguments = parser.parse_args()
    if os.name != "nt":
        parser.error("Build the Windows package on Windows.")

    solver = Path(arguments.solver).expanduser().resolve()
    if not solver.is_file() or solver.suffix.lower() != ".exe":
        parser.error("--solver must be an existing Windows executable.")

    destination = ROOT / "dist" / "HMBreachGUI"
    if destination.exists():
        parser.error(f"Package already exists and will not be overwritten: {destination}")

    build_root = ROOT / "build"
    build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="package-", dir=build_root) as temporary:
        staging = Path(temporary)
        command = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--onedir", "--windowed",
            "--contents-directory", ".",
            "--name", "HMBreachGUI",
            "--paths", str(ROOT),
            "--distpath", str(staging / "dist"),
            "--workpath", str(staging / "work"),
            "--specpath", str(staging),
            "--add-binary", f"{solver};.",
            "--add-data", f"{ROOT / 'examples' / 'turbulence_input.json'};examples",
            "--add-data", f"{ROOT / 'LICENSE'};.",
            "--exclude-module", "PySide6.QtCharts",
            str(ROOT / "GUI" / "app.py"),
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        built_package = staging / "dist" / "HMBreachGUI"
        if destination.exists():
            parser.error(f"Package appeared during the build; refusing to overwrite: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(built_package), str(destination))

    print(f"Local test package: {destination}")
    print("Do not distribute until dependency licensing and clean-machine verification are complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
