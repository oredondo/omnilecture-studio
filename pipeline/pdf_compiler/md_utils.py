"""Deterministic Markdown cleanups applied before organizing / rendering."""
import re
from typing import Dict, List

_FENCE_RE = re.compile(r"```[ \t]*mermaid[ \t]*\n(.*?)\n[ \t]*```", re.S | re.I)
_NODE_RE = re.compile(r'([A-Za-z_][\w]*)\s*(?:\["(.*?)"\]|\[(.*?)\]|\("(.*?)"\)|\{"(.*?)"\})')
_EDGE_RE = re.compile(r'^\s*([A-Za-z_]\w*)\s*(?:\[.*?\]|\(.*?\)|\{.*?\})?\s*-->\s*(?:\|[^|]*\|\s*)?([A-Za-z_]\w*)')


def _clean_label_part(part: str) -> str:
    part = re.sub(r"<[^>]+>", "", part)
    return re.sub(r"^\s*[•\-\*]\s*", "", part).strip()


def mermaid_to_outline(code: str) -> str:
    """Converts a mermaid flowchart (graph/flowchart) into a simple nested bullet list.
    Keeps every label text; returns '' if it cannot be parsed."""
    labels: Dict[str, str] = {}
    for m in _NODE_RE.finditer(code):
        text = next((g for g in m.groups()[1:] if g is not None), None)
        if text is not None:
            labels.setdefault(m.group(1), text)

    children: Dict[str, List[str]] = {}
    order: List[str] = []
    targets = set()
    for line in code.splitlines():
        m = _EDGE_RE.match(line)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        for n in (a, b):
            if n not in order:
                order.append(n)
        children.setdefault(a, []).append(b)
        targets.add(b)

    if not order:
        return ""
    roots = [n for n in order if n not in targets]
    out: List[str] = []
    seen = set()

    def emit(node: str, depth: int):
        if node in seen:
            return
        seen.add(node)
        raw = labels.get(node, node)
        parts = [p for p in (_clean_label_part(x) for x in re.split(r"<br\s*/?>", raw)) if p]
        starts_with_bullet = bool(re.match(r"^\s*[•\-\*]", re.sub(r"<[^>]+>", "", raw)))
        ind = "  " * depth
        if not parts:
            parts = [node]
        if starts_with_bullet:
            for p in parts:
                out.append(f"{ind}- {p}")
            sub = depth + 1
        else:
            out.append(f"{ind}- **{parts[0]}**" if depth == 0 else f"{ind}- {parts[0]}")
            for p in parts[1:]:
                out.append(f"{ind}  - {p}")
            sub = depth + 1
        for c in children.get(node, []):
            emit(c, sub)

    for r in roots:
        emit(r, 0)
    return "\n".join(out)


def replace_mermaid_blocks(md: str) -> str:
    def repl(m):
        outline = mermaid_to_outline(m.group(1))
        return f"\n{outline}\n" if outline else m.group(0)
    return _FENCE_RE.sub(repl, md)


def clean_latex(md: str) -> str:
    """Replaces simple inline LaTeX (arrows, \\text{}) with plain text, since no math engine is used."""
    def fix(expr: str) -> str:
        expr = re.sub(r"\\(?:long)?rightarrow", "→", expr)
        expr = re.sub(r"\\(?:long)?leftarrow", "←", expr)
        expr = re.sub(r"\\text\{(.*?)\}", r"\1", expr)
        return expr.strip()

    md = re.sub(r"\$\$(.+?)\$\$", lambda m: fix(m.group(1)), md, flags=re.S)
    md = re.sub(r"\$([^$\n]*\\[A-Za-z]+[^$\n]*)\$", lambda m: fix(m.group(1)), md)
    return md


def preprocess_markdown(md: str) -> str:
    return clean_latex(replace_mermaid_blocks(md))
