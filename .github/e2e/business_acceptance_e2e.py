#!/usr/bin/env python3
"""Business-facing OpenRouter/Gemma acceptance suite for SQLCheck.

Synthetic SQL only. The artifact may retain SQL/model output because no real taxpayer,
application number, API key, or production identifier is used here.

This runner calls the real HTTP /api/analyze endpoint, so it exercises the FastAPI
orchestration, deterministic rule engine, Oracle evidence selector, OpenRouter adapter,
Gemma 4 31B response handling, server-side safety/revalidation and response schema.
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
        "id": "Q01",
        "name": "土地稅案件：固定前綴 SUBSTR + 同欄位 OR + 彙總",
        "cost": 52340,
        "expected_evidence": ["ORACLE11G_TRANSFORMED_COLUMN", "ORACLE11G_PREFIX_LIKE_RANGE_SCAN"],
        "sql": """
SELECT A.TAX_ID,
       A.CASE_NO,
       B.OWNER_NAME,
       SUM(NVL(P.PAID_AMOUNT, 0)) AS PAID_TOTAL
  FROM TAX_CASE A
  JOIN TAX_OWNER B
    ON B.OWNER_ID = A.OWNER_ID
  LEFT JOIN TAX_PAYMENT P
    ON P.CASE_NO = A.CASE_NO
 WHERE SUBSTR(A.AREA_CODE, 1, 3) = '107'
   AND (A.STATUS = 'A' OR A.STATUS = 'B' OR A.STATUS = 'C')
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.CASE_TYPE = :CASE_TYPE
 GROUP BY A.TAX_ID, A.CASE_NO, B.OWNER_NAME
HAVING SUM(NVL(P.PAID_AMOUNT, 0)) > 0
""".strip(),
    },
    {
        "id": "Q02",
        "name": "納稅義務人查詢：前置萬用字元 LIKE + 多表條件",
        "cost": 38110,
        "expected_evidence": ["ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT"],
        "sql": """
SELECT A.CASE_NO,
       O.OWNER_ID,
       O.OWNER_NAME,
       A.TAX_YEAR,
       A.TAX_AMOUNT
  FROM TAX_CASE A
  JOIN TAX_OWNER O
    ON O.OWNER_ID = A.OWNER_ID
  JOIN TAX_DISTRICT D
    ON D.DISTRICT_ID = A.DISTRICT_ID
 WHERE O.OWNER_NAME LIKE '%股份%'
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS
   AND D.CITY_CODE = :CITY_CODE
 ORDER BY A.CASE_NO
""".strip(),
    },
    {
        "id": "Q03",
        "name": "車籍異動：重複相關 MAX 子查詢取最新紀錄",
        "cost": 74220,
        "expected_evidence": ["ORACLE11G_SUBQUERY_UNNESTING"],
        "sql": """
SELECT V.VEHICLE_ID,
       V.OWNER_ID,
       (SELECT MAX(H.UPDATE_DATE)
          FROM VEHICLE_HISTORY H
         WHERE H.VEHICLE_ID = V.VEHICLE_ID
           AND H.STATUS = 'A') AS LAST_DATE,
       (SELECT MAX(H.UPDATE_TIME)
          FROM VEHICLE_HISTORY H
         WHERE H.VEHICLE_ID = V.VEHICLE_ID
           AND H.STATUS = 'A') AS LAST_TIME
  FROM VEHICLE_MASTER V
 WHERE V.STATUS = :STATUS
   AND V.UPDATE_DATE =
       (SELECT MAX(H2.UPDATE_DATE)
          FROM VEHICLE_HISTORY H2
         WHERE H2.VEHICLE_ID = V.VEHICLE_ID
           AND H2.STATUS = 'A')
   AND V.UPDATE_TIME =
       (SELECT MAX(H3.UPDATE_TIME)
          FROM VEHICLE_HISTORY H3
         WHERE H3.VEHICLE_ID = V.VEHICLE_ID
           AND H3.STATUS = 'A')
""".strip(),
    },
    {
        "id": "Q04",
        "name": "欠稅統計：UNION ALL 多分支重複讀取相同來源",
        "cost": 66180,
        "expected_evidence": ["ORACLE11G_VISIT_DATA_FEWER_TIMES"],
        "sql": """
SELECT L.DISTRICT_ID, 'A' AS BUCKET, COUNT(*) AS CNT, SUM(L.BALANCE) AS AMT
  FROM TAX_LEDGER L
  JOIN TAX_CASE C ON C.CASE_NO = L.CASE_NO
 WHERE L.BALANCE > 0
   AND C.STATUS = 'A'
   AND L.TAX_YEAR = :TAX_YEAR
 GROUP BY L.DISTRICT_ID
UNION ALL
SELECT L.DISTRICT_ID, 'B' AS BUCKET, COUNT(*) AS CNT, SUM(L.BALANCE) AS AMT
  FROM TAX_LEDGER L
  JOIN TAX_CASE C ON C.CASE_NO = L.CASE_NO
 WHERE L.BALANCE BETWEEN :LOW_AMT AND :HIGH_AMT
   AND C.STATUS = 'A'
   AND L.TAX_YEAR = :TAX_YEAR
 GROUP BY L.DISTRICT_ID
UNION ALL
SELECT L.DISTRICT_ID, 'C' AS BUCKET, COUNT(*) AS CNT, SUM(L.BALANCE) AS AMT
  FROM TAX_LEDGER L
  JOIN TAX_CASE C ON C.CASE_NO = L.CASE_NO
 WHERE L.BALANCE > :HIGH_AMT
   AND C.STATUS = 'A'
   AND L.TAX_YEAR = :TAX_YEAR
 GROUP BY L.DISTRICT_ID
""".strip(),
    },
    {
        "id": "Q05",
        "name": "地籍勾稽：JOIN 前先加工複合代碼",
        "cost": 59300,
        "expected_evidence": ["ORACLE11G_TRANSFORMED_COLUMN"],
        "sql": """
SELECT A.CASE_NO,
       A.LAND_KEY,
       B.SECTION_CODE,
       B.LAND_NO,
       A.TAX_AMOUNT
  FROM LAND_TAX_CASE A
  JOIN LAND_MASTER B
    ON SUBSTR(A.LAND_KEY, 1, 8) = B.SECTION_CODE
   AND SUBSTR(A.LAND_KEY, 9, 4) = B.LAND_NO
 WHERE A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS
   AND B.ACTIVE_FLAG = 'Y'
""".strip(),
    },
    {
        "id": "Q06",
        "name": "稅目代碼查詢：欄位串接後再比對",
        "cost": 42990,
        "expected_evidence": ["ORACLE11G_TRANSFORMED_COLUMN"],
        "sql": """
SELECT A.CASE_NO,
       A.TAX_CD,
       A.SUBTAX_CD,
       A.TAX_AMOUNT,
       O.OWNER_NAME
  FROM TAX_CASE A
  JOIN TAX_OWNER O
    ON O.OWNER_ID = A.OWNER_ID
 WHERE A.TAX_CD || A.SUBTAX_CD = :FULL_TAX_CODE
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS
   AND A.TAX_AMOUNT > :MIN_AMOUNT
""".strip(),
    },
    {
        "id": "Q07",
        "name": "管理碼查詢：SUBSTR 非第一碼位置的安全改寫邊界",
        "cost": 47250,
        "expected_evidence": ["ORACLE11G_TRANSFORMED_COLUMN", "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT"],
        "sql": """
SELECT A.CASE_NO,
       A.MANAGE_CD,
       A.OWNER_ID,
       A.TAX_AMOUNT,
       D.DISTRICT_NAME
  FROM TAX_CASE A
  JOIN TAX_DISTRICT D
    ON D.DISTRICT_ID = A.DISTRICT_ID
 WHERE SUBSTR(A.MANAGE_CD, 6, 3) = '551'
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS
   AND D.CITY_CODE = :CITY_CODE
 ORDER BY A.CASE_NO
""".strip(),
    },
    {
        "id": "Q08",
        "name": "跨年度案件：DISTINCT + 前置萬用字元 LIKE",
        "cost": 55840,
        "expected_evidence": ["ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT"],
        "sql": """
SELECT DISTINCT A.CASE_NO,
       O.OWNER_ID,
       O.OWNER_NAME,
       A.TAX_YEAR
  FROM TAX_CASE A
  JOIN TAX_OWNER O
    ON O.OWNER_ID = A.OWNER_ID
  LEFT JOIN TAX_NOTICE N
    ON N.CASE_NO = A.CASE_NO
 WHERE O.OWNER_NAME LIKE '%公司'
   AND A.TAX_YEAR BETWEEN :YEAR_FROM AND :YEAR_TO
   AND A.STATUS = :STATUS
   AND N.NOTICE_TYPE = :NOTICE_TYPE
""".strip(),
    },
    {
        "id": "Q09",
        "name": "分級清冊：同來源 UNION ALL + 同欄位 OR",
        "cost": 69840,
        "expected_evidence": ["ORACLE11G_VISIT_DATA_FEWER_TIMES"],
        "sql": """
SELECT C.DISTRICT_ID, 'NORMAL' AS CLASS_CODE, C.CASE_NO, C.TAX_AMOUNT
  FROM TAX_CASE C
  JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE (C.STATUS = 'A' OR C.STATUS = 'B')
   AND C.TAX_AMOUNT <= :LIMIT_AMT
   AND C.TAX_YEAR = :TAX_YEAR
UNION ALL
SELECT C.DISTRICT_ID, 'HIGH' AS CLASS_CODE, C.CASE_NO, C.TAX_AMOUNT
  FROM TAX_CASE C
  JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE (C.STATUS = 'A' OR C.STATUS = 'B')
   AND C.TAX_AMOUNT > :LIMIT_AMT
   AND C.TAX_YEAR = :TAX_YEAR
""".strip(),
    },
    {
        "id": "Q10",
        "name": "多條件勾稽：加工 JOIN + 前置萬用字元",
        "cost": 78360,
        "expected_evidence": ["ORACLE11G_TRANSFORMED_COLUMN", "ORACLE11G_LEADING_WILDCARD_RANGE_LIMIT"],
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
        "id": "Q11",
        "name": "最新異動 + 串接代碼：兩種 advice-only 邊界同時存在",
        "cost": 81200,
        "expected_evidence": ["ORACLE11G_SUBQUERY_UNNESTING", "ORACLE11G_TRANSFORMED_COLUMN"],
        "sql": """
SELECT V.VEHICLE_ID,
       V.OWNER_ID,
       V.TAX_CD,
       V.SUBTAX_CD,
       (SELECT MAX(H.CHANGE_DATE)
          FROM VEHICLE_HISTORY H
         WHERE H.VEHICLE_ID = V.VEHICLE_ID
           AND H.STATUS = 'A') AS LAST_CHANGE_DATE,
       (SELECT MAX(H.CHANGE_TIME)
          FROM VEHICLE_HISTORY H
         WHERE H.VEHICLE_ID = V.VEHICLE_ID
           AND H.STATUS = 'A') AS LAST_CHANGE_TIME
  FROM VEHICLE_MASTER V
 WHERE V.TAX_CD || V.SUBTAX_CD = :FULL_TAX_CODE
   AND V.STATUS = :STATUS
   AND V.TAX_YEAR = :TAX_YEAR
""".strip(),
    },
    {
        "id": "Q12",
        "name": "長 SQL 壓力案例：多分支 UNION ALL + SUBSTR 固定前綴",
        "cost": 88900,
        "expected_evidence": ["ORACLE11G_VISIT_DATA_FEWER_TIMES", "ORACLE11G_TRANSFORMED_COLUMN", "ORACLE11G_PREFIX_LIKE_RANGE_SCAN"],
        "sql": """
SELECT C.DISTRICT_ID, 'B01' AS BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 1 AND 1000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'B02' AS BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 1001 AND 5000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'B03' AS BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 5001 AND 10000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'B04' AS BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 10001 AND 20000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'B05' AS BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 20001 AND 30000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'B06' AS BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 30001 AND 50000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'B07' AS BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 50001 AND 80000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'B08' AS BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 80001 AND 120000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'B09' AS BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT BETWEEN 120001 AND 200000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'B10' AS BUCKET, COUNT(*) CNT, SUM(C.TAX_AMOUNT) AMT
  FROM TAX_CASE C JOIN TAX_OWNER O ON O.OWNER_ID = C.OWNER_ID
 WHERE SUBSTR(C.AREA_CODE,1,3)='107' AND C.STATUS='A' AND C.TAX_YEAR=:Y AND C.TAX_AMOUNT > 200000
 GROUP BY C.DISTRICT_ID
""".strip(),
    },
]

SIMPLIFIED_ONLY = set("数据库让说后优记录动态执")
UNSUPPORTED_ASSERTIONS = [
    re.compile(r"(?:已|確定|確認)(?:會)?使用索引", re.I),
    re.compile(r"(?:未|沒有)使用索引", re.I),
    re.compile(r"索引失效", re.I),
    re.compile(r"(?:已|確定|確認).{0,8}(?:Full\s*Table\s*Scan|全表掃描)", re.I),
    re.compile(r"(?:Execution\s*Plan|執行計畫).{0,12}(?:顯示|證明|確認)", re.I),
    re.compile(r"改善後\s*COST", re.I),
    re.compile(r"(?:速度|效能|執行時間).{0,12}(?:提升|改善|減少).{0,4}\d+\s*%", re.I),
]
ABSOLUTE_PHRASES = ("保證會", "必然會", "肯定會", "絕對會", "百分之百會")


def post_analyze(case: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "application_no": f"E2E-{case['id']}-20260925",
        "cost": case["cost"],
        "sql": case["sql"],
        "execution_plan": None,
        "include_ai": True,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + "/api/analyze",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ai_prose(result: dict[str, Any]) -> str:
    ai = result.get("ai") or {}
    parts: list[str] = []
    if isinstance(ai.get("summary"), str):
        parts.append(ai["summary"])
    for item in ai.get("advice") or []:
        if not isinstance(item, dict):
            continue
        for key in ("title", "explanation"):
            if isinstance(item.get(key), str):
                parts.append(item[key])
    suggested = ai.get("suggested_sql") or {}
    if isinstance(suggested, dict) and isinstance(suggested.get("reason"), str):
        parts.append(suggested["reason"])
    return "\n".join(parts)


def scan_safety(text: str) -> list[str]:
    problems: list[str] = []
    for rx in UNSUPPORTED_ASSERTIONS:
        hit = rx.search(text)
        if hit:
            problems.append("疑似無依據斷言：" + hit.group(0))
    for phrase in ABSOLUTE_PHRASES:
        if phrase in text:
            problems.append("過度肯定語氣：" + phrase)
    if "一定會" in text and not any(s in text for s in ("不一定會", "不代表一定會", "不能保證一定會")):
        problems.append("過度肯定語氣：一定會")
    return problems


def friendly_heuristics(result: dict[str, Any]) -> list[str]:
    ai = result.get("ai") or {}
    problems: list[str] = []
    summary = ai.get("summary") or ""
    advice = ai.get("advice") or []
    if len(summary) > 260:
        problems.append(f"摘要過長：{len(summary)} 字")
    if len(advice) > 3:
        problems.append(f"建議超過 3 項：{len(advice)}")
    for idx, item in enumerate(advice, start=1):
        explanation = str((item or {}).get("explanation") or "")
        if len(explanation) > 520:
            problems.append(f"第 {idx} 項說明過長：{len(explanation)} 字")
    simplified = sorted({ch for ch in ai_prose(result) if ch in SIMPLIFIED_ONLY})
    if simplified:
        problems.append("疑似簡體字：" + "".join(simplified))
    return problems


def evidence_problems(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    items = result.get("performance_evidence") or []
    ids = {str(item.get("evidence_id")) for item in items if isinstance(item, dict)}
    problems: list[str] = []
    missing = [eid for eid in case["expected_evidence"] if eid not in ids]
    if missing:
        problems.append("缺少預期 Oracle evidence：" + ", ".join(missing))
    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("source_label") or "")
        document = str(item.get("source_document") or "")
        claim = str(item.get("claim_zh_tw") or "")
        caveat = str(item.get("caveat_zh_tw") or "")
        if "Oracle" not in label or "Oracle" not in document:
            problems.append(f"{item.get('evidence_id')}: 來源不是 Oracle 官方文件標示")
        if not claim or not caveat:
            problems.append(f"{item.get('evidence_id')}: claim/caveat 不完整")
    ai = result.get("ai") or {}
    if ai.get("status") == "ok" and (ai.get("advice") or []) and not items:
        problems.append("AI 有建議，但畫面沒有 Oracle performance evidence")
    return problems


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    (out / "final_api").mkdir(exist_ok=True)
    cases_out = [
        {k: v for k, v in case.items() if k in {"id", "name", "cost", "sql", "expected_evidence"}}
        for case in CASES
    ]
    (out / "cases.json").write_text(
        json.dumps(cases_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    rows: list[dict[str, Any]] = []
    overall_fail = False

    for case in CASES:
        print(f"[RUN] {case['id']} {case['name']}", flush=True)
        started = time.perf_counter()
        transport_error: str | None = None
        try:
            result = post_analyze(case)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            result = {}
            transport_error = type(exc).__name__
        elapsed = round(time.perf_counter() - started, 2)

        if result:
            (out / "final_api" / f"{case['id']}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

        ai = result.get("ai") or {}
        prose = ai_prose(result)
        safety = scan_safety(prose)
        friendly = friendly_heuristics(result) if result else ["無結果"]
        evidence = evidence_problems(case, result) if result else ["無結果"]
        status_ok = ai.get("status") == "ok"
        degrade_code = ai.get("degrade_code")
        advice_count = len(ai.get("advice") or [])
        evidence_count = len(result.get("performance_evidence") or [])
        outcome = (ai.get("suggested_sql") or {}).get("outcome")
        passed = (
            transport_error is None
            and status_ok
            and not safety
            and not friendly
            and not evidence
        )
        overall_fail |= not passed
        rows.append(
            {
                "id": case["id"],
                "name": case["name"],
                "elapsed_seconds": elapsed,
                "transport_error": transport_error,
                "ai_status": ai.get("status"),
                "degrade_code": degrade_code,
                "advice_count": advice_count,
                "evidence_count": evidence_count,
                "suggested_outcome": outcome,
                "safety_problems": safety,
                "friendly_heuristic_problems": friendly,
                "evidence_problems": evidence,
                "machine_pass": passed,
            }
        )
        print(
            f"[DONE] {case['id']} ai={ai.get('status')} advice={advice_count} "
            f"evidence={evidence_count} outcome={outcome} pass={passed} t={elapsed}s",
            flush=True,
        )

    # Reliability follow-up: Q08 exposed an unusually verbose DISTINCT + leading-wildcard
    # combination in the first run. Re-run it three independent times so a one-off
    # provider/model sample is not mistaken for a deterministic product failure.
    reliability_dir = out / "reliability"
    reliability_dir.mkdir(exist_ok=True)
    q08 = next(case for case in CASES if case["id"] == "Q08")
    reliability_rows: list[dict[str, Any]] = []
    for repeat in range(1, 4):
        print(f"[REPEAT] Q08 r{repeat}", flush=True)
        started = time.perf_counter()
        try:
            repeated = post_analyze(q08)
            transport = None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            repeated = {}
            transport = type(exc).__name__
        elapsed = round(time.perf_counter() - started, 2)
        if repeated:
            (reliability_dir / f"Q08_r{repeat}.json").write_text(
                json.dumps(repeated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        repeated_ai = repeated.get("ai") or {}
        reliability_rows.append({
            "repeat": repeat,
            "elapsed_seconds": elapsed,
            "transport_error": transport,
            "ai_status": repeated_ai.get("status"),
            "degrade_code": repeated_ai.get("degrade_code"),
            "advice_count": len(repeated_ai.get("advice") or []),
            "evidence_count": len(repeated.get("performance_evidence") or []),
            "outcome": (repeated_ai.get("suggested_sql") or {}).get("outcome"),
        })
    (out / "q08_reliability.json").write_text(
        json.dumps(reliability_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    (out / "api_acceptance.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    md = [
        "# SQLCheck OpenRouter / Gemma 4 31B — Business Acceptance (machine checks)",
        "",
        "此檔只做可自動化的初篩；最終「白話、友善、直覺、是否誤導」仍由人工閱讀實際輸出判定。",
        "",
        "| 案例 | AI | 建議 | Oracle 依據 | 改寫狀態 | 機器初篩 |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        md.append(
            f"| {row['id']} {row['name']} | {row['ai_status']} | {row['advice_count']} | "
            f"{row['evidence_count']} | {row['suggested_outcome']} | "
            f"{'PASS' if row['machine_pass'] else 'REVIEW/FAIL'} |"
        )
    md += ["", "## 自動檢查異常"]
    any_problem = False
    for row in rows:
        problems = (
            ([f"transport={row['transport_error']}"] if row["transport_error"] else [])
            + ([f"ai_status={row['ai_status']} degrade_code={row['degrade_code']}"] if row["ai_status"] != "ok" else [])
            + row["safety_problems"]
            + row["friendly_heuristic_problems"]
            + row["evidence_problems"]
        )
        if problems:
            any_problem = True
            md.append(f"- **{row['id']}**：" + "；".join(problems))
    if not any_problem:
        md.append("- 無。")
    md += ["", "## Q08 可靠度重跑（另做 3 次，不覆蓋第一次結果）"]
    for item in reliability_rows:
        md.append(
            f"- r{item['repeat']}: ai={item['ai_status']}, degrade={item['degrade_code']}, "
            f"advice={item['advice_count']}, outcome={item['outcome']}, {item['elapsed_seconds']}s"
        )

    (out / "API_MACHINE_REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return 2 if overall_fail else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(main(args.out))
