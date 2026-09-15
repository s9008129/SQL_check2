"""SQL candidate detection from extracted attachment text (PRD §10, §11,
§35, §52).

"The attachment has text" is not "the text is SQL" (PRD §11 opening line) —
this module is that second layer of judgment. It never decides compliance
and never skips human confirmation: every result flows back into the SQL
editor for the user to review (PRD §11.1 point 9), regardless of how
confident the detection was. The three states the frontend actually needs
(PRD §11.4) collapse to `found` + `statement_count`; the finer high/medium/
low confidence sqlglot could offer is deliberately not surfaced (PRD "前端
不需要顯示技術分數").
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from app.services.sql_parser import parse_sql_text

_FENCE_RE = re.compile(r"```([A-Za-z0-9_+/-]*)\n(.*?)```", re.DOTALL)
_SQL_FENCE_LANGS = {"sql", "oracle", "plsql", "pl/sql"}
_STATEMENT_START_RE = re.compile(
    r"^[ \t]*(WITH|SELECT|UPDATE|DELETE|INSERT|MERGE|DECLARE|BEGIN)\b",
    re.IGNORECASE | re.MULTILINE,
)
_CSV_REQUIRED_KEYWORDS = ("FROM", "SET", "INTO")
_NOT_FOUND_MESSAGE = "附件中未辨識到可檢核的 SQL，請確認內容或直接貼上 SQL。"

# Clause keywords that legitimately continue a statement across a blank
# line (Oracle SQL is routinely hand-formatted with blank lines between
# clauses). A paragraph that does *not* start with one of these ends the
# candidate block — this is what separates trailing prose ("如有問題請洽承
# 辦人。") from a genuine multi-clause statement.
_CONTINUATION_RE = re.compile(
    r"^[ \t]*("
    r"WHERE|FROM|JOIN|LEFT|RIGHT|FULL|INNER|OUTER|CROSS|ON|AND|OR|"
    r"GROUP\s+BY|ORDER\s+BY|HAVING|SET|VALUES|UNION|INTERSECT|MINUS|"
    r"CONNECT\s+BY|START\s+WITH|WHEN|THEN|ELSE|END|\)|,"
    r")",
    re.IGNORECASE,
)


@dataclass
class DetectResult:
    sql: str
    statement_count: int
    needs_confirmation: bool
    found: bool
    message: str


def _trim_trailing_prose(segment: str) -> str:
    """A candidate block runs from its opening keyword to the *next*
    statement-start match (or end of text) — never cut at a bare blank line,
    since formatted SQL routinely contains blank lines between clauses (PRD
    §11.1). But once a blank-line-separated paragraph no longer looks like a
    clause continuation (e.g. trailing prose such as "如有問題請洽承辦
    人。"), everything from there on is dropped."""
    paragraphs = re.split(r"\n[ \t]*\n", segment)
    kept = [paragraphs[0]]
    for para in paragraphs[1:]:
        first_line = next((ln for ln in para.split("\n") if ln.strip()), "")
        if _CONTINUATION_RE.match(first_line):
            kept.append(para)
        else:
            break
    return "\n\n".join(kept)


def _candidate_blocks(text: str) -> list[str]:
    matches = list(_STATEMENT_START_RE.finditer(text))
    blocks: list[str] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = _trim_trailing_prose(text[m.start() : end]).strip()
        if block:
            blocks.append(block)
    return blocks


def _ensure_semicolon(sql: str) -> str:
    sql = sql.rstrip()
    return sql if sql.endswith(";") else sql + ";"


def _join_candidates(items: list[str]) -> str:
    """Join independently-detected candidates (separate CSV cells, separate
    markdown fences, separate free-text blocks) so the combined text is
    unambiguous multi-statement SQL for sql_parser.py's semicolon-based
    splitter — without this, two SELECTs joined only by a blank line parse
    as one (invalid) statement instead of two."""
    if len(items) <= 1:
        return "\n\n".join(items)
    return "\n\n".join(_ensure_semicolon(item) for item in items)


def _detect_from_markdown(text: str) -> str:
    """PRD §10.2 priority: fenced ```sql/oracle/plsql blocks first, then any
    other fenced block that itself looks SQL-shaped, then free text. Prose
    headings/explanations outside these must never leak into the result."""
    fences = _FENCE_RE.findall(text)
    sql_fences = [b.strip() for _lang, b in fences if _lang.lower() in _SQL_FENCE_LANGS and b.strip()]
    if sql_fences:
        return _join_candidates(sql_fences)

    for lang, body in fences:
        if lang.lower() not in _SQL_FENCE_LANGS and _STATEMENT_START_RE.search(body):
            return body.strip()

    return _join_candidates(_candidate_blocks(text))


def _detect_from_csv(text: str) -> str:
    """PRD §10.3: a cell counts as a SQL candidate only if it starts with a
    statement keyword AND contains a structural keyword (FROM/SET/INTO) —
    guards against misreading a plain-data CSV as SQL."""
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        rows = []

    candidates: list[str] = []
    for row in rows:
        for cell in row:
            cell = cell.strip()
            if len(cell) < 8 or not _STATEMENT_START_RE.match(cell):
                continue
            upper = cell.upper()
            if any(kw in upper for kw in _CSV_REQUIRED_KEYWORDS):
                candidates.append(cell)
    return _join_candidates(candidates)


def _validated_statement_count(text: str) -> int:
    """Statements sql_parser could not even guess a real keyword for
    (statement_type "UNKNOWN") are ordinary prose, not SQL — they must not
    count as "found" (PRD §11.4's three user-facing states never include a
    false positive)."""
    if not text.strip():
        return 0
    return len([s for s in parse_sql_text(text).statements if s.statement_type != "UNKNOWN"])


def detect_sql(text: str, ext: str) -> DetectResult:
    ext = ext.lower()
    if ext == ".sql":
        candidate = text.strip()
    elif ext in (".md", ".markdown"):
        candidate = _detect_from_markdown(text)
    elif ext == ".csv":
        candidate = _detect_from_csv(text)
    else:  # .txt and anything else: free-text scanning
        candidate = _join_candidates(_candidate_blocks(text))
        if not candidate:
            # No keyword-anchored line found at all — the whole file might
            # still just be SQL (e.g. odd leading whitespace); let the
            # parser have the final say rather than declaring failure here.
            candidate = text.strip()

    candidate = candidate.strip()
    count = _validated_statement_count(candidate) if candidate else 0

    if count == 0:
        return DetectResult(sql="", statement_count=0, needs_confirmation=False, found=False, message=_NOT_FOUND_MESSAGE)

    message = (
        "已辨識 1 段 SQL，請確認內容後再開始檢核。"
        if count == 1
        else f"已辨識 {count} 段 SQL，請確認內容後再開始檢核。"
    )
    return DetectResult(sql=candidate, statement_count=count, needs_confirmation=True, found=True, message=message)
