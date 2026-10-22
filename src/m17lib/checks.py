"""Checks for parts, symbols and footprints. Each finding has a clear message for a pull request."""

from __future__ import annotations

import math
import re
import os
from dataclasses import dataclass
from pathlib import Path

from . import sexpr
from .parts import Part

# Silkscreen text for all M17 footprints.
SILK_TEXT_SIZE = 0.8
SILK_TEXT_THICKNESS = 0.15
# JLCPCB manufacturing limits that are not KiCad DRC rules.
MIN_SILK_LINE = 0.15
MIN_ANNULAR_RING = 0.15
MIN_PTH_DRILL = 0.2
MIN_NPTH_DRILL = 0.5
PIN_GRID = 1.27
KICAD_FOOTPRINT_DIRS = ("/usr/share/kicad/footprints", "/usr/local/share/kicad/footprints")
KICAD_3DMODEL_DIRS = ("/usr/share/kicad/3dmodels", "/usr/local/share/kicad/3dmodels")


@dataclass(slots=True)
class Finding:
    level: str  # "error" or "warning"
    item: str
    message: str


def _error(item: str, message: str) -> Finding:
    return Finding("error", item, message)


def _warn(item: str, message: str) -> Finding:
    return Finding("warning", item, message)


def _num(node: list | None, index: int = 1) -> float:
    return float(node[index].name) if node is not None else 0.0


def _layers(node: list) -> list[str]:
    layers = sexpr.find(node, "layers")
    if layers is not None:
        return [str(x) for x in layers[1:]]
    layer = sexpr.find(node, "layer")
    return [str(layer[1])] if layer is not None else []


def kicad_dir(env: str, defaults: tuple[str, ...]) -> Path | None:
    for candidate in (os.environ.get(env), *defaults):
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    return None


def footprint_path(root: Path, ref: str) -> Path | None:
    lib, name = ref.split(":", 1)
    local = root / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod"
    if local.is_file():
        return local
    stock = kicad_dir("KICAD10_FOOTPRINT_DIR", KICAD_FOOTPRINT_DIRS)
    if stock is not None:
        path = stock / f"{lib}.pretty" / f"{name}.kicad_mod"
        if path.is_file():
            return path
    return None


# Part data


def check_part(part: Part) -> list[Finding]:
    item = f"part {part.part_id}"
    findings = []
    if part.in_bom and not part.datasheet:
        findings.append(_error(item, "No datasheet. Add the URL of the official datasheet from the manufacturer."))
    elif part.datasheet and not part.datasheet.startswith("https://"):
        findings.append(_warn(item, f"The datasheet URL does not use https: {part.datasheet}"))
    if part.in_bom and not part.fields.get("mouser"):
        findings.append(_warn(item, f"Not at Mouser. Source: {part.fields.get('source', '')}"))
    if part.in_bom and not part.fields.get("lcsc"):
        findings.append(_warn(item, "No LCSC number. If JLCPCB has this part, add the LCSC number (recommended)."))
    return findings


# Symbols


def check_symbol(part: Part, symbol: list) -> list[Finding]:
    """Check a base symbol for one part."""
    item = f"symbol {part.symbol}"
    findings: list[Finding] = []
    pins = [p for unit in sexpr.find_all(symbol, "symbol") for p in sexpr.find_all(unit, "pin")]
    if not pins:
        if part.in_bom:
            findings.append(_error(item, "The symbol has no pins."))
        return findings

    by_number: dict[str, list[list]] = {}
    for pin in pins:
        number = sexpr.find(pin, "number")
        name = sexpr.find(pin, "name")
        at = sexpr.find(pin, "at")
        pin_no = number[1] if number else ""
        if not pin_no:
            findings.append(_error(item, "A pin has no pin number."))
            continue
        by_number.setdefault(pin_no, []).append(pin)
        if at is not None:
            x, y = _num(at, 1), _num(at, 2)
            if not (_on_grid(x) and _on_grid(y)):
                findings.append(_error(item, f"Pin {pin_no} is not on the 1.27 mm (50 mil) grid: ({x}, {y})."))
        if pin[1] == sexpr.Sym("unspecified"):
            findings.append(_warn(item, f"Pin {pin_no} ({name[1] if name else ''}) has the electrical type 'unspecified'."))

    for number, same in by_number.items():
        names = {str(sexpr.find(p, "name")[1]) for p in same}
        if len(same) > 1 and len(names) > 1:
            findings.append(_error(item, f"Pin number {number} is used {len(same)} times with different names: {sorted(names)}."))
    return findings


def _on_grid(value: float) -> bool:
    steps = value / PIN_GRID
    return abs(steps - round(steps)) < 1e-6


def symbol_pin_numbers(symbol: list) -> set[str]:
    numbers = set()
    for unit in sexpr.find_all(symbol, "symbol"):
        for pin in sexpr.find_all(unit, "pin"):
            number = sexpr.find(pin, "number")
            if number is not None and number[1]:
                numbers.add(number[1])
    return numbers


def check_pin_pad_match(part: Part, symbol: list, footprint: list) -> list[Finding]:
    item = f"part {part.part_id}"
    pins = symbol_pin_numbers(symbol)
    pads = {str(p[1]) for p in sexpr.find_all(footprint, "pad") if str(p[1])}
    findings = []
    missing = sorted(pins - pads, key=_natural)
    if missing:
        findings.append(_error(item, f"These symbol pins have no pad in the footprint: {', '.join(missing)}."))
    extra = sorted(pads - pins, key=_natural)
    if extra:
        findings.append(_warn(item, f"These footprint pads have no symbol pin: {', '.join(extra)}. "
                                   "This is correct only for mounting or shield pads."))
    return findings


def _natural(text: str) -> tuple:
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text))


# Footprints


def check_footprint(path: Path) -> list[Finding]:
    """Static checks for one of our footprints. KiCad DRC checks clearances separately."""
    item = f"footprint {path.parent.stem}:{path.stem}"
    findings: list[Finding] = []
    fp = sexpr.parse(path.read_text(encoding="utf-8"))
    if str(fp[1]) != path.stem:
        findings.append(_error(item, f"The footprint name '{fp[1]}' is different from the file name."))

    attr = sexpr.find(fp, "attr")
    if attr is None:
        findings.append(_error(item, "Set the footprint type (SMD or through hole) in the footprint properties."))

    graphics = [g for g in fp if sexpr.head(g) in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly")]
    layers_used = {layer for g in graphics for layer in _layers(g)}
    pads = sexpr.find_all(fp, "pad")
    board_only = attr is not None and sexpr.Sym("board_only") in attr

    if not board_only:
        if not ({"F.CrtYd", "B.CrtYd"} & layers_used):
            findings.append(_error(item, "No courtyard. Draw the courtyard on F.CrtYd around the part and its pads."))
        if not ({"F.Fab", "B.Fab"} & layers_used):
            findings.append(_warn(item, "No part outline on F.Fab. Draw the body outline of the part on F.Fab."))
        if not pads:
            findings.append(_error(item, "The footprint has no pads."))
        if sexpr.find(fp, "model") is None:
            findings.append(_warn(item, "No 3D model. If the manufacturer supplies a 3D model, embed it in the footprint."))

    for graphic in graphics:
        if {"F.SilkS", "B.SilkS"} & set(_layers(graphic)):
            stroke = sexpr.find(graphic, "stroke")
            width = _num(sexpr.find(stroke, "width")) if stroke else 0.0
            fill = sexpr.find(graphic, "fill")
            filled = fill is not None and str(fill[1]) in ("yes", "solid")
            if width < MIN_SILK_LINE - 1e-9 and not filled:
                findings.append(_error(item, f"A silkscreen line is {width} mm wide. The minimum is {MIN_SILK_LINE} mm."))
                break

    findings += _check_texts(item, fp)
    findings += _check_pads(item, pads)
    findings += _check_model(item, fp)
    return findings


def _check_texts(item: str, fp: list) -> list[Finding]:
    findings = []
    texts = [t for t in fp if sexpr.head(t) in ("property", "fp_text")]
    reference_on_silk = False
    for text in texts:
        layers = _layers(text)
        if not layers or layers[0] not in ("F.SilkS", "B.SilkS"):
            continue
        label = str(text[1]) if sexpr.head(text) == "property" else f"text '{text[2]}'"
        if sexpr.head(text) == "property" and text[1] == "Reference":
            reference_on_silk = True
        hidden = sexpr.find(text, "hide")
        if hidden is not None and str(hidden[1]) == "yes":
            continue
        font = sexpr.find(sexpr.find(text, "effects") or [], "font") or []
        size = sexpr.find(font, "size")
        thickness = sexpr.find(font, "thickness")
        w, h = (_num(size, 1), _num(size, 2)) if size else (0.0, 0.0)
        t = _num(thickness) if thickness else 0.0
        if not (math.isclose(w, SILK_TEXT_SIZE) and math.isclose(h, SILK_TEXT_SIZE)
                and math.isclose(t, SILK_TEXT_THICKNESS)):
            findings.append(_error(item, f"Silkscreen {label} is {w} x {h} mm, {t} mm thick. "
                                         f"Use {SILK_TEXT_SIZE} x {SILK_TEXT_SIZE} mm, {SILK_TEXT_THICKNESS} mm thick "
                                         f"(run 'uv run m17lib fix-silk')."))
    if not reference_on_silk:
        findings.append(_warn(item, "The reference designator is not on the silkscreen."))
    return findings


def _check_pads(item: str, pads: list[list]) -> list[Finding]:
    findings = []
    for pad in pads:
        number = str(pad[1]) or "(no number)"
        kind = str(pad[2])
        layers = _layers(pad)
        drill = sexpr.find(pad, "drill")
        size = sexpr.find(pad, "size")
        if kind == "smd":
            copper = [layer for layer in layers if layer.endswith(".Cu")]
            if not copper:
                continue
            side = copper[0].split(".")[0]
            if f"{side}.Mask" not in layers:
                findings.append(_error(item, f"SMD pad {number} has no solder mask opening ({side}.Mask)."))
            if f"{side}.Paste" not in layers:
                findings.append(_warn(item, f"SMD pad {number} has no solder paste ({side}.Paste). "
                                            "This is correct only if separate paste pads are used."))
        elif kind == "thru_hole" and drill is not None:
            hole = _drill_size(drill)
            if hole < MIN_PTH_DRILL - 1e-9:
                findings.append(_error(item, f"Plated hole of pad {number} is {hole} mm. The minimum is {MIN_PTH_DRILL} mm."))
            if size is not None:
                ring = (min(_num(size, 1), _num(size, 2)) - hole) / 2
                if ring < MIN_ANNULAR_RING - 1e-9:
                    findings.append(_error(item, f"Annular ring of pad {number} is {ring:.3f} mm. "
                                                 f"The minimum is {MIN_ANNULAR_RING} mm."))
        elif kind == "np_thru_hole" and drill is not None:
            hole = _drill_size(drill)
            if hole < MIN_NPTH_DRILL - 1e-9:
                findings.append(_error(item, f"Non plated hole is {hole} mm. The minimum is {MIN_NPTH_DRILL} mm."))
    return findings


def _drill_size(drill: list) -> float:
    values = [float(x.name) for x in drill[1:] if isinstance(x, sexpr.Sym) and x.name.replace(".", "", 1).isdigit()]
    return min(values) if values else 0.0


def _check_model(item: str, fp: list) -> list[Finding]:
    findings = []
    embedded = sexpr.find(fp, "embedded_files")
    embedded_names = set()
    if embedded is not None:
        for file in sexpr.find_all(embedded, "file"):
            name = sexpr.find(file, "name")
            if name is not None:
                embedded_names.add(name[1])
    for model in sexpr.find_all(fp, "model"):
        path = str(model[1])
        if path.startswith("kicad-embed://"):
            if path.removeprefix("kicad-embed://") not in embedded_names:
                findings.append(_error(item, f"The embedded 3D model '{path}' is missing in the footprint file."))
        elif path.startswith("${KICAD10_3DMODEL_DIR}/"):
            models = kicad_dir("KICAD10_3DMODEL_DIR", KICAD_3DMODEL_DIRS)
            if models is not None and not (models / path.split("/", 1)[1]).is_file():
                findings.append(_error(item, f"The KiCad 3D model '{path}' does not exist."))
        else:
            findings.append(_error(item, f"The 3D model path '{path}' works only on one computer. Embed the model."))
    return findings
