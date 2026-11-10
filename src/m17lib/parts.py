"""Load and validate part definitions from YAML files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .alternates import ALT_EMPTY, ALT_FIELD_NAMES, ALT_SEPARATOR, ALTERNATE_KEYS

SCHEMA_VERSION = 1
LIBRARY_NAME = re.compile(r"^M17_[A-Za-z0-9]+$")
PART_ID = re.compile(r"^[A-Z0-9][A-Z0-9.+_-]*$")
LIB_REF = re.compile(r"^[A-Za-z0-9_.+-]+:[^:\s]+$")
FIELD_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
LCSC = re.compile(r"^C[0-9]+$")

REQUIRED = ("part_id", "type", "symbol", "value", "description")
# Parts on the BOM must also have these. Power symbols and board features (in_bom: false) do not.
REQUIRED_BOM = ("manufacturer", "mpn", "datasheet")
# Keys that map to KiCad built-in fields or control generation.
BUILTIN = {"part_id", "symbol", "footprint", "value", "datasheet", "description", "in_bom"}
# Order codes: only these fields. LCSC is the field that JLCPCB and KiKit expect.
FIELD_NAMES = {"mpn": "MPN", "lcsc": "LCSC", "mouser": "Mouser", **ALT_FIELD_NAMES}


class ValidationError(ValueError):
    """Raised when part data is invalid. Holds every problem found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(slots=True)
class Part:
    part_id: str
    library: str
    symbol: str
    footprint: str
    value: str
    datasheet: str
    description: str
    in_bom: bool
    fields: dict[str, str] = field(default_factory=dict)
    source: str = ""

    @property
    def base_symbol(self) -> tuple[str, str]:
        lib, name = self.symbol.split(":", 1)
        return lib, name


def field_name(key: str) -> str:
    return FIELD_NAMES.get(key, key[:1].upper() + key[1:])


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip()


def load_parts(parts_dir: Path) -> dict[str, list[Part]]:
    """Return parts grouped by library name. Raise ValidationError on any problem."""
    problems: list[str] = []
    libraries: dict[str, list[Part]] = {}
    seen: dict[str, str] = {}

    files = sorted(parts_dir.glob("*.yaml"))
    if not files:
        raise ValidationError([f"{parts_dir}: no YAML files found"])

    for path in files:
        source = path.name
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            problems.append(f"{source}: invalid YAML: {exc}")
            continue
        if not isinstance(data, dict):
            problems.append(f"{source}: root must be a mapping")
            continue
        if data.get("schema_version") != SCHEMA_VERSION:
            problems.append(f"{source}: schema_version must be {SCHEMA_VERSION}")
        library = data.get("library")
        if not isinstance(library, str) or not LIBRARY_NAME.match(library):
            problems.append(f"{source}: library must match {LIBRARY_NAME.pattern}")
            continue
        raw_parts = data.get("parts")
        if not isinstance(raw_parts, list) or not raw_parts:
            problems.append(f"{source}: parts must be a non-empty list")
            continue

        for index, raw in enumerate(raw_parts):
            where = f"{source}: parts[{index}]"
            if not isinstance(raw, dict):
                problems.append(f"{where}: must be a mapping")
                continue
            part, errors = _parse_part(raw, library, source)
            label = f"{source}: {part.part_id or f'parts[{index}]'}"
            problems.extend(f"{label}: {e}" for e in errors)
            if errors:
                continue
            if part.part_id in seen:
                problems.append(f"{label}: duplicate part_id, first defined in {seen[part.part_id]}")
                continue
            seen[part.part_id] = source
            libraries.setdefault(library, []).append(part)

    if problems:
        raise ValidationError(problems)
    for parts in libraries.values():
        parts.sort(key=lambda p: p.part_id)
    return libraries


def _parse_part(raw: dict, library: str, source: str) -> tuple[Part, list[str]]:
    errors: list[str] = []
    values: dict[str, str] = {}
    alt_fields: dict[str, str] = {}
    for key, value in raw.items():
        key = str(key)
        if not FIELD_KEY.match(key):
            errors.append(f"invalid key '{key}', use lower case and '_'")
            continue
        if key == "alternates":
            alt_fields = _parse_alternates(value, _text(raw.get("mpn")), errors)
            continue
        if key.startswith("alt_"):
            errors.append(f"'{key}' is generated, use the 'alternates' list")
            continue
        if isinstance(value, (list, dict)):
            errors.append(f"'{key}' must be a scalar value")
            continue
        values[key] = _text(value)

    in_bom = values.get("in_bom", "yes") != "no"
    for key in REQUIRED:
        if not values.get(key):
            errors.append(f"missing required field '{key}'")

    part_id = values.get("part_id", "")
    if part_id and not PART_ID.match(part_id):
        errors.append(f"part_id must match {PART_ID.pattern}")
    symbol = values.get("symbol", "")
    if symbol and not LIB_REF.match(symbol):
        errors.append("symbol must be 'Library:Name'")
    footprint = values.get("footprint", "")
    if footprint and not LIB_REF.match(footprint):
        errors.append("footprint must be 'Library:Name'")
    if in_bom:
        for key in REQUIRED_BOM:
            if not values.get(key):
                errors.append(f"missing required field '{key}'")
        # Mouser is the primary source. Every part on the BOM must be orderable there.
        # Mouser is the primary source. If Mouser does not sell the part, 'source' must say where to buy it.
        if not values.get("mouser") and not values.get("source"):
            errors.append("missing field 'mouser'. If Mouser does not sell this part, add 'source' "
                          "with a URL or a note where to buy it, for example 'LCSC only'")
        if not footprint:
            errors.append("missing required field 'footprint'")
    lcsc = values.get("lcsc", "")
    if lcsc and not LCSC.match(lcsc):
        errors.append(f"lcsc '{lcsc}' must match {LCSC.pattern}")
    datasheet = values.get("datasheet", "")
    if datasheet and not datasheet.startswith("https://"):
        errors.append("datasheet must be an https:// URL of the official datasheet")

    extra = {k: v for k, v in values.items() if k not in BUILTIN and v}
    extra.update(alt_fields)
    part = Part(
        part_id=part_id,
        library=library,
        symbol=symbol,
        footprint=footprint,
        value=values.get("value", ""),
        datasheet=datasheet,
        description=values.get("description", ""),
        in_bom=in_bom,
        fields=dict(sorted(extra.items(), key=lambda kv: _field_order(kv[0]))),
        source=source,
    )
    return part, errors


def _parse_alternates(raw: object, mpn: str, errors: list[str]) -> dict[str, str]:
    """Check the 'alternates' list. Return the Alt fields (values in list order, '-' if empty)."""
    if not isinstance(raw, list) or not raw:
        errors.append("'alternates' must be a non-empty list")
        return {}
    items: list[dict[str, str]] = []
    seen = {mpn}
    for index, alt in enumerate(raw):
        where = f"alternates[{index}]"
        if not isinstance(alt, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        unknown = sorted(set(map(str, alt)) - set(ALTERNATE_KEYS))
        if unknown:
            errors.append(f"{where}: unknown key(s) {', '.join(unknown)}, use {', '.join(ALTERNATE_KEYS)}")
        item = {k: _text(alt.get(k)) for k in ALTERNATE_KEYS}
        for key in ("manufacturer", "mpn"):
            if not item[key]:
                errors.append(f"{where}: missing required field '{key}'")
        if not item["mouser"] and not item["lcsc"]:
            errors.append(f"{where}: needs 'mouser' or 'lcsc'")
        if item["lcsc"] and not LCSC.match(item["lcsc"]):
            errors.append(f"{where}: lcsc '{item['lcsc']}' must match {LCSC.pattern}")
        for key, value in item.items():
            if "," in value or value == ALT_EMPTY:
                errors.append(f"{where}: '{key}' must not contain ',' or be '{ALT_EMPTY}'")
        if item["mpn"] in seen:
            errors.append(f"{where}: mpn '{item['mpn']}' is the part itself or a duplicate")
        seen.add(item["mpn"])
        items.append(item)
    fields: dict[str, str] = {}
    for key in ALTERNATE_KEYS:
        if any(i[key] for i in items):
            fields[f"alt_{key}"] = ALT_SEPARATOR.join(i[key] or ALT_EMPTY for i in items)
    return fields


_ORDER = ("manufacturer", "mpn", "mouser", "lcsc", "source",
          "alt_manufacturer", "alt_mpn", "alt_mouser", "alt_lcsc", "type")


def _field_order(key: str) -> tuple[int, str]:
    return (_ORDER.index(key), "") if key in _ORDER else (len(_ORDER), key)
