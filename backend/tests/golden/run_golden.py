"""Golden-dataset check against a REAL Ollama/Gemma instance (PRD §56).

Production-host-only: requires a reachable Ollama with the configured model
already pulled (see README's verification table — this cannot run on the
dev machine, which has no Ollama). Not a pytest test (no `test_` prefix, not
auto-discovered) — run explicitly after deployment:

    cd backend
    uv run python tests/golden/run_golden.py [--base-url https://localhost] [-v]

Checks each case's live AI output against the PRD §56 acceptance criteria:
no fabricated Index/Execution-Plan/Full-Table-Scan claims, no fabricated
post-rewrite Oracle COST, no forbidden-severity wording unless the rule
engine already returned BLOCK, Traditional-Chinese (not PRC) vocabulary,
`estimated_improvement_pct` within [0, 100] and a multiple of 5 or null, and
that the rule engine's own verdict (not the AI) is what the case expects.
This does NOT re-invent judgment — it calls the exact same `sql_parser` /
`rule_engine` / `ai_service` the running application uses, straight from
this same codebase, not a re-implementation.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass
class GoldenCase:
    name: str
    sql: str
    cost: int
    expect_compliance: str | None = None  # "PASS" | "BLOCK" | "REVIEW" | None (don't check)
    expect_candidate_allowed: bool | None = None


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
]


@dataclass
class CaseResult:
    case: GoldenCase
    ok: bool
    problems: list[str] = field(default_factory=list)


def _check_vocabulary(text: str | None) -> list[str]:
    if not text:
        return []
    hits = sorted({ch for ch in text if ch in _SIMPLIFIED_ONLY_CHARS})
    return [f"疑似簡體字：{hits}"] if hits else []


def _check_forbidden(text: str | None, forbidden: tuple[str, ...]) -> list[str]:
    if not text:
        return []
    return [f"命中禁語：{phrase}" for phrase in forbidden if phrase in text]


async def run_case(case: GoldenCase, settings) -> CaseResult:
    problems: list[str] = []
    parsed = parse_sql_text(case.sql)
    compliance, _rows, findings = rule_engine.evaluate(
        parsed, case.cost, settings.rules_config, settings.important_tables_config
    )

    if case.expect_compliance and compliance.status != case.expect_compliance:
        problems.append(f"預期中心規範為 {case.expect_compliance}，實際為 {compliance.status}")

    ai_result = await ai_service.get_ai_result(
        sql_text=case.sql,
        cost=case.cost,
        compliance_status=compliance.status,
        findings=findings,
        statements=parsed.statements,
        settings=settings,
    )

    if ai_result.status != "ok":
        problems.append(f"AI 未成功回應（status={ai_result.status}）：{ai_result.message}")
        return CaseResult(case=case, ok=not problems, problems=problems)

    forbidden = tuple(settings.ai_guard.get("forbidden_phrases", _FORBIDDEN_DEFAULTS))
    texts = [ai_result.summary] + [a.title for a in ai_result.advice] + [a.explanation for a in ai_result.advice]
    for t in texts:
        problems += _check_forbidden(t, forbidden)
        problems += _check_vocabulary(t)

    pct = ai_result.estimated_improvement_pct
    if pct is not None and (pct < 0 or pct > 100 or pct % 5 != 0):
        problems.append(f"estimated_improvement_pct 不合法：{pct}（須為 0-100 且為 5 的倍數，或 null）")

    if case.expect_candidate_allowed is False and ai_result.suggested_sql and ai_result.suggested_sql.available:
        problems.append("此案例不應提供建議寫法，但 AI 回傳 available=true")

    return CaseResult(case=case, ok=not problems, problems=problems)


async def main_async(base_url: str | None, verbose: bool) -> int:
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

    print(f"\n{passed}/{len(results)} golden cases passed")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SQLCheck 2.0 golden dataset against a live Ollama")
    parser.add_argument("--base-url", default=None, help="Override OLLAMA_BASE_URL for this run")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    return asyncio.run(main_async(args.base_url, args.verbose))


if __name__ == "__main__":
    raise SystemExit(main())
