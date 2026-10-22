import re
from pathlib import Path

import yaml

from m17lib.cli import ROOT

FOOTPRINTS = ROOT / "footprints"
EMBED = re.compile(r'\(model "kicad-embed://([^"]+)"')
MODEL_PATH = re.compile(r'\(model "([^"]+)"')


def embedded_models() -> set[tuple[str, str]]:
    found = set()
    for path in FOOTPRINTS.glob("*.pretty/*.kicad_mod"):
        ref = f"{path.parent.stem}:{path.stem}"
        for name in EMBED.findall(path.read_text(encoding="utf-8")):
            found.add((ref, name))
    return found


def test_every_embedded_model_has_a_source():
    data = yaml.safe_load((FOOTPRINTS / "models.yaml").read_text(encoding="utf-8"))
    listed = {(m["footprint"], m["file"]) for m in data["models"]}
    for model in data["models"]:
        assert model.get("owner") and model.get("source", "").startswith("https://"), model
    assert embedded_models() - listed == set(), "add these models to footprints/models.yaml"
    assert listed - embedded_models() == set(), "remove these entries from footprints/models.yaml"


def test_models_are_embedded_or_from_kicad():
    # A path to a local file does not work on other computers.
    for path in FOOTPRINTS.glob("*.pretty/*.kicad_mod"):
        for model in MODEL_PATH.findall(path.read_text(encoding="utf-8")):
            assert model.startswith(("kicad-embed://", "${KICAD10_3DMODEL_DIR}/")), f"{path.name}: {model}"
