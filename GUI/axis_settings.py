"""Automatic and user-configured chart axis ranges and tick spacing."""

import math
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext

import tkinter as tk
from tkinter import messagebox, ttk


AXES = (("horizontal", "Horizontal"), ("left", "Left vertical"), ("right", "Right vertical"))
MAX_TICKS = 200


def automatic_range(values):
    if not values:
        return 0.0, 1.0
    low, high = min(values), max(values)
    if low == high:
        margin = (abs(low) * 0.05 or math.ulp(low)) if low else 0.1
    else:
        margin = high / 20 - low / 20
    lower, upper = low - margin, high + margin
    if not math.isfinite(lower):
        lower = low
    if not math.isfinite(upper):
        upper = high
    if not math.isfinite(upper - lower) or lower == upper:
        raise ValueError("Selected values are too large to display on a chart.")
    return lower, upper


def _nice_interval(span):
    target = span / 5
    if not math.isfinite(target) or target <= 0:
        raise ValueError("The axis range is too small to calculate tick spacing.")
    exponent = math.floor(math.log10(target))
    for multiplier in (1, 2, 5, 10):
        interval = float(f"{multiplier}e{exponent}")
        if math.isfinite(interval) and (interval >= target or math.isclose(interval, target, rel_tol=1e-12)):
            return interval
    raise ValueError("The axis range is too large to calculate tick spacing.")


def _label_format(lower, upper, interval):
    decimals = max(0, -Decimal(str(interval)).normalize().as_tuple().exponent)
    magnitude = max(abs(lower), abs(upper))
    if magnitude < 1e9 and decimals <= 8:
        return f"%.{decimals}f"
    digits = math.ceil(math.log10(magnitude) - math.log10(interval)) + 2 if magnitude else 6
    return f"%.{min(17, max(6, digits))}g"


def axis_ticks(lower, upper, interval, label_format):
    with localcontext() as context:
        context.prec = 50
        step = Decimal(str(interval))
        first = int((Decimal(str(lower)) / step).to_integral_value(rounding=ROUND_CEILING))
        last = int((Decimal(str(upper)) / step).to_integral_value(rounding=ROUND_FLOOR))
        count = last - first + 1
        if count < 1 or count > MAX_TICKS:
            raise ValueError(f"Tick interval must produce between 1 and {MAX_TICKS} major ticks.")
        ticks = []
        labels = set()
        for index in range(first, last + 1):
            value = 0.0 if index == 0 else float(index * step)
            label = label_format % value
            if label in labels or (value != 0 and float(label) == 0):
                raise ValueError(
                    "Tick labels cannot be distinguished at this precision. "
                    "Choose more decimal places, automatic formatting, or a larger tick interval."
                )
            if ticks and value <= ticks[-1][1]:
                raise ValueError("Axis ticks are too close to display distinctly.")
            labels.add(label)
            ticks.append((label, value))
        return ticks


def axis_parameters(values, settings):
    lower, upper, interval, decimals = settings
    if decimals is not None and decimals not in (1, 2, 3):
        raise ValueError("Decimal places must be automatic, 1, 2, or 3.")
    if interval is not None and (not math.isfinite(interval) or interval <= 0):
        raise ValueError("Tick interval must be a positive finite number.")
    if not values and lower is None and upper is None:
        interval = None
    if lower is None and upper is None:
        lower, upper = automatic_range(values)
    elif lower is None or upper is None:
        raise ValueError("Enter both minimum and maximum, or leave both blank for automatic limits.")
    if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
        raise ValueError("Minimum and maximum must be finite, with minimum less than maximum.")
    span = upper - lower
    if not math.isfinite(span) or span <= 0:
        raise ValueError("The axis range is too large or too small.")
    if interval is None:
        interval = _nice_interval(span)
    if interval < math.ulp(max(abs(lower), abs(upper))):
        raise ValueError("Tick interval is too small for the selected axis limits.")
    lower_tick, upper_tick = lower / interval, upper / interval
    if not math.isfinite(lower_tick) or not math.isfinite(upper_tick):
        raise ValueError("Tick interval is too small for the selected axis limits.")
    label_format = _label_format(lower, upper, interval) if decimals is None else f"%.{decimals}f"
    axis_ticks(lower, upper, interval, label_format)
    return lower, upper, interval, label_format


class AxisSettingsDialog(tk.Toplevel):
    def __init__(self, mode, settings, validate, parent=None):
        super().__init__(parent)
        self.title("Axis settings")
        if parent is not None:
            self.transient(parent)
        self.grab_set()
        self._validate = validate
        self.settings = None
        description = ttk.Label(
            self,
            text=(
                f"{'Profile chart' if mode == 'profile' else 'Flow top view'}: "
                "leave fields blank for automatic values. Enter both limits together."
            ),
        )
        description.grid(row=0, column=0, columnspan=5, sticky="w", padx=8, pady=8)
        for column, title in enumerate(("Axis", "Minimum", "Maximum", "Major tick interval", "Decimal places")):
            ttk.Label(self, text=title).grid(row=1, column=column, sticky="w", padx=4)
        self.fields = {}
        self.decimals = {}
        for row, (key, title) in enumerate(AXES, start=1):
            ttk.Label(self, text=title).grid(row=row + 1, column=0, sticky="w", padx=4, pady=3)
            self.fields[key] = []
            for column, value in enumerate(settings[key][:3], start=1):
                variable = tk.StringVar(value="" if value is None else str(value))
                field = ttk.Entry(self, textvariable=variable, width=18)
                field.grid(row=row + 1, column=column, sticky="ew", padx=4, pady=3)
                if mode == "top" and key == "right":
                    field.state(["disabled"])
                self.fields[key].append(variable)
            precision = tk.StringVar(
                value="Automatic" if settings[key][3] is None else str(settings[key][3])
            )
            combo = ttk.Combobox(
                self, textvariable=precision, values=("Automatic", "1", "2", "3"),
                state="readonly", width=12,
            )
            if mode == "top" and key == "right":
                combo.state(["disabled"])
            self.decimals[key] = precision
            combo.grid(row=row + 1, column=4, sticky="ew", padx=4, pady=3)
        note = ttk.Label(
            self, text="Ticks are anchored at zero. Settings apply to this plot type for this session."
        )
        note.grid(row=5, column=0, columnspan=5, sticky="w", padx=8, pady=8)
        buttons = ttk.Frame(self)
        buttons.grid(row=6, column=0, columnspan=5, sticky="e", padx=8, pady=8)
        ttk.Button(buttons, text="Reset to automatic", command=self._reset).pack(side="left", padx=4)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        ttk.Button(buttons, text="OK", command=self.accept).pack(side="left", padx=4)
        for column in range(1, 5):
            self.columnconfigure(column, weight=1)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _reset(self):
        for fields in self.fields.values():
            for field in fields:
                field.set("")
        for precision in self.decimals.values():
            precision.set("Automatic")

    def accept(self):
        settings = {}
        try:
            for key, title in AXES:
                values = []
                for field in self.fields[key]:
                    text = field.get().strip()
                    if not text:
                        values.append(None)
                        continue
                    try:
                        value = float(text)
                    except ValueError as error:
                        raise ValueError(f"{title}: enter a number or leave the field blank.") from error
                    if not math.isfinite(value):
                        raise ValueError(f"{title}: values must be finite.")
                    values.append(value)
                precision = self.decimals[key].get()
                settings[key] = (*values, None if precision == "Automatic" else int(precision))
            self._validate(settings)
        except ValueError as error:
            messagebox.showwarning("Invalid axis settings", str(error), parent=self)
            return
        self.settings = settings
        self.destroy()
