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
