"""Golden-dataset check against a REAL Ollama/Gemma instance (PRD §56).

Production-host-only: requires a reachable Ollama with the configured model
already pulled (see README's verification table — this cannot run on the
dev machine, which has no Ollama). Not a pytest test (no `test_` prefix, not
auto-discovered) — run explicitly after deployment:

    cd backend
    uv run python tests/golden/run_golden.py [--base-url https://localhost] [-v] [--out evidence.json]

What it checks per case, against the PRD §56 acceptance criteria:

- deterministic layer (asserted strictly, these are facts this repository
  owns): the rule engine's own verdict, which rule ids fired, and the
  parser's structural-complexity flags;
- AI layer (few, explicit assertions — this is a real-model smoke test, not
  a deterministic unit test): no fabricated Index / Execution-Plan /
  Full-Table-Scan claims, no fabricated post-rewrite Oracle COST, no
  forbidden-severity wording unless the rule engine already returned BLOCK,
  Traditional-Chinese (not PRC) vocabulary, `estimated_improvement_pct`
  within [0, 100] and a multiple of 5 or null, plus whatever each case
  declares via `expect_no_advice` / `expect_outcome_in` /
  `expect_candidate_allowed`.

Clean-SQL cases (`expect_no_advice`) are strict (2026-09-17 round-1
third-party review): BOTH `advice == []` AND
`suggested_sql.outcome == "not_needed"` must hold. A contradictory state
(outcome=not_needed with 1-3 advice items) is exactly the "hard-sell"
behaviour this case exists to catch, so it is a FAIL, not a pass.

Evidence / de-identification policy (2026-09-17, binding):
golden cases must stay synthetic or de-identified. `--out` writes ONLY the
per-case record built in `run_case` — case name, verdicts, rule
ids/statuses, advice count, per-advice `verification`, rewrite outcome,
improvement potential, token counts, latency and pass/fail. The recorder is
incapable of writing SQL text, model output, API responses or application
numbers: only whitelisted keys are copied out of the live objects, and
`_safe_stats()` whitelists the diagnostic keys as well. A `.gitignore`d
output directory is not a licence to store un-deidentified data — never
post-process the record into a less safe shape.

This does NOT re-invent judgment — it calls the exact same `sql_parser` /
`rule_engine` / `ai_service` the running application uses, straight from
this same codebase, not a re-implementation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/ on sys.path

from app.services import ai_service, rule_engine  # noqa: E402
from app.services.sql_parser import parse_sql_text  # noqa: E402
from app.settings import get_settings  # noqa: E402

# Simplified-Chinese-only characters that must never appear in AI output for
# this Taiwan deployment (PRD §22 "避免...數據庫" etc.) — a light heuristic,
# not a full classifier, but catches the common offenders directly.
_SIMPLIFIED_ONLY_CHARS = set("数据库让说后优记录动态执")

_FORBIDDEN_DEFAULTS = (
    "Full Table Scan",
    "全表掃描",
    "索引失效",
    "已使用索引",
    "未使用索引",
    "改善後 COST",
    "Execution Plan",
    "執行計畫",
    "已驗證",
    "高風險",
    "嚴重問題",
)

# Only these diagnostic keys are copied out of `ai_service.LAST_CALL_STATS`
# into evidence — the recorder must be incapable of writing prompt/response
# payloads even if that diagnostic hook ever grows new keys.
_STATS_KEYS = (
    "model",
    "num_ctx",
    "think",
    "done_reason",
    "eval_count",
    "prompt_eval_count",
    "total_duration_ms",
)


@dataclass
class GoldenCase:
    name: str
    sql: str
    cost: int
    # --- deterministic-layer expectations (facts this repo owns; strict) ---
    expect_compliance: str | None = None  # "PASS" | "BLOCK" | "REVIEW" | None (don't check)
    expect_finding_rule_ids: tuple[str, ...] | None = None
    expect_complexity_flags: tuple[str, ...] | None = None
    # --- AI-behaviour expectations (live model; kept few and explicit) ---
    expect_candidate_allowed: bool | None = None
    # Clean-SQL case: the model must not invent improvements. Strict: both
    # `advice == []` and `suggested_sql.outcome == "not_needed"` are required
    # (a "not_needed" answer that still carries advice is a FAIL). The
    # evidence records the observed state as `quiet_kind`.
    expect_no_advice: bool = False
    # When set, `suggested_sql.outcome` must be one of these values.
    expect_outcome_in: tuple[str, ...] | None = None


CASES: list[GoldenCase] = [
    GoldenCase(
        name="trunc_hout120_notice_only",
        sql="SELECT A.TAX_ID, A.TXN_DATE FROM HOUT120 A WHERE TRUNC(A.TXN_DATE) = :D AND A.STATUS = :S",
        cost=68420,
        expect_compliance="PASS",
        expect_candidate_allowed=True,
    ),
    GoldenCase(
        name="missing_where_delete_blocks",
        sql="DELETE FROM T A",
        cost=5000,
        expect_compliance="BLOCK",
        expect_candidate_allowed=False,
    ),
    GoldenCase(
        name="parallel_hint_blocks",
        sql="SELECT /*+ PARALLEL(A,4) */ * FROM T A WHERE A.X=1",
        cost=1000,
        expect_compliance="BLOCK",
        expect_candidate_allowed=False,
    ),
    GoldenCase(
        name="cost_over_threshold_blocks",
        sql="SELECT A.X FROM T A WHERE A.X=1",
        cost=150000,
        expect_compliance="BLOCK",
    ),
    GoldenCase(
        name="clean_select_no_findings",
        sql="SELECT A.X FROM T A WHERE A.ID = :ID",
        cost=1000,
        expect_compliance="PASS",
        expect_candidate_allowed=True,
    ),
    GoldenCase(
        name="complex_outer_join_no_candidate",
        sql=(
            "SELECT A.X, B.Y FROM T A LEFT JOIN T2 B ON A.ID = B.ID "
            "WHERE A.STATUS = :S GROUP BY A.X, B.Y"
        ),
        cost=1000,
        expect_compliance="PASS",
        expect_candidate_allowed=False,
    ),
    # --- 2026-09-17 Batch 4a additions (all synthetic SQL) ---
    GoldenCase(
        name="clean_sql_expects_no_advice",
        # Plainly good SELECT: bind equality only, no function on the
        # constrained columns, no structure flags. The model must not invent
        # improvements for it (accepts advice==[] or outcome==not_needed).
        sql="SELECT A.TAX_ID, A.AMOUNT FROM T A WHERE A.ID = :ID AND A.STATUS = :S",
        cost=900,
        expect_compliance="PASS",
        expect_no_advice=True,
    ),
    GoldenCase(
        name="upper_function_on_condition",
        sql="SELECT A.TAX_ID FROM T A WHERE UPPER(A.STATUS) = :S",
        cost=1200,
        expect_compliance="PASS",
        expect_finding_rule_ids=("R005",),
    ),
    GoldenCase(
        name="to_char_on_date_condition",
        sql="SELECT A.TAX_ID FROM T A WHERE TO_CHAR(A.TXN_DATE, 'YYYYMMDD') = :D",
        cost=1200,
        expect_compliance="PASS",
        expect_finding_rule_ids=("R005",),
    ),
    GoldenCase(
        name="nvl_in_condition",
        sql="SELECT A.TAX_ID FROM T A WHERE NVL(A.FLAG, 'N') = :F",
        cost=1200,
        expect_compliance="PASS",
        expect_finding_rule_ids=("R005",),
    ),
    GoldenCase(
        name="select_star_structure_flag",
        # SELECT * is a structural-complexity fact (S component), not a rule
        # NOTICE — the deterministic expectation is the parser flag.
        sql="SELECT * FROM T A WHERE A.ID = :ID",
        cost=1000,
        expect_compliance="PASS",
        expect_complexity_flags=("select_star",),
    ),
    GoldenCase(
        name="cartesian_join_structure_flag",
        # Old-style comma join with no ON condition joining B to A: the WHERE
        # restricts A only, so this is the cartesian-join pattern the model
        # must call out (structural flag, not a rule NOTICE).
        sql="SELECT A.X, B.Y FROM T A, T2 B WHERE A.ID = :ID",
        cost=1000,
        expect_compliance="PASS",
        expect_complexity_flags=("cartesian_join",),
    ),
]


@dataclass
class CaseResult:
    case: GoldenCase
    ok: bool
    problems: list[str] = field(default_factory=list)
    # De-identified evidence record — see the module docstring; deliberately
    # has no SQL / model-output field.
    record: dict[str, Any] = field(default_factory=dict)


def _check_vocabulary(text: str | None) -> list[str]:
    if not text:
        return []
    hits = sorted({ch for ch in text if ch in _SIMPLIFIED_ONLY_CHARS})
    return [f"疑似簡體字：{hits}"] if hits else []


def _check_forbidden(text: str | None, forbidden: tuple[str, ...]) -> list[str]:
    if not text:
        return []
    return [f"命中禁語：{phrase}" for phrase in forbidden if phrase in text]


def _safe_stats(raw: Any) -> dict[str, Any]:
    """Copy only whitelisted diagnostic keys out of `LAST_CALL_STATS`.

    Read defensively: the hook may be absent (older deployment) or a
    different shape; an empty dict simply means "no token diagnostics".
    """
    if not isinstance(raw, dict):
        return {}
    return {key: raw[key] for key in _STATS_KEYS if key in raw}


def evaluate_no_advice_expectation(outcome: str | None, advice_count: int) -> tuple[str | None, list[str]]:
    """Strict judgement for `expect_no_advice` cases (clean SQL).

    Both signals are required: no advice at all AND `not_needed`. The old
    "either/or" logic let `outcome=not_needed` with fabricated advice through,
    which is precisely the hard-sell behaviour these cases must catch.

    Returns (quiet_kind, problems); `quiet_kind` is recorded in the evidence.
    """
    advice_empty = advice_count == 0
    outcome_quiet = outcome == "not_needed"
    if advice_empty and outcome_quiet:
        return "not_needed", []
    if outcome_quiet:  # contradictory: claims nothing to improve, yet advises
        return "not_needed_with_advice", [
            f"矛盾狀態：suggested_sql.outcome=not_needed 但同時回傳 {advice_count} 條建議（乾淨 SQL 不得硬湊建議）"
        ]
    if advice_empty:
        return "advice_empty", [f"未回傳建議但 suggested_sql.outcome={outcome}（預期 not_needed）"]
    return "neither", [f"此案例不應出現 AI 建議，但回傳 {advice_count} 條（outcome={outcome}）"]


async def run_case(case: GoldenCase, settings) -> CaseResult:
    problems: list[str] = []
    parsed = parse_sql_text(case.sql)
    compliance, _rows, findings = rule_engine.evaluate(
        parsed, case.cost, settings.rules_config, settings.important_tables_config
    )

    if case.expect_compliance and compliance.status != case.expect_compliance:
        problems.append(f"預期中心規範為 {case.expect_compliance}，實際為 {compliance.status}")

    fired_rule_ids = {f.rule_id for f in findings}
    if case.expect_finding_rule_ids:
        missing_rules = [rid for rid in case.expect_finding_rule_ids if rid not in fired_rule_ids]
        if missing_rules:
            problems.append(f"預期規則未觸發：{missing_rules}（實際：{sorted(fired_rule_ids) or '無'}）")

    if case.expect_complexity_flags:
        present_flags: set[str] = set()
        for stmt in parsed.statements:
            present_flags |= set(stmt.complexity_flags)
        missing_flags = [fl for fl in case.expect_complexity_flags if fl not in present_flags]
        if missing_flags:
            problems.append(f"預期結構旗標未出現：{missing_flags}（實際：{sorted(present_flags) or '無'}）")

    started = time.perf_counter()
    ai_result = await ai_service.get_ai_result(
        sql_text=case.sql,
        cost=case.cost,
        compliance_status=compliance.status,
        findings=findings,
        statements=parsed.statements,
        settings=settings,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)

    record: dict[str, Any] = {
        "case": case.name,
        "compliance": compliance.status,
        "findings": [{"rule_id": f.rule_id, "status": f.status} for f in findings],
        "advice_count": 0,
        "advice_verification": [],
        "outcome": None,
        "improvement_potential": None,
        "quiet_kind": None,
        "latency_ms": latency_ms,
        "stats": {},
        "ok": False,
        "problems": problems,
    }

    if ai_result.status != "ok":
        problems.append(f"AI 未成功回應（status={ai_result.status}）：{ai_result.message}")
        record["improvement_potential"] = ai_result.improvement_potential
        record["problems"] = list(problems)
        record["ok"] = not problems
        return CaseResult(case=case, ok=not problems, problems=problems, record=record)

    forbidden = tuple(settings.ai_guard.get("forbidden_phrases", _FORBIDDEN_DEFAULTS))
    texts = [ai_result.summary] + [a.title for a in ai_result.advice] + [a.explanation for a in ai_result.advice]
    for t in texts:
        problems += _check_forbidden(t, forbidden)
        problems += _check_vocabulary(t)

    pct = ai_result.estimated_improvement_pct
    if pct is not None and (pct < 0 or pct > 100 or pct % 5 != 0):
        problems.append(f"estimated_improvement_pct 不合法：{pct}（須為 0-100 且為 5 的倍數，或 null）")

    suggested = ai_result.suggested_sql
    outcome = suggested.outcome if suggested is not None else None

    if case.expect_candidate_allowed is False and suggested is not None and suggested.available:
        problems.append("此案例不應提供建議寫法，但 AI 回傳 available=true")

    quiet_kind: str | None = None
    if case.expect_no_advice:
        quiet_kind, quiet_problems = evaluate_no_advice_expectation(outcome, len(ai_result.advice))
        problems += quiet_problems

    if case.expect_outcome_in is not None and outcome not in case.expect_outcome_in:
        problems.append(f"預期 suggested_sql.outcome 為 {case.expect_outcome_in}，實際為 {outcome}")

    record.update(
        {
            "advice_count": len(ai_result.advice),
            "advice_verification": [a.verification for a in ai_result.advice],
            "outcome": outcome,
            "improvement_potential": ai_result.improvement_potential,
            "quiet_kind": quiet_kind,
            # `LAST_CALL_STATS` is reset at the start of get_ai_result, so an
            # empty dict here means no Ollama call diagnostics were available
            # (e.g. the request was gated before reaching the model).
            "stats": _safe_stats(getattr(ai_service, "LAST_CALL_STATS", None)),
            "problems": list(problems),
            "ok": not problems,
        }
    )
    return CaseResult(case=case, ok=not problems, problems=problems, record=record)


def _summary_line(result: CaseResult) -> str:
    """One-line per-case diagnostics: rewrite outcome, advice count,
    improvement potential, wall-clock latency, and prompt/eval token counts
    (from the defensive `LAST_CALL_STATS` read)."""
    rec = result.record
    stats = rec.get("stats") or {}
    bits = [
        f"outcome={rec.get('outcome')}",
        f"advice={rec.get('advice_count')}",
        f"potential={rec.get('improvement_potential')}",
        f"latency={rec.get('latency_ms')}ms",
    ]
    if rec.get("quiet_kind"):
        bits.append(f"quiet={rec['quiet_kind']}")
    if stats:
        bits.append(
            "tokens="
            f"prompt:{stats.get('prompt_eval_count')}/eval:{stats.get('eval_count')}"
            f" ctx:{stats.get('num_ctx')} done:{stats.get('done_reason')}"
        )
    else:
        bits.append("tokens=n/a")
    return "    · " + " ".join(bits)


def _write_evidence(path: Path, results: list[CaseResult], passed: int) -> None:
    target = path.expanduser()
    if target.parent != Path("."):
        target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "note": (
            "去識別化 golden evidence：僅含案例名稱、判定、規則 id/狀態、verification、"
            "token 數與 latency；不含 SQL 原文、模型原始輸出、API response 或申請單號。"
        ),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "passed": passed,
        "total": len(results),
        "cases": [r.record for r in results],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def main_async(base_url: str | None, verbose: bool, out_path: Path | None) -> int:
    settings = get_settings()
    if base_url:
        object.__setattr__(settings.ollama, "base_url", base_url)  # OllamaSettings is frozen

    results = [await run_case(c, settings) for c in CASES]

    passed = sum(1 for r in results if r.ok)
    for r in results:
        status = "PASS" if r.ok else "FAIL"
        print(f"[{status}] {r.case.name}")
        if not r.ok or verbose:
            for p in r.problems:
                print(f"    - {p}")
            print(_summary_line(r))

    if out_path is not None:
        _write_evidence(out_path, results, passed)
        print(
            f"\n已寫入去識別化 evidence：{out_path}"
            "（僅含判定／verification／token／latency，不含 SQL 或模型原始輸出）"
        )

    print(f"\n{passed}/{len(results)} golden cases passed")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SQLCheck 2.0 golden dataset against a live Ollama")
    parser.add_argument("--base-url", default=None, help="Override OLLAMA_BASE_URL for this run")
    parser.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help="將去識別化 evidence 寫入此檔案（僅判定／verification／token／latency；預設只印出摘要）",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    out_path = Path(args.out) if args.out else None
    return asyncio.run(main_async(args.base_url, args.verbose, out_path))


if __name__ == "__main__":
    raise SystemExit(main())
