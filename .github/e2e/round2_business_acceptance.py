#!/usr/bin/env python3
"""Round-2 business acceptance for SQLCheck / OpenRouter Gemma 4 31B.

All SQL is synthetic. This suite targets the exact failures found in Round 1:
- aggregate NVL must not be mislabeled as an NVL predicate;
- every visible AI advice must be bound to a deterministic pattern and Oracle evidence;
- multi-pattern SQL must not cross-wire one pattern's safe copy into another;
- repeated-query prose must be cautious, not absolute;
- output truncation recovery must stay useful and bounded.

The runner talks to the real /api/analyze endpoint so it exercises the same
FastAPI -> parser/rules -> evidence -> OpenRouter -> safety finalizer path as UI.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = "http://127.0.0.1:8000"

CASES: list[dict[str, Any]] = [
    {
        "id": "R2-01",
        "name": "彙總 NVL 誤判防護 + 固定前綴 SUBSTR",
        "cost": 57320,
        "expected_evidence": {
            "ORACLE11G_TRANSFORMED_COLUMN",
            "ORACLE11G_PREFIX_LIKE_RANGE_SCAN",
        },
        "required_advice_patterns": {"SUBSTR_EQ_TO_LIKE"},
        "forbidden_advice_patterns": {"NVL_EQ_TO_OR_IS_NULL"},
        "sql": """
SELECT A.CASE_NO,
       A.AREA_CODE,
       SUM(NVL(P.PAID_AMOUNT, 0)) AS PAID_TOTAL
  FROM TAX_CASE A
  JOIN TAX_PAYMENT P ON P.CASE_NO = A.CASE_NO
 WHERE SUBSTR(A.AREA_CODE, 1, 3) = '107'
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS
 GROUP BY A.CASE_NO, A.AREA_CODE
HAVING SUM(NVL(P.PAID_AMOUNT, 0)) > 0
""".strip(),
    },
    {
        "id": "R2-02",
        "name": "直接 NVL 條件：要能精準辨識但不可猜改寫",
        "cost": 42110,
        "expected_evidence": {"ORACLE11G_TRANSFORMED_COLUMN"},
        "required_advice_patterns": {"NVL_EQ_TO_OR_IS_NULL"},
        "forbidden_advice_patterns": set(),
        "sql": """
SELECT A.CASE_NO, A.OWNER_ID, A.STATUS
  FROM TAX_CASE A
 WHERE NVL(A.CLOSE_FLAG, 'N') = 'N'
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS
""".strip(),
    },
    {
        "id": "R2-03",
        "name": "加工 JOIN + 前置萬用字元：防止兩張卡片文案串線",
        "cost": 79240,
        "expected_evidence": {
            "ORACLE11G_TRANSFORMED_COLUMN",
            "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT",
        },
        "required_advice_patterns": {
            "COMPOSITE_KEY_EXPRESSION_JOIN",
            "LEADING_WILDCARD_LIKE",
        },
        "forbidden_advice_patterns": set(),
        "sql": """
SELECT A.CASE_NO,
       A.COMPOSITE_KEY,
       B.KEY_HEAD,
       B.KEY_TAIL,
       O.OWNER_NAME
  FROM TAX_CASE A
  JOIN KEY_REFERENCE B
    ON SUBSTR(A.COMPOSITE_KEY, 1, 6) = B.KEY_HEAD
   AND SUBSTR(A.COMPOSITE_KEY, 7, 4) = B.KEY_TAIL
  JOIN TAX_OWNER O
    ON O.OWNER_ID = A.OWNER_ID
 WHERE O.OWNER_NAME LIKE '%商行%'
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS
""".strip(),
    },
    {
        "id": "R2-04",
        "name": "DISTINCT + JOIN：每則建議都要有 Oracle 依據",
        "cost": 61870,
        "expected_evidence": {"ORACLE11G_DISTINCT_DUPLICATE_ELIMINATION"},
        "required_advice_patterns": {"DISTINCT_REMOVAL"},
        "forbidden_advice_patterns": set(),
        "sql": """
SELECT DISTINCT A.CASE_NO,
       O.OWNER_ID,
       O.OWNER_NAME,
       N.NOTICE_TYPE
  FROM TAX_CASE A
  JOIN TAX_OWNER O ON O.OWNER_ID = A.OWNER_ID
  LEFT JOIN TAX_NOTICE N ON N.CASE_NO = A.CASE_NO
 WHERE A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS
   AND N.NOTICE_TYPE = :NOTICE_TYPE
""".strip(),
    },
    {
        "id": "R2-05",
        "name": "重複 MAX 最新紀錄：語氣必須保守",
        "cost": 76450,
        "expected_evidence": {"ORACLE11G_SUBQUERY_UNNESTING"},
        "required_advice_patterns": {"LATEST_ROW_CORRELATED_MAX"},
        "forbidden_advice_patterns": set(),
        "sql": """
SELECT V.VEHICLE_ID,
       V.OWNER_ID,
       (SELECT MAX(H.CHANGE_DATE)
          FROM VEHICLE_HISTORY H
         WHERE H.VEHICLE_ID = V.VEHICLE_ID
           AND H.STATUS = 'A') AS LAST_CHANGE_DATE,
       (SELECT MAX(H.CHANGE_TIME)
          FROM VEHICLE_HISTORY H
         WHERE H.VEHICLE_ID = V.VEHICLE_ID
           AND H.STATUS = 'A') AS LAST_CHANGE_TIME
  FROM VEHICLE_MASTER V
 WHERE V.TAX_YEAR = :TAX_YEAR
   AND V.STATUS = :STATUS
""".strip(),
    },
    {
        "id": "R2-06",
        "name": "TO_CHAR 日期條件：不能自行發明日期邊界",
        "cost": 44880,
        "expected_evidence": {"ORACLE11G_TRANSFORMED_COLUMN"},
        "required_advice_patterns": {"TO_CHAR_CONDITION_PREDICATE"},
        "forbidden_advice_patterns": set(),
        "sql": """
SELECT A.CASE_NO, A.TXN_DATE, A.TAX_AMOUNT
  FROM TAX_CASE A
 WHERE TO_CHAR(A.TXN_DATE, 'YYYY') = '2024'
   AND A.STATUS = :STATUS
   AND A.DISTRICT_ID = :DISTRICT_ID
""".strip(),
    },
    {
        "id": "R2-07",
        "name": "TRUNC 日期條件：只能給確認方向",
        "cost": 46720,
        "expected_evidence": {"ORACLE11G_TRANSFORMED_COLUMN"},
        "required_advice_patterns": {"TRUNC_EQ_TO_RANGE"},
        "forbidden_advice_patterns": set(),
        "sql": """
SELECT A.CASE_NO, A.TXN_DATE, A.OWNER_ID
  FROM TAX_CASE A
 WHERE TRUNC(A.TXN_DATE) = :QUERY_DATE
   AND A.STATUS = :STATUS
   AND A.TAX_YEAR = :TAX_YEAR
""".strip(),
    },
    {
        "id": "R2-08",
        "name": "UPPER 條件：不得假設資料大小寫已統一",
        "cost": 39820,
        "expected_evidence": {"ORACLE11G_TRANSFORMED_COLUMN"},
        "required_advice_patterns": {"UPPER_CASE_FOLD_REMOVAL"},
        "forbidden_advice_patterns": set(),
        "sql": """
SELECT O.OWNER_ID, O.OWNER_NAME, O.EMAIL
  FROM TAX_OWNER O
 WHERE UPPER(O.EMAIL) = :EMAIL_UPPER
   AND O.ACTIVE_FLAG = :ACTIVE_FLAG
""".strip(),
    },
    {
        "id": "R2-09",
        "name": "長 UNION ALL + 固定前綴 SUBSTR：截斷恢復壓力測試",
        "cost": 89320,
        "expected_evidence": {
            "ORACLE11G_VISIT_DATA_FEWER_TIMES",
            "ORACLE11G_TRANSFORMED_COLUMN",
            "ORACLE11G_PREFIX_LIKE_RANGE_SCAN",
        },
        "required_advice_patterns": {
            "REPEATED_SOURCE_UNION_BRANCH",
            "SUBSTR_EQ_TO_LIKE",
        },
        "forbidden_advice_patterns": set(),
        "sql": """
SELECT C.DISTRICT_ID, 'A1' BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID=C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 1 AND 1000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'A2' BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID=C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 1001 AND 5000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'A3' BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID=C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 5001 AND 10000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'A4' BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID=C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 10001 AND 20000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'A5' BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID=C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 20001 AND 50000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'A6' BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID=C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT > 50000
 GROUP BY C.DISTRICT_ID
""".strip(),
    },
    {
        "id": "R2-10",
        "name": "串接條件 + 前置萬用字元：多 pattern evidence 對齊",
        "cost": 70410,
        "expected_evidence": {
            "ORACLE11G_TRANSFORMED_COLUMN",
            "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT",
        },
        "required_advice_patterns": {
            "STRING_CONCAT_PREDICATE_SPLIT",
            "LEADING_WILDCARD_LIKE",
        },
        "forbidden_advice_patterns": set(),
        "sql": """
SELECT A.CASE_NO,
       A.TAX_CD,
       A.SUBTAX_CD,
       O.OWNER_NAME,
       A.TAX_AMOUNT
  FROM TAX_CASE A
  JOIN TAX_OWNER O ON O.OWNER_ID = A.OWNER_ID
 WHERE A.TAX_CD || A.SUBTAX_CD = :FULL_TAX_CODE
   AND O.OWNER_NAME LIKE '%企業%'
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS
""".strip(),
    },
]

SIMPLIFIED_ONLY = set("数据库让说后优记录动态执")
FORBIDDEN_CLAIMS = [
    re.compile(r"Full\s*Table\s*Scan|全表掃描|全資料表掃描", re.I),
    re.compile(r"索引失效|已使用索引|未使用索引|使用了索引|沒有使用索引", re.I),
    re.compile(r"改善後\s*COST", re.I),
    re.compile(r"(?:速度|效能|執行時間).{0,15}(?:提升|改善|減少).{0,5}\d+\s*%", re.I),
    re.compile(r"(?:已測試|已驗證|實測)", re.I),
]
DATE_LITERAL_RE = re.compile(r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")
ABSOLUTE_REPEATED_RE = re.compile(r"每筆資料都會|每一筆資料都會|一定會.*重複", re.I)


def post(case: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(
        {
            "application_no": f"ROUND2-{case['id']}",
            "cost": case["cost"],
            "sql": case["sql"],
            "execution_plan": None,
            "include_ai": True,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + "/api/analyze",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.loads(response.read().decode("utf-8"))


def visible_prose(result: dict[str, Any]) -> str:
    ai = result.get("ai") or {}
    parts = [str(ai.get("summary") or "")]
    for item in ai.get("advice") or []:
        parts.append(str(item.get("title") or ""))
        parts.append(str(item.get("explanation") or ""))
    suggested = ai.get("suggested_sql") or {}
    parts.append(str(suggested.get("reason") or ""))
    return "\n".join(parts)


def judge(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    ai = result.get("ai") or {}
    if ai.get("status") != "ok":
        problems.append(f"AI 未完成：status={ai.get('status')} degrade={ai.get('degrade_code')}")
        return problems

    evidence = result.get("performance_evidence") or []
    evidence_ids = {str(x.get("evidence_id")) for x in evidence if isinstance(x, dict)}
    missing = sorted(case["expected_evidence"] - evidence_ids)
    if missing:
        problems.append("缺少預期 Oracle evidence：" + ", ".join(missing))

    advice = ai.get("advice") or []
    advice_patterns = {str(x.get("pattern_id")) for x in advice if isinstance(x, dict) and x.get("pattern_id")}
    missing_patterns = sorted(case["required_advice_patterns"] - advice_patterns)
    if missing_patterns:
        problems.append("缺少應呈現的 evidence-backed advice pattern：" + ", ".join(missing_patterns))

    forbidden_patterns = sorted(case["forbidden_advice_patterns"] & advice_patterns)
    if forbidden_patterns:
        problems.append("不應出現的 advice pattern：" + ", ".join(forbidden_patterns))

    for index, item in enumerate(advice, start=1):
        if not isinstance(item, dict):
            problems.append(f"第 {index} 項 advice 格式異常")
            continue
        pattern_id = item.get("pattern_id")
        linked = item.get("evidence_ids") or []
        if not pattern_id:
            problems.append(f"第 {index} 項 advice 沒有 pattern_id")
        if not linked:
            problems.append(f"第 {index} 項 advice 沒有 Oracle evidence_ids")
        unknown = [x for x in linked if x not in evidence_ids]
        if unknown:
            problems.append(f"第 {index} 項 advice 引用不存在的 evidence：{unknown}")
        explanation = str(item.get("explanation") or "")
        if len(explanation) > 430:
            problems.append(f"第 {index} 項 explanation 過長：{len(explanation)} 字")

        if pattern_id == "COMPOSITE_KEY_EXPRESSION_JOIN":
            if "JOIN" not in explanation and "勾稽" not in explanation and "原始欄位" not in explanation:
                problems.append("加工 JOIN 建議沒有講到 JOIN／原始欄位")
            if "前置萬用字元" in explanation:
                problems.append("加工 JOIN 建議被 LIKE 文案串線")
        elif pattern_id == "LEADING_WILDCARD_LIKE":
            if "萬用字元" not in explanation and "比對範圍" not in explanation:
                problems.append("前置 LIKE 建議沒有講到萬用字元／比對範圍")
            if "JOIN 在比對前" in explanation:
                problems.append("LIKE 建議被 JOIN 文案串線")
        elif pattern_id == "LATEST_ROW_CORRELATED_MAX":
            if ABSOLUTE_REPEATED_RE.search(explanation):
                problems.append("重複 MAX 使用過度肯定語氣")
            if "可能" not in explanation:
                problems.append("重複 MAX 缺少可能性語氣")
        elif pattern_id in {"TRUNC_EQ_TO_RANGE", "TO_CHAR_CONDITION_PREDICATE"}:
            if DATE_LITERAL_RE.search(explanation):
                problems.append(f"{pattern_id} 自行產生具體日期")
        elif pattern_id == "UPPER_CASE_FOLD_REMOVAL":
            if re.search(r"資料(?:已|都|全部).{0,8}(?:統一|相同).{0,5}大小寫", explanation):
                problems.append("UPPER 建議自行假設資料大小寫已統一")

    prose = visible_prose(result)
    for rx in FORBIDDEN_CLAIMS:
        hit = rx.search(prose)
        if hit:
            problems.append("疑似無依據／禁語：" + hit.group(0))
    simplified = sorted({ch for ch in prose if ch in SIMPLIFIED_ONLY})
    if simplified:
        problems.append("疑似簡體字：" + "".join(simplified))
    if len(str(ai.get("summary") or "")) > 270:
        problems.append("summary 過長")

    # Specific regression: SUM(NVL(...)) must not create the simple NVL pattern.
    if case["id"] == "R2-01":
        if any(x.get("pattern_id") == "NVL_EQ_TO_OR_IS_NULL" for x in evidence if isinstance(x, dict)):
            problems.append("SUM(NVL(...)) 被 evidence selector 誤判為 NVL predicate")

    return problems


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    (out / "final_api").mkdir(exist_ok=True)
    serializable_cases = []
    for case in CASES:
        serializable_cases.append({
            **{k: v for k, v in case.items() if k not in {"expected_evidence", "required_advice_patterns", "forbidden_advice_patterns"}},
            "expected_evidence": sorted(case["expected_evidence"]),
            "required_advice_patterns": sorted(case["required_advice_patterns"]),
            "forbidden_advice_patterns": sorted(case["forbidden_advice_patterns"]),
        })
    (out / "cases.json").write_text(json.dumps(serializable_cases, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

    rows: list[dict[str, Any]] = []
    failed = False
    for case in CASES:
        print(f"[RUN] {case['id']} {case['name']}", flush=True)
        started = time.perf_counter()
        transport: str | None = None
        try:
            result = post(case)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            result = {}
            transport = type(exc).__name__
        elapsed = round(time.perf_counter() - started, 2)
        if result:
            (out / "final_api" / f"{case['id']}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8"
            )
        problems = [f"transport={transport}"] if transport else judge(case, result)
        passed = not problems
        failed |= not passed
        ai = result.get("ai") or {}
        rows.append({
            "id": case["id"],
            "name": case["name"],
            "elapsed_seconds": elapsed,
            "ai_status": ai.get("status"),
            "degrade_code": ai.get("degrade_code"),
            "advice_patterns": [x.get("pattern_id") for x in ai.get("advice") or []],
            "advice_evidence_ids": [x.get("evidence_ids") for x in ai.get("advice") or []],
            "performance_evidence_ids": [x.get("evidence_id") for x in result.get("performance_evidence") or []],
            "outcome": (ai.get("suggested_sql") or {}).get("outcome"),
            "problems": problems,
            "pass": passed,
        })
        print(f"[DONE] {case['id']} pass={passed} t={elapsed}s problems={problems}", flush=True)

    # Reliability repeats on the two Round-1 failure classes:
    # multi-pattern drift and long-output/truncation.
    reliability: list[dict[str, Any]] = []
    for case_id in ("R2-03", "R2-09"):
        case = next(x for x in CASES if x["id"] == case_id)
        for repeat in range(1, 4):
            started = time.perf_counter()
            try:
                result = post(case)
                transport = None
                problems = judge(case, result)
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                result = {}
                transport = type(exc).__name__
                problems = [f"transport={transport}"]
            reliability.append({
                "case_id": case_id,
                "repeat": repeat,
                "elapsed_seconds": round(time.perf_counter()-started, 2),
                "ai_status": (result.get("ai") or {}).get("status"),
                "degrade_code": (result.get("ai") or {}).get("degrade_code"),
                "problems": problems,
                "pass": not problems,
            })
            failed |= bool(problems)
    (out / "reliability.json").write_text(json.dumps(reliability, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (out / "acceptance.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

    md = [
        "# SQLCheck Round-2 OpenRouter/Gemma — machine acceptance",
        "",
        "| Case | AI | Advice patterns | Oracle evidence | Result |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        md.append(
            f"| {row['id']} | {row['ai_status']} | {', '.join(x or '—' for x in row['advice_patterns']) or '—'} | "
            f"{', '.join(row['performance_evidence_ids']) or '—'} | {'PASS' if row['pass'] else 'FAIL'} |"
        )
    md += ["", "## Problems"]
    problem_count = 0
    for row in rows:
        for problem in row["problems"]:
            problem_count += 1
            md.append(f"- {row['id']}: {problem}")
    if not problem_count:
        md.append("- 無。")
    md += ["", "## Reliability repeats"]
    for item in reliability:
        md.append(
            f"- {item['case_id']} r{item['repeat']}: "
            f"{'PASS' if item['pass'] else 'FAIL'} / ai={item['ai_status']} / degrade={item['degrade_code']}"
        )
    (out / "MACHINE_REPORT.md").write_text("\n".join(md)+"\n", encoding="utf-8")
    return 2 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(main(args.out))
