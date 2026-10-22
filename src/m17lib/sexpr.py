"""Minimal S-expression reader and writer for KiCad files."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Sym:
    """Bare (unquoted) atom such as a keyword or a number."""

    name: str

    def __str__(self) -> str:
        return self.name


Node = list | str | Sym

_TOKEN = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def parse(text: str) -> list:
    """Parse one top level S-expression. Quoted atoms become str, bare atoms Sym."""
    stack: list[list] = []
    result: list | None = None
    pos = 0
    length = len(text)
    while pos < length:
        match = _TOKEN.match(text, pos)
        if match is None:
            if text[pos:].strip() == "":
                break
            raise ValueError(f"unexpected character at offset {pos}")
        pos = match.end()
        open_paren, close_paren, quoted, bare = match.groups()
        if open_paren:
            stack.append([])
        elif close_paren:
            if not stack:
                raise ValueError(f"unbalanced ')' at offset {pos}")
            done = stack.pop()
            if stack:
                stack[-1].append(done)
            else:
                result = done
        elif quoted is not None:
            if not stack:
                raise ValueError("atom outside of a list")
            stack[-1].append(_unescape(quoted))
        elif bare is not None:
            if not stack:
                raise ValueError("atom outside of a list")
            stack[-1].append(Sym(bare))
    if stack or result is None:
        raise ValueError("unbalanced S-expression")
    return result


def _unescape(value: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), value)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _atom(node: str | Sym) -> str:
    if isinstance(node, Sym):
        return node.name
    return f'"{_escape(node)}"'


def compact(node: list) -> str:
    """Write a node on one line."""
    return "(" + " ".join(compact(x) if isinstance(x, list) else _atom(x) for x in node) + ")"


def dump(node: list) -> str:
    """Write a node exactly as KiCad does (port of KICAD_FORMAT::Prettify, normal mode)."""
    return prettify(compact(node))


def prettify(source: str) -> str:
    xy_column_limit = 99
    wrap_threshold = 72
    out: list[str] = []
    depth = 0
    last = ""
    in_quote = False
    inserted_space = False
    multi_line = False
    in_xy = False
    column = 0
    backslashes = 0
    length = len(source)

    def next_non_ws(i: int) -> str:
        while i < length and source[i] in " \t\n\r":
            i += 1
        return source[i] if i < length else ""

    for i, ch in enumerate(source):
        nxt = next_non_ws(i)
        if ch in " \t\n\r" and not in_quote:
            if not inserted_space and depth > 0 and last != "(" and nxt not in (")", "("):
                if in_xy or column < wrap_threshold:
                    out.append(" ")
                    column += 1
                else:
                    out.append("\n" + "\t" * depth)
                    column = depth
                    multi_line = True
                inserted_space = True
            continue

        inserted_space = False
        if ch == "(" and not in_quote:
            is_xy = source.startswith("xy ", i + 1)
            if not out:
                out.append("(")
                column += 1
            elif in_xy and is_xy and column < xy_column_limit:
                out.append(" (")
                column += 2
            else:
                out.append("\n" + "\t" * depth + "(")
                column = depth + 1
            in_xy = is_xy
            depth += 1
        elif ch == ")" and not in_quote:
            depth = max(depth - 1, 0)
            if last == ")" or multi_line:
                out.append("\n" + "\t" * depth + ")")
                column = depth + 1
                multi_line = False
            else:
                out.append(")")
                column += 1
        else:
            if ch == "\\":
                backslashes += 1
            elif ch == '"' and backslashes % 2 == 0:
                in_quote = not in_quote
            if ch != "\\":
                backslashes = 0
            out.append(ch)
            column += 1
        last = ch
    return "".join(out) + "\n"


def head(node: Node) -> str | None:
    if isinstance(node, list) and node and isinstance(node[0], Sym):
        return node[0].name
    return None


def find(node: list, name: str) -> list | None:
    for child in node:
        if head(child) == name:
            return child
    return None


def find_all(node: list, name: str) -> list[list]:
    return [child for child in node if head(child) == name]
