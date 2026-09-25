#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import dataclasses
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.api import analyze
from app.schemas import AnalyzeRequest
from app.services import ai_service, llm_provider, rule_engine
from app.services.sql_parser import parse_sql_text
from app.settings import get_settings

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "complex_openrouter_e2e"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "case_json").mkdir(exist_ok=True)
(OUT / "raw_model").mkdir(exist_ok=True)

def long_select_sql() -> str:
    cols = ",\n       ".join(f"A.C{i:03d} AS COL_{i:03d}" for i in range(1, 141))
    return f"""
SELECT {cols},
       A.CASE_ID,
       B.DISTRICT_NAME
FROM TAX_CASE A
JOIN TAX_DISTRICT B
  ON A.DISTRICT_CD = B.DISTRICT_CD
WHERE SUBSTR(A.YEAR_CODE, 1, 2) = '13'
  AND A.OWNER_NAME LIKE '%公司%'
  AND A.STATUS IN ('A','B')
ORDER BY A.CASE_ID
""".strip()

CASES: list[dict[str, Any]] = [
    {
        "id": "CX01",
        "title": "固定前綴 SUBSTR＋多表彙總",
        "cost": 28640,
        "expected_evidence": {"ORACLE11G_TRANSFORMED_COLUMN", "ORACLE11G_PREFIX_LIKE_RANGE_SCAN"},
        "sql": """
SELECT A.DISTRICT_CD,
       B.DISTRICT_NAME,
       COUNT(*) AS CASE_CNT,
       SUM(D.TAX_AMOUNT) AS TAX_AMOUNT
FROM TAX_CASE A
JOIN TAX_DISTRICT B ON A.DISTRICT_CD = B.DISTRICT_CD
JOIN TAX_DETAIL D ON D.CASE_ID = A.CASE_ID
WHERE SUBSTR(A.YEAR_CODE, 1, 2) = '13'
  AND A.STATUS = 'A'
  AND (A.TAX_TYPE = 'H' OR A.TAX_TYPE = 'L')
GROUP BY A.DISTRICT_CD, B.DISTRICT_NAME
ORDER BY A.DISTRICT_CD
""".strip(),
    },
    {
        "id": "CX02",
        "title": "定位 SUBSTR＋多條件查詢",
        "cost": 41220,
        "expected_evidence": {"ORACLE11G_TRANSFORMED_COLUMN", "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT"},
        "sql": """
SELECT A.CASE_ID,
       A.MANAGE_KEY,
       A.STATUS,
       B.AREA_NAME
FROM TAX_CASE A
JOIN TAX_AREA B ON A.AREA_CD = B.AREA_CD
WHERE SUBSTR(A.MANAGE_KEY, 6, 3) = '551'
  AND A.STATUS IN ('A','B')
  AND A.CLOSE_DATE IS NULL
ORDER BY A.CASE_ID
""".strip(),
    },
    {
        "id": "CX03",
        "title": "前置萬用字元 LIKE＋彙總",
        "cost": 53780,
        "expected_evidence": {"ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT"},
        "sql": """
SELECT A.DISTRICT_CD,
       COUNT(*) AS CNT,
       SUM(A.TAX_AMOUNT) AS TOTAL_AMOUNT
FROM TAX_CASE A
JOIN TAX_DISTRICT B ON A.DISTRICT_CD = B.DISTRICT_CD
WHERE A.OWNER_NAME LIKE '%公司%'
  AND A.STATUS = 'A'
  AND A.TAX_AMOUNT > 0
GROUP BY A.DISTRICT_CD
HAVING COUNT(*) > 1
ORDER BY TOTAL_AMOUNT DESC
""".strip(),
    },
    {
        "id": "CX04",
        "title": "欄位加工後 JOIN＋群組統計",
        "cost": 46890,
        "expected_evidence": {"ORACLE11G_TRANSFORMED_COLUMN"},
        "sql": """
SELECT B.DISTRICT_NAME,
       A.TAX_CD,
       COUNT(*) AS CNT
FROM TAX_CASE A
JOIN TAX_MAP B
  ON SUBSTR(A.MANAGE_KEY, 1, 2) = B.DISTRICT_CD
 AND A.TAX_CD = B.TAX_CD
WHERE A.STATUS = 'A'
  AND A.TAX_AMOUNT > 0
GROUP BY B.DISTRICT_NAME, A.TAX_CD
ORDER BY B.DISTRICT_NAME, A.TAX_CD
""".strip(),
    },
    {
        "id": "CX05",
        "title": "欄位串接條件＋多表查詢",
        "cost": 39410,
        "expected_evidence": {"ORACLE11G_TRANSFORMED_COLUMN"},
        "sql": """
SELECT A.CASE_ID,
       A.TAX_CD,
       A.SUBTAX_CD,
       B.DESCRIPTION
FROM TAX_CASE A
JOIN TAX_CODE B ON A.TAX_CD = B.TAX_CD
WHERE A.TAX_CD || A.SUBTAX_CD = '551'
  AND A.STATUS = 'A'
  AND B.ACTIVE_FLAG = 'Y'
ORDER BY A.CASE_ID
""".strip(),
    },
    {
        "id": "CX06",
        "title": "同來源 UNION ALL 重複讀取",
        "cost": 72100,
        "expected_evidence": {"ORACLE11G_VISIT_DATA_FEWER_TIMES"},
        "sql": """
SELECT A.AREA_CD, 'LOW' AS AMOUNT_LEVEL, COUNT(*) AS CNT
FROM TAX_CASE A
WHERE A.TAX_CD = '55'
  AND A.STATUS = 'A'
  AND A.TAX_AMOUNT <= 1000
GROUP BY A.AREA_CD
UNION ALL
SELECT B.AREA_CD, 'MID' AS AMOUNT_LEVEL, COUNT(*) AS CNT
FROM TAX_CASE B
WHERE B.TAX_CD = '55'
  AND B.STATUS = 'A'
  AND B.TAX_AMOUNT > 1000
  AND B.TAX_AMOUNT <= 5000
GROUP BY B.AREA_CD
UNION ALL
SELECT C.AREA_CD, 'HIGH' AS AMOUNT_LEVEL, COUNT(*) AS CNT
FROM TAX_CASE C
WHERE C.TAX_CD = '55'
  AND C.STATUS = 'A'
  AND C.TAX_AMOUNT > 5000
GROUP BY C.AREA_CD
""".strip(),
    },
    {
        "id": "CX07",
        "title": "重複相關 MAX 取得最新紀錄",
        "cost": 66350,
        "expected_evidence": {"ORACLE11G_SUBQUERY_UNNESTING"},
        "sql": """
SELECT A.CASE_ID,
       B.UPDATE_DATE,
       B.UPDATE_TIME,
       B.STATUS
FROM TAX_CASE A
JOIN TAX_HISTORY B ON B.CASE_ID = A.CASE_ID
WHERE A.STATUS = 'A'
  AND B.UPDATE_DATE = (
      SELECT MAX(H.UPDATE_DATE)
      FROM TAX_HISTORY H
      WHERE H.CASE_ID = A.CASE_ID
  )
  AND B.UPDATE_TIME = (
      SELECT MAX(H2.UPDATE_TIME)
      FROM TAX_HISTORY H2
      WHERE H2.CASE_ID = A.CASE_ID
  )
ORDER BY A.CASE_ID
""".strip(),
    },
    {
        "id": "CX08",
        "title": "最新紀錄子查詢＋前置 LIKE",
        "cost": 78460,
        "expected_evidence": {"ORACLE11G_SUBQUERY_UNNESTING", "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT"},
        "sql": """
SELECT A.CASE_ID,
       A.OWNER_NAME,
       B.UPDATE_DATE,
       B.UPDATE_TIME
FROM TAX_CASE A
JOIN TAX_HISTORY B ON B.CASE_ID = A.CASE_ID
WHERE A.OWNER_NAME LIKE '%行號%'
  AND A.STATUS = 'A'
  AND B.UPDATE_DATE = (
      SELECT MAX(H.UPDATE_DATE)
      FROM TAX_HISTORY H
      WHERE H.CASE_ID = A.CASE_ID
  )
  AND B.UPDATE_TIME = (
      SELECT MAX(H2.UPDATE_TIME)
      FROM TAX_HISTORY H2
      WHERE H2.CASE_ID = A.CASE_ID
  )
""".strip(),
    },
    {
        "id": "CX09",
        "title": "複合鍵加工 JOIN＋固定前綴條件",
        "cost": 59230,
        "expected_evidence": {"ORACLE11G_TRANSFORMED_COLUMN", "ORACLE11G_PREFIX_LIKE_RANGE_SCAN"},
        "sql": """
SELECT A.CASE_ID,
       B.DISTRICT_NAME,
       C.CODE_NAME
FROM TAX_CASE A
JOIN TAX_DISTRICT B
  ON SUBSTR(A.MANAGE_KEY, 1, 2) = B.DISTRICT_CD
JOIN TAX_CODE C
  ON A.TAX_CD = C.TAX_CD
WHERE SUBSTR(A.YEAR_CODE, 1, 2) = '13'
  AND A.STATUS = 'A'
  AND C.ACTIVE_FLAG = 'Y'
ORDER BY B.DISTRICT_NAME, A.CASE_ID
""".strip(),
    },
    {
        "id": "CX10",
        "title": "Issue #37 類型超長 SELECT 壓力案例",
        "cost": 88900,
        "expected_evidence": {"ORACLE11G_TRANSFORMED_COLUMN", "ORACLE11G_PREFIX_LIKE_RANGE_SCAN", "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT"},
        "sql": long_select_sql(),
    },
    {
        "id": "CX11",
        "title": "UNION ALL＋固定前綴 SUBSTR",
        "cost": 74680,
        "expected_evidence": {"ORACLE11G_VISIT_DATA_FEWER_TIMES", "ORACLE11G_TRANSFORMED_COLUMN", "ORACLE11G_PREFIX_LIKE_RANGE_SCAN"},
        "sql": """
SELECT A.AREA_CD, COUNT(*) AS CNT
FROM TAX_CASE A
WHERE SUBSTR(A.YEAR_CODE, 1, 2) = '13'
  AND A.STATUS = 'A'
  AND A.TAX_AMOUNT <= 3000
GROUP BY A.AREA_CD
UNION ALL
SELECT B.AREA_CD, COUNT(*) AS CNT
FROM TAX_CASE B
WHERE SUBSTR(B.YEAR_CODE, 1, 2) = '13'
  AND B.STATUS = 'A'
  AND B.TAX_AMOUNT > 3000
GROUP BY B.AREA_CD
""".strip(),
    },
    {
        "id": "CX12",
        "title": "多重改善訊號綜合案例",
        "cost": 81750,
        "expected_evidence": {"ORACLE11G_TRANSFORMED_COLUMN", "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT"},
        "sql": """
SELECT B.DISTRICT_NAME,
       A.TAX_CD,
       A.SUBTAX_CD,
       COUNT(*) AS CNT,
       SUM(A.TAX_AMOUNT) AS TOTAL_AMOUNT
FROM TAX_CASE A
JOIN TAX_MAP B
  ON SUBSTR(A.MANAGE_KEY, 1, 2) = B.DISTRICT_CD
WHERE A.TAX_CD || A.SUBTAX_CD = '551'
  AND A.OWNER_NAME LIKE '%企業%'
  AND A.STATUS = 'A'
GROUP BY B.DISTRICT_NAME, A.TAX_CD, A.SUBTAX_CD
HAVING SUM(A.TAX_AMOUNT) > 0
ORDER BY TOTAL_AMOUNT DESC
""".strip(),
    },
]

CURRENT: dict[str, Any] = {}
CAPTURES: list[dict[str, Any]] = []
ORIGINAL_GENERATE = llm_provider.generate_structured_json

def _extract_payload(user_content: str) -> dict[str, Any] | None:
    prefix = "<SQL_DATA>\n"
    suffix = "\n</SQL_DATA>"
    if not user_content.startswith(prefix) or not user_content.endswith(suffix):
        return None
    try:
        return json.loads(user_content[len(prefix):-len(suffix)])
    except Exception:
        return None

async def capturing_generate(*args, **kwargs):
    reply = await ORIGINAL_GENERATE(*args, **kwargs)
    raw_json = None
    try:
        raw_json = json.loads(reply.content)
    except Exception:
        pass
    CAPTURES.append({
        "case_id": CURRENT.get("case_id"),
        "attempt_index": 1 + sum(1 for x in CAPTURES if x.get("case_id") == CURRENT.get("case_id")),
        "provider": reply.provider,
        "model": reply.model,
        "finish_reason": reply.finish_reason,
        "prompt_tokens": reply.prompt_tokens,
        "output_tokens": reply.output_tokens,
        "total_tokens": reply.total_tokens,
        "total_duration_ms": reply.total_duration_ms,
        "request_max_output_tokens": kwargs.get("max_output_tokens"),
        "payload": _extract_payload(kwargs.get("user_content", "")),
        "raw_json": raw_json,
        "raw_text": reply.content,
    })
    return reply

def deterministic_projection(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "compliance": result.get("compliance"),
        "rules": result.get("rules"),
        "findings": result.get("findings"),
        "improvement": result.get("improvement"),
        "verified_rewrites": result.get("verified_rewrites"),
        "performance_evidence": result.get("performance_evidence"),
    }

def ai_prose(final: dict[str, Any]) -> str:
    ai = final.get("ai") or {}
    parts: list[str] = []
    for key in ("summary", "message"):
        if isinstance(ai.get(key), str):
            parts.append(ai[key])
    for advice in ai.get("advice") or []:
        if isinstance(advice, dict):
            for key in ("title", "explanation", "assumption"):
                if isinstance(advice.get(key), str):
                    parts.append(advice[key])
    suggested = ai.get("suggested_sql") or {}
    if isinstance(suggested, dict) and isinstance(suggested.get("reason"), str):
        parts.append(suggested["reason"])
    return "\n".join(parts)

UNSUPPORTED = re.compile(
    r"Full\s*Table\s*Scan|全表掃描|已使用索引|未使用索引|索引失效|改善後\s*COST|"
    r"實際(?:執行)?時間|實際提升|效能提升\s*\d+%|提升\s*\d+%|"
    r"一定(?:會|能)|必然|保證(?:會|能)?|百分之百|100%\s*(?:會|改善)|"
    r"執行計畫(?:顯示|證明)|Execution\s*Plan\s*(?:shows|proves)",
    re.IGNORECASE,
)
JARGON = re.compile(
    r"\b(?:cardinality|selectivity|sargable|predicate pushdown|unnesting|CBO|access path)\b",
    re.IGNORECASE,
)
SIMPLIFIED_ONLY = set("数据库让说后优记录动态执")
ABSOLUTE_HYPE = re.compile(r"大幅(?:提升|改善)|顯著(?:提升|改善)|徹底(?:解決|改善)|最佳效能")

def readability_review(final: dict[str, Any]) -> dict[str, Any]:
    ai = final.get("ai") or {}
    advice = ai.get("advice") or []
    problems: list[str] = []
    lengths: list[int] = []
    for item in advice:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        explanation = str(item.get("explanation") or "").strip()
        if not title:
            problems.append("建議缺少標題")
        if not explanation:
            problems.append("建議缺少白話說明")
        lengths.append(len(explanation))
        if len(title) > 32:
            problems.append(f"建議標題偏長：{len(title)} 字")
        if len(explanation) > 240:
            problems.append(f"建議說明偏長：{len(explanation)} 字")
        if JARGON.search(explanation):
            problems.append("建議含未白話化的英文字詞")
    prose = ai_prose(final)
    simp = sorted({ch for ch in prose if ch in SIMPLIFIED_ONLY})
    if simp:
        problems.append(f"出現疑似簡體字：{''.join(simp)}")
    return {
        "advice_count": len(advice),
        "mean_explanation_chars": round(statistics.mean(lengths), 1) if lengths else 0,
        "max_explanation_chars": max(lengths) if lengths else 0,
        "problems": problems,
    }

async def call(case: dict[str, Any], include_ai: bool) -> dict[str, Any]:
    CURRENT.clear()
    CURRENT["case_id"] = case["id"]
    result = await analyze(
        AnalyzeRequest(
            application_no=f"E2E-{case['id']}",
            cost=case["cost"],
            sql=case["sql"],
            include_ai=include_ai,
        )
    )
    return result.model_dump(mode="json")

async def controlled_truncation_probe() -> dict[str, Any]:
    settings = get_settings()
    probe_settings = dataclasses.replace(
        settings,
        llm=dataclasses.replace(
            settings.llm,
            max_output_tokens=32,
            truncation_retry_max_output_tokens=8192,
        ),
    )
    sql = CASES[9]["sql"]
    parsed = parse_sql_text(sql)
    compliance, _rows, findings = rule_engine.evaluate(
        parsed, 88900, probe_settings.rules_config, probe_settings.important_tables_config
    )
    before = len(CAPTURES)
    CURRENT.clear()
    CURRENT["case_id"] = "TRUNCATION_PROBE"
    started = time.perf_counter()
    result = await ai_service.get_ai_result(
        sql_text=sql,
        cost=88900,
        compliance_status=compliance.status,
        findings=findings,
        statements=parsed.statements,
        settings=probe_settings,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    attempts = CAPTURES[before:]
    return {
        "status": result.status,
        "degrade_code": result.degrade_code,
        "outcome": result.suggested_sql.outcome if result.suggested_sql else None,
        "elapsed_ms": elapsed_ms,
        "attempts": [
            {
                "finish_reason": a["finish_reason"],
                "output_tokens": a["output_tokens"],
                "request_max_output_tokens": a["request_max_output_tokens"],
            }
            for a in attempts
        ],
        "passed": (
            result.status == "ok"
            and len(attempts) >= 2
            and attempts[0]["request_max_output_tokens"] == 32
            and attempts[-1]["request_max_output_tokens"] == 8192
        ),
    }

async def main() -> int:
    llm_provider.generate_structured_json = capturing_generate
    all_results: list[dict[str, Any]] = []
    overall_problems: list[str] = []

    for case in CASES:
        before = len(CAPTURES)
        baseline = await call(case, False)
        started = time.perf_counter()
        final = await call(case, True)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        attempts = CAPTURES[before:]

        evidence = final.get("performance_evidence") or []
        evidence_ids = {str(x.get("evidence_id")) for x in evidence if isinstance(x, dict)}
        missing_evidence = sorted(set(case["expected_evidence"]) - evidence_ids)
        ai = final.get("ai") or {}
        prose = ai_prose(final)
        unsupported_hits = sorted(set(m.group(0) for m in UNSUPPORTED.finditer(prose)))
        hype_hits = sorted(set(m.group(0) for m in ABSOLUTE_HYPE.finditer(prose)))
        source_problems = [
            f"非 Oracle 11g 官方來源：{x.get('source_label')}"
            for x in evidence
            if isinstance(x, dict) and x.get("source_label") != "Oracle Database 11g 官方文件"
        ]
        readability = readability_review(final)
        deterministic_equal = deterministic_projection(baseline) == deterministic_projection(final)
        provider_ok = bool(attempts) and all(
            a.get("provider") == "openrouter" and a.get("model") == "google/gemma-4-31b-it"
            for a in attempts
        )

        problems: list[str] = []
        if ai.get("status") != "ok":
            problems.append(f"AI 狀態不是 ok：{ai.get('status')} / {ai.get('message')}")
        if not deterministic_equal:
            problems.append("AI ON/OFF 改變了 deterministic 權威結果")
        if missing_evidence:
            problems.append(f"缺少預期 Oracle evidence：{missing_evidence}")
        if not evidence:
            problems.append("沒有任何 Oracle 11g performance evidence")
        problems += source_problems
        if unsupported_hits:
            problems.append(f"出現無證據／誇大宣稱：{unsupported_hits}")
        if hype_hits:
            problems.append(f"出現誇大用語：{hype_hits}")
        problems += readability["problems"]
        if not provider_ok:
            problems.append("Provider/Model 不是 OpenRouter google/gemma-4-31b-it")
        if evidence and not (ai.get("advice") or []):
            problems.append("已有可說明的效能依據，但 AI 沒有提供任何學習型建議")
        if ((ai.get("suggested_sql") or {}).get("outcome")) == "not_needed" and evidence:
            problems.append("已有效能 evidence 卻回傳 not_needed，語意矛盾")

        record = {
            "id": case["id"],
            "title": case["title"],
            "cost": case["cost"],
            "sql": case["sql"],
            "expected_evidence": sorted(case["expected_evidence"]),
            "observed_evidence": evidence,
            "evidence_ids": sorted(evidence_ids),
            "baseline": baseline,
            "final": final,
            "provider_attempts": [
                {
                    "provider": a["provider"],
                    "model": a["model"],
                    "finish_reason": a["finish_reason"],
                    "prompt_tokens": a["prompt_tokens"],
                    "output_tokens": a["output_tokens"],
                    "total_tokens": a["total_tokens"],
                    "total_duration_ms": a["total_duration_ms"],
                    "request_max_output_tokens": a["request_max_output_tokens"],
                }
                for a in attempts
            ],
            "elapsed_ms": elapsed_ms,
            "deterministic_equal": deterministic_equal,
            "readability": readability,
            "unsupported_hits": unsupported_hits,
            "hype_hits": hype_hits,
            "problems": problems,
            "passed_model_api": not problems,
        }
        all_results.append(record)
        (OUT / "case_json" / f"{case['id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for idx, a in enumerate(attempts, start=1):
            (OUT / "raw_model" / f"{case['id']}_attempt_{idx}.json").write_text(
                json.dumps(
                    {
                        "provider": a["provider"],
                        "model": a["model"],
                        "finish_reason": a["finish_reason"],
                        "request_max_output_tokens": a["request_max_output_tokens"],
                        "raw_json": a["raw_json"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        overall_problems.extend(f"{case['id']}: {p}" for p in problems)

    probe = await controlled_truncation_probe()
    if not probe["passed"]:
        overall_problems.append(f"TRUNCATION_PROBE: fallback 驗證失敗：{probe}")

    summary = {
        "provider": "openrouter",
        "model": "google/gemma-4-31b-it",
        "case_count": len(CASES),
        "case_pass_count": sum(1 for x in all_results if x["passed_model_api"]),
        "all_case_model_api_pass": all(x["passed_model_api"] for x in all_results),
        "controlled_truncation_probe": probe,
        "problems": overall_problems,
    }
    (OUT / "results.json").write_text(
        json.dumps({"summary": summary, "cases": all_results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# OpenRouter / Gemma 4 31B 複雜 SQL 模型與 API 驗收",
        "",
        f"- 測試案例：{len(CASES)}",
        f"- 模型/API 通過：{summary['case_pass_count']}/{len(CASES)}",
        f"- Provider：OpenRouter / google/gemma-4-31b-it",
        f"- Issue #37 controlled truncation fallback：{'PASS' if probe['passed'] else 'FAIL'}",
        "",
        "## 案例結果",
        "",
        "| 案例 | 主題 | Oracle 依據 | AI 建議 | 結果 |",
        "|---|---|---:|---:|---|",
    ]
    for item in all_results:
        final_ai = item["final"].get("ai") or {}
        lines.append(
            f"| {item['id']} | {item['title']} | {len(item['observed_evidence'])} | "
            f"{len(final_ai.get('advice') or [])} | {'PASS' if item['passed_model_api'] else 'FAIL'} |"
        )
    lines += ["", "## 問題"]
    if overall_problems:
        lines.extend(f"- {p}" for p in overall_problems)
    else:
        lines.append("- 模型/API 層未發現驗收違規。")
    (OUT / "MODEL_API_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
