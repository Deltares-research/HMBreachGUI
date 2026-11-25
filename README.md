# HMBreach GUI

A Windows desktop interface for editing HMBreach cases, running calculations,
and exploring and exporting results. The GUI uses PySide6 and PyQtGraph.

The HMBreach calculation executable is distributed separately and is not
included in this repository. A compatible executable is required to run
calculations; the GUI can also open previously saved results.

## Run from source

From the repository root, using a Python version supported by PySide6:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r GUI\requirements.txt
.\.venv\Scripts\python.exe -m GUI.app
```

On the Run tab, browse to the separately supplied `HMBreach.exe` and select
an output working directory. The sample case loads at startup. The solver
uses the output paths specified in the case and can overwrite existing files,
including outside the working directory when absolute paths are used.

## Build a local Windows package

On Windows, install the packaging requirements in a virtual environment and
provide a separately built, compatible solver executable:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r GUI\requirements-packaging.txt
.\.venv\Scripts\python.exe GUI\package_windows.py --solver C:\path\to\HMBreach.exe
```

The script creates `dist\HMBreachGUI`, containing `HMBreachGUI.exe`, the
solver and their runtime dependencies. It refuses to overwrite an existing
package. The bundled GUI selects the adjacent solver by default. Keep the
package and solver out of the public source repository.

This is a local test package, not a release: dependency license notices and
obligations still need review, and the package must be verified on a clean
Windows machine before distribution.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_gui*.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_pyside_prototype.py -v
```

Solver integration tests are skipped unless a compatible executable is found
at `build\Release\HMBreach.exe` or `HMBREACH_EXECUTABLE` points to one.

## License

The GUI source is licensed under the [MIT License](./LICENSE). Dependencies,
including PySide6, Qt, PyQtGraph and NumPy, have their own licenses. The
separately supplied calculation executable is not covered by this license.
Distributors are responsible for the applicable dependency license obligations.
