"""Automatic fixes for footprints."""

from __future__ import annotations

from pathlib import Path

from . import sexpr
from .checks import MIN_SILK_LINE, SILK_TEXT_SIZE, SILK_TEXT_THICKNESS
from .sexpr import Sym

SILK = ("F.SilkS", "B.SilkS")


def _num(value: float) -> Sym:
    return Sym(f"{value:g}")


def fix_silk(path: Path) -> bool:
    """Set all silkscreen text to the M17 size and widen thin silkscreen lines. Return True if changed."""
    original = path.read_text(encoding="utf-8")
    fp = sexpr.parse(original)
    for node in fp:
        tag = sexpr.head(node)
        layer = sexpr.find(node, "layer") if isinstance(node, list) else None
        if layer is None or str(layer[1]) not in SILK:
            continue
        if tag in ("property", "fp_text"):
            effects = sexpr.find(node, "effects")
            font = sexpr.find(effects, "font") if effects else None
            if font is None:
                continue
            for child in font:
                if sexpr.head(child) == "size":
                    child[1:3] = [_num(SILK_TEXT_SIZE), _num(SILK_TEXT_SIZE)]
                elif sexpr.head(child) == "thickness":
                    child[1] = _num(SILK_TEXT_THICKNESS)
            if sexpr.find(font, "thickness") is None:
                font.append([Sym("thickness"), _num(SILK_TEXT_THICKNESS)])
        elif tag in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
            stroke = sexpr.find(node, "stroke")
            width = sexpr.find(stroke, "width") if stroke else None
            if width is not None and float(width[1].name) < MIN_SILK_LINE:
                width[1] = _num(MIN_SILK_LINE)
    text = sexpr.dump(fp)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False
