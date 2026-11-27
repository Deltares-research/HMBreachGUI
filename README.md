# HMBreach GUI

A Windows desktop interface for editing HMBreach cases, running calculations,
and exploring and exporting results. The GUI uses Tkinter/ttk and Matplotlib.

The HMBreach calculation executable is distributed separately and is not
included in this repository. A compatible executable is required to run
calculations; the GUI can also open previously saved results.
The header identifies this as a development build based on GUI version
`0.1.0`; it does not identify the solver version.

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
directory in the user's application settings. A five-layer example loads at
startup; the previous turbulence example remains available under `examples`.
The Input table has space for ten layers, and its actions stay visible below the
scrollable editor. The startup window retains 3:2 proportions and fits the
screen; on smaller screens, scroll the editor to reach the table. The solver
uses the output paths specified in the case and can overwrite existing files,
including outside the working directory when absolute paths are used.
If a calculation fails, review the Run tab output, edit the model, and run it
again. Previously loaded results are retained after a failed calculation.

The Help tab opens the bundled scientific README as a formatted offline page
in the default browser. A modern browser with
MathML support is required for equations; links to solver source files may not
be present in the package. When running from source, place a
`SCIENTIFICREADME.md` in the repository root.
Choose documentation corresponding to your solver executable; their versions
are not checked by the GUI. The Input tab's gradient is the dimensionless
external hydraulic gradient for each layer.

Click an editable table cell once to replace its value. Press Enter to finish
editing or Escape to cancel. Layer angles are near the start of the Input table.
To edit angles, turn off **Use coordinate slope geometry** on the Geometry tab;
coordinate geometry and layer angles cannot be used together. In turbulence
mode, each layer requires an angle when coordinate geometry is off.

On the Geometry tab, the original slope remains visible as a dashed grey
reference while drawing. **Update input layers from slope** splits the layers
at slope bends and material boundaries, extends the bottom material if needed,
and truncates layers below the drawn slope. The calculated angles are shown
in the Input table. With coordinate geometry enabled, only the coordinates
are saved for the solver; angles are reconstructed for display on reopening.
Changing the slope or layers clears these reference angles until the layers
are updated again. The supplied solver rejects slope angles above 45 degrees.

## Build a local Windows package

On Windows, install the packaging requirements in a virtual environment and
provide a separately built, compatible solver executable:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r GUI\requirements-packaging.txt
.\.venv\Scripts\python.exe GUI\package_windows.py `
  --solver C:\path\to\HMBreach.exe `
  --scientific-readme C:\path\to\SCIENTIFICREADME.md `
  --output dist\HMBreachGUI-no-qt
```

The output directory defaults to `dist\HMBreachGUI`; `--output` lets you
choose another directory without overwriting an existing package. The package
contains `HMBreachGUI.exe`, the solver and their runtime dependencies. The
specified scientific README is bundled for the Help tab's browser viewer.
The Deltares logo file in the repository root is included in the package.
The selected scientific README must have its `examples\initial_conditions_geometry.svg`
diagram alongside it at that relative path.
The build checks that no Qt or PyQtGraph artifacts were bundled and collects
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
