"""改善優先指數編製模型 (PRD §16; weights and bands fully driven by
`rules.yaml: improvement_score`, see that file's header comment for the
formula). This module only does arithmetic on data supplied by
rule_engine.py's findings and sql_parser.py's per-statement facts — it never
invents a rule or a weight itself (PRD §16.1 "不讓 AI 自由打分").
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.schemas import AdviceItem, Finding, ImprovementBreakdownItem, ImprovementResult
from app.services.rule_engine import GLOBAL_STATEMENT_INDEX, WEIGHT_KEYS
from app.services.sql_parser import ParsedStatement


def _decayed_sum(counts: Counter[str], weights: dict[str, Any], decay: list[float]) -> float:
    total = 0.0
    for weight_key, count in counts.items():
        w = float(weights.get(weight_key, 0))
        for i in range(count):
            factor = decay[i] if i < len(decay) else decay[-1]
            total += w * factor
    return total


def _weight_key_counts(findings: list[Finding], statement_index: int | None) -> Counter[str]:
    counts: Counter[str] = Counter()
    for f in findings:
        if statement_index is not None and f.statement_index != statement_index:
            continue
        if statement_index is None and f.statement_index != GLOBAL_STATEMENT_INDEX:
            continue
        key = WEIGHT_KEYS.get(f.rule_id)
        if key:
            counts[key] += 1
    return counts


def _structure_score(stmt: ParsedStatement, structure_cfg: dict[str, Any]) -> float:
    weights = structure_cfg.get("weights", {})
    total = sum(float(weights.get(flag, 0)) for flag in stmt.complexity_flags)
    threshold = int(structure_cfg.get("many_tables_threshold", 4))
    if stmt.table_count >= threshold:
        total += float(weights.get("many_tables", 0))
    return min(total, float(structure_cfg.get("max", 15)))


def _cost_ratio_score(cost: int, threshold: int, cost_ratio_cfg: dict[str, Any]) -> tuple[float, float]:
    ratio = cost / max(threshold, 1)
    for band in cost_ratio_cfg.get("bands", []):
        max_ratio = band.get("max_ratio")
        if max_ratio is None or ratio <= float(max_ratio):
            return float(band.get("score", 0)), ratio
    return float(cost_ratio_cfg.get("max", 15)), ratio


def _ai_adjustment_score(advice: list[AdviceItem] | None, ai_cfg: dict[str, Any]) -> float:
    if not advice:
        return 0.0
    impact_scores = ai_cfg.get("impact_scores", {})
    total = sum(float(impact_scores.get(a.impact, 0)) for a in advice if a.impact)
    return min(total, float(ai_cfg.get("max", 10)))


def _level_for_score(score: int, levels_cfg: dict[str, Any]) -> tuple[str, str, str]:
    for key, level_key in (("priority", "PRIORITY"), ("improve", "IMPROVE"), ("good", "GOOD")):
        cfg = levels_cfg.get(key, {})
        lo = cfg.get("min", 0)
        hi = cfg.get("max", 100)
        if score >= lo and score <= hi:
            return level_key, cfg.get("label", key), cfg.get("color", "green")
    # Fallback: should not happen with a well-formed config, but never crash.
    return "PRIORITY", "優先改善", "red"


def compute(
    statements: list[ParsedStatement],
    findings: list[Finding],
    cost: int,
    rules_config: dict[str, Any],
    ai_advice: list[AdviceItem] | None = None,
) -> ImprovementResult:
    sc = rules_config.get("improvement_score", {})
    rf_cfg = sc.get("rule_findings", {})
    st_cfg = sc.get("structure", {})
    cr_cfg = sc.get("cost_ratio", {})
    ai_cfg = sc.get("ai_adjustment", {})
    levels_cfg = sc.get("levels", {})
    max_score = int(sc.get("max_score", 100))
    block_floor = int(sc.get("block_floor", 80))
    decay = [float(x) for x in rf_cfg.get("repeat_decay", [1.0, 0.5, 0.25])] or [1.0]
    weights = rf_cfg.get("weights", {})
    rf_max = float(rf_cfg.get("max", 70))

    r001_threshold = 100000
    for r in rules_config.get("rules", []):
        if r.get("id") == "R001":
            r001_threshold = int(r.get("threshold", 100000))

    global_counts = _weight_key_counts(findings, statement_index=None)
    global_f = min(_decayed_sum(global_counts, weights, decay), rf_max)

    per_statement_totals: list[tuple[float, float]] = []  # (F_i, S_i)
    for stmt in statements:
        counts = _weight_key_counts(findings, statement_index=stmt.index)
        f_i = _decayed_sum(counts, weights, decay)
        f_i = min(f_i + global_f, rf_max)
        s_i = _structure_score(stmt, st_cfg)
        per_statement_totals.append((f_i, s_i))

    # A virtual "global-only" entry keeps `base` sensible even when there are
    # zero statements (e.g. nothing could be parsed at all) or when no
    # per-statement finding exists but COST alone is over threshold.
    per_statement_totals.append((global_f, 0.0))

    winning_f, winning_s = max(per_statement_totals, key=lambda t: t[0] + t[1])
    base = winning_f + winning_s

    cost_score, ratio = _cost_ratio_score(cost, r001_threshold, cr_cfg)
    ai_score = _ai_adjustment_score(ai_advice, ai_cfg)

    raw = base + cost_score + ai_score
    score = max(0, min(max_score, round(raw)))

    has_block = any(f.status == "BLOCK" for f in findings)
    floor_applied = False
    if has_block and score < block_floor:
        score = block_floor
        floor_applied = True

    level, label, color = _level_for_score(score, levels_cfg)

    # 2026-09-17 user feedback: the old labels ("COST 佔規範門檻約 69%") were
    # not understandable by the reviewers. Every component now has a short
    # label plus a plain-language `detail` that states what is measured, the
    # actual value for this case and the maximum points it can contribute.
    st_max = int(st_cfg.get("max", 15))
    cr_max = int(cr_cfg.get("max", 15))
    ai_max = int(ai_cfg.get("max", 10))
    ratio_pct = round(ratio * 100)
    breakdown = [
        ImprovementBreakdownItem(
            component="rule_findings",
            label="規則檢核發現的問題",
            score=round(winning_f, 1),
            detail=f"依中心規範各項檢核（含 COST 是否超標）命中的項目加分，命中越多、越嚴重分數越高，最多 {int(rf_max)} 分。",
        ),
        ImprovementBreakdownItem(
            component="structure",
            label="SQL 寫法複雜程度",
            score=round(winning_s, 1),
            detail=f"多表關聯、笛卡兒積、多層子查詢、SELECT *、DISTINCT 等寫法會加分，最多 {st_max} 分。",
        ),
        ImprovementBreakdownItem(
            component="cost_ratio",
            label="COST 接近門檻的程度",
            score=round(cost_score, 1),
            detail=(
                f"目前 COST {cost:,} 約為規範門檻 {r001_threshold:,} 的 {ratio_pct}%，"
                f"越接近或超過門檻加分越多，最多 {cr_max} 分。"
            ),
        ),
        ImprovementBreakdownItem(
            component="ai_adjustment",
            label="AI 建議的影響程度",
            score=round(ai_score, 1),
            detail=f"依 AI 每一項改善建議標示的影響高低加分，最多 {ai_max} 分。",
        ),
    ]
    if floor_applied:
        breakdown.append(
            ImprovementBreakdownItem(
                component="block_floor",
                label="不符合中心規範的最低指數",
                score=float(block_floor),
                detail=f"只要有任何一項不符合中心規範，指數一律至少為 {block_floor}。",
            )
        )

    return ImprovementResult(score=score, level=level, label=label, color=color, breakdown=breakdown)
