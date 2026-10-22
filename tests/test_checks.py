from pathlib import Path

from m17lib import checks, sexpr
from m17lib.fixes import fix_silk
from m17lib.parts import Part

GOOD_FP = """(footprint "Test"
\t(layer "F.Cu")
\t(property "Reference" "REF**" (at 0 -2 0) (layer "F.SilkS") (effects (font (size 0.8 0.8) (thickness 0.15))))
\t(property "Value" "Test" (at 0 2 0) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
\t(attr smd)
\t(fp_line (start -1 -1) (end 1 -1) (stroke (width 0.15) (type solid)) (layer "F.SilkS"))
\t(fp_rect (start -1.5 -1.5) (end 1.5 1.5) (stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))
\t(fp_rect (start -1 -1) (end 1 1) (stroke (width 0.1) (type solid)) (fill no) (layer "F.Fab"))
\t(pad "1" smd rect (at -0.5 0) (size 0.5 0.5) (layers "F.Cu" "F.Mask" "F.Paste"))
\t(pad "2" smd rect (at 0.5 0) (size 0.5 0.5) (layers "F.Cu" "F.Mask" "F.Paste"))
\t(model "${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0402_1005Metric.step")
)
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "M17_Test.pretty" / "Test.kicad_mod"
    path.parent.mkdir(exist_ok=True)
    path.write_text(text)
    return path


def errors(findings):
    return [f.message for f in findings if f.level == "error"]


def test_good_footprint(tmp_path):
    assert errors(checks.check_footprint(write(tmp_path, GOOD_FP))) == []


def test_missing_courtyard(tmp_path):
    text = GOOD_FP.replace('(layer "F.CrtYd")', '(layer "F.Fab")')
    assert any("courtyard" in e for e in errors(checks.check_footprint(write(tmp_path, text))))


def test_missing_mask_and_model(tmp_path):
    text = GOOD_FP.replace('"F.Cu" "F.Mask" "F.Paste"))\n\t(pad "2"', '"F.Cu" "F.Paste"))\n\t(pad "2"')
    text = "\n".join(line for line in text.splitlines() if "(model" not in line) + "\n"
    findings = checks.check_footprint(write(tmp_path, text))
    assert any("solder mask" in e for e in errors(findings))
    assert any("3D model" in f.message and f.level == "warning" for f in findings)


def test_silk_text_size_and_fix(tmp_path):
    text = GOOD_FP.replace("(size 0.8 0.8) (thickness 0.15)", "(size 1 1) (thickness 0.12)")
    text = text.replace("(width 0.15)", "(width 0.1)")
    path = write(tmp_path, text)
    assert any("Silkscreen" in e for e in errors(checks.check_footprint(path)))
    assert fix_silk(path)
    assert errors(checks.check_footprint(path)) == []


def test_local_model_path_is_error(tmp_path):
    text = GOOD_FP.replace("${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes", "/home/user/models")
    assert any("one computer" in e for e in errors(checks.check_footprint(write(tmp_path, text))))


def make_part(**changes) -> Part:
    values = dict(part_id="X", library="M17_Test", symbol="Device:R", footprint="Lib:Fp", value="1k",
                  datasheet="https://example.com/x.pdf", description="x", in_bom=True,
                  fields={"mouser": "1", "lcsc": "C1"})
    values.update(changes)
    return Part(**values)


def test_part_datasheet_required():
    assert any("datasheet" in e for e in errors(checks.check_part(make_part(datasheet=""))))


def test_part_lcsc_is_only_a_warning():
    findings = checks.check_part(make_part(fields={"mouser": "1"}))
    assert errors(findings) == [] and any("LCSC" in f.message for f in findings)


def test_symbol_pin_off_grid_and_pad_match():
    symbol = sexpr.parse("""(symbol "S" (symbol "S_1_1"
        (pin passive line (at 0 0.5 0) (length 2.54) (name "A") (number "1"))
        (pin passive line (at 0 2.54 0) (length 2.54) (name "B") (number "3"))))""")
    part = make_part(symbol="Lib:S")
    assert any("grid" in e for e in errors(checks.check_symbol(part, symbol)))
    fp = sexpr.parse(GOOD_FP)
    assert any("3" in e for e in errors(checks.check_pin_pad_match(part, symbol, fp)))
