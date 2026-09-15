"""Deterministic rule engine (PRD §13, §15). Rule *judgment* lives entirely
here and nowhere else — sql_parser.py only extracts facts, and ai_service.py
never influences these results (PRD §13.1: "Gemma 不負責決定 COST 是否超標 /
WHERE 是否存在 / Parallel Hint 是否存在 / OR 是否存在 / ... ").

Every BLOCK/NOTICE threshold and every important-table entry comes from
`rules.yaml` / `important_tables.yaml`, never hardcoded here (PRD §13.3).
"""

from __future__ import annotations

import fnmatch
from typing import Any

from app.schemas import ComplianceResult, Finding, RuleRow
from app.services.sql_parser import ParsedSql, ParsedStatement

# Maps rule_id -> the improvement_score.yaml weight key it feeds (see
# improvement_score.py). Kept here, next to the rules that create findings,
# so the two files cannot silently drift apart.
WEIGHT_KEYS: dict[str, str] = {
    "R001": "cost_over_threshold",
    "R002": "missing_where",
    "R003": "parallel_hint",
    "R004": "leading_wildcard_like",
    "R005": "function_on_condition",
    "R006": "or_condition",
    "R007": "important_table_notice",
    "R008": "forbidden_operation",
}

GLOBAL_STATEMENT_INDEX = -1  # Finding.statement_index sentinel for whole-request facts (COST)


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _rule_def(rules_config: dict[str, Any], rule_id: str) -> dict[str, Any]:
    for r in rules_config.get("rules", []):
        if r.get("id") == rule_id:
            return r
    return {}


def _seg_prefix(stmt: ParsedStatement, multi: bool) -> str:
    return f"第{stmt.index + 1}段：" if multi else ""


# ---------------------------------------------------------------------------
# R001 — COST (global, not statement-scoped)
# ---------------------------------------------------------------------------
def _eval_cost(cost: int, rules_config: dict[str, Any]) -> tuple[RuleRow, list[Finding]]:
    rdef = _rule_def(rules_config, "R001")
    threshold = int(rdef.get("threshold", 100000))
    enabled = rdef.get("enabled", True)
    findings: list[Finding] = []

    if not enabled:
        return RuleRow(rule_id="R001", name="COST", status="NA", evidence=_fmt_int(cost), note="規則未啟用"), findings

    if cost >= threshold:
        row = RuleRow(
            rule_id="R001",
            name="COST",
            status="BLOCK",
            evidence=_fmt_int(cost),
            note=f"超過規範門檻 {_fmt_int(threshold)}",
        )
        findings.append(
            Finding(rule_id="R001", status="BLOCK", fact=f"COST {_fmt_int(cost)}", statement_index=GLOBAL_STATEMENT_INDEX)
        )
        return row, findings

    row = RuleRow(
        rule_id="R001", name="COST", status="PASS", evidence=_fmt_int(cost), note=f"低於規範門檻 {_fmt_int(threshold)}"
    )
    return row, findings


# ---------------------------------------------------------------------------
# R002 — WHERE 查詢條件
# ---------------------------------------------------------------------------
def _eval_where(statements: list[ParsedStatement], rules_config: dict[str, Any]) -> tuple[RuleRow, list[Finding]]:
    rdef = _rule_def(rules_config, "R002")
    if not rdef.get("enabled", True):
        return RuleRow(rule_id="R002", name="WHERE 查詢條件", status="NA", evidence="規則未啟用", note=""), []

    multi = len(statements) > 1
    applicable = [s for s in statements if s.where_applicable]
    findings: list[Finding] = []

    if not applicable:
        return RuleRow(
            rule_id="R002", name="WHERE 查詢條件", status="NA", evidence="不適用", note="此次 SQL 不需要 WHERE 條件"
        ), findings

    missing = [s for s in applicable if s.has_where is False]
    unknown = [s for s in applicable if s.has_where is None]

    for s in missing:
        findings.append(
            Finding(rule_id="R002", status="BLOCK", fact="缺少 WHERE 條件", statement_index=s.index)
        )

    if missing:
        evidence = "、".join(f"{_seg_prefix(s, multi)}缺少 WHERE 條件" for s in missing)
        return RuleRow(
            rule_id="R002", name="WHERE 查詢條件", status="BLOCK", evidence=evidence, note="依中心規範，查詢須有 WHERE 查詢條件"
        ), findings

    if unknown:
        evidence = "、".join(f"{_seg_prefix(s, multi)}SQL 結構較複雜，無法確認" for s in unknown)
        return RuleRow(
            rule_id="R002", name="WHERE 查詢條件", status="REVIEW", evidence=evidence, note="請人工確認是否已有適當查詢條件"
        ), findings

    return RuleRow(
        rule_id="R002", name="WHERE 查詢條件", status="PASS", evidence="已設定", note="已有限制查詢條件"
    ), findings


# ---------------------------------------------------------------------------
# R003 — Parallel Hint (token-level; see sql_parser.detect_parallel_hint_text)
# ---------------------------------------------------------------------------
def _eval_parallel_hint(statements: list[ParsedStatement], rules_config: dict[str, Any]) -> tuple[RuleRow, list[Finding]]:
    rdef = _rule_def(rules_config, "R003")
    if not rdef.get("enabled", True):
        return RuleRow(rule_id="R003", name="Parallel Hint", status="NA", evidence="規則未啟用", note=""), []

    multi = len(statements) > 1
    hit = [s for s in statements if s.hint_evidence]
    findings: list[Finding] = []
    for s in hit:
        findings.append(Finding(rule_id="R003", status="BLOCK", fact=s.hint_evidence or "", statement_index=s.index))

    if hit:
        evidence = "、".join(f"{_seg_prefix(s, multi)}{s.hint_evidence}" for s in hit)
        return RuleRow(
            rule_id="R003", name="Parallel Hint", status="BLOCK", evidence=evidence, note="禁止使用 Parallel Hint"
        ), findings

    return RuleRow(rule_id="R003", name="Parallel Hint", status="PASS", evidence="未發現", note="符合"), findings


# ---------------------------------------------------------------------------
# R004 — LIKE 前置萬用字元
# ---------------------------------------------------------------------------
def _eval_like(statements: list[ParsedStatement], rules_config: dict[str, Any]) -> tuple[RuleRow, list[Finding]]:
    rdef = _rule_def(rules_config, "R004")
    if not rdef.get("enabled", True):
        return RuleRow(rule_id="R004", name="LIKE 前置萬用字元", status="NA", evidence="規則未啟用", note=""), []

    multi = len(statements) > 1
    findings: list[Finding] = []
    evidences: list[str] = []
    for s in statements:
        for fact in s.like_findings:
            findings.append(Finding(rule_id="R004", status="NOTICE", fact=fact, statement_index=s.index))
            evidences.append(f"{_seg_prefix(s, multi)}{fact}")

    if evidences:
        return RuleRow(
            rule_id="R004",
            name="LIKE 前置萬用字元",
            status="NOTICE",
            evidence="、".join(evidences),
            note="可評估調整為後置萬用字元或其他查詢方式",
        ), findings

    return RuleRow(rule_id="R004", name="LIKE 前置萬用字元", status="PASS", evidence="未發現", note="目前無需調整"), findings


# ---------------------------------------------------------------------------
# R005 — 條件欄位使用函數
# ---------------------------------------------------------------------------
def _eval_function_on_condition(
    statements: list[ParsedStatement], rules_config: dict[str, Any]
) -> tuple[RuleRow, list[Finding]]:
    rdef = _rule_def(rules_config, "R005")
    if not rdef.get("enabled", True):
        return RuleRow(rule_id="R005", name="條件欄位使用函數", status="NA", evidence="規則未啟用", note=""), []

    multi = len(statements) > 1
    findings: list[Finding] = []
    evidences: list[str] = []
    for s in statements:
        for fact in s.function_findings:
            findings.append(Finding(rule_id="R005", status="NOTICE", fact=fact, statement_index=s.index))
            evidences.append(f"{_seg_prefix(s, multi)}{fact}")

    if evidences:
        return RuleRow(
            rule_id="R005",
            name="條件欄位使用函數",
            status="NOTICE",
            evidence="、".join(evidences),
            note="可評估調整寫法，讓資料庫有更多機會採用較有效率的查詢方式",
        ), findings

    return RuleRow(rule_id="R005", name="條件欄位使用函數", status="PASS", evidence="未發現", note="目前無需調整"), findings


# ---------------------------------------------------------------------------
# R006 — OR 條件
# ---------------------------------------------------------------------------
def _eval_or(statements: list[ParsedStatement], rules_config: dict[str, Any]) -> tuple[RuleRow, list[Finding]]:
    rdef = _rule_def(rules_config, "R006")
    if not rdef.get("enabled", True):
        return RuleRow(rule_id="R006", name="OR 條件", status="NA", evidence="規則未啟用", note=""), []

    multi = len(statements) > 1
    findings: list[Finding] = []
    total = 0
    evidences: list[str] = []
    for s in statements:
        if s.or_findings:
            total += len(s.or_findings)
            findings.append(
                Finding(rule_id="R006", status="NOTICE", fact=f"{len(s.or_findings)} 處 OR 條件", statement_index=s.index)
            )
            evidences.append(f"{_seg_prefix(s, multi)}{len(s.or_findings)} 處")

    if total:
        return RuleRow(
            rule_id="R006",
            name="OR 條件",
            status="NOTICE",
            evidence="、".join(evidences) if multi else f"共 {total} 處",
            note="可評估是否能簡化條件或改用其他查詢方式",
        ), findings

    return RuleRow(rule_id="R006", name="OR 條件", status="PASS", evidence="未發現", note="目前無需調整"), findings


# ---------------------------------------------------------------------------
# R007 — 重要資料表 / R008 — 重要資料表禁止操作
# ---------------------------------------------------------------------------
def _match_entry(table: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in entries:
        name = entry.get("name")
        pattern = entry.get("pattern")
        if name and table.upper() == str(name).upper():
            return entry
        if pattern and fnmatch.fnmatch(table.upper(), str(pattern).upper()):
            return entry
    return None


def _eval_important_tables(
    statements: list[ParsedStatement], rules_config: dict[str, Any], tables_config: dict[str, Any]
) -> tuple[RuleRow, list[Finding]]:
    rdef = _rule_def(rules_config, "R007")
    if not rdef.get("enabled", True):
        return RuleRow(rule_id="R007", name="重要資料表", status="NA", evidence="規則未啟用", note=""), []

    entries = tables_config.get("important_tables", [])
    multi = len(statements) > 1
    findings: list[Finding] = []
    hits: list[tuple[str, str]] = []  # (evidence_text, message)

    for s in statements:
        matched_tables: list[str] = []
        message = ""
        for table in sorted(s.tables):
            entry = _match_entry(table, entries)
            if entry:
                matched_tables.append(table)
                message = entry.get("message", "")
                findings.append(
                    Finding(rule_id="R007", status="NOTICE", fact=table, statement_index=s.index, table=table)
                )
        if matched_tables:
            hits.append((f"{_seg_prefix(s, multi)}{'、'.join(matched_tables)}", message))

    if hits:
        evidence = "、".join(h[0] for h in hits)
        notes = list(dict.fromkeys(h[1] for h in hits if h[1]))  # de-dupe, keep order
        return RuleRow(
            rule_id="R007", name="重要資料表", status="NOTICE", evidence=evidence, note="；".join(notes)
        ), findings

    return RuleRow(rule_id="R007", name="重要資料表", status="PASS", evidence="未發現", note="符合"), findings


def _eval_forbidden_operations(
    statements: list[ParsedStatement], rules_config: dict[str, Any], tables_config: dict[str, Any]
) -> tuple[RuleRow, list[Finding]]:
    rdef = _rule_def(rules_config, "R008")
    if not rdef.get("enabled", True):
        return RuleRow(rule_id="R008", name="重要資料表禁止操作", status="NA", evidence="規則未啟用", note=""), []

    entries = tables_config.get("forbidden_operations", [])
    multi = len(statements) > 1
    findings: list[Finding] = []
    hits: list[tuple[str, str]] = []

    if entries:
        for s in statements:
            matched_tables: list[str] = []
            message = ""
            for table in sorted(s.tables):
                for entry in entries:
                    stypes = [str(t).upper() for t in entry.get("statement_types", [])]
                    if stypes and s.statement_type.upper() not in stypes:
                        continue
                    name = entry.get("name")
                    pattern = entry.get("pattern")
                    matched = (name and table.upper() == str(name).upper()) or (
                        pattern and fnmatch.fnmatch(table.upper(), str(pattern).upper())
                    )
                    if matched:
                        matched_tables.append(table)
                        message = entry.get("message", "禁止此操作。")
                        findings.append(
                            Finding(rule_id="R008", status="BLOCK", fact=table, statement_index=s.index, table=table)
                        )
                        break
            if matched_tables:
                hits.append((f"{_seg_prefix(s, multi)}{'、'.join(matched_tables)}", message))

    if hits:
        evidence = "、".join(h[0] for h in hits)
        notes = list(dict.fromkeys(h[1] for h in hits if h[1]))
        return RuleRow(
            rule_id="R008", name="重要資料表禁止操作", status="BLOCK", evidence=evidence, note="；".join(notes)
        ), findings

    return RuleRow(rule_id="R008", name="重要資料表禁止操作", status="PASS", evidence="未發現", note="符合"), findings


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------
_BLOCK_RULE_IDS = ("R001", "R002", "R003", "R008")


def evaluate(
    parsed: ParsedSql,
    cost: int,
    rules_config: dict[str, Any],
    important_tables_config: dict[str, Any],
) -> tuple[ComplianceResult, list[RuleRow], list[Finding]]:
    """Run every rule and produce the overall compliance verdict (PRD §15):
    any BLOCK among the block-class rules wins outright ("不符合中心規範");
    otherwise any REVIEW among them means "請人工確認"; otherwise "符合".
    NOTICE-class rules never affect this verdict (PRD §15, §16.1).
    """
    statements = parsed.statements

    rows: list[RuleRow] = []
    findings: list[Finding] = []

    for row, fs in (
        _eval_cost(cost, rules_config),
        _eval_where(statements, rules_config),
        _eval_parallel_hint(statements, rules_config),
        _eval_like(statements, rules_config),
        _eval_function_on_condition(statements, rules_config),
        _eval_or(statements, rules_config),
        _eval_important_tables(statements, rules_config, important_tables_config),
        _eval_forbidden_operations(statements, rules_config, important_tables_config),
    ):
        rows.append(row)
        findings.extend(fs)

    by_id = {r.rule_id: r for r in rows}
    block_rows = [by_id[rid] for rid in _BLOCK_RULE_IDS if rid in by_id]
    block_count = sum(1 for r in block_rows if r.status == "BLOCK")
    has_review = any(r.status == "REVIEW" for r in block_rows)
    notice_count = sum(1 for r in rows if r.status == "NOTICE")

    if block_count > 0:
        compliance = ComplianceResult(
            status="BLOCK", label="不符合中心規範", notice_count=notice_count, block_count=block_count
        )
    elif has_review:
        compliance = ComplianceResult(
            status="REVIEW", label="請人工確認", notice_count=notice_count, block_count=0
        )
    else:
        compliance = ComplianceResult(
            status="PASS", label="符合中心規範", notice_count=notice_count, block_count=0
        )

    return compliance, rows, findings
