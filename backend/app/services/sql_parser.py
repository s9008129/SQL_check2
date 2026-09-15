"""Oracle-dialect SQL parsing and fact extraction (PRD §11, §12).

This module turns raw SQL text into a list of `ParsedStatement` objects that
`rule_engine.py` and `improvement_score.py` consume. It never rewrites SQL
and never decides compliance — it only extracts facts (tables, WHERE
presence, OR/LIKE/function findings, hint text, structural-complexity
flags). Rule *judgment* stays entirely in `rule_engine.py`, per PRD §13.1
("規則引擎是 deterministic. Gemma 不負責決定 ...").

Two correctness findings from `tests/_spike_sqlglot.py` /
`tests/_spike_sqlglot2.py` (see tasks/lessons.md) shape this module:

- `error_level=ErrorLevel.RAISE` does NOT reliably raise on malformed SQL;
  garbage like "SELEKT * FRM T" silently parses into an unrelated
  expression (e.g. `Alias(Mul(Column, Column))`). We additionally require
  the top-level node to be one of the expected statement types.
- `exp.And` / `exp.Or` are themselves subclasses of `exp.Func` (MRO:
  And -> Connector -> Binary -> Func). A naive `isinstance(node, exp.Func)`
  walk over a WHERE clause would misreport the whole boolean expression as
  "a function on a condition column". Function-on-column detection instead
  walks `exp.Predicate` nodes (EQ/NEQ/GT/.../Like/In/Between — a base class
  that excludes And/Or) and inspects only their direct comparison operands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.tokens import Tokenizer, TokenType

from app.services.text_normalize import normalize_text, strip_sqlplus_commands

DIALECT = "oracle"

PARSE_FAILED_MESSAGE = "SQL 結構較複雜，目前無法完整解析，請確認 SQL 內容後再試一次。"

_STATEMENT_EXPR_TYPES = (
    exp.Select,
    exp.Update,
    exp.Delete,
    exp.Insert,
    exp.Merge,
    exp.Union,
    exp.Except,
    exp.Intersect,
)

_PLSQL_START_RE = re.compile(
    r"^\s*(DECLARE\b|BEGIN\b|CREATE(\s+OR\s+REPLACE)?\s+"
    r"(PROCEDURE|FUNCTION|PACKAGE\s+BODY|PACKAGE|TRIGGER)\b)",
    re.IGNORECASE,
)
_SLASH_TERMINATOR_RE = re.compile(r"^\s*/\s*$")

_HINT_BLOCK_RE = re.compile(r"/\*\+(.*?)\*/", re.DOTALL)
_HINT_LINE_RE = re.compile(r"--\+([^\n]*)")
_PARALLEL_RE = re.compile(r"\bPARALLEL(_INDEX)?\b", re.IGNORECASE)
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")

_LEADING_KEYWORD_RE = re.compile(
    r"^\s*(WITH|SELECT|UPDATE|DELETE|INSERT|MERGE)\b", re.IGNORECASE
)
_TABLE_GUESS_RE = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([A-Za-z_][A-Za-z0-9_$#]*(?:\.[A-Za-z_][A-Za-z0-9_$#]*)?)",
    re.IGNORECASE,
)

_tokenizer = Tokenizer(dialect=DIALECT)


@dataclass
class ParsedStatement:
    index: int
    raw_sql: str
    statement_type: str  # SELECT / UPDATE / DELETE / INSERT / MERGE / PLSQL / UNKNOWN
    parse_status: str  # "ok" | "failed"
    tree: exp.Expression | None = None
    tables: set[str] = field(default_factory=set)
    table_count: int = 0
    where_applicable: bool = False
    has_where: bool | None = None  # None = unknown (parse failed / not applicable)
    or_findings: list[str] = field(default_factory=list)
    like_findings: list[str] = field(default_factory=list)
    function_findings: list[str] = field(default_factory=list)
    hint_evidence: str | None = None
    complexity_flags: set[str] = field(default_factory=set)


@dataclass
class ParsedSql:
    statements: list[ParsedStatement]
    sqlplus_commands: list[str]
    parse_message: str | None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------
def parse_sql_text(raw_text: str) -> ParsedSql:
    normalized = normalize_text(raw_text)
    split = strip_sqlplus_commands(normalized)

    statements: list[ParsedStatement] = []
    idx = 0
    for chunk_text, is_plsql in _split_top_level(split.sql_text):
        if not chunk_text.strip():
            continue
        if is_plsql:
            statements.append(_build_plsql_statement(idx, chunk_text))
            idx += 1
            continue
        for stmt_text in _split_semicolons(chunk_text):
            if not stmt_text.strip():
                continue
            statements.append(_build_statement(idx, stmt_text))
            idx += 1

    analyzable = [s for s in statements if s.statement_type != "PLSQL"]
    parse_message = None
    if not statements or (analyzable and all(s.parse_status == "failed" for s in analyzable)):
        parse_message = PARSE_FAILED_MESSAGE

    return ParsedSql(
        statements=statements, sqlplus_commands=split.sqlplus_commands, parse_message=parse_message
    )


# ---------------------------------------------------------------------------
# Statement splitting
# ---------------------------------------------------------------------------
def _split_top_level(text: str) -> list[tuple[str, bool]]:
    """Split into ordered (raw_segment, is_plsql) chunks. A PL/SQL block runs
    from a DECLARE/BEGIN/CREATE ... (PROCEDURE|FUNCTION|PACKAGE|TRIGGER) line
    to a standalone "/" terminator line or EOF (PRD §11.2 PL/SQL DECLARE/BEGIN).
    """
    lines = text.split("\n")
    chunks: list[tuple[str, bool]] = []
    buf: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if _PLSQL_START_RE.match(line):
            if buf:
                chunks.append(("\n".join(buf), False))
                buf = []
            plsql_lines = [line]
            i += 1
            while i < n and not _SLASH_TERMINATOR_RE.match(lines[i]):
                plsql_lines.append(lines[i])
                i += 1
            if i < n:  # consume the terminating "/" line itself
                i += 1
            chunks.append(("\n".join(plsql_lines), True))
            continue
        buf.append(line)
        i += 1
    if buf:
        chunks.append(("\n".join(buf), False))
    return chunks


def _split_semicolons(text: str) -> list[str]:
    """Split on top-level statement-terminating semicolons using sqlglot's
    tokenizer, so semicolons inside string literals or comments never split
    a statement (verified in tests/_spike_sqlglot.py block 17)."""
    try:
        tokens = _tokenizer.tokenize(text)
    except Exception:
        return re.split(r";", text)

    segments: list[str] = []
    start = 0
    for tok in tokens:
        if tok.token_type == TokenType.SEMICOLON:
            segments.append(text[start : tok.end + 1])
            start = tok.end + 1
    segments.append(text[start:])
    return segments


# ---------------------------------------------------------------------------
# Per-statement parsing
# ---------------------------------------------------------------------------
def _try_parse(segment_text: str) -> exp.Expression | None:
    try:
        tree = sqlglot.parse_one(segment_text, read=DIALECT)
    except ParseError:
        return None
    except Exception:
        return None
    if not isinstance(tree, _STATEMENT_EXPR_TYPES):
        # Parsed "successfully" but into an unrelated expression (e.g. a
        # typo'd keyword reinterpreted as a column/alias) — see lessons.md.
        return None
    return tree


def _guess_statement_type_from_text(text: str) -> str:
    m = _LEADING_KEYWORD_RE.match(text)
    if not m:
        return "UNKNOWN"
    kw = m.group(1).upper()
    return "SELECT" if kw == "WITH" else kw


def _guess_tables_from_text(text: str) -> set[str]:
    scan_text = _blank_string_literals(text)
    tables = set()
    for m in _TABLE_GUESS_RE.finditer(scan_text):
        name = m.group(1).split(".")[-1].upper()
        tables.add(name)
    return tables


def _build_plsql_statement(index: int, raw_sql: str) -> ParsedStatement:
    stmt = ParsedStatement(
        index=index, raw_sql=raw_sql, statement_type="PLSQL", parse_status="failed"
    )
    stmt.hint_evidence = detect_parallel_hint_text(raw_sql)
    stmt.tables = _guess_tables_from_text(raw_sql)
    stmt.table_count = len(stmt.tables)
    stmt.where_applicable = False
    stmt.has_where = None
    return stmt


def _build_statement(index: int, raw_sql: str) -> ParsedStatement:
    tree = _try_parse(raw_sql)
    hint_evidence = detect_parallel_hint_text(raw_sql)

    if tree is None:
        stype = _guess_statement_type_from_text(raw_sql)
        stmt = ParsedStatement(
            index=index, raw_sql=raw_sql, statement_type=stype, parse_status="failed"
        )
        stmt.hint_evidence = hint_evidence
        stmt.tables = _guess_tables_from_text(raw_sql)
        stmt.table_count = len(stmt.tables)
        # UNKNOWN (no recognizable leading keyword at all, e.g. "SELEKT ...")
        # is treated as WHERE-applicable-but-unknown too, not "not
        # applicable": we genuinely cannot tell whether this needed a WHERE
        # clause, which is a REVIEW situation (PRD §15 "不得亂判 PASS"), not
        # an N/A one. Only a confirmed PLSQL/MERGE classification is a real
        # N/A (handled elsewhere, never reaches this branch as "UNKNOWN").
        stmt.where_applicable = stype in ("SELECT", "UPDATE", "DELETE", "UNKNOWN")
        stmt.has_where = None
        return stmt

    stype = _statement_type_name(tree)
    stmt = ParsedStatement(index=index, raw_sql=raw_sql, statement_type=stype, parse_status="ok", tree=tree)
    stmt.hint_evidence = hint_evidence
    stmt.tables = {t.name.upper() for t in tree.find_all(exp.Table) if t.name}
    stmt.table_count = len(stmt.tables)

    where_applicable, has_where = _where_check(tree, stype)
    stmt.where_applicable = where_applicable
    stmt.has_where = has_where

    scope_roots = _condition_scope_roots(tree, stype)
    stmt.or_findings = _find_or(scope_roots)
    stmt.like_findings = _find_leading_wildcard_like(scope_roots)
    stmt.function_findings = _find_function_on_condition(scope_roots)
    stmt.complexity_flags = _safe_complexity_flags(tree, stype)
    return stmt


def _statement_type_name(tree: exp.Expression) -> str:
    if isinstance(tree, (exp.Select, exp.Union, exp.Except, exp.Intersect)):
        return "SELECT"
    if isinstance(tree, exp.Update):
        return "UPDATE"
    if isinstance(tree, exp.Delete):
        return "DELETE"
    if isinstance(tree, exp.Insert):
        return "INSERT"
    if isinstance(tree, exp.Merge):
        return "MERGE"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Parallel hint detection (token/text-level — see lessons.md: exp.Hint is not
# consistently populated across statement types or hint comment styles).
# ---------------------------------------------------------------------------
def _blank_string_literals(text: str) -> str:
    return _STRING_LITERAL_RE.sub(lambda m: " " * len(m.group(0)), text)


def detect_parallel_hint_text(raw_sql: str) -> str | None:
    """Return the raw hint comment text if it requests a PARALLEL hint,
    scanning both `/*+ ... */` and `--+ ...` forms. String literals are
    blanked (length-preserving) first so a literal containing hint-like text
    can never trigger a false positive; NOPARALLEL is naturally excluded
    because `\\bPARALLEL\\b` requires a word boundary that does not exist
    between "NO" and "PARALLEL" in a single identifier token.
    """
    scan_text = _blank_string_literals(raw_sql)
    for m in _HINT_BLOCK_RE.finditer(scan_text):
        if _PARALLEL_RE.search(m.group(1)):
            return raw_sql[m.start() : m.end()].strip()
    for m in _HINT_LINE_RE.finditer(scan_text):
        if _PARALLEL_RE.search(m.group(1)):
            return raw_sql[m.start() : m.end()].strip()
    return None


# ---------------------------------------------------------------------------
# WHERE applicability / presence (PRD §8, §13, §14)
# ---------------------------------------------------------------------------
def _flatten_set_op(tree: exp.Expression) -> list[exp.Expression]:
    if isinstance(tree, (exp.Union, exp.Except, exp.Intersect)):
        branches: list[exp.Expression] = []
        for side in (tree.left, tree.right):
            if isinstance(side, (exp.Union, exp.Except, exp.Intersect)):
                branches.extend(_flatten_set_op(side))
            elif side is not None:
                branches.append(side)
        return branches
    return [tree]


def _select_has_real_from(select: exp.Select) -> bool:
    """False for `SELECT 1` (no FROM) or bare `SELECT ... FROM DUAL` with no
    joins — WHERE is not meaningfully applicable to either (PRD §14)."""
    # NOTE: sqlglot 30.18 stores the FROM clause under the args key "from_"
    # (trailing underscore, since "from" is a Python keyword) — confirmed
    # empirically; `select.args.get("from")` silently returns None. See
    # tasks/lessons.md.
    from_ = select.args.get("from_")
    if from_ is None:
        return False
    direct = from_.this
    return not (
        isinstance(direct, exp.Table)
        and direct.name
        and direct.name.upper() == "DUAL"
        and not select.args.get("joins")
    )


def _own_where(select: exp.Select) -> bool:
    return select.args.get("where") is not None


def _where_check(tree: exp.Expression, stype: str) -> tuple[bool, bool | None]:
    if stype == "SELECT":
        branches = [b for b in _flatten_set_op(tree) if isinstance(b, exp.Select)]
        applicable = [b for b in branches if _select_has_real_from(b)]
        if not applicable:
            return False, None
        return True, all(_own_where(b) for b in applicable)
    if stype in ("UPDATE", "DELETE"):
        return True, tree.args.get("where") is not None
    if stype == "INSERT":
        source = tree.args.get("expression")
        if isinstance(source, (exp.Select, exp.Union, exp.Except, exp.Intersect)):
            return _where_check(source, "SELECT")
        return False, None  # INSERT ... VALUES — WHERE concept does not apply
    return False, None  # MERGE / UNKNOWN — not evaluated by R002


# ---------------------------------------------------------------------------
# Condition-scope collection (WHERE / HAVING / JOIN ON — PRD's stated scope
# for R004/R005/R006) and the findings that walk it.
# ---------------------------------------------------------------------------
def _collect_select_scope(select: exp.Select, roots: list[exp.Expression]) -> None:
    where = select.args.get("where")
    if where is not None:
        roots.append(where)
    having = select.args.get("having")
    if having is not None:
        roots.append(having)
    for join in select.args.get("joins") or []:
        on = join.args.get("on")
        if on is not None:
            roots.append(on)


def _condition_scope_roots(tree: exp.Expression, stype: str) -> list[exp.Expression]:
    roots: list[exp.Expression] = []
    if stype == "SELECT":
        for branch in _flatten_set_op(tree):
            if isinstance(branch, exp.Select):
                _collect_select_scope(branch, roots)
    elif stype in ("UPDATE", "DELETE"):
        where = tree.args.get("where")
        if where is not None:
            roots.append(where)
    elif stype == "INSERT":
        source = tree.args.get("expression")
        if isinstance(source, exp.Select):
            _collect_select_scope(source, roots)
        elif isinstance(source, (exp.Union, exp.Except, exp.Intersect)):
            for branch in _flatten_set_op(source):
                if isinstance(branch, exp.Select):
                    _collect_select_scope(branch, roots)
    elif stype == "MERGE":
        on = tree.args.get("on")
        if on is not None:
            roots.append(on)
    return roots


def _find_or(scope_roots: list[exp.Expression]) -> list[str]:
    findings: list[str] = []
    for root in scope_roots:
        for node in root.find_all(exp.Or):
            findings.append(node.sql(dialect=DIALECT))
    return findings


def _leading_wildcard_literal(pattern: exp.Expression | None) -> str | None:
    if isinstance(pattern, exp.Literal) and pattern.is_string:
        value = pattern.this
        if value.startswith("%") or value.startswith("_"):
            return value if len(value) <= 12 else value[:12] + "…"
        return None
    if isinstance(pattern, exp.DPipe):
        return _leading_wildcard_literal(pattern.this)
    return None


def _find_leading_wildcard_like(scope_roots: list[exp.Expression]) -> list[str]:
    findings: list[str] = []
    for root in scope_roots:
        for lk in root.find_all(exp.Like, exp.ILike):
            pattern = lk.args.get("expression")
            wildcard = _leading_wildcard_literal(pattern)
            if wildcard is not None:
                column_text = lk.this.sql(dialect=DIALECT)
                findings.append(f"{column_text} LIKE '{wildcard}'")
    return findings


def _find_function_on_condition(scope_roots: list[exp.Expression]) -> list[str]:
    findings: list[str] = []
    seen: set[str] = set()
    for root in scope_roots:
        for pred in root.find_all(exp.Predicate):
            if isinstance(pred, (exp.Between, exp.In)):
                sides = [pred.this]
            else:
                sides = [pred.args.get("this"), pred.args.get("expression")]
            for side in sides:
                # `exp.Connector` (And/Or) is technically an exp.Func subclass
                # in this sqlglot version — see lessons.md — excluded defensively
                # even though exp.Predicate already never yields And/Or itself.
                # The function must also actually wrap a *column* — e.g.
                # `A.CREATED >= TRUNC(SYSDATE)` wraps a constant, not the
                # condition column, and is the PRD-recommended pattern
                # (PRD §31), not a finding.
                if (
                    isinstance(side, exp.Func)
                    and not isinstance(side, exp.Connector)
                    and side.find(exp.Column) is not None
                ):
                    text = side.sql(dialect=DIALECT)
                    if text not in seen:
                        seen.add(text)
                        findings.append(text)
    return findings


# ---------------------------------------------------------------------------
# Structural-complexity flags (advisory only — feeds improvement_score.py's S
# component and the AI candidate-SQL gate, never a BLOCK/NOTICE rule). Best
# effort: any unexpected AST shape degrades to "no flag" rather than raising,
# since imprecision here only affects an advisory score, not compliance.
# ---------------------------------------------------------------------------
_AGG_FUNC_NAMES = {"COUNT", "SUM", "AVG", "MIN", "MAX", "LISTAGG", "STDDEV", "VARIANCE", "MEDIAN"}


def _safe_complexity_flags(tree: exp.Expression, stype: str) -> set[str]:
    try:
        return _complexity_flags(tree, stype)
    except Exception:
        return set()


def _has_aggregate(select: exp.Select) -> bool:
    for item in select.expressions:
        for f in item.find_all(exp.Func):
            if isinstance(f, getattr(exp, "AggFunc", ())) or type(f).__name__.upper() in _AGG_FUNC_NAMES:
                return True
    return False


def _is_correlated(select: exp.Select, outer_aliases: set[str]) -> bool:
    where = select.args.get("where")
    if where is None:
        return False
    own_aliases = {t.alias_or_name.upper() for t in select.find_all(exp.Table) if t.alias_or_name}
    for col in where.find_all(exp.Column):
        tbl = (col.table or "").upper()
        if tbl and tbl not in own_aliases and tbl in outer_aliases:
            return True
    return False


def _complexity_flags(tree: exp.Expression, stype: str) -> set[str]:
    flags: set[str] = set()

    for node in tree.find_all(exp.Union, exp.Except, exp.Intersect):
        flags.add("set_operation")
        if node.args.get("distinct") is not False:
            flags.add("distinct_or_union")

    branches = _flatten_set_op(tree) if stype == "SELECT" else [tree]
    selects = [b for b in branches if isinstance(b, exp.Select)]
    outer_aliases = {t.alias_or_name.upper() for t in tree.find_all(exp.Table) if t.alias_or_name}

    for select in selects:
        if select.args.get("distinct"):
            flags.add("distinct")
        if any(isinstance(e, exp.Star) for e in select.expressions):
            flags.add("select_star")
        if select.args.get("group") or _has_aggregate(select):
            flags.add("group_by_aggregate")
        if list(select.find_all(exp.Window)):
            flags.add("window_function")
        if select.args.get("connect"):
            flags.add("connect_by")
        for col in select.find_all(exp.Column):
            if col.args.get("join_mark"):
                flags.add("outer_join")
                break
        joins = select.args.get("joins") or []
        for join in joins:
            side = str(join.args.get("side") or "").upper()
            kind = str(join.args.get("kind") or "").upper()
            if side in ("LEFT", "RIGHT", "FULL"):
                flags.add("outer_join")
            if not join.args.get("on") and not join.args.get("using") and kind != "CROSS":
                # Covers both an ANSI `JOIN` with no condition and an
                # old-style comma join `FROM T1, T2` (sqlglot represents the
                # latter as an on-less Join too — verified empirically).
                flags.add("cartesian_join")
        for rn in select.find_all(exp.Column):
            if rn.name and rn.name.upper() == "ROWNUM":
                flags.add("rownum")
                break
        for in_node in select.find_all(exp.In):
            if in_node.args.get("query") is not None:
                negated = bool(in_node.args.get("is_not")) or isinstance(in_node.parent, exp.Not)
                if negated:
                    flags.add("not_in_subquery")
        for sub in select.find_all(exp.Select):
            if sub is select:
                continue
            if _is_correlated(sub, outer_aliases):
                flags.add("correlated_subquery")
                break

    return flags
