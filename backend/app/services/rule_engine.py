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
            # `>=`: the rule is 「COST 須低於門檻」, so exactly-at-threshold is
            # BLOCK too — say 「達到或超過」 so the boundary case reads correctly.
            note=f"達到或超過規範門檻 {_fmt_int(threshold)}",
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
#
# SELECT 沒有 top-level WHERE 時，sql_parser.py 的 restriction_kind 會分類是否仍有
# 限制條件證據（JOIN ON 含常數、JOIN 鍵值關聯、或子查詢／WITH 內有 WHERE）；
# 每種 kind 的 PASS／REVIEW／BLOCK 由 rules.yaml 決定。2026-09-19 預設設定改為：
# 子查詢／WITH 內確有 WHERE 可 PASS；只有 JOIN ON 證據時 REVIEW，不把「有 JOIN」
# 自動翻譯成「符合中心明文 WHERE 要求」。UPDATE/DELETE 邏輯不變。
# ---------------------------------------------------------------------------
# (label, note) 供 restriction_kind 為 PASS／REVIEW／BLOCK 時的白話說明。note
# 只在最終判定為 PASS 時顯示於「說明」欄；BLOCK／REVIEW 一律沿用既有固定文案，
# 避免對「不符合／請確認」的原因產生誤導性的正面措辭。
_RESTRICTION_EVIDENCE_TEXT: dict[str, tuple[str, str]] = {
    "source_where": (
        "限制條件位於子查詢／WITH 內",
        "外層未寫 WHERE，但子查詢／WITH 內已有 WHERE 限制條件",
    ),
    "join_on_constant": (
        "限制條件位於 JOIN ON（INNER JOIN 含常數條件）",
        "INNER JOIN 的 ON 條件可限縮連接結果，但主查詢未使用 WHERE",
    ),
    "join_on_outer_constant": (
        "限制條件位於 JOIN ON（外部連接含常數條件）",
        "外部連接的 ON 條件主要影響副表對應結果，不會縮小主表查詢範圍，且主查詢未使用 WHERE",
    ),
    "join_on_only": (
        "以 JOIN 條件連接資料表（未寫 WHERE）",
        "目前只有 JOIN 鍵值關聯，主查詢未使用 WHERE 限制查詢範圍",
    ),
}


def _restriction_verdict(kind: str, r002_cfg: dict[str, Any]) -> str:
    verdicts = r002_cfg.get("restriction_verdicts", {})
    # Unconfigured kind defaults to the conservative "review", never a
    # silent "pass" — rules.yaml is expected to list all four kinds
    # explicitly (see its own comment), this is only a safety net.
    return str(verdicts.get(kind, "review")).lower()


def _statement_where_status(s: ParsedStatement, r002_cfg: dict[str, Any]) -> tuple[str, str, str]:
    """Per-statement (status, evidence_text, note_text) for R002, given one
    where_applicable statement."""
    if s.has_where is True:
        return "PASS", "已設定", "已有限制查詢條件"
    if s.has_where is None:
        return "REVIEW", "SQL 結構較複雜，無法確認", "請人工確認是否已有適當查詢條件"

    # has_where is False from here on.
    if s.restriction_kind is None:
        return "BLOCK", "缺少 WHERE 條件", "依中心規範，查詢須有 WHERE 查詢條件"

    verdict = _restriction_verdict(s.restriction_kind, r002_cfg)
    label, note = _RESTRICTION_EVIDENCE_TEXT[s.restriction_kind]
    if verdict == "block":
        return "BLOCK", f"{label}（依設定判定為不符合）", "依中心規範，查詢須有 WHERE 查詢條件"
    if verdict == "review":
        return "REVIEW", label, f"{note}；請確認是否符合中心作業要求"
    return "PASS", label, note


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

    per_stmt = [(s, *_statement_where_status(s, rdef)) for s in applicable]

    for s, status, evidence, _note in per_stmt:
        if status == "PASS":
            continue
        if s.has_where is None:
            # Pre-existing behavior, unchanged: a parse-uncertain statement
            # ("SQL 結構較複雜，無法確認") only affects the RuleRow's overall
            # REVIEW status, never produces a Finding — it was never scored
            # via improvement_score.py's rule-findings component, and this
            # restriction-evidence feature must not silently change that.
            continue
        findings.append(Finding(rule_id="R002", status=status, fact=evidence, statement_index=s.index))

    blocked = [(s, ev) for s, status, ev, _ in per_stmt if status == "BLOCK"]
    if blocked:
        evidence = "、".join(f"{_seg_prefix(s, multi)}{ev}" for s, ev in blocked)
        return RuleRow(
            rule_id="R002", name="WHERE 查詢條件", status="BLOCK", evidence=evidence, note="依中心規範，查詢須有 WHERE 查詢條件"
        ), findings

    reviewed = [(s, ev, note) for s, status, ev, note in per_stmt if status == "REVIEW"]
    if reviewed:
        evidence = "、".join(f"{_seg_prefix(s, multi)}{ev}" for s, ev, _note in reviewed)
        notes = list(dict.fromkeys(note for _s, _ev, note in reviewed))
        return RuleRow(
            rule_id="R002",
            name="WHERE 查詢條件",
            status="REVIEW",
            evidence=evidence,
            note="；".join(notes),
        ), findings

    # Everything PASS — either a real WHERE, or restriction evidence
    # configured to pass. Show every statement's own evidence text (not
    # just "已設定") so multi-statement / evidence-based passes stay
    # traceable, and de-dupe notes so the same explanation isn't repeated.
    evidence_parts = [f"{_seg_prefix(s, multi)}{ev}" for s, _status, ev, _note in per_stmt]
    notes = list(dict.fromkeys(note for _s, _status, _ev, note in per_stmt))
    return RuleRow(
        rule_id="R002",
        name="WHERE 查詢條件",
        status="PASS",
        evidence="、".join(evidence_parts) if multi else evidence_parts[0],
        note="；".join(notes),
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
