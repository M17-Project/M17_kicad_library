"""Board project tools. Standard library only, so a board repo needs no extra packages."""

from __future__ import annotations

import csv
import json
import re
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections import OrderedDict
from datetime import date
from pathlib import Path

from . import sexpr, tables

LIB_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = LIB_ROOT / "templates" / "board"
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Template file -> output path. {name} is the board name.
TEMPLATES = {
    "board.kicad_pro.in": "{name}.kicad_pro",
    "board.kicad_sch.in": "{name}.kicad_sch",
    "board.kicad_pcb.in": "{name}.kicad_pcb",
    "Makefile.in": "Makefile",
    "gitignore.in": ".gitignore",
    "README.md.in": "README.md",
    "build.yml.in": ".github/workflows/build.yml",
}


# Project creation

# JLCPCB 4 layer stackups without extra cost: 1 oz outer and 0.5 oz inner copper.
# Source: JLCPCB impedance templates. Check the stackup again before you order.
# Layers: (name, type, thickness mm, material, epsilon_r)
MASK = 0.0152
STACKUPS = {
    "JLC04101H-7628": [
        ("prepreg", 0.2104, "7628", 4.4), ("core", 0.5, "FR4", 4.6), ("prepreg", 0.2104, "7628", 4.4),
    ],
    "JLC04081H-7628": [
        ("prepreg", 0.2104, "7628", 4.4), ("core", 0.25, "FR4", 4.6), ("prepreg", 0.2104, "7628", 4.4),
    ],
    "JLC04081H-3313": [
        ("prepreg", 0.0994, "3313", 4.1), ("core", 0.5, "FR4", 4.6), ("prepreg", 0.0994, "3313", 4.1),
    ],
}
DEFAULT_STACKUP = "JLC04101H-7628"
OUTER_CU = 0.035
INNER_CU = 0.0152


def stackup_sexpr(name: str) -> tuple[str, float]:
    """Return the KiCad (stackup ...) block for a JLCPCB stackup and the board thickness."""
    dielectrics = STACKUPS[name]
    copper = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    lines = [
        '\t\t(stackup',
        '\t\t\t(layer "F.SilkS" (type "Top Silk Screen"))',
        '\t\t\t(layer "F.Paste" (type "Top Solder Paste"))',
        f'\t\t\t(layer "F.Mask" (type "Top Solder Mask") (thickness {MASK}))',
    ]
    thickness = 2 * MASK + 2 * OUTER_CU + 2 * INNER_CU
    for index, (kind, value, material, er) in enumerate(dielectrics):
        cu = OUTER_CU if index == 0 else INNER_CU
        lines.append(f'\t\t\t(layer "{copper[index]}" (type "copper") (thickness {cu}))')
        lines.append(
            f'\t\t\t(layer "dielectric {index + 1}" (type "{kind}") (thickness {value}) '
            f'(material "{material}") (epsilon_r {er}) (loss_tangent 0.02))'
        )
        thickness += value
    lines += [
        f'\t\t\t(layer "B.Cu" (type "copper") (thickness {OUTER_CU}))',
        f'\t\t\t(layer "B.Mask" (type "Bottom Solder Mask") (thickness {MASK}))',
        '\t\t\t(layer "B.Paste" (type "Bottom Solder Paste"))',
        '\t\t\t(layer "B.SilkS" (type "Bottom Silk Screen"))',
        '\t\t\t(copper_finish "None")',
        '\t\t\t(dielectric_constraints yes)',
        '\t\t)',
    ]
    return "\n".join(lines), round(thickness, 4)


def new_board(target: Path, name: str, title: str, revision: str, stackup: str) -> list[Path]:
    if not NAME.match(name):
        raise SystemExit(f"error: board name '{name}' must use lower case letters, digits and '-'")
    if not (target / tables.LIB_DIR).is_dir():
        raise SystemExit(f"error: '{tables.LIB_DIR}/' not found. Add the library as a git submodule first")
    stackup_text, thickness = stackup_sexpr(stackup)
    values = {
        "STACKUP": stackup_text,
        "NAME": name,
        "TITLE": title,
        "REVISION": revision,
        "DATE": date.today().isoformat(),
        "THICKNESS": str(thickness),
        "SCH_UUID": str(uuid.uuid4()),
    }
    outputs = {target / out.format(name=name): TEMPLATE_DIR / src for src, out in TEMPLATES.items()}
    existing = [p for p in outputs if p.exists()]
    if existing:
        raise SystemExit("error: these files exist already: " + ", ".join(str(p) for p in existing))

    written = []
    for out, src in outputs.items():
        text = src.read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace("{{" + key + "}}", value)
        if out.suffix in (".kicad_pcb", ".kicad_sch"):
            text = sexpr.dump(sexpr.parse(text))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        written.append(out)
    written.extend(write_tables(target))
    set_wip(target, True)
    return written


def write_tables(target: Path) -> list[Path]:
    sym = target / "sym-lib-table"
    fp = target / "fp-lib-table"
    sym.write_text(tables.sym_lib_table(LIB_ROOT), encoding="utf-8")
    fp.write_text(tables.fp_lib_table(LIB_ROOT), encoding="utf-8")
    return [sym, fp]


# Work in progress marking

WIP_TEXT = "WORK IN PROGRESS - DO NOT ORDER"
WIP_VAR = "WIP_MARK"
DO_NOT_ORDER = "DO-NOT-ORDER.txt"
DO_NOT_ORDER_TEXT = (
    "DO NOT ORDER\n\n"
    "This design is a work in progress. It is not checked and not ready for\n"
    "manufacture. The KiCad text variable WIP_MARK in the project marks it.\n"
)


def _project(target: Path) -> Path:
    projects = sorted(target.glob("*.kicad_pro"))
    if len(projects) != 1:
        raise SystemExit(f"error: expected one .kicad_pro file in {target}, found {len(projects)}")
    return projects[0]


def is_wip(target: Path) -> bool:
    """A board is work in progress when the project text variable WIP_MARK is not empty."""
    data = json.loads(_project(target).read_text(encoding="utf-8"))
    return bool((data.get("text_variables") or {}).get(WIP_VAR, "").strip())


def set_wip(target: Path, on: bool) -> None:
    pro = _project(target)
    data = json.loads(pro.read_text(encoding="utf-8"))
    data.setdefault("text_variables", {})[WIP_VAR] = WIP_TEXT if on else ""
    pro.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def mark_do_not_order(paths: list[Path]) -> None:
    """Put DO-NOT-ORDER.txt into each directory and each ZIP file."""
    for path in paths:
        if path.is_dir():
            (path / DO_NOT_ORDER).write_text(DO_NOT_ORDER_TEXT, encoding="utf-8")
        elif path.suffix == ".zip":
            with zipfile.ZipFile(path, "a") as archive:
                if DO_NOT_ORDER not in archive.namelist():
                    archive.writestr(DO_NOT_ORDER, DO_NOT_ORDER_TEXT)


# Report checks


def check_erc(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    for sheet in data.get("sheets", []):
        for v in sheet.get("violations", []):
            problems.append(f"ERC {v.get('severity')}: {v.get('type')}: {v.get('description')} {_items(v)}")
    return problems


def check_drc(path: Path, wip: bool = False) -> tuple[list[str], list[str]]:
    """Return (problems, warnings). For a work in progress design, layout findings are warnings.
    The schematic parity check is always strict."""
    data = json.loads(path.read_text(encoding="utf-8"))
    problems, warnings = [], []
    for group in ("violations", "unconnected_items", "schematic_parity"):
        for v in data.get(group, []):
            text = f"DRC {v.get('severity')}: {v.get('type')}: {v.get('description')} {_items(v)}"
            if wip and group != "schematic_parity":
                warnings.append(text)
            else:
                problems.append(text)
    return problems, warnings


def _items(violation: dict) -> str:
    descriptions = [i.get("description", "") for i in violation.get("items", [])]
    return "[" + "; ".join(d for d in descriptions if d) + "]" if descriptions else ""


# BOM


def read_bom(xml_path: Path) -> list[dict[str, str]]:
    """Read a KiCad python-bom XML export. Return one row per placed, fitted BOM component."""
    root = ET.parse(xml_path).getroot()
    rows = []
    for comp in root.iter("comp"):
        props = {p.get("name"): p.get("value") for p in comp.findall("property")}
        if "exclude_from_bom" in props or "dnp" in props:
            continue
        fields = {f.get("name"): (f.text or "").strip() for f in comp.iter("field")}
        fields["Reference"] = comp.get("ref", "")
        fields["Value"] = (comp.findtext("value") or "").strip()
        fields["Footprint"] = (comp.findtext("footprint") or "").strip()
        rows.append(fields)
    return rows


def group(rows: list[dict[str, str]], key: str) -> OrderedDict[str, list[dict[str, str]]]:
    groups: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
    for row in sorted(rows, key=lambda r: (r.get(key, ""), _ref_key(r["Reference"]))):
        groups.setdefault(row.get(key, ""), []).append(row)
    return groups


def _ref_key(ref: str) -> tuple[str, int]:
    match = re.match(r"([A-Za-z_#]+)(\d*)", ref)
    if not match:
        return (ref, 0)
    return (match.group(1), int(match.group(2) or 0))


def check_bom(rows: list[dict[str, str]]) -> list[str]:
    missing = [r["Reference"] for r in rows if not r.get("Mouser") and not r.get("Source")]
    if missing:
        return [f"BOM: no Mouser number and no Source for {', '.join(sorted(missing, key=_ref_key))}"]
    return []


def write_mouser_bom(rows: list[dict[str, str]], csv_path: Path) -> None:
    """CSV for the Mouser BOM tool: one line per Mouser part number."""
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Mouser Part Number", "Quantity", "Manufacturer", "MPN", "Description", "References"])
        for mouser, items in group([r for r in rows if r.get("Mouser")], "Mouser").items():
            first = items[0]
            refs = ",".join(r["Reference"] for r in items)
            writer.writerow([mouser, len(items), first.get("Manufacturer", ""), first.get("MPN", ""),
                             first.get("Description", ""), refs])


def write_other_bom(rows: list[dict[str, str]], csv_path: Path) -> None:
    """CSV of the parts that Mouser does not sell, with the place to buy them."""
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Source", "LCSC", "Quantity", "Manufacturer", "MPN", "Description", "References"])
        for mpn, items in group([r for r in rows if not r.get("Mouser")], "MPN").items():
            first = items[0]
            refs = ",".join(r["Reference"] for r in items)
            writer.writerow([first.get("Source", ""), first.get("LCSC", ""), len(items),
                             first.get("Manufacturer", ""), mpn, first.get("Description", ""), refs])


def write_jlcpcb_bom(rows: list[dict[str, str]], csv_path: Path) -> None:
    """CSV for JLCPCB assembly. Parts without an LCSC number are listed with an empty code."""
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for _, items in group(rows, "MPN").items():
            first = items[0]
            refs = ",".join(r["Reference"] for r in items)
            footprint = first["Footprint"].split(":", 1)[-1]
            writer.writerow([first["Value"], refs, footprint, first.get("LCSC", "")])


# Command line


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="m17board", description="M17 board project tools")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="create a new KiCad board project in the current directory")
    new.add_argument("name", help="board name, for example rru2-rf-sx1255")
    new.add_argument("--title", help="human readable title (default: the board name)")
    new.add_argument("--revision", default="A")
    new.add_argument("--stackup", default=DEFAULT_STACKUP, choices=sorted(STACKUPS),
                     help=f"JLCPCB 4 layer stackup (default: {DEFAULT_STACKUP}, 1.0 mm)")

    sub.add_parser("tables", help="rewrite sym-lib-table and fp-lib-table from the library")

    rep = sub.add_parser("check-reports", help="fail on any ERC or DRC violation")
    rep.add_argument("--erc", type=Path, required=True)
    rep.add_argument("--drc", type=Path, required=True)
    rep.add_argument("--wip", action="store_true", help="work in progress: layout DRC findings are warnings")

    wip = sub.add_parser("wip", help="mark the board as work in progress (on) or ready to order (off)")
    wip.add_argument("state", choices=["on", "off", "status"])
    wip.add_argument("--short", action="store_true", help="status: print only 'on' or nothing")

    dno = sub.add_parser("do-not-order", help=f"put {DO_NOT_ORDER} into directories and ZIP files")
    dno.add_argument("paths", nargs="+", type=Path)

    bom = sub.add_parser("bom", help="check the BOM and write Mouser and JLCPCB CSV files")
    bom.add_argument("xml", type=Path, help="KiCad python-bom XML export")
    bom.add_argument("--mouser", type=Path, required=True)
    bom.add_argument("--jlcpcb", type=Path, required=True)
    bom.add_argument("--other", type=Path, required=True, help="CSV of parts that Mouser does not sell")

    args = parser.parse_args(argv)
    cwd = Path.cwd()

    if args.command == "new":
        for path in new_board(cwd, args.name, args.title or args.name, args.revision, args.stackup):
            print(f"wrote {path.relative_to(cwd)}")
        return 0
    if args.command == "tables":
        for path in write_tables(cwd):
            print(f"wrote {path.relative_to(cwd)}")
        return 0
    if args.command == "wip":
        if args.state != "status":
            set_wip(cwd, args.state == "on")
        state = is_wip(cwd)
        if args.short:
            print("on" if state else "")
        else:
            print("work in progress" if state else "ready to order (WIP_MARK is empty)")
        return 0
    if args.command == "do-not-order":
        mark_do_not_order(args.paths)
        return 0
    if args.command == "check-reports":
        drc_problems, warnings = check_drc(args.drc, args.wip)
        problems = check_erc(args.erc) + drc_problems
        for warning in warnings:
            print(f"warning (work in progress): {warning}", file=sys.stderr)
        if warnings:
            print(f"{len(warnings)} layout finding(s) allowed because the board is work in progress", file=sys.stderr)
    else:
        rows = read_bom(args.xml)
        write_mouser_bom(rows, args.mouser)
        write_other_bom(rows, args.other)
        write_jlcpcb_bom(rows, args.jlcpcb)
        problems = check_bom(rows)

    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem(s) found", file=sys.stderr)
        return 1
    print("ok")
    return 0
