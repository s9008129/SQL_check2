"""Text normalization applied before SQL parsing (PRD §11.1, §11.2).

Two independent concerns, each with its own tested surface:

1. Character-level normalization: smart quotes / full-width punctuation /
   NBSP / zero-width characters routinely appear in text pasted from Word or
   exported from PDF, and silently break sqlglot's tokenizer (e.g. a
   full-width "＝" is not recognized as "=").
2. Separating SQL*Plus client-only commands from the SQL statements they
   surround, WITHOUT mis-detecting a genuine `UPDATE t SET col = 1` line as
   the SQL*Plus `SET` command (see `_SQLPLUS_SET_RE` below for the guard).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_SMART_QUOTES = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "′": "'",
    "″": '"',
}
_FULLWIDTH_PUNCT = {
    "，": ",",
    "。": ".",
    "；": ";",
    "：": ":",
    "（": "(",
    "）": ")",
    "！": "!",
    "？": "?",
    "＝": "=",
    "＜": "<",
    "＞": ">",
    "『": "'",
    "』": "'",
    "「": '"',
    "」": '"',
}
_ZERO_WIDTH_RE = re.compile("[​‌‍﻿]")
_NBSP_RE = re.compile("[   ]")
_TRANSLATE_TABLE = str.maketrans({**_SMART_QUOTES, **_FULLWIDTH_PUNCT})


def normalize_text(text: str) -> str:
    """Fold smart quotes / full-width punctuation / NBSP / zero-width chars
    to their plain equivalents and normalize line endings. Idempotent."""
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _NBSP_RE.sub(" ", text)
    text = text.translate(_TRANSLATE_TABLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


# ---------------------------------------------------------------------------
# SQL*Plus command stripping (PRD §11.2)
# ---------------------------------------------------------------------------
_SQLPLUS_ONLY_KEYWORDS = (
    "SPOOL",
    "PROMPT",
    "DEFINE",
    "UNDEFINE",
    "WHENEVER",
    "EXIT",
    "QUIT",
    "CONNECT",
    "DISCONNECT",
    "COLUMN",
    "TTITLE",
    "BTITLE",
    "CLEAR",
    "PAUSE",
    "SHOW",
    "DESCRIBE",
    "ACCEPT",
    "HOST",
    "REM",
    "REMARK",
)
_SQLPLUS_ONLY_RE = re.compile(
    r"^\s*(" + "|".join(_SQLPLUS_ONLY_KEYWORDS) + r")\b", re.IGNORECASE
)
# SQL*Plus "SET <option> <value>" (e.g. SET LINESIZE 200, SET SERVEROUTPUT ON).
# Deliberately requires the line to contain no "=" so a real
# `UPDATE t SET col = 1` continuation line is never mistaken for this.
_SQLPLUS_SET_RE = re.compile(r"^\s*SET\s+\S+", re.IGNORECASE)
_SCRIPT_INCLUDE_RE = re.compile(r"^\s*@@?\S+")


def _is_sqlplus_line(line: str) -> bool:
    if _SQLPLUS_ONLY_RE.match(line):
        return True
    if _SCRIPT_INCLUDE_RE.match(line):
        return True
    return bool(_SQLPLUS_SET_RE.match(line) and "=" not in line)


@dataclass
class SplitPlusResult:
    sql_text: str
    sqlplus_commands: list[str] = field(default_factory=list)


def strip_sqlplus_commands(text: str) -> SplitPlusResult:
    """Remove SQL*Plus client-only command lines, returning the remaining
    text plus the list of removed command lines (for diagnostics only; PRD
    does not require showing these to the user). A bare "/" line is left
    untouched here — sql_parser.py's PL/SQL block splitter needs it as the
    block terminator.
    """
    kept: list[str] = []
    removed: list[str] = []
    for line in text.split("\n"):
        if _is_sqlplus_line(line):
            removed.append(line.strip())
        else:
            kept.append(line)
    return SplitPlusResult(sql_text="\n".join(kept), sqlplus_commands=removed)
