"""Base symbol handling and atomic symbol library generation."""

from __future__ import annotations

import copy
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import sexpr
from .parts import Part, field_name
from .sexpr import Sym

KICAD_SYM_VERSION = "20251024"
GENERATOR = "m17lib"
GENERATOR_VERSION = "1"
BUILTIN_PROPS = ("Reference", "Value", "Footprint", "Datasheet", "Description")
BASE_PREFIX = "BASE_"
BASE_NOTE = "Base symbol. Do not place it. Use a part from this library."


@dataclass(slots=True)
class BaseSymbol:
    library: str
    name: str
    node: list
    path: Path


def read_library(path: Path) -> list:
    node = sexpr.parse(path.read_text(encoding="utf-8"))
    if sexpr.head(node) != "kicad_symbol_lib":
        raise ValueError(f"{path}: not a KiCad symbol library")
    return node


def new_library() -> list:
    return [
        Sym("kicad_symbol_lib"),
        [Sym("version"), Sym(KICAD_SYM_VERSION)],
        [Sym("generator"), GENERATOR],
        [Sym("generator_version"), GENERATOR_VERSION],
    ]


def library_symbols(lib: list) -> dict[str, list]:
    return {node[1]: node for node in sexpr.find_all(lib, "symbol")}


def load_base_symbols(base_dir: Path) -> dict[tuple[str, str], BaseSymbol]:
    """Load every symbol from base-symbols/<Library>.kicad_sym."""
    result: dict[tuple[str, str], BaseSymbol] = {}
    for path in sorted(base_dir.glob("*.kicad_sym")):
        lib = read_library(path)
        for name, node in library_symbols(lib).items():
            if sexpr.find(node, "extends") is not None:
                raise ValueError(f"{path}: base symbol '{name}' must not use 'extends', flatten it")
            result[(path.stem, name)] = BaseSymbol(path.stem, name, node, path)
    return result


def prop_name(prop: list) -> str:
    """Name of a property. A private property is (property private "name" "value")."""
    return prop[2] if prop[1] == Sym("private") else prop[1]


def flatten(symbol: list, lib: list) -> list:
    """Return a copy of a symbol with its 'extends' parent chain merged in."""
    parent_ref = sexpr.find(symbol, "extends")
    if parent_ref is None:
        return copy.deepcopy(symbol)
    symbols = library_symbols(lib)
    parent_name = parent_ref[1]
    if parent_name not in symbols:
        raise ValueError(f"parent symbol '{parent_name}' not found")
    parent = flatten(symbols[parent_name], lib)
    name = symbol[1]
    child_props = {prop_name(p): p for p in sexpr.find_all(symbol, "property")}

    merged: list = [Sym("symbol"), name]
    for item in parent[2:]:
        tag = sexpr.head(item)
        if tag == "property" and prop_name(item) in child_props:
            merged.append(copy.deepcopy(child_props.pop(prop_name(item))))
        elif tag == "symbol":
            unit = copy.deepcopy(item)
            unit[1] = name + unit[1][len(parent_name):]
            merged.append(unit)
        else:
            merged.append(item)
    # Child-only properties go after the inherited ones, before the units.
    first_unit = next((i for i, x in enumerate(merged) if sexpr.head(x) == "symbol"), len(merged))
    merged[first_unit:first_unit] = [copy.deepcopy(p) for p in child_props.values()]
    return merged


def _prop(base: list, name: str) -> list | None:
    for prop in sexpr.find_all(base, "property"):
        if prop[1] == name:
            return prop
    return None


def _hidden_prop(name: str, value: str, template: list | None) -> list:
    effects = sexpr.find(template, "effects") if template else None
    if effects is None:
        effects = [Sym("effects"), [Sym("font"), [Sym("size"), Sym("1.27"), Sym("1.27")]]]
    return [
        Sym("property"),
        name,
        value,
        [Sym("at"), Sym("0"), Sym("0"), Sym("0")],
        [Sym("show_name"), Sym("no")],
        [Sym("do_not_autoplace"), Sym("no")],
        [Sym("hide"), Sym("yes")],
        copy.deepcopy(effects),
    ]


def _with_value(prop: list, value: str) -> list:
    new = copy.deepcopy(prop)
    new[2] = value
    return new


def renamed_base(base: BaseSymbol, in_bom: bool = True) -> list:
    """Copy of a base symbol for a generated library, with a name that cannot collide with a part.
    KiCad keeps the BOM flag in the root symbol, so parts that are not on the BOM need their own base."""
    node = copy.deepcopy(base.node)
    flag = sexpr.find(node, "in_bom")
    if flag is not None:
        flag[1] = Sym("yes" if in_bom else "no")
    new_name = BASE_PREFIX + base.name
    node[1] = new_name
    for item in node[2:]:
        if sexpr.head(item) == "symbol":
            item[1] = new_name + item[1][len(base.name):]
        elif sexpr.head(item) == "property" and item[1] == "Description":
            item[2] = BASE_NOTE
    return node


def derived_symbol(part: Part, base: BaseSymbol) -> list:
    node: list = [Sym("symbol"), part.part_id, [Sym("extends"), BASE_PREFIX + base.name]]
    values = {
        "Value": part.value,
        "Footprint": part.footprint,
        "Datasheet": part.datasheet,
        "Description": part.description,
    }
    for name in BUILTIN_PROPS:
        template = _prop(base.node, name)
        if name == "Reference":
            if template is None:
                raise ValueError(f"{part.part_id}: base symbol has no Reference")
            node.append(copy.deepcopy(template))
        elif template is not None:
            node.append(_with_value(template, values[name]))
        else:
            node.append(_hidden_prop(name, values[name], _prop(base.node, "Footprint")))
    hidden_template = _prop(base.node, "Footprint")
    for key, value in part.fields.items():
        node.append(_hidden_prop(field_name(key), value, hidden_template))
    keywords = " ".join(dict.fromkeys(x for x in (part.value, part.fields.get("mpn", "")) if x))
    node.append(_hidden_prop("ki_keywords", keywords, None))
    fp_filters = _prop(base.node, "ki_fp_filters")
    if fp_filters is not None:
        # KiCad writes the inherited filter into derived symbols, keep files identical.
        node.append(copy.deepcopy(fp_filters))
    node.append([Sym("embedded_fonts"), Sym("no")])
    return node


def build_library(parts: list[Part], bases: dict[tuple[str, str], BaseSymbol]) -> list:
    """Build one atomic library: used base symbols first, then one derived symbol per part."""
    problems: list[str] = []
    used: dict[str, BaseSymbol] = {}
    bom_flags: dict[str, set[bool]] = {}
    for part in parts:
        key = part.base_symbol
        base = bases.get(key)
        if base is None:
            problems.append(f"{part.source}: {part.part_id}: base symbol '{part.symbol}' not found in base-symbols/")
            continue
        other = used.get(base.name)
        if other is not None and (other.library, other.name) != key:
            problems.append(f"{part.part_id}: base name '{base.name}' exists in two base libraries")
            continue
        used[base.name] = base
        bom_flags.setdefault(base.name, set()).add(part.in_bom)
    for name, flags in bom_flags.items():
        if len(flags) > 1:
            problems.append(f"base symbol '{name}' is used by parts on the BOM and parts not on the BOM")
    if problems:
        raise ValueError("\n".join(problems))

    lib = new_library()
    for name in sorted(used):
        lib.append(renamed_base(used[name], in_bom=True in bom_flags[name]))
    for part in parts:
        lib.append(derived_symbol(part, bases[part.base_symbol]))
    return lib


def render(lib: list) -> str:
    return sexpr.dump(lib)


def import_symbol(source_lib: Path, name: str, target: Path) -> None:
    """Copy one symbol from a KiCad library into a base library, flattened."""
    lib = read_library(source_lib)
    symbols = library_symbols(lib)
    if name not in symbols:
        raise ValueError(f"{source_lib}: symbol '{name}' not found")
    symbol = flatten(symbols[name], lib)

    target_lib = read_library(target) if target.exists() else new_library()
    existing = library_symbols(target_lib)
    existing[name] = symbol
    out = [item for item in target_lib if sexpr.head(item) not in ("symbol", "embedded_fonts")]
    out.extend(existing[key] for key in sorted(existing))
    target.write_text(render(out), encoding="utf-8")
    normalize(target)


def normalize(path: Path) -> None:
    """Let KiCad rewrite a base library so it is in the current file format."""
    kicad_cli = shutil.which("kicad-cli")
    if kicad_cli is None:
        raise RuntimeError("kicad-cli not found, it is necessary to import symbols")
    subprocess.run([kicad_cli, "sym", "upgrade", "--force", str(path)], check=True, capture_output=True)
