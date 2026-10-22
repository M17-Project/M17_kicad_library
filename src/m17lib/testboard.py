"""Put one footprint on a small test board, then run KiCad DRC and make renders."""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from . import sexpr
from .checks import Finding, _error, _warn
from .sexpr import Sym

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "board"
MARGIN = 1.5
# DRC results that do not apply to a single footprint on a test board.
IGNORED_DRC = {"lib_footprint_issues", "lib_footprint_mismatch", "unconnected_items", "footprint_type_mismatch",
               "silk_edge_clearance"}


def _strip_library_header(fp: list) -> list:
    return [x for x in fp if sexpr.head(x) not in ("version", "generator", "generator_version")]


def _bbox(fp: list) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []

    def visit(node: list) -> None:
        for child in node:
            if not isinstance(child, list):
                continue
            tag = sexpr.head(child)
            if tag in ("start", "end", "center", "mid", "xy") and len(child) >= 3:
                xs.append(float(child[1].name))
                ys.append(float(child[2].name))
            elif tag == "pad":
                at, size = sexpr.find(child, "at"), sexpr.find(child, "size")
                if at is not None and size is not None:
                    r = max(float(size[1].name), float(size[2].name)) / 2
                    x, y = float(at[1].name), float(at[2].name)
                    xs.extend((x - r, x + r))
                    ys.extend((y - r, y + r))
            elif tag not in ("property", "fp_text", "model", "embedded_files"):
                visit(child)

    visit(fp)
    if not xs:
        return (-2.0, -2.0, 2.0, 2.0)
    return (min(xs), min(ys), max(xs), max(ys))


def make_board(footprint_file: Path, lib_ref: str, out_dir: Path) -> Path:
    """Write test.kicad_pcb and test.kicad_pro. Each pad number gets its own net."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fp = _strip_library_header(sexpr.parse(footprint_file.read_text(encoding="utf-8")))
    fp[1] = lib_ref
    layer_index = next(i for i, x in enumerate(fp) if sexpr.head(x) == "layer")
    fp[layer_index + 1:layer_index + 1] = [
        [Sym("uuid"), str(uuid.uuid4())],
        [Sym("at"), Sym("0"), Sym("0")],
    ]
    for pad in sexpr.find_all(fp, "pad"):
        if str(pad[1]):
            pad.append([Sym("net"), f"PAD_{pad[1]}"])

    x0, y0, x1, y1 = _bbox(fp)
    board = sexpr.parse((TEMPLATE_DIR / "board.kicad_pcb.in").read_text(encoding="utf-8")
                        .replace("{{STACKUP}}", "").replace("{{THICKNESS}}", "0.8")
                        .replace("{{TITLE}}", lib_ref).replace("{{DATE}}", "").replace("{{REVISION}}", ""))
    outline = [
        Sym("gr_rect"),
        [Sym("start"), Sym(f"{x0 - MARGIN:.4f}"), Sym(f"{y0 - MARGIN:.4f}")],
        [Sym("end"), Sym(f"{x1 + MARGIN:.4f}"), Sym(f"{y1 + MARGIN:.4f}")],
        [Sym("stroke"), [Sym("width"), Sym("0.05")], [Sym("type"), Sym("default")]],
        [Sym("fill"), Sym("no")],
        [Sym("layer"), "Edge.Cuts"],
        [Sym("uuid"), str(uuid.uuid4())],
    ]
    tail = next(i for i, x in enumerate(board) if sexpr.head(x) == "embedded_fonts")
    board[tail:tail] = [fp, outline]
    pcb = out_dir / "test.kicad_pcb"
    pcb.write_text(sexpr.dump(board), encoding="utf-8")

    project = json.loads((TEMPLATE_DIR / "board.kicad_pro.in").read_text(encoding="utf-8"))
    project["meta"]["filename"] = "test.kicad_pro"
    # Inside one footprint, check against the manufacturing minimum, not the board default netclass.
    rules = project["board"]["design_settings"]["rules"]
    project["net_settings"]["classes"][0]["clearance"] = rules["min_clearance"]
    (out_dir / "test.kicad_pro").write_text(json.dumps(project, indent=2), encoding="utf-8")
    return pcb


def run_drc(pcb: Path, item: str) -> list[Finding]:
    report = pcb.with_suffix(".drc.json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--units", "mm",
                    "-o", str(report), str(pcb)], check=True, capture_output=True)
    data = json.loads(report.read_text(encoding="utf-8"))
    findings = []
    for group in ("violations", "unconnected_items"):
        for v in data.get(group, []):
            if v.get("type") in IGNORED_DRC:
                continue
            items = "; ".join(i.get("description", "") for i in v.get("items", []))
            text = f"KiCad DRC ({v.get('type')}): {v.get('description')}. {items}".strip()
            findings.append(_error(item, text) if v.get("severity") == "error" else _warn(item, text))
    return findings


def render(pcb: Path, out_png: Path, view: str) -> None:
    args = ["kicad-cli", "pcb", "render", "--quality", "high", "--background", "opaque",
            "-w", "800", "-h", "600", "-o", str(out_png)]
    if view == "top":
        args += ["--side", "top", "--zoom", "0.9"]
    else:
        args += ["--side", "top", "--rotate", "-50,0,35", "--zoom", "0.75"]
    subprocess.run([*args, str(pcb)], check=True, capture_output=True)
