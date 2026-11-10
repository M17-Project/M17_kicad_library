import json
import zipfile

from m17lib import board


def drc_report(tmp_path):
    path = tmp_path / "drc.json"
    path.write_text(json.dumps({
        "violations": [{"type": "clearance", "severity": "error", "description": "x", "items": []}],
        "unconnected_items": [{"type": "unconnected_items", "severity": "error", "description": "y", "items": []}],
        "schematic_parity": [{"type": "missing_footprint", "severity": "warning", "description": "z", "items": []}],
    }))
    return path


def test_drc_strict(tmp_path):
    problems, warnings = board.check_drc(drc_report(tmp_path))
    assert len(problems) == 3 and warnings == []


def test_drc_work_in_progress_keeps_parity_strict(tmp_path):
    problems, warnings = board.check_drc(drc_report(tmp_path), wip=True)
    assert len(warnings) == 2
    assert len(problems) == 1 and "missing_footprint" in problems[0]


def test_set_wip(tmp_path):
    pro = tmp_path / "x.kicad_pro"
    pro.write_text(json.dumps({"text_variables": {}}))
    assert not board.is_wip(tmp_path)
    board.set_wip(tmp_path, True)
    assert board.is_wip(tmp_path)
    assert json.loads(pro.read_text())["text_variables"][board.WIP_VAR] == board.WIP_TEXT
    board.set_wip(tmp_path, False)
    assert not board.is_wip(tmp_path)


def test_do_not_order(tmp_path):
    archive = tmp_path / "gerbers.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("a.gbr", "x")
    board.mark_do_not_order([archive, tmp_path])
    board.mark_do_not_order([archive])
    assert zipfile.ZipFile(archive).namelist().count(board.DO_NOT_ORDER) == 1
    assert (tmp_path / board.DO_NOT_ORDER).exists()


def test_fp_lib_table_lists_kicad_libraries_used_by_parts():
    from m17lib.cli import ROOT
    from m17lib import tables

    text = tables.fp_lib_table(ROOT)
    assert '(name "Resistor_SMD")' in text and "${KICAD10_FOOTPRINT_DIR}/Resistor_SMD.pretty" in text
    assert "${KIPRJMOD}/lib/footprints/M17_ICs.pretty" in text
    assert '(name "M17_ICs")' in text and "${KICAD10_FOOTPRINT_DIR}/M17_ICs" not in text


BOM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <components>
    <comp ref="U3"><value>LP5907MFX-3.3</value><footprint>Package_TO_SOT_SMD:SOT-23-5</footprint>
      <fields>
        <field name="Manufacturer">Texas Instruments</field>
        <field name="MPN">LP5907MFX-3.3/NOPB</field>
        <field name="Mouser">595-LP5907MFX-3.3NPB</field>
        <field name="LCSC">C80670</field>
        <field name="Alt Manufacturer">onsemi, Example</field>
        <field name="Alt MPN">NCP163ASN330T1G, EX123</field>
        <field name="Alt Mouser">863-NCP163ASN330T1G, -</field>
        <field name="Alt LCSC">C603656, C1</field>
      </fields>
    </comp>
    <comp ref="R1"><value>10k</value><footprint>Resistor_SMD:R_0402_1005Metric</footprint>
      <fields><field name="MPN">RC0402</field><field name="Mouser">603-RC0402</field></fields>
    </comp>
  </components>
</export>
"""


def test_bom_csv_lists_alternates(tmp_path):
    import csv

    xml = tmp_path / "bom.xml"
    xml.write_text(BOM_XML)
    rows = board.read_bom(xml)
    board.write_mouser_bom(rows, tmp_path / "mouser.csv")
    board.write_jlcpcb_bom(rows, tmp_path / "jlc.csv")
    board.write_alternates_bom(rows, tmp_path / "alt.csv")
    mouser = {r["References"]: r for r in csv.DictReader((tmp_path / "mouser.csv").open())}
    assert mouser["U3"]["Alt Mouser Part Number"] == "863-NCP163ASN330T1G"
    assert mouser["U3"]["Alt MPN"] == "NCP163ASN330T1G"
    assert mouser["R1"]["Alt MPN"] == ""
    jlc_header = (tmp_path / "jlc.csv").read_text().splitlines()[0]
    assert jlc_header == "Comment,Designator,Footprint,LCSC Part #"
    alts = list(csv.DictReader((tmp_path / "alt.csv").open()))
    assert [(a["Alt MPN"], a["Alt Mouser Part Number"], a["Alt LCSC"]) for a in alts] == [
        ("NCP163ASN330T1G", "863-NCP163ASN330T1G", "C603656"), ("EX123", "", "C1")]
