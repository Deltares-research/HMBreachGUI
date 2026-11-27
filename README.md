# HMBreach GUI

A Windows desktop interface for editing HMBreach cases, running calculations,
and exploring and exporting results. The GUI uses Tkinter/ttk and Matplotlib.

The HMBreach calculation executable is distributed separately and is not
included in this repository. A compatible executable is required to run
calculations; the GUI can also open previously saved results.

## Run from source

From the repository root, using a Windows Python installation that includes
Tk/Tcl:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r GUI\requirements.txt
.\.venv\Scripts\python.exe -m GUI.app
```

On the Run tab, browse to the separately supplied `HMBreach.exe` and select
an output working directory. The GUI remembers the last existing working
directory in the user's application settings. The sample case loads at startup. The solver
uses the output paths specified in the case and can overwrite existing files,
including outside the working directory when absolute paths are used.

The Help tab opens a user-selected scientific README as Markdown source. Select
the documentation corresponding to your solver executable; their versions are
not checked by the GUI. The Input tab's gradient is the dimensionless external
hydraulic gradient for each layer.

## Build a local Windows package

On Windows, install the packaging requirements in a virtual environment and
provide a separately built, compatible solver executable:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r GUI\requirements-packaging.txt
.\.venv\Scripts\python.exe GUI\package_windows.py `
  --solver C:\path\to\HMBreach.exe `
  --output dist\HMBreachGUI-no-qt
```

The output directory defaults to `dist\HMBreachGUI`; `--output` lets you
choose another directory without overwriting an existing package. The package
contains `HMBreachGUI.exe`, the solver and their runtime dependencies. The
build checks that no Qt or PyQtGraph artifacts were bundled and collects
third-party license files and a versioned inventory under `licenses\`. The GUI
selects the adjacent solver by default. Keep the package and solver out of the
public source repository.

This is a local test package, not a release: dependency license notices and
obligations still need review, and the package must be verified on a clean
Windows machine before distribution. The inventory does not enumerate all
bundled native libraries or the separately supplied solver.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Solver integration tests are skipped unless `HMBREACH_EXECUTABLE` points to a
compatible executable or it is available at `build\Release\HMBreach.exe`.

## License

The GUI source is licensed under the [MIT License](./LICENSE). Dependencies,
including Matplotlib, NumPy, Pillow and Tcl/Tk, have their own licenses. The
separately supplied calculation executable is not covered by this license.
Distributors are responsible for the applicable dependency license obligations.
