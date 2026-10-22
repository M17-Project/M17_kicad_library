"""KiCad library tables for a board project that uses this library as 'lib/'."""

from __future__ import annotations

from pathlib import Path

LIB_DIR = "lib"


def sym_lib_table(library_root: Path) -> str:
    rows = [
        f'  (lib (name "{path.stem}")(type "KiCad")'
        f'(uri "${{KIPRJMOD}}/{LIB_DIR}/symbols/{path.name}")(options "")(descr ""))'
        for path in sorted((library_root / "symbols").glob("*.kicad_sym"))
    ]
    return "(sym_lib_table\n  (version 7)\n" + "".join(r + "\n" for r in rows) + ")\n"


def fp_lib_table(library_root: Path) -> str:
    rows = [
        f'  (lib (name "{path.stem}")(type "KiCad")'
        f'(uri "${{KIPRJMOD}}/{LIB_DIR}/footprints/{path.name}")(options "")(descr ""))'
        for path in sorted((library_root / "footprints").glob("*.pretty"))
    ]
    return "(fp_lib_table\n  (version 7)\n" + "".join(r + "\n" for r in rows) + ")\n"
