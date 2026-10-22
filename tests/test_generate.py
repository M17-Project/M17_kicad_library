from pathlib import Path

import pytest

from m17lib import sexpr
from m17lib.cli import ROOT, generate
from m17lib.parts import ValidationError, load_parts
from m17lib.symbols import BASE_PREFIX, build_library, load_base_symbols

BASE_LIB = """(kicad_symbol_lib
\t(version 20251024)
\t(generator "test")
\t(symbol "R"
\t\t(property "Reference" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
\t\t(property "Value" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
\t\t(property "Footprint" "" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
\t\t(property "Datasheet" "" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
\t\t(property "Description" "Resistor" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))
\t\t(symbol "R_0_1" (rectangle (start -1 -2) (end 1 2)))
\t)
)
"""

PART = """
  - part_id: RES-10K-0402
    type: resistor
    symbol: Device:R
    footprint: Resistor_SMD:R_0402_1005Metric
    value: 10k
    manufacturer: YAGEO
    mpn: RC0402FR-0710KL
    mouser: 603-RC0402FR-0710KL
    lcsc: C25744
    datasheet: https://www.yageo.com/rc.pdf
    description: 0402 resistor
"""


def make_root(tmp_path: Path, parts_yaml: str) -> Path:
    (tmp_path / "parts").mkdir()
    (tmp_path / "base-symbols").mkdir()
    (tmp_path / "symbols").mkdir()
    (tmp_path / "base-symbols" / "Device.kicad_sym").write_text(BASE_LIB)
    (tmp_path / "parts" / "passives.yaml").write_text(
        "schema_version: 1\nlibrary: M17_Passives\nparts:\n" + parts_yaml
    )
    return tmp_path


def test_sexpr_round_trip_matches_kicad_format():
    text = (ROOT / "base-symbols" / "Device.kicad_sym").read_text()
    assert sexpr.dump(sexpr.parse(text)) == text


def test_generates_derived_symbol(tmp_path):
    root = make_root(tmp_path, PART)
    (path, text), = generate(root).items()
    assert path.name == "M17_Passives.kicad_sym"
    lib = sexpr.parse(text)
    symbols = {s[1]: s for s in sexpr.find_all(lib, "symbol")}
    assert set(symbols) == {BASE_PREFIX + "R", "RES-10K-0402"}
    part = symbols["RES-10K-0402"]
    assert sexpr.find(part, "extends")[1] == BASE_PREFIX + "R"
    props = {p[1]: p[2] for p in sexpr.find_all(part, "property")}
    assert props["Value"] == "10k"
    assert props["Footprint"] == "Resistor_SMD:R_0402_1005Metric"
    assert props["Mouser"] == "603-RC0402FR-0710KL"
    assert props["MPN"] == "RC0402FR-0710KL"
    assert props["LCSC"] == "C25744"
    base_units = [s[1] for s in sexpr.find_all(symbols[BASE_PREFIX + "R"], "symbol")]
    assert base_units == [BASE_PREFIX + "R_0_1"]


def test_mouser_is_required(tmp_path):
    root = make_root(tmp_path, PART.replace("    mouser: 603-RC0402FR-0710KL\n", ""))
    with pytest.raises(ValidationError, match="mouser"):
        load_parts(root / "parts")


def test_mouser_not_required_outside_bom(tmp_path):
    yaml = PART.replace("    mouser: 603-RC0402FR-0710KL\n", "    in_bom: false\n")
    root = make_root(tmp_path, yaml)
    assert load_parts(root / "parts")["M17_Passives"][0].in_bom is False


@pytest.mark.parametrize(
    "old, new, message",
    [
        ("lcsc: C25744", "lcsc: 25744", "lcsc"),
        ("symbol: Device:R", "symbol: R", "symbol"),
        ("datasheet: https://www.yageo.com/rc.pdf", "datasheet: /home/x.pdf", "datasheet"),
        ("    datasheet: https://www.yageo.com/rc.pdf\n", "", "datasheet"),
        ("    value: 10k\n", "", "value"),
    ],
)
def test_invalid_fields(tmp_path, old, new, message):
    root = make_root(tmp_path, PART.replace(old, new))
    with pytest.raises(ValidationError, match=message):
        load_parts(root / "parts")


def test_duplicate_part_id(tmp_path):
    root = make_root(tmp_path, PART + PART)
    with pytest.raises(ValidationError, match="duplicate"):
        load_parts(root / "parts")


def test_missing_base_symbol(tmp_path):
    root = make_root(tmp_path, PART.replace("Device:R", "Device:X"))
    parts = load_parts(root / "parts")["M17_Passives"]
    with pytest.raises(ValueError, match="not found"):
        build_library(parts, load_base_symbols(root / "base-symbols"))


def test_repository_is_up_to_date():
    for path, text in generate(ROOT).items():
        assert path.read_text() == text, f"{path.name} is out of date, run 'uv run m17lib generate'"


def test_source_replaces_mouser(tmp_path):
    yaml = PART.replace("    mouser: 603-RC0402FR-0710KL\n", "    source: LCSC only\n")
    part = load_parts(make_root(tmp_path, yaml) / "parts")["M17_Passives"][0]
    assert part.fields["source"] == "LCSC only"


def test_non_bom_part_needs_no_order_data(tmp_path):
    yaml = """
  - part_id: GND
    type: power
    symbol: Device:R
    value: GND
    in_bom: false
    description: Power symbol
"""
    part = load_parts(make_root(tmp_path, yaml) / "parts")["M17_Passives"][0]
    assert part.in_bom is False


def test_non_bom_part_gets_base_without_bom_flag(tmp_path):
    root = make_root(tmp_path, PART.replace("RES-10K-0402", "LOGO").replace("    mouser: 603-RC0402FR-0710KL\n", "    in_bom: false\n"))
    (root / "base-symbols" / "Device.kicad_sym").write_text(BASE_LIB.replace('(symbol "R"\n', '(symbol "R"\n\t\t(in_bom yes)\n'))
    (path, text), = generate(root).items()
    base = next(s for s in sexpr.find_all(sexpr.parse(text), "symbol") if s[1] == BASE_PREFIX + "R")
    assert sexpr.find(base, "in_bom")[1] == sexpr.Sym("no")
