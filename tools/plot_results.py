#!/usr/bin/env python3
"""Plot HMBreach results against horizontal coordinate X as an SVG."""

import argparse
import math
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"main": MAIN_NS, "rel": PKG_REL_NS}
CELL_REFERENCE = re.compile(r"([A-Z]+)")
COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9")


def read_xml(archive, name):
    try:
        return ElementTree.fromstring(archive.read(name))
    except KeyError as error:
        raise ValueError(f"Workbook is missing {name}") from error
    except ElementTree.ParseError as error:
        raise ValueError(f"Workbook contains invalid XML in {name}: {error}") from error


def worksheet_path(archive, sheet_name):
    workbook = read_xml(archive, "xl/workbook.xml")
    relationships = read_xml(archive, "xl/_rels/workbook.xml.rels")
    targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall("rel:Relationship", NS)
    }

    for sheet in workbook.findall("main:sheets/main:sheet", NS):
        if sheet.attrib.get("name") != sheet_name:
            continue
        relationship_id = sheet.attrib.get(f"{{{DOC_REL_NS}}}id")
        if relationship_id not in targets:
            raise ValueError(f"Workbook has no relationship for sheet {sheet_name!r}")
        target = targets[relationship_id].replace("\\", "/")
        if target.startswith("/"):
            return target.lstrip("/")
        return str(PurePosixPath("xl") / target)

    raise ValueError(f"Workbook does not contain a {sheet_name!r} sheet")


def read_shared_strings(archive):
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    except ElementTree.ParseError as error:
        raise ValueError(f"Workbook contains invalid shared strings: {error}") from error

    return [
        "".join(text.text or "" for text in item.iter(f"{{{MAIN_NS}}}t"))
        for item in root.findall("main:si", NS)
    ]


def cell_value(cell, shared_strings):
    cell_type = cell.attrib.get("t")
    value = cell.find("main:v", NS)

    if cell_type == "inlineStr":
        inline = cell.find("main:is", NS)
        return "" if inline is None else "".join(
            text.text or "" for text in inline.iter(f"{{{MAIN_NS}}}t")
        )
    if value is None:
        return ""
    if cell_type == "s":
        try:
            return shared_strings[int(value.text)]
        except (ValueError, IndexError, TypeError) as error:
            raise ValueError("Workbook contains an invalid shared-string index") from error
    if cell_type in ("str", "e"):
        return value.text or ""

    try:
        result = float(value.text)
    except (ValueError, TypeError) as error:
        raise ValueError(f"Workbook contains a non-numeric result: {value.text!r}") from error
    if not math.isfinite(result):
        raise ValueError("Workbook contains a non-finite numeric result")
    return result


def read_results(archive):
    shared_strings = read_shared_strings(archive)
    path = worksheet_path(archive, "Results")
    root = read_xml(archive, path)
    sheet_data = root.find("main:sheetData", NS)
    if sheet_data is None:
        raise ValueError("The Results sheet is empty")

    rows = []
    for row in sheet_data.findall("main:row", NS):
        values = {}
        for cell in row.findall("main:c", NS):
            reference = CELL_REFERENCE.match(cell.attrib.get("r", ""))
            if reference is None:
                continue
            values[reference.group(1)] = cell_value(cell, shared_strings)
        rows.append(values)

    if not rows:
        raise ValueError("The Results sheet is empty")

    headers = {
        str(value).strip().lower(): column
        for column, value in rows[0].items()
    }
    base_metrics = (
        "x",
        "z",
        "water_level",
        "h",
        "u",
        "c",
        "froude",
        "erosion_velocity",
        "q",
        "sediment_transport",
        "sedimentation_velocity",
        "entrainment_velocity",
        "ds",
    )
    optional_metrics = (
        "step",
        "s",
        "width_m",
        "total_discharge",
        "total_sediment_transport",
        "local_error_h",
        "local_error_u",
        "local_error_c",
        "local_error_width",
        "error_norm",
        "rejected_steps",
        "v_wal",
        "initial_sediment_transport",
        "sediment_transport_amplification",
        "maximum_transport_ratio",
        "breach_flow_criterion_met",
    )
    metrics = base_metrics + tuple(
        name for name in optional_metrics if name in headers
    )
    required = ("layer", *base_metrics)
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(
            "The Results sheet is missing required columns: "
            + ", ".join(missing)
        )

    profiles = {}
    for row_number, row in enumerate(rows[1:], start=2):
        if not row:
            continue
        try:
            layer = int(row[headers["layer"]])
            if layer <= 0:
                raise ValueError
            point = {}
            for name in metrics:
                point[name] = float(row[headers[name]])
                if not math.isfinite(point[name]):
                    raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ValueError(
                f"Invalid or incomplete result data on Results row {row_number}"
            ) from error
        profiles.setdefault(layer, []).append(point)

    if not profiles:
        raise ValueError("The Results sheet contains no profile data")
    return profiles


def xml_escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def tick_values(low, high, count=5):
    if low == high:
        padding = abs(low) * 0.05 or 1.0
        low -= padding
        high += padding
    step = (high - low) / count
    return [low + step * index for index in range(count + 1)]


def format_tick(value):
    if value == 0:
        return "0"
    if abs(value) >= 10000 or abs(value) < 0.001:
        return f"{value:.2e}"
    return f"{value:.4g}"


def make_panel(profiles, metric, title, unit, x, y, width, height):
    left = x + 72
    right = x + width - 18
    top = y + 38
    bottom = y + height - 58
    plot_width = right - left
    plot_height = bottom - top

    distance_values = [
        point["x"]
        for points in profiles.values()
        for point in points
    ]
    result_values = [
        point[metric]
        for points in profiles.values()
        for point in points
    ]
    x_min, x_max = min(distance_values), max(distance_values)
    result_min, result_max = min(result_values), max(result_values)
    if x_min == x_max:
        padding = abs(x_min) * 0.05 or 1.0
        x_min -= padding
        x_max += padding
    if result_min == result_max:
        padding = abs(result_min) * 0.05 or 1.0
        result_min -= padding
        result_max += padding

    def map_x(value):
        return left + (value - x_min) / (x_max - x_min) * plot_width

    def map_y(value):
        return bottom - (value - result_min) / (result_max - result_min) * plot_height

    output = [
        f'<g font-family="Arial, sans-serif" fill="#222">',
        f'<text x="{x + width / 2:.1f}" y="{y + 22}" text-anchor="middle" '
        f'font-size="17" font-weight="bold">{xml_escape(title)}</text>',
    ]

    for value in tick_values(x_min, x_max):
        position = map_x(value)
        output.append(
            f'<line x1="{position:.2f}" y1="{top}" x2="{position:.2f}" '
            f'y2="{bottom}" stroke="#dddddd"/>'
        )
        output.append(
            f'<text x="{position:.2f}" y="{bottom + 20}" text-anchor="middle" '
            f'font-size="11">{xml_escape(format_tick(value))}</text>'
        )

    for value in tick_values(result_min, result_max):
        position = map_y(value)
        output.append(
            f'<line x1="{left}" y1="{position:.2f}" x2="{right}" '
            f'y2="{position:.2f}" stroke="#dddddd"/>'
        )
        output.append(
            f'<text x="{left - 9}" y="{position + 4:.2f}" text-anchor="end" '
            f'font-size="11">{xml_escape(format_tick(value))}</text>'
        )

    output.extend(
        [
            f'<rect x="{left}" y="{top}" width="{plot_width}" '
            f'height="{plot_height}" fill="none" stroke="#333"/>',
            f'<text x="{(left + right) / 2:.1f}" y="{bottom + 42}" '
            'text-anchor="middle" font-size="12">X (m)</text>',
            f'<text x="{x + 17}" y="{(top + bottom) / 2:.1f}" '
            f'text-anchor="middle" font-size="12" '
            f'transform="rotate(-90 {x + 17} {(top + bottom) / 2:.1f})">'
            f'{xml_escape(title)} ({xml_escape(unit)})</text>',
        ]
    )

    for index, (layer, points) in enumerate(sorted(profiles.items())):
        color = COLORS[index % len(COLORS)]
        coordinates = " ".join(
            f"{map_x(point['x']):.2f},{map_y(point[metric]):.2f}"
            for point in points
        )
        output.append(
            f'<polyline points="{coordinates}" fill="none" '
            f'stroke="{color}" stroke-width="2"/>'
        )
        for point in points:
            output.append(
                f'<circle cx="{map_x(point["x"]):.2f}" '
                f'cy="{map_y(point[metric]):.2f}" r="2" fill="{color}"/>'
            )
    output.append("</g>")
    return "\n".join(output)


def make_svg(profiles, title):
    width = 1500
    available_metrics = {
        metric
        for points in profiles.values()
        for point in points
        for metric in point
    }
    panels = [
        ("z", "Bed elevation z", "m"),
        ("water_level", "Water level", "m"),
        ("h", "Flow depth h", "m"),
        ("u", "Mixture velocity u", "m/s"),
        ("c", "Sand concentration c", "-"),
        ("froude", "Froude number", "-"),
        ("erosion_velocity", "Erosion velocity", "m/s"),
        ("v_wal", "Wall retreat velocity v_wal", "m/s"),
        ("q", "Specific discharge q", "m2/s"),
        ("width_m", "Breach width b", "m"),
        ("total_discharge", "Total discharge Q", "m3/s"),
        ("sediment_transport", "Sediment transport", "kg/(s m)"),
        ("sediment_transport_amplification", "Transport amplification sz/sz0", "-"),
        ("total_sediment_transport", "Total sediment transport", "kg/s"),
        ("sedimentation_velocity", "Sedimentation velocity", "m/s"),
        ("entrainment_velocity", "Entrainment velocity", "m/s"),
        ("ds", "Integration step ds", "m"),
    ]
    panels = [
        panel for panel in panels if panel[0] in available_metrics
    ]
    height = 40 + ((len(panels) + 2) // 3) * 330 + 30
    output = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g font-family="Arial, sans-serif" fill="#222">',
        f'<text x="{width / 2}" y="28" text-anchor="middle" '
        f'font-size="20" font-weight="bold">{xml_escape(title)}</text>',
        "</g>",
    ]
    panel_width, panel_height = 480, 320
    for index, (metric, label, unit) in enumerate(panels):
        x = 10 + (index % 3) * 500
        y = 40 + (index // 3) * 330
        output.append(
            make_panel(
                profiles, metric, label, unit, x, y, panel_width, panel_height
            )
        )

    legend_y = height - 15
    legend_width = len(profiles) * 100
    legend_x = (width - legend_width) / 2
    for index, layer in enumerate(sorted(profiles)):
        x = legend_x + index * 100
        color = COLORS[index % len(COLORS)]
        output.extend(
            [
                f'<line x1="{x:.1f}" y1="{legend_y}" x2="{x + 24:.1f}" '
                f'y2="{legend_y}" stroke="{color}" stroke-width="3"/>',
                f'<text x="{x + 30:.1f}" y="{legend_y + 4}" '
                f'font-family="Arial, sans-serif" font-size="12">'
                f'Layer {layer}</text>',
            ]
        )
    output.append("</svg>")
    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description="Plot layer profiles from an HMBreach Excel results workbook."
    )
    parser.add_argument("workbook", type=Path, help="Input .xlsx workbook")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output SVG filename (defaults to <workbook>_plot.svg)",
    )
    arguments = parser.parse_args()

    if arguments.workbook.suffix.lower() != ".xlsx":
        parser.error("workbook must have an .xlsx extension")
    output = arguments.output or arguments.workbook.with_name(
        arguments.workbook.stem + "_plot.svg"
    )

    try:
        with zipfile.ZipFile(arguments.workbook) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise ValueError(f"Workbook ZIP data is corrupt: {bad_member}")
            profiles = read_results(archive)

        svg = make_svg(
            profiles,
            f"HMBreach results: {arguments.workbook.name}",
        )
        output.write_text(svg, encoding="utf-8")
    except (OSError, zipfile.BadZipFile, ValueError) as error:
        print(f"Plotting failed: {error}", file=sys.stderr)
        return 1

    print(f"Plot written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
