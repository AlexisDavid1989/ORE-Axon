"""Edit `bench/source_questions.json` in place without disturbing its layout.

The question file is hand-formatted - one question per block, list entries lined
up under the first - and reads well in review because of it. Loading and dumping
would reflow all of it, so `bench --promote` edits the text instead: a small
scanner records where every value starts and ends, and only the lists that
actually change are re-rendered, in the same layout. Every other byte is copied
through.

The layout rule the renderer follows, and the tests check against the real file,
is: a list's first entry sits right after `[`, and each further entry goes on its
own line at that same column. A one-entry list is inline. `format_question`,
`append_questions_text` and `add_fields_text` write new questions and fields by
the same rule, and reproduce every existing question byte for byte.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Span:
    kind: str                 # obj | arr | str | lit
    start: int
    end: int
    #: obj: [(key, key_start, key_end, value Span)]; arr: [Span]
    items: list = field(default_factory=list)


class _Scanner:
    def __init__(self, text: str):
        self.t = text
        self.i = 0

    def ws(self):
        while self.i < len(self.t) and self.t[self.i] in " \t\r\n":
            self.i += 1

    def string(self) -> int:
        assert self.t[self.i] == '"'
        self.i += 1
        while self.t[self.i] != '"':
            self.i += 2 if self.t[self.i] == "\\" else 1
        self.i += 1
        return self.i

    def value(self) -> Span:
        self.ws()
        start, c = self.i, self.t[self.i]
        if c == "{":
            return self.obj()
        if c == "[":
            return self.arr()
        if c == '"':
            return Span("str", start, self.string())
        while self.i < len(self.t) and self.t[self.i] not in ",}] \t\r\n":
            self.i += 1
        return Span("lit", start, self.i)

    def obj(self) -> Span:
        start = self.i
        self.i += 1
        items = []
        while True:
            self.ws()
            if self.t[self.i] == "}":
                self.i += 1
                return Span("obj", start, self.i, items)
            k0 = self.i
            k1 = self.string()
            key = json.loads(self.t[k0:k1])
            self.ws()
            assert self.t[self.i] == ":", f"expected ':' at {self.i}"
            self.i += 1
            items.append((key, k0, k1, self.value()))
            self.ws()
            if self.t[self.i] == ",":
                self.i += 1

    def arr(self) -> Span:
        start = self.i
        self.i += 1
        items = []
        while True:
            self.ws()
            if self.t[self.i] == "]":
                self.i += 1
                return Span("arr", start, self.i, items)
            items.append(self.value())
            self.ws()
            if self.t[self.i] == ",":
                self.i += 1


def parse_spans(text: str) -> Span:
    return _Scanner(text).value()


def _column(text: str, pos: int) -> int:
    return pos - (text.rfind("\n", 0, pos) + 1)


def render_list(entries: list[str], col: int, nl: str = "\n") -> str:
    """A list of strings in the file's layout; `col` is where its first entry sits."""
    return "[" + (f",{nl}" + " " * col).join(
        json.dumps(e, ensure_ascii=False) for e in entries) + "]"


def _member(obj: Span, key: str):
    for m in obj.items:
        if m[0] == key:
            return m
    return None


def _find_question(root: Span, text: str, qid: str) -> Span:
    questions = _member(root, "questions")
    if questions is None:
        raise ValueError("no `questions` array in the file")
    for q in questions[3].items:
        ident = _member(q, "id")
        if ident and json.loads(text[ident[3].start:ident[3].end]) == qid:
            return q
    raise ValueError(f"no question {qid!r} in the file")


def promote_text(text: str, moves: dict[str, list[str]]) -> str:
    """Move the named `xfail_nodes` entries into `required_nodes`, per question.

    Layout is kept: entries are appended to an existing `required_nodes` list in
    its own alignment; when there is none, one is created on the line before
    `xfail_nodes` (or, if every gap moved, `xfail_nodes` is renamed in place);
    an `xfail_nodes` left empty is removed together with its separator."""
    nl = "\r\n" if "\r\n" in text else "\n"
    root = parse_spans(text)
    edits: list[tuple[int, int, str]] = []
    for qid, moved in moves.items():
        if not moved:
            continue
        q = _find_question(root, text, qid)
        req, gap = _member(q, "required_nodes"), _member(q, "xfail_nodes")
        if gap is None:
            raise ValueError(f"{qid}: has no xfail_nodes to promote from")
        gap_entries = json.loads(text[gap[3].start:gap[3].end])
        unknown = [e for e in moved if e not in gap_entries]
        if unknown:
            raise ValueError(f"{qid}: not in xfail_nodes: {unknown}")
        taken = [e for e in gap_entries if e in moved]
        keep = [e for e in gap_entries if e not in moved]
        gap_col = _column(text, gap[3].start) + 1

        if req is not None:
            entries = json.loads(text[req[3].start:req[3].end]) + taken
            edits.append((req[3].start, req[3].end,
                          render_list(entries, _column(text, req[3].start) + 1, nl)))
            if keep:
                edits.append((gap[3].start, gap[3].end, render_list(keep, gap_col, nl)))
            else:
                later = [m for m in q.items if m[1] > gap[1]]
                if later:
                    edits.append((gap[1], later[0][1], ""))
                else:
                    prev = [m for m in q.items if m[1] < gap[1]][-1]
                    edits.append((prev[3].end, gap[3].end, ""))
        elif not keep:
            sep = text[gap[2]:gap[3].start]
            bracket_col = _column(text, gap[1]) + len('"required_nodes"') + len(sep)
            edits.append((gap[1], gap[3].end, '"required_nodes"' + sep
                          + render_list(taken, bracket_col + 1, nl)))
        else:
            key_col = _column(text, gap[1])
            line_start = text.rfind("\n", 0, gap[1]) + 1
            own_line = not text[line_start:gap[1]].strip()
            head = '"required_nodes": '
            new = head + render_list(taken, key_col + len(head) + 1, nl) + ","
            new += (nl + " " * key_col) if own_line else " "
            edits.append((gap[1], gap[1], new))
            edits.append((gap[3].start, gap[3].end, render_list(keep, gap_col, nl)))

    for start, end, replacement in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        text = text[:start] + replacement + text[end:]
    json.loads(text)          # an edit that broke the file must not be written
    return text


def promote_file(path: Path, moves: dict[str, list[str]]) -> None:
    raw = path.read_bytes().decode("utf-8")
    path.write_bytes(promote_text(raw, moves).encode("utf-8"))


# ---------------------------------------------------------------------------
# Authoring: write new questions and fields in the same layout
# ---------------------------------------------------------------------------

def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_member(key: str, value, col: int, nl: str) -> str:
    """One `"key": value` member. Lists use the aligned layout; a dict puts one
    pair per line under the first (a list inside a pair stays on its line)."""
    if isinstance(value, list):
        return f'"{key}": ' + render_list(value, col + len(f'"{key}": ['), nl)
    if isinstance(value, dict):
        pad = col + len(f'"{key}": {{')
        pairs = [f"{_dump(k)}: {_dump(v)}" for k, v in value.items()]
        return f'"{key}": {{' + (f",{nl}" + " " * pad).join(pairs) + "}"
    return f'"{key}": {_dump(value)}'


def format_question(q: dict, nl: str = "\n", indent: int = 4) -> str:
    """One question object in the file's layout: scalar fields on the first line,
    then each list or dict field on a line of its own, one column further in."""
    scalars = [k for k, v in q.items() if not isinstance(v, (list, dict))]
    blocks = [k for k, v in q.items() if isinstance(v, (list, dict))]
    head = "{" + ", ".join(f'"{k}": {_dump(q[k])}' for k in scalars)
    lines = [" " * indent + head + ("," if blocks else "")]
    for i, key in enumerate(blocks):
        tail = "," if i < len(blocks) - 1 else ""
        lines.append(" " * (indent + 1) + _render_member(key, q[key], indent + 1, nl) + tail)
    return nl.join(lines) + "}"


def append_questions_text(text: str, questions: list[dict]) -> str:
    """Add whole questions after the last one in the file."""
    if not questions:
        return text
    nl = "\r\n" if "\r\n" in text else "\n"
    root = parse_spans(text)
    last = _member(root, "questions")[3].items[-1]
    body = ("," + nl).join(format_question(q, nl) for q in questions)
    out = text[:last.end] + "," + nl + body + text[last.end:]
    json.loads(out)
    return out


def add_fields_text(text: str, fields: dict[str, dict]) -> str:
    """Add fields ({qid: {key: value}}) to existing questions, after their last
    member, in the file's layout. A key already present is an error: this adds,
    it does not rewrite."""
    nl = "\r\n" if "\r\n" in text else "\n"
    root = parse_spans(text)
    edits = []
    for qid, new in fields.items():
        q = _find_question(root, text, qid)
        clash = [k for k in new if _member(q, k) is not None]
        if clash:
            raise ValueError(f"{qid}: already has {clash}")
        last = q.items[-1][3]
        key_at = q.items[-1][1]
        line_start = text.rfind("\n", 0, key_at) + 1
        # A question with no block fields keeps everything on one line; new
        # fields then go one column in from its brace, like the others do.
        col = (key_at - line_start if not text[line_start:key_at].strip()
               else _column(text, q.start) + 1)
        add = "".join("," + nl + " " * col + _render_member(k, v, col, nl)
                      for k, v in new.items())
        edits.append((last.end, last.end, add))
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    json.loads(text)
    return text
