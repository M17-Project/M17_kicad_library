"""Check parts and make previews. The result is a Markdown report for a pull request comment."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from . import checks, sexpr, testboard
from .checks import Finding
from .parts import Part, ValidationError, load_parts
from .symbols import BaseSymbol, load_base_symbols

MARKER = "<!-- m17lib-check -->"


@dataclass(slots=True)
class Result:
    title: str
    findings: list[Finding] = field(default_factory=list)
    images: list[tuple[str, str]] = field(default_factory=list)  # (caption, file name)
    details: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.level == "error" for f in self.findings)


@dataclass(slots=True)
class Library:
    parts: dict[str, Part]
    bases: dict[tuple[str, str], BaseSymbol]
    footprints: dict[str, str]  # "Lib:Name" -> file text


def load_library(root: Path) -> Library:
    libraries = load_parts(root / "parts")
    footprints = {
        f"{p.parent.stem}:{p.stem}": p.read_text(encoding="utf-8")
        for p in sorted((root / "footprints").glob("*.pretty/*.kicad_mod"))
    }
    return Library(
        parts={p.part_id: p for lib in libraries.values() for p in lib},
        bases=load_base_symbols(root / "base-symbols"),
        footprints=footprints,
    )


def _fingerprint(lib: Library, part: Part) -> str:
    base = lib.bases.get(part.base_symbol)
    data = repr((part, sexpr.compact(base.node) if base else None, lib.footprints.get(part.footprint)))
    return hashlib.sha256(data.encode()).hexdigest()


def _library_at(root: Path, ref: str, into: Path) -> Library | None:
    """Load the library as it is at a git ref. Return None if that version cannot be loaded."""
    archive = subprocess.run(["git", "-C", str(root), "archive", ref, "parts", "base-symbols", "footprints"],
                             capture_output=True)
    if archive.returncode != 0:
        return None
    with tarfile.open(fileobj=BytesIO(archive.stdout)) as tar:
        tar.extractall(into, filter="data")
    try:
        return load_library(into)
    except (ValidationError, ValueError, OSError):
        return None


def changed_items(root: Path, lib: Library, base_ref: str) -> tuple[list[str], list[str]]:
    """Return part ids and local footprint refs that are new or changed since base_ref."""
    with tempfile.TemporaryDirectory() as tmp:
        old = _library_at(root, base_ref, Path(tmp))
        if old is None:
            return sorted(lib.parts), sorted(lib.footprints)
        parts = [pid for pid, part in sorted(lib.parts.items())
                 if pid not in old.parts or _fingerprint(lib, part) != _fingerprint(old, old.parts[pid])]
        footprints = [ref for ref, text in sorted(lib.footprints.items()) if old.footprints.get(ref) != text]
    return parts, footprints


def _svg_to_png(svg: Path, png: Path) -> bool:
    converter = shutil.which("rsvg-convert")
    if converter is None:
        return False
    subprocess.run([converter, "-w", "800", "-b", "white", "-o", str(png), str(svg)], check=True)
    return True


def _export_svg(cmd: list[str], target: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([*cmd, "-o", tmp], check=True, capture_output=True)
        svg = next(Path(tmp).glob("*.svg"))
        shutil.move(svg, target)


def review_part(root: Path, lib: Library, part: Part, out: Path, render: bool) -> Result:
    result = Result(f"Part `{part.part_id}`")
    result.findings += checks.check_part(part)
    result.details += [f"Value: {part.value}", f"MPN: {part.fields.get('manufacturer', '')} {part.fields.get('mpn', '')}",
                       f"Mouser: {part.fields.get('mouser', '-')}", f"LCSC: {part.fields.get('lcsc', '-')}",
                       f"Datasheet: {part.datasheet or '-'}", f"Symbol: `{part.symbol}`",
                       f"Footprint: `{part.footprint}`"]
    base = lib.bases.get(part.base_symbol)
    if base is None:
        result.findings.append(checks._error(f"part {part.part_id}", f"Base symbol `{part.symbol}` not found."))
        return result
    result.findings += checks.check_symbol(part, base.node)

    fp_file = checks.footprint_path(root, part.footprint) if part.footprint else None
    if part.footprint and fp_file is None:
        result.findings.append(checks._error(f"part {part.part_id}", f"Footprint `{part.footprint}` not found."))
    if fp_file is not None:
        result.findings += checks.check_pin_pad_match(part, base.node, sexpr.parse(fp_file.read_text(encoding="utf-8")))

    if render:
        name = _safe(part.part_id)
        sym_svg = out / f"{name}_symbol.svg"
        _export_svg(["kicad-cli", "sym", "export", "svg", "--symbol", part.part_id,
                     str(root / "symbols" / f"{part.library}.kicad_sym")], sym_svg)
        if _svg_to_png(sym_svg, sym_svg.with_suffix(".png")):
            result.images.append(("Symbol", sym_svg.with_suffix(".png").name))
        if fp_file is not None:
            result.images += _footprint_images(fp_file, part.footprint, out, name)
    return result


def review_footprint(root: Path, ref: str, out: Path, render: bool) -> Result:
    result = Result(f"Footprint `{ref}`")
    path = checks.footprint_path(root, ref)
    assert path is not None
    result.findings += checks.check_footprint(path)
    with tempfile.TemporaryDirectory() as tmp:
        pcb = testboard.make_board(path, ref, Path(tmp))
        result.findings += testboard.run_drc(pcb, f"footprint {ref}")
    if render:
        result.images += _footprint_images(path, ref, out, _safe(ref))
    return result


def _footprint_images(path: Path, ref: str, out: Path, name: str) -> list[tuple[str, str]]:
    images = []
    fp_svg = out / f"{name}_footprint.svg"
    _export_svg(["kicad-cli", "fp", "export", "svg", "--footprint", path.stem,
                 "--layers", "F.Cu,F.Paste,F.Mask,F.SilkS,F.Fab,F.CrtYd", str(path.parent)], fp_svg)
    if _svg_to_png(fp_svg, fp_svg.with_suffix(".png")):
        images.append(("Footprint", fp_svg.with_suffix(".png").name))
    with tempfile.TemporaryDirectory() as tmp:
        pcb = testboard.make_board(path, ref, Path(tmp))
        png = out / f"{name}_3d.png"
        testboard.render(pcb, png, "iso")
        images.append(("3D", png.name))
    return images


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in text)


def generated_up_to_date(root: Path) -> Result:
    from .cli import generate

    result = Result("Generated symbol libraries")
    try:
        outputs = generate(root)
    except ValidationError as exc:
        result.findings += [checks._error("parts", p) for p in exc.problems]
        return result
    except ValueError as exc:
        result.findings.append(checks._error("parts", str(exc)))
        return result
    for path, text in outputs.items():
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            result.findings.append(checks._error(path.name, "Out of date. Run 'uv run m17lib generate' and commit the result."))
    return result


def report(results: list[Result], image_base: str) -> str:
    errors = sum(1 for r in results for f in r.findings if f.level == "error")
    warnings = sum(1 for r in results for f in r.findings if f.level == "warning")
    verdict = "**Result: FAIL.** Correct the errors below." if errors else "**Result: PASS.** The changes can be merged."
    lines = [MARKER, "## Library check", "", verdict, "",
             f"{len(results) - 1} changed item(s), {errors} error(s), {warnings} warning(s).", ""]
    for result in results:
        if not result.findings and not result.images and not result.details:
            continue
        icon = "✅" if result.ok else "❌"
        lines += [f"### {icon} {result.title}", ""]
        if result.details:
            lines += [" · ".join(result.details), ""]
        for f in result.findings:
            mark = "❌ **Error**" if f.level == "error" else "⚠️ Warning"
            lines.append(f"- {mark} ({f.item}): {f.message}")
        if result.findings:
            lines.append("")
        if result.images:
            lines.append("| " + " | ".join(c for c, _ in result.images) + " |")
            lines.append("|" + "---|" * len(result.images))
            lines.append("| " + " | ".join(f'<img src="{image_base}{n}" width="260">' for _, n in result.images) + " |")
            lines.append("")
    return "\n".join(lines) + "\n"


def run(root: Path, out: Path, base_ref: str | None, render: bool, image_base: str = "",
        only: list[str] | None = None) -> tuple[str, bool]:
    out.mkdir(parents=True, exist_ok=True)
    results = [generated_up_to_date(root)]
    if not results[0].ok:
        text = report(results, image_base)
        (out / "report.md").write_text(text, encoding="utf-8")
        return text, False
    lib = load_library(root)
    if only:
        unknown = [x for x in only if x not in lib.parts and x not in lib.footprints]
        if unknown:
            raise SystemExit(f"error: unknown part or footprint: {', '.join(unknown)}")
        part_ids = [x for x in only if x in lib.parts]
        footprint_refs = [x for x in only if x in lib.footprints]
    elif base_ref:
        part_ids, footprint_refs = changed_items(root, lib, base_ref)
    else:
        part_ids, footprint_refs = sorted(lib.parts), sorted(lib.footprints)
    for ref in footprint_refs:
        results.append(review_footprint(root, ref, out, render))
    for pid in part_ids:
        results.append(review_part(root, lib, lib.parts[pid], out, render))
    text = report(results, image_base)
    (out / "report.md").write_text(text, encoding="utf-8")
    return text, all(r.ok for r in results)
