"""Case and versioned result persistence for the PySide6 GUI."""

import json
import math
import os
import tempfile
import zipfile
from pathlib import Path

from tools.plot_results import read_results


def _object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"Invalid JSON number: {value}")


def read_json(path):
    with Path(path).open("r", encoding="utf-8-sig") as file:
        return json.load(
            file,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_invalid_constant,
        )


def write_json(path, data):
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    destination = Path(path)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n",
            dir=destination.parent, prefix=".hmbreach-", suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            file.write(text)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_case(path):
    case = read_json(path)
    if not isinstance(case, dict):
        raise ValueError("The case must be a JSON object.")
    if not isinstance(case.get("initial_conditions"), dict):
        raise ValueError("initial_conditions must be an object.")
    if not isinstance(case.get("layers"), list):
        raise ValueError("layers must be an array.")
    if any(not isinstance(layer, dict) for layer in case["layers"]):
        raise ValueError("Each layer must be an object.")
    if not isinstance(case.get("settings", {}), dict):
        raise ValueError("settings must be an object.")
    return case


def validate_case(case):
    initial = case["initial_conditions"]
    settings = case.get("settings", {})
    layers = case["layers"]

    def known_keys(container, allowed, label):
        unknown = set(container) - set(allowed)
        if unknown:
            raise ValueError(f"{label} has unsupported fields: {', '.join(sorted(unknown))}.")

    known_keys(case, ("settings", "initial_conditions", "layers"), "Case")
    known_keys(settings, (
        "mode", "calculation_model", "physical_constants", "model_options",
        "workbook_file", "profile_file", "width_model", "width_geometry",
        "width_fit_type", "width_fit_max_iterations", "slope_geometry",
    ), "Settings")
    known_keys(initial, (
        "vz_mm_s", "initial_layer_thickness_m", "initial_froude",
        "initial_concentration_percent", "initial_width_m",
    ), "Initial conditions")
    if settings.get("calculation_model", "steady_profile") != "steady_profile":
        raise ValueError("Only steady-profile calculations are supported in this GUI.")
    if not layers:
        raise ValueError("Add at least one layer.")
    mode = settings.get("mode", "breach")
    if mode not in ("breach", "turbulence"):
        raise ValueError("settings.mode must be breach or turbulence.")
    width_model = settings.get("width_model", "b_constant")
    if width_model not in ("b_constant", "unit_width", "b_fit", "b_calc", "fanning", "geometry"):
        raise ValueError("Unsupported flow-width model.")

    def number(container, key, label, required=True):
        value = container.get(key)
        if value is None and not required:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be a number.")
        try:
            finite = math.isfinite(value)
        except OverflowError as error:
            raise ValueError(f"{label} must be finite.") from error
        if not finite:
            raise ValueError(f"{label} must be finite.")
        return value

    if "workbook_file" in settings and "profile_file" in settings:
        raise ValueError("Set only one workbook output file.")
    for key in ("workbook_file", "profile_file"):
        if key in settings and (not isinstance(settings[key], str) or not settings[key]):
            raise ValueError(f"{key} must be a non-empty path.")
        if key in settings and not settings[key].endswith(".xlsx"):
            raise ValueError(f"{key} must have an .xlsx extension.")
    constants = settings.get("physical_constants", {})
    options = settings.get("model_options", {})
    if not isinstance(constants, dict) or not isinstance(options, dict):
        raise ValueError("Physical constants and model options must be objects.")
    constant_defaults = {
        "g": 9.81236, "rho_w": 1000.0, "rho_s": 2650.0,
        "temperature_c": 15.0, "f0": 0.05, "fki": 0.333, "rk3": 0.0015,
    }
    known_keys(constants, (*constant_defaults, "phi_deg", "erosion_variant",
                           "erosion_a", "erosion_b", "delta_n"), "Physical constants")
    variant = constants.get("erosion_variant", "variant_2")
    if variant not in ("variant_1", "variant_2"):
        raise ValueError("Erosion variant must be variant_1 or variant_2.")
    effective = {
        key: number(constants, key, f"Physical constant {key}") if key in constants else value
        for key, value in constant_defaults.items()
    }
    if effective["g"] <= 0 or effective["rho_w"] <= 0 or effective["rho_s"] <= effective["rho_w"]:
        raise ValueError("Gravity and water density must be positive; sediment density must exceed water density.")
    if effective["temperature_c"] <= -20:
        raise ValueError("Temperature must be greater than -20 degrees C.")
    for key in ("f0", "fki", "rk3", "erosion_a", "erosion_b"):
        if key in constants and number(constants, key, f"Physical constant {key}") < 0:
            raise ValueError(f"Physical constant {key} must be non-negative.")
    if "phi_deg" in constants and not 0 < number(constants, "phi_deg", "Friction angle") < 90:
        raise ValueError("Friction angle must be between 0 and 90 degrees.")
    if "delta_n" in constants and number(constants, "delta_n", "Dilatancy") <= 0:
        raise ValueError("Dilatancy must be positive.")
    option_defaults = {
        "max_angle_iterations": 80, "max_steps": 2000000,
        "alpha_min_deg": 5.0, "alpha_max_deg": 89.9,
        "angle_tolerance_deg": 1.0e-8, "equilibrium_relative_tolerance": 0.01,
        "critical_froude_guard": 1.0e-8, "minimum_ds_factor": 1.0e-8,
        "concentration_margin": 1.0e-10, "adaptive_relative_tolerance": 1.0e-3,
        "adaptive_absolute_tolerance": 1.0e-8,
    }
    known_keys(options, (*option_defaults, "adaptive_step_sizing"), "Model options")
    effective_options = {
        key: number(options, key, f"Model option {key}") if key in options else value
        for key, value in option_defaults.items()
    }
    for key in ("max_angle_iterations", "max_steps"):
        value = effective_options[key]
        if value <= 0 or value != int(value) or value > 2147483647:
            raise ValueError(f"Model option {key} must be a positive integer.")
    if not 0 < effective_options["alpha_min_deg"] < effective_options["alpha_max_deg"] < 90:
        raise ValueError("Angle bounds must satisfy 0 < minimum < maximum < 90 degrees.")
    for key in (
        "angle_tolerance_deg", "equilibrium_relative_tolerance", "critical_froude_guard",
        "minimum_ds_factor", "adaptive_relative_tolerance", "adaptive_absolute_tolerance",
    ):
        if effective_options[key] <= 0:
            raise ValueError(f"Model option {key} must be positive.")
    if not 0 <= effective_options["concentration_margin"] < 1:
        raise ValueError("Concentration margin must be at least 0 and less than 1.")
    if "adaptive_step_sizing" in options and not isinstance(options["adaptive_step_sizing"], bool):
        raise ValueError("Adaptive step sizing must be true or false.")

    for key, label in (
        ("vz_mm_s", "Suction velocity"),
        ("initial_layer_thickness_m", "Initial thickness"),
        ("initial_froude", "Initial Froude number"),
        ("initial_concentration_percent", "Initial concentration"),
    ):
        if number(initial, key, label) <= 0:
            raise ValueError(f"{label} must be positive.")
    if width_model not in ("b_constant", "unit_width"):
        if number(initial, "initial_width_m", "Initial width") <= 0:
            raise ValueError("Initial width must be positive.")
    elif "initial_width_m" in initial:
        raise ValueError("Initial width is not used in B-Constant mode.")

    has_geometry = "slope_geometry" in settings
    for index, layer in enumerate(layers, start=1):
        prefix = f"Layer {index}"
        known_keys(layer, (
            "thickness_m", "d50_micrometre", "porosity_percent", "external_gradient",
            "permeability_mm_s", "user_d15", "d15_micrometre", "initial_alpha_deg",
            "flow_width_m",
        ), prefix)
        if number(layer, "thickness_m", f"{prefix} thickness") <= 0:
            raise ValueError(f"{prefix} thickness must be positive.")
        if number(layer, "d50_micrometre", f"{prefix} d50") <= 0:
            raise ValueError(f"{prefix} d50 must be positive.")
        porosity = number(layer, "porosity_percent", f"{prefix} porosity")
        if not 0 < porosity < 100:
            raise ValueError(f"{prefix} porosity must be between 0 and 100%.")
        number(layer, "external_gradient", f"{prefix} external gradient")
        if not isinstance(layer.get("user_d15", False), bool):
            raise ValueError(f"{prefix} user d15 must be true or false.")
        d15 = number(layer, "d15_micrometre", f"{prefix} d15", required=False)
        if d15 is not None and d15 <= 0:
            raise ValueError(f"{prefix} d15 must be positive.")
        if layer.get("user_d15", False) and d15 is None:
            raise ValueError(f"{prefix} requires d15 when user d15 is enabled.")
        permeability = number(
            layer, "permeability_mm_s", f"{prefix} permeability", required=False
        )
        if permeability is not None and permeability <= 0:
            raise ValueError(f"{prefix} permeability must be positive or blank.")
        angle = number(layer, "initial_alpha_deg", f"{prefix} angle", required=False)
        if angle is not None and not 0 < angle < 90:
            raise ValueError(f"{prefix} angle must be between 0 and 90 degrees.")
        if has_geometry and angle is not None:
            raise ValueError(f"{prefix} angle cannot be combined with slope geometry.")
        if mode == "turbulence" and not has_geometry and angle is None:
            raise ValueError(f"{prefix} requires an angle in turbulence mode.")
        width = number(layer, "flow_width_m", f"{prefix} flow width", required=False)
        if width_model == "b_fit" and (width is None or width <= 0):
            raise ValueError(f"{prefix} requires a positive flow width in B-Fit mode.")
        if width_model != "b_fit" and width is not None:
            raise ValueError(f"{prefix} flow width is only supported in B-Fit mode.")
    if initial["initial_concentration_percent"] >= 100 - layers[0]["porosity_percent"]:
        raise ValueError("Initial concentration must be below 100% minus first-layer porosity.")
    if "width_fit_type" in settings or "width_fit_max_iterations" in settings:
        if width_model != "b_fit":
            raise ValueError("Width-fit settings are only valid in B-Fit mode.")
    if "width_fit_type" in settings and settings["width_fit_type"] not in (
        "straight_line", "poly2", "poly3", "poly4", "exp", "power", "log",
        "rodbard", "gamma_variate",
    ):
        raise ValueError("Unsupported width-fit function.")
    if "width_fit_max_iterations" in settings:
        limit = number(settings, "width_fit_max_iterations", "Width-fit iteration limit")
        if limit <= 0 or limit != int(limit) or limit > 2147483647:
            raise ValueError("Width-fit iteration limit must be a positive integer.")
    width_geometry = settings.get("width_geometry", [])
    if not isinstance(width_geometry, list):
        raise ValueError("Width geometry must be an array.")
    if width_model == "geometry":
        if not width_geometry:
            raise ValueError("Width geometry must contain at least one point.")
        previous_s = 0.0
        for index, point in enumerate(width_geometry, start=1):
            if not isinstance(point, dict):
                raise ValueError(f"Width geometry point {index} must be an object.")
            known_keys(point, ("s_m", "width_m"), f"Width geometry point {index}")
            distance = number(point, "s_m", f"Width geometry point {index} distance")
            width = number(point, "width_m", f"Width geometry point {index} width")
            if distance <= previous_s or width <= 0:
                raise ValueError("Width geometry needs increasing positive distances and widths.")
            previous_s = distance
    elif width_geometry:
        raise ValueError("Width geometry points are only valid in geometry width mode.")

    if has_geometry:
        geometry = settings["slope_geometry"]
        if not isinstance(geometry, list) or len(geometry) < 2:
            raise ValueError("Slope geometry must contain at least two points.")
        points = []
        for index, point in enumerate(geometry, start=1):
            if not isinstance(point, dict):
                raise ValueError(f"Slope geometry point {index} must be an object.")
            known_keys(point, ("x_m", "y_m"), f"Slope geometry point {index}")
            points.append((
                number(point, "x_m", f"Slope geometry point {index} x"),
                number(point, "y_m", f"Slope geometry point {index} y"),
            ))
        total_depth = sum(layer["thickness_m"] for layer in layers)
        if not math.isfinite(total_depth):
            raise ValueError("Total layer thickness must be finite.")
        for previous, current in zip(points, points[1:]):
            if current[0] <= previous[0] or current[1] > previous[1]:
                raise ValueError("Slope geometry must have increasing X and non-increasing Y.")
            if not math.isfinite(current[0] - previous[0]):
                raise ValueError("Slope geometry horizontal distances must be finite.")
            if (current[1] >= previous[1] and current[1] < 0 and
                    previous[1] > -total_depth):
                raise ValueError("Slope geometry segments within the layers must descend.")
        if points[0][1] < 0 and points[1][1] >= points[0][1]:
            raise ValueError("Slope geometry must descend below y=0.")
        if points[-1][1] > -total_depth:
            raise ValueError("Slope geometry must cover the total layer thickness.")


def results_from_workbook(path, case):
    with zipfile.ZipFile(path) as workbook:
        profiles = read_results(workbook)
    return {
        "format": "hmbreach-results",
        "version": 1,
        "input": case,
        "profiles": [
            {"layer": layer, "points": points}
            for layer, points in profiles.items()
        ],
    }


def validate_results(results):
    if not isinstance(results, dict) or results.get("format") != "hmbreach-results":
        raise ValueError("Not an HMBreach results JSON file.")
    if type(results.get("version")) is not int or results["version"] != 1:
        raise ValueError("Unsupported HMBreach results JSON version.")
    if not isinstance(results.get("input"), dict):
        raise ValueError("Results must include the input case.")
    profiles = results.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("Results must contain at least one profile.")
    layers = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("Each result profile must be an object.")
        layer = profile.get("layer")
        points = profile.get("points")
        if type(layer) is not int or layer <= 0 or layer in layers:
            raise ValueError("Result profiles must have unique positive layer numbers.")
        layers.add(layer)
        if not isinstance(points, list) or not points:
            raise ValueError(f"Result layer {layer} has no points.")
        for point in points:
            if not isinstance(point, dict) or not all(
                name in point for name in ("x", "z", "h", "u", "c")
            ):
                raise ValueError(f"Result layer {layer} has an incomplete point.")
            try:
                invalid = any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in point.values()
                )
            except OverflowError as error:
                raise ValueError(f"Result layer {layer} contains a non-finite numeric value.") from error
            if invalid:
                raise ValueError(f"Result layer {layer} contains a non-finite numeric value.")
    return results
