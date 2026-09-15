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
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot.tokens import Tokenizer, TokenType

DIALECT = "oracle"
MIN_MASKED_DIGITS = 6

_STR_PREFIX = "STR"
_NUM_PREFIX = "NUM"

_tokenizer = Tokenizer(dialect=DIALECT)


@dataclass
class MaskResult:
    masked_sql: str
    reverse_map: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------
def mask_sql(raw_sql: str) -> MaskResult:
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
        return _mask_fallback_regex(raw_sql)

    try:
        return _mask_via_tokens(raw_sql)
    except Exception:
        return _mask_fallback_regex(raw_sql)


def unmask_sql(text: str | None, reverse_map: dict[str, str]) -> str | None:
    """Reverse-substitute known `:STR_NNN` / `:NUM_NNN` placeholders back to
    their original literal text (used on the AI's `suggested_sql.sql`, so a
    human reviewer sees real values, not placeholders, in the rewrite).
    Placeholders with no known mapping are left as-is; never raises.
    """
    if not text:
        return text
    try:
        return _PLACEHOLDER_RE.sub(lambda m: reverse_map.get(m.group(0), m.group(0)), text)
    except Exception:
        return text


# ---------------------------------------------------------------------------
# Primary path: token-position masking on the original text
# ---------------------------------------------------------------------------
def _digit_count(text: str) -> int:
    return sum(ch.isdigit() for ch in text)


def _mask_via_tokens(raw_sql: str) -> MaskResult:
    tokens = _tokenizer.tokenize(raw_sql)
    out: list[str] = []
    reverse_map: dict[str, str] = {}
    last = 0
    str_n = 0
    num_n = 0

    for i, tok in enumerate(tokens):
        if tok.token_type == TokenType.STRING:
            str_n += 1
            placeholder = f":{_STR_PREFIX}_{str_n:03d}"
        elif tok.token_type == TokenType.NUMBER:
            if _digit_count(tok.text) < MIN_MASKED_DIGITS:
                continue
            prev = tokens[i - 1] if i > 0 else None
            if prev is not None and prev.token_type == TokenType.COLON:
                continue  # positional bind variable (e.g. :123456), not a literal
            num_n += 1
            placeholder = f":{_NUM_PREFIX}_{num_n:03d}"
        else:
            continue

        original = raw_sql[tok.start : tok.end + 1]
        reverse_map[placeholder] = original
        out.append(raw_sql[last : tok.start])
        out.append(placeholder)
        last = tok.end + 1

    out.append(raw_sql[last:])
    return MaskResult(masked_sql="".join(out), reverse_map=reverse_map)


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


def _mask_fallback_regex(raw_sql: str) -> MaskResult:
    reverse_map: dict[str, str] = {}
    counters = {"str": 0, "num": 0}

    def _sub_str(m: re.Match[str]) -> str:
        counters["str"] += 1
        placeholder = f":{_STR_PREFIX}_{counters['str']:03d}"
        reverse_map[placeholder] = m.group(0)
        return placeholder

    # Mask strings first so any digits *inside* a string literal are removed
    # from the text before the numeric pass runs over it (avoids double
    # masking / corrupting an already-replaced span).
    masked = _STRING_LITERAL_RE.sub(_sub_str, raw_sql)

    def _sub_num(m: re.Match[str]) -> str:
        counters["num"] += 1
        placeholder = f":{_NUM_PREFIX}_{counters['num']:03d}"
        reverse_map[placeholder] = m.group(0)
        return placeholder

    masked = _NUMERIC_LITERAL_RE.sub(_sub_num, masked)
    return MaskResult(masked_sql=masked, reverse_map=reverse_map)
