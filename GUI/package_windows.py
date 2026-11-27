"""Build a local portable Windows package containing the GUI and solver."""

import argparse
from importlib.metadata import distribution
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tkinter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DISTRIBUTIONS = (
    "matplotlib", "numpy", "pillow", "packaging", "python-dateutil", "pyparsing",
    "cycler", "kiwisolver", "contourpy", "fonttools", "tzdata", "pyinstaller",
    "markdown-it-py", "mdurl", "mdit-py-plugins", "latex2mathml",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", required=True, help="Path to a compatible HMBreach.exe")
    parser.add_argument(
        "--scientific-readme", required=True,
        help="Path to the scientific README for the supplied solver",
    )
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
    scientific_readme = Path(arguments.scientific_readme).expanduser().resolve()
    if not scientific_readme.is_file():
        parser.error("--scientific-readme must be an existing file.")
    diagram = scientific_readme.parent / "examples" / "initial_conditions_geometry.svg"
    if not diagram.is_file():
        parser.error(f"Scientific README diagram is missing: {diagram}")
    logo = ROOT / "Deltares_logo_Wit_RGB.png"
    if not logo.is_file():
        parser.error(f"Deltares logo is missing: {logo}")

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
        bundled_readme = staging / "SCIENTIFICREADME.md"
        shutil.copy2(scientific_readme, bundled_readme)
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
            "--add-data", f"{ROOT / 'examples' / 'default_input.json'};examples",
            "--add-data", f"{ROOT / 'examples' / 'turbulence_input.json'};examples",
            "--add-data", f"{diagram};examples",
            "--add-data", f"{ROOT / 'examples' / 'coordinate_geometry_input.json'};examples",
            "--add-data", f"{bundled_readme};.",
            "--add-data", f"{logo};.",
            "--add-data", f"{ROOT / 'LICENSE'};.",
            "--add-data", f"{license_root};licenses",
            "--collect-data", "latex2mathml",
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
        if not copied and package == "latex2mathml" and installed.version == "3.81.1":
            # The 3.81.1 wheel omits the upstream license file.
            target = license_root / package / "LICENSE"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "GUI" / "licenses" / "latex2mathml-LICENSE", target)
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
    _write_license_inventory(license_root, tcl_root)
    return license_root


def _write_license_inventory(license_root, tcl_root):
    rows = []
    for package in RUNTIME_DISTRIBUTIONS:
        installed = distribution(package)
        license_name = _license_declaration(installed.metadata)
        role = "Build-time" if package == "pyinstaller" else "Runtime"
        rows.append((package, installed.version, license_name, role, f"{package}/"))

    rows.extend([
        (
            "Python",
            sys.version.split()[0],
            "Python Software Foundation License",
            "Runtime",
            "Python/LICENSE.txt",
        ),
        (
            "Tcl",
            tkinter.Tcl().eval("info patchlevel"),
            "Tcl/Tk License",
            "Runtime",
            "Tcl-Tk/",
        ),
        (
            "Tk",
            _tk_version(tcl_root),
            "Tcl/Tk License",
            "Runtime",
            "Tcl-Tk/",
        ),
    ])

    lines = [
        "# Third-party license inventory",
        "",
        "Generated from the Python environment configured for",
        "`GUI/package_windows.py`.",
        "Package license names come from installed metadata; Python and Tcl/Tk",
        "license names identify their included license terms. Consult the",
        "included files for full texts, bundled-component notices, and",
        "exceptions. The separately supplied HMBreach solver is not included.",
        "This inventory does not enumerate every bundled native library;",
        "their versions, licenses, and notices require separate review.",
        "",
        "| Component | Version | Declared license | Role | Included license files |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {name} | {version} | {license_name} | {role} | `{files}` |"
        for name, version, license_name, role, files in rows
    )
    (license_root / "THIRD_PARTY_LICENSES.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _tk_version(tcl_root):
    for package_index in sorted(tcl_root.glob("tk*/pkgIndex.tcl")):
        match = re.search(
            r"^\s*package ifneeded Tk\s+([0-9.]+)",
            package_index.read_text(encoding="utf-8", errors="replace"),
            re.MULTILINE,
        )
        if match:
            return match.group(1)
    raise RuntimeError(f"Unable to determine the Tk version under {tcl_root}.")


def _license_declaration(metadata):
    expression = metadata.get("License-Expression")
    if expression:
        return expression

    license_text = metadata.get("License", "").strip()
    first_line = next(
        (
            line.strip()
            for line in license_text.splitlines()
            if line.strip() and set(line.strip()) != {"="}
        ),
        "",
    )
    if first_line.lower().startswith("license agreement") or (
        first_line.lower().startswith("gpl") and "exception" in first_line.lower()
    ):
        return first_line

    classifiers = [
        classifier.rsplit(" :: ", 1)[-1]
        for classifier in metadata.get_all("Classifier", [])
        if classifier.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(classifiers)
    if first_line:
        return first_line
    raise RuntimeError(f"No license declaration found for {metadata.get('Name', 'unknown package')}.")


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
