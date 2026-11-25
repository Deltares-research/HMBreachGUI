"""Build a local portable Windows package containing the GUI and solver."""

import argparse
from importlib.metadata import distribution
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DISTRIBUTIONS = (
    "matplotlib", "numpy", "pillow", "packaging", "python-dateutil", "pyparsing",
    "cycler", "kiwisolver", "contourpy", "fonttools", "tzdata", "pyinstaller",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", required=True, help="Path to a compatible HMBreach.exe")
    parser.add_argument(
        "--output", default=str(ROOT / "dist" / "HMBreachGUI"),
        help="Output package directory (default: dist/HMBreachGUI)",
    )
    arguments = parser.parse_args()
    if os.name != "nt":
        parser.error("Build the Windows package on Windows.")

    solver = Path(arguments.solver).expanduser().resolve()
    if not solver.is_file() or solver.suffix.lower() != ".exe":
        parser.error("--solver must be an existing Windows executable.")

    destination = Path(arguments.output).expanduser()
    if not destination.is_absolute():
        destination = ROOT / destination
    destination = destination.resolve()
    if destination.exists():
        parser.error(f"Package already exists and will not be overwritten: {destination}")

    build_root = ROOT / "build"
    build_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="package-", dir=build_root) as temporary:
        staging = Path(temporary)
        license_root = _stage_licenses(staging)
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
            "--add-data", f"{license_root};licenses",
            "--exclude-module", "PySide6",
            "--exclude-module", "PySide2",
            "--exclude-module", "PyQt5",
            "--exclude-module", "PyQt6",
            "--exclude-module", "pyqtgraph",
            "--exclude-module", "matplotlib.backends.backend_qt",
            "--exclude-module", "matplotlib.backends.backend_qt5",
            "--exclude-module", "matplotlib.backends.backend_qt5agg",
            "--exclude-module", "matplotlib.backends.backend_qt5cairo",
            "--exclude-module", "matplotlib.backends.backend_qtagg",
            "--exclude-module", "matplotlib.backends.backend_qtcairo",
            "--exclude-module", "matplotlib.backends.qt_compat",
            str(ROOT / "GUI" / "app.py"),
        ]
        subprocess.run(command, cwd=ROOT, check=True)
        built_package = staging / "dist" / "HMBreachGUI"
        _verify_no_qt(built_package)
        if destination.exists():
            parser.error(f"Package appeared during the build; refusing to overwrite: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(built_package), str(destination))

    print(f"Local test package: {destination}")
    print("Do not distribute until dependency licensing and clean-machine verification are complete.")
    return 0


def _stage_licenses(staging):
    license_root = staging / "licenses"
    for package in RUNTIME_DISTRIBUTIONS:
        installed = distribution(package)
        copied = 0
        for relative_path in installed.files or ():
            name = Path(str(relative_path)).name
            if not re.match(r"^(license|copying|notice)", name, re.IGNORECASE):
                continue
            source = installed.locate_file(relative_path)
            if not source.is_file():
                continue
            target = license_root / package / Path(str(relative_path))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
        if not copied:
            raise RuntimeError(f"No license files found for runtime dependency {package}.")

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError(f"Python license file is missing: {python_license}")
    python_target = license_root / "Python" / python_license.name
    python_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(python_license, python_target)

    tcl_root = Path(sys.base_prefix) / "tcl"
    tcl_licenses = [
        path for path in tcl_root.rglob("*")
        if path.is_file() and path.name.lower() == "license.terms"
    ]
    if not tcl_licenses:
        raise RuntimeError(f"No Tcl/Tk license terms found under {tcl_root}.")
    for source in tcl_licenses:
        relative = source.relative_to(tcl_root)
        target = license_root / "Tcl-Tk" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return license_root


def _verify_no_qt(package):
    forbidden_directories = {"pyside6", "pyside2", "pyqt5", "pyqt6", "pyqtgraph"}
    for path in package.rglob("*"):
        if any(part.lower() in forbidden_directories for part in path.parts):
            raise RuntimeError(f"Unexpected Qt-dependent package artifact: {path}")
        if path.suffix.lower() == ".dll" and path.name.lower().startswith(("qt", "libqt")):
            raise RuntimeError(f"Unexpected Qt runtime library: {path}")
    archive = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller.utils.cliutils.archive_viewer",
            "-l", str(package / "HMBreachGUI.exe"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.lower()
    forbidden_modules = (
        "pyside6", "pyside2", "pyqt5", "pyqt6", "pyqtgraph",
        "backend_qt", "qt_compat", "qt6core.dll", "qt6gui.dll", "qt6widgets.dll",
    )
    for module in forbidden_modules:
        if module in archive:
            raise RuntimeError(f"Unexpected Qt-dependent executable module: {module}")


if __name__ == "__main__":
    raise SystemExit(main())
