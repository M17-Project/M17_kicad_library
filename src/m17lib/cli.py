"""Command line interface: m17lib <command>."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import tables
from .parts import ValidationError, load_parts
from .symbols import build_library, import_symbol, load_base_symbols, render

ROOT = Path(__file__).resolve().parents[2]
KICAD_SYMBOL_DIRS = ("/usr/share/kicad/symbols", "/usr/local/share/kicad/symbols")


def generate(root: Path) -> dict[Path, str]:
    """Return the expected content of every generated file."""
    libraries = load_parts(root / "parts")
    bases = load_base_symbols(root / "base-symbols")
    return {
        root / "symbols" / f"{name}.kicad_sym": render(build_library(parts, bases))
        for name, parts in sorted(libraries.items())
    }


def cmd_generate(args: argparse.Namespace) -> int:
    root = args.root
    try:
        outputs = generate(root)
    except ValidationError as exc:
        for problem in exc.problems:
            print(f"error: {problem}", file=sys.stderr)
        print(f"{len(exc.problems)} problem(s) found", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    existing = set((root / "symbols").glob("*.kicad_sym"))
    stale = sorted(existing - set(outputs))
    changed = [p for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]

    if args.check:
        for path in changed:
            print(f"out of date: {path.relative_to(root)}", file=sys.stderr)
        for path in stale:
            print(f"not generated from parts/: {path.relative_to(root)}", file=sys.stderr)
        if changed or stale:
            print("run 'uv run m17lib generate' and commit the result", file=sys.stderr)
            return 1
        print(f"ok: {len(outputs)} symbol libraries are up to date")
        return 0

    (root / "symbols").mkdir(exist_ok=True)
    for path in stale:
        path.unlink()
        print(f"removed {path.relative_to(root)}")
    for path in changed:
        path.write_text(outputs[path], encoding="utf-8")
        print(f"wrote {path.relative_to(root)}")
    print(f"ok: {len(outputs)} symbol libraries, {len(changed)} changed")
    return 0


def _kicad_symbol_dir() -> Path:
    for candidate in (os.environ.get("KICAD10_SYMBOL_DIR"), *KICAD_SYMBOL_DIRS):
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    raise SystemExit("KiCad symbol directory not found, set KICAD10_SYMBOL_DIR")


def cmd_import_symbol(args: argparse.Namespace) -> int:
    """Copy stock KiCad symbols into base-symbols/<Library>.kicad_sym."""
    source_dir = _kicad_symbol_dir()
    for ref in args.symbols:
        lib, _, name = ref.partition(":")
        if not name:
            print(f"error: '{ref}' must be 'Library:Name'", file=sys.stderr)
            return 1
        source = Path(args.file) if args.file else source_dir / f"{lib}.kicad_sym"
        target = args.root / "base-symbols" / f"{args.into or lib}.kicad_sym"
        import_symbol(source, name, target)
        print(f"imported {ref} into {target.relative_to(args.root)}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Check parts and footprints, make previews and a Markdown report."""
    from . import review

    render = not args.no_render and (bool(args.base) or bool(args.items))
    text, ok = review.run(args.root, args.out, args.base, render, args.image_base, args.items)
    print(text)
    print(f"report: {args.out / 'report.md'}")
    return 0 if ok else 1


def cmd_fix_silk(args: argparse.Namespace) -> int:
    from .fixes import fix_silk

    changed = [p for p in sorted((args.root / "footprints").glob("*.pretty/*.kicad_mod")) if fix_silk(p)]
    for path in changed:
        print(f"fixed {path.relative_to(args.root)}")
    print(f"ok: {len(changed)} footprint(s) changed")
    return 0


def cmd_tables(args: argparse.Namespace) -> int:
    board = args.board_dir
    (board / "sym-lib-table").write_text(tables.sym_lib_table(args.root), encoding="utf-8")
    (board / "fp-lib-table").write_text(tables.fp_lib_table(args.root), encoding="utf-8")
    print(f"wrote {board / 'sym-lib-table'} and {board / 'fp-lib-table'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m17lib", description="M17 KiCad library tools")
    parser.add_argument("--root", type=Path, default=ROOT, help="library root directory")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="generate symbols/ from parts/ and base-symbols/")
    gen.add_argument("--check", action="store_true", help="fail if generated files are out of date")
    gen.set_defaults(func=cmd_generate)

    imp = sub.add_parser("import-symbol", help="copy KiCad stock symbols into base-symbols/")
    imp.add_argument("symbols", nargs="+", metavar="Library:Name")
    imp.add_argument("--file", help="read from this .kicad_sym file instead of the KiCad library")
    imp.add_argument("--into", help="target base library name (default: source library name)")
    imp.set_defaults(func=cmd_import_symbol)

    chk = sub.add_parser("check", help="check parts and footprints, make previews and a report")
    chk.add_argument("items", nargs="*", metavar="PART_ID|Lib:Footprint", help="check only these items")
    chk.add_argument("--base", help="check only items changed since this git ref, for example origin/main")
    chk.add_argument("--out", type=Path, default=Path("check"), help="directory for the report and images")
    chk.add_argument("--no-render", action="store_true", help="do not make images")
    chk.add_argument("--image-base", default="", help="URL prefix for images in the report")
    chk.set_defaults(func=cmd_check)

    fix = sub.add_parser("fix-silk", help="set silkscreen text in all footprints to the M17 size")
    fix.set_defaults(func=cmd_fix_silk)

    tab = sub.add_parser("tables", help="write sym-lib-table and fp-lib-table for a board project")
    tab.add_argument("board_dir", type=Path)
    tab.set_defaults(func=cmd_tables)

    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
