"""KiCad library tables for a board project that uses this library as 'lib/'."""

from __future__ import annotations

import re
from pathlib import Path

LIB_DIR = "lib"
FOOTPRINT_FIELD = re.compile(r'\(property "Footprint" "([^":]+):')


def sym_lib_table(library_root: Path) -> str:
    rows = [
        f'  (lib (name "{path.stem}")(type "KiCad")'
        f'(uri "${{KIPRJMOD}}/{LIB_DIR}/symbols/{path.name}")(options "")(descr ""))'
        for path in sorted((library_root / "symbols").glob("*.kicad_sym"))
    ]
    return "(sym_lib_table\n  (version 7)\n" + "".join(r + "\n" for r in rows) + ")\n"


def stock_footprint_libraries(library_root: Path) -> list[str]:
    """KiCad footprint libraries that the parts use and that are not in footprints/."""
    local = {p.stem for p in (library_root / "footprints").glob("*.pretty")}
    used = set()
    for path in (library_root / "symbols").glob("*.kicad_sym"):
        used.update(FOOTPRINT_FIELD.findall(path.read_text(encoding="utf-8")))
    return sorted(used - local)


def fp_lib_table(library_root: Path) -> str:
    # The KiCad footprint libraries are in the project table too, so that a board
    # does not depend on the global library table of a computer (for example in the CI).
    rows = [
        f'  (lib (name "{path.stem}")(type "KiCad")'
        f'(uri "${{KIPRJMOD}}/{LIB_DIR}/footprints/{path.name}")(options "")(descr ""))'
        for path in sorted((library_root / "footprints").glob("*.pretty"))
    ]
    rows += [
        f'  (lib (name "{name}")(type "KiCad")'
        f'(uri "${{KICAD10_FOOTPRINT_DIR}}/{name}.pretty")(options "")(descr "KiCad library"))'
        for name in stock_footprint_libraries(library_root)
    ]
    return "(fp_lib_table\n  (version 7)\n" + "".join(r + "\n" for r in rows) + ")\n"
