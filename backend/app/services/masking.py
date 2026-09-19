"""Literal masking before SQL text is sent to the AI model (PRD §17.4,
§20, §56: "AI 不得看到原始文字/日期/大數字常數").

Design (verified empirically against sqlglot 30.18 — see
tasks/lessons.md's existing sqlglot findings before assuming anything about
this library):

- We first try `sqlglot.parse_one(raw_sql, read="oracle")` purely as an
  "is this well-formed enough to trust" gate.
- When it parses, the actual text substitution is done with sqlglot's
  *tokenizer* (`sqlglot.tokens.Tokenizer`), not by mutating the AST and
  re-serializing it. This was a deliberate choice after spiking both: walking
  the parsed tree with `tree.find_all(exp.Literal)` does NOT yield nodes in
  left-to-right source order (empirically confirmed — for
  `WHERE B='second' AND A='first' OR C=999999`, `find_all` visits the `OR`
  branch's literal before the `AND` branch's two literals, i.e. 999999,
  'second', 'first' — not source order), which would break the PRD's
  "first-seen order" numbering requirement. Token start/end offsets are
  inherently in source order, are already used elsewhere in this codebase
  (sql_parser.py's `_split_semicolons`), and let us substitute directly into
  the original text — so formatting/casing the reviewer already sees is left
  untouched apart from the masked spans (nicer for a human comparing
  "original SQL" vs the AI's masked view than a fully re-serialized/
  re-cased AST dump would be).
- Bind variables already in the SQL (`:SOME_NAME`) tokenize as a separate
  `COLON` + `VAR`/`NUMBER` token pair, never as `TokenType.STRING`, so they
  are naturally left untouched by masking, which only ever rewrites STRING
  and NUMBER tokens. A positional bind like `:1` tokenizes its digit as a
  NUMBER token preceded by COLON — we explicitly skip masking a NUMBER token
  when the immediately preceding token is COLON, so a (rare) long positional
  bind like `:123456` is never mistaken for a numeric literal.
- If parsing fails outright, we fall back to a conservative, sqlglot-free
  regex pass over the raw text (must never raise, per PRD §56 "AI 絕不可成為
  單點故障" applying transitively to anything feeding the AI path).

Digit-count threshold: PRD asks to mask "numeric literals with 6+ digits"
(dates/IDs/large amounts) while leaving short ordinary integers (e.g. `2`,
`LIMIT 10`) alone. We implement that literally: count digit characters in
the literal's text and mask at >=6. (The PRD parenthetical also lists
"100000" as an example of something "fine to leave" in the same breath as
mentioning the 6-digit rule, which is inconsistent with the rule as stated —
100000 has 6 digits. We follow the explicit, testable "6+ digits" rule
rather than invent an undocumented special case for one literal value; see
this file's tests for the exact boundary.)

Short-ASCII string exception (2026-09-16, `app.yaml: masking.
keep_short_ascii_literal_max_len`): a string literal is left unmasked when
its content (excluding quotes) is at most that many characters AND contains
only ASCII letters/digits/`%`/`_`. This covers Oracle-style short codes and
LIKE patterns such as `'H'`, `'55'`, `'55R'`, `'114%'` — real production SQL
observed in testing routinely uses these, and masking them away left the AI
completely unable to reason about (or rewrite) year-prefix `LIKE` patterns
into range comparisons, which was one confirmed cause of the model always
declining to propose a rewrite. Anything containing a non-ASCII character
(e.g. a Chinese name) or longer than the threshold (dates, ID numbers,
address codes — anything that could plausibly be personal data) is still
always masked, regardless of this exception.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot.tokens import Tokenizer, TokenType

DIALECT = "oracle"
MIN_MASKED_DIGITS = 6
DEFAULT_KEEP_SHORT_ASCII_MAX_LEN = 4

_STR_PREFIX = "STR"
_NUM_PREFIX = "NUM"

_tokenizer = Tokenizer(dialect=DIALECT)

# A literal's content is left unmasked only if it matches this in full
# (ASCII letters/digits/percent/underscore only — no spaces, no punctuation,
# no non-ASCII characters).
_KEEP_SHORT_ASCII_RE = re.compile(r"^[A-Za-z0-9%_]*$")


@dataclass
class MaskResult:
    masked_sql: str
    reverse_map: dict[str, str] = field(default_factory=dict)
    # placeholder -> {"kind": "string"|"number", "length": int,
    # "wildcard": "none"|"leading"|"trailing"|"both", "shape": "digits"|
    # "alnum"|"text"} for every placeholder actually created (never for a
    # literal kept unmasked). Never contains the literal's actual value —
    # sent to the AI (unlike reverse_map) as extra structural context so it
    # can still reason about e.g. "this is a leading-wildcard LIKE pattern"
    # without seeing the real text.
    literal_hints: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------
def mask_sql(raw_sql: str, keep_short_ascii_max_len: int = DEFAULT_KEEP_SHORT_ASCII_MAX_LEN) -> MaskResult:
    """Mask string/large-numeric literals in `raw_sql`, returning the masked
    text plus a placeholder -> original-text reverse mapping. Never raises —
    worst case (unparseable input, or any unexpected error while walking the
    parsed tokens) degrades to the conservative regex fallback.
    """
    if not raw_sql or not raw_sql.strip():
        return MaskResult(masked_sql=raw_sql, reverse_map={})

    try:
        sqlglot.parse_one(raw_sql, read=DIALECT)
    except Exception:
        return _mask_fallback_regex(raw_sql, keep_short_ascii_max_len)

    try:
        return _mask_via_tokens(raw_sql, keep_short_ascii_max_len)
    except Exception:
        return _mask_fallback_regex(raw_sql, keep_short_ascii_max_len)


def unmask_sql(text: str | None, reverse_map: dict[str, str]) -> str | None:
    """Reverse-substitute known `:STR_NNN` / `:NUM_NNN` placeholders back to
    their original literal text (used on the AI's `suggested_sql.sql`, so a
    human reviewer sees real values, not placeholders, in the rewrite).
    Placeholders with no known mapping are left as-is (the original SQL may
    legitimately contain a bind named like one; ai_service decides what to do
    with the ones the model invented, see `scrub_invented_placeholders`).
    Never raises.
    """
    if not text:
        return text
    try:
        return _PLACEHOLDER_RE.sub(lambda m: reverse_map.get(m.group(0), m.group(0)), text)
    except Exception:
        return text


# What a model-invented `:STR_NNN` / `:NUM_NNN` becomes (see below).
INVENTED_PLACEHOLDER = ":VALUE"


def scrub_invented_placeholders(text: str | None, original_sql: str) -> str | None:
    """2026-09-17 blind-spot fix: the model sometimes invents a `:STR_001`-
    style bind of its own (e.g. when suggesting a WHERE for a statement that
    had no literal at all). After unmasking, any placeholder that is neither
    in the reverse map nor literally present in the original SQL is masking
    internals leaking to the reviewer — rewrite it to the neutral `:VALUE`.
    Binds that the user's own SQL already contains are left untouched."""
    if not text:
        return text
    try:
        return _PLACEHOLDER_RE.sub(lambda m: m.group(0) if m.group(0) in original_sql else INVENTED_PLACEHOLDER, text)
    except Exception:
        return text


# ---------------------------------------------------------------------------
# Literal hint classification (shared by both masking paths)
# ---------------------------------------------------------------------------
def _literal_shape(inner: str) -> str:
    if inner.isdigit():
        return "digits"
    if inner.isalnum():
        return "alnum"
    return "text"


def _literal_wildcard(inner: str) -> str:
    leading = inner.startswith("%") or inner.startswith("_")
    trailing = inner.endswith("%") or inner.endswith("_")
    if leading and trailing:
        return "both"
    if leading:
        return "leading"
    if trailing:
        return "trailing"
    return "none"


def _literal_hint(kind: str, inner: str, oracle_literal_type: str | None = None) -> dict[str, Any]:
    hint: dict[str, Any] = {
        "kind": kind,
        "length": len(inner),
        "wildcard": _literal_wildcard(inner) if kind == "string" else "none",
        "shape": _literal_shape(inner),
    }
    if oracle_literal_type is not None:
        hint["oracle_literal_type"] = oracle_literal_type
    return hint


def _oracle_typed_literal(raw_sql: str, literal_start: int) -> str | None:
    """Return DATE/TIMESTAMP when a string token is an Oracle typed literal.

    This preserves type context without revealing the literal value itself.
    """
    prefix = raw_sql[max(0, literal_start - 24) : literal_start]
    match = re.search(r"\b(DATE|TIMESTAMP)\s*$", prefix, re.IGNORECASE)
    return match.group(1).lower() if match else None


def _is_keepable_short_ascii(inner: str, max_len: int) -> bool:
    return len(inner) <= max_len and bool(_KEEP_SHORT_ASCII_RE.fullmatch(inner))


# ---------------------------------------------------------------------------
# Primary path: token-position masking on the original text
# ---------------------------------------------------------------------------
def _digit_count(text: str) -> int:
    return sum(ch.isdigit() for ch in text)


def _mask_via_tokens(raw_sql: str, keep_short_ascii_max_len: int) -> MaskResult:
    tokens = _tokenizer.tokenize(raw_sql)
    out: list[str] = []
    reverse_map: dict[str, str] = {}
    literal_hints: dict[str, dict[str, Any]] = {}
    last = 0
    str_n = 0
    num_n = 0

    for i, tok in enumerate(tokens):
        if tok.token_type == TokenType.STRING:
            # tok.text is the string's content with quotes already stripped
            # (confirmed empirically) — exactly what the keep-short-ASCII
            # check and the hint classifier need.
            if _is_keepable_short_ascii(tok.text, keep_short_ascii_max_len):
                continue  # left as-is in the output; no placeholder, no counter increment
            str_n += 1
            placeholder = f":{_STR_PREFIX}_{str_n:03d}"
            literal_hints[placeholder] = _literal_hint(
                "string", tok.text, _oracle_typed_literal(raw_sql, tok.start)
            )
        elif tok.token_type == TokenType.NUMBER:
            if _digit_count(tok.text) < MIN_MASKED_DIGITS:
                continue
            prev = tokens[i - 1] if i > 0 else None
            if prev is not None and prev.token_type == TokenType.COLON:
                continue  # positional bind variable (e.g. :123456), not a literal
            num_n += 1
            placeholder = f":{_NUM_PREFIX}_{num_n:03d}"
            literal_hints[placeholder] = _literal_hint("number", tok.text)
        else:
            continue

        original = raw_sql[tok.start : tok.end + 1]
        reverse_map[placeholder] = original
        out.append(raw_sql[last : tok.start])
        out.append(placeholder)
        last = tok.end + 1

    out.append(raw_sql[last:])
    return MaskResult(masked_sql="".join(out), reverse_map=reverse_map, literal_hints=literal_hints)


# ---------------------------------------------------------------------------
# Fallback path: sqlglot-free regex masking of raw text (parse failed)
# ---------------------------------------------------------------------------
# Mirrors sql_parser.py's `_STRING_LITERAL_RE`: single-quoted string, with
# '' as the escaped-quote form.
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")

# 6+ consecutive digits (optionally with a decimal tail), not immediately
# preceded by a word character, `:` (bind variable) or `.` (already-consumed
# decimal), and not immediately followed by a word character (so digits
# embedded in an identifier like TABLE123456 are never matched).
_NUMERIC_LITERAL_RE = re.compile(r"(?<![:\w.])\d{6,}(?:\.\d+)?(?!\w)")

_PLACEHOLDER_RE = re.compile(r":(?:STR|NUM)_\d+")


def _mask_fallback_regex(raw_sql: str, keep_short_ascii_max_len: int) -> MaskResult:
    reverse_map: dict[str, str] = {}
    literal_hints: dict[str, dict[str, Any]] = {}
    counters = {"str": 0, "num": 0}

    def _sub_str(m: re.Match[str]) -> str:
        full = m.group(0)
        inner = full[1:-1] if len(full) >= 2 else ""
        if _is_keepable_short_ascii(inner, keep_short_ascii_max_len):
            return full
        counters["str"] += 1
        placeholder = f":{_STR_PREFIX}_{counters['str']:03d}"
        reverse_map[placeholder] = full
        literal_hints[placeholder] = _literal_hint(
            "string", inner, _oracle_typed_literal(raw_sql, m.start())
        )
        return placeholder

    # Mask strings first so any digits *inside* a string literal are removed
    # from the text before the numeric pass runs over it (avoids double
    # masking / corrupting an already-replaced span).
    masked = _STRING_LITERAL_RE.sub(_sub_str, raw_sql)

    def _sub_num(m: re.Match[str]) -> str:
        counters["num"] += 1
        placeholder = f":{_NUM_PREFIX}_{counters['num']:03d}"
        reverse_map[placeholder] = m.group(0)
        literal_hints[placeholder] = _literal_hint("number", m.group(0))
        return placeholder

    masked = _NUMERIC_LITERAL_RE.sub(_sub_num, masked)
    return MaskResult(masked_sql=masked, reverse_map=reverse_map, literal_hints=literal_hints)


# ---------------------------------------------------------------------------
# De-identification for the SQL archive (backend/app/services/sql_archive.py)
# — stricter than `mask_sql`: also strips non-hint comments (free-text
# comments routinely contain applicant names/notes) and sweeps the residual
# text for ID-number/email/long-digit shapes as defense in depth. Never
# returns the reverse map (the archive must never be able to recover
# original values) and never raises — any unexpected failure degrades to a
# fixed marker that leaks nothing, rather than ever falling back to raw SQL.
# ---------------------------------------------------------------------------
_BLOCK_COMMENT_NON_HINT_RE = re.compile(r"/\*(?!\+)(?:[^*]|\*(?!/))*\*/", re.DOTALL)
_LINE_COMMENT_NON_HINT_RE = re.compile(r"--(?!\+)[^\n]*")
_TW_ID_LIKE_RE = re.compile(r"\b[A-Za-z][12]\d{8}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_LONG_DIGIT_RUN_RE = re.compile(r"(?<!\w)\d{8,}(?!\w)")

DEIDENTIFY_FAILED_MARKER = "[DEIDENTIFY_FAILED]"


def _strip_non_hint_comments(text: str) -> str:
    text = _BLOCK_COMMENT_NON_HINT_RE.sub(" ", text)
    text = _LINE_COMMENT_NON_HINT_RE.sub("", text)
    return text


def deidentify_sql(raw_sql: str) -> str:
    """Best-effort, defense-in-depth de-identification for the SQL archive.
    Not used on the AI request path (that stays on `mask_sql`, which must
    preserve as much structure as possible for the model to reason about);
    this is deliberately more aggressive since its output may be read by a
    human or another AI process later, offline, with no re-validation step.
    """
    if not raw_sql or not raw_sql.strip():
        return raw_sql
    try:
        masked = mask_sql(raw_sql).masked_sql
        stripped = _strip_non_hint_comments(masked)
        stripped = _TW_ID_LIKE_RE.sub("[REDACTED]", stripped)
        stripped = _EMAIL_RE.sub("[REDACTED]", stripped)
        stripped = _LONG_DIGIT_RUN_RE.sub("[REDACTED]", stripped)
        return stripped
    except Exception:
        return DEIDENTIFY_FAILED_MARKER
