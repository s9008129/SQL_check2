#!/usr/bin/env python3
"""Round-2 business acceptance for SQLCheck + OpenRouter Gemma 4 31B.

Synthetic SQL only. This suite specifically re-tests the four defects found in
the first business acceptance:
- aggregate NVL must not be misclassified as an NVL predicate;
- every visible AI performance advice must carry server-validated pattern and
  Oracle evidence provenance;
- multi-pattern advice must not borrow another pattern's wording;
- long/complex output must stay usable without misleading truncation copy.
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
        "id": "S01",
        "name": "彙總 NVL 不得誤判 + 固定前綴 SUBSTR",
        "cost": 52700,
        "expected_patterns": ["SUBSTR_EQ_TO_LIKE"],
        "forbidden_patterns": ["NVL_EQ_TO_OR_IS_NULL"],
        "sql": """SELECT A.CASE_NO,
       SUM(NVL(P.PAID_AMT, 0)) AS PAID_TOTAL
  FROM R2_TAX_CASE A
  JOIN R2_PAYMENT P ON P.CASE_NO = A.CASE_NO
 WHERE SUBSTR(A.AREA_CODE, 1, 2) = 'TN'
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS
 GROUP BY A.CASE_NO
HAVING SUM(NVL(P.PAID_AMT, 0)) > 0""",
    },
    {
        "id": "S02",
        "name": "直接 NVL 條件必須精準辨識",
        "cost": 41300,
        "expected_patterns": ["NVL_EQ_TO_OR_IS_NULL"],
        "forbidden_patterns": [],
        "sql": """SELECT A.CASE_NO, A.OWNER_ID, A.TAX_AMOUNT
  FROM R2_TAX_CASE A
 WHERE NVL(A.CANCEL_FLAG, 'N') = 'N'
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS
   AND A.TAX_AMOUNT > :MIN_AMT""",
    },
    {
        "id": "S03",
        "name": "加工 JOIN + 前置萬用字元，多 Pattern 不得串線",
        "cost": 63400,
        "expected_patterns": ["COMPOSITE_KEY_EXPRESSION_JOIN", "LEADING_WILDCARD_LIKE"],
        "forbidden_patterns": [],
        "sql": """SELECT A.CASE_NO, A.LAND_KEY, B.SECTION_KEY, O.OWNER_NAME
  FROM R2_LAND_CASE A
  JOIN R2_LAND_MASTER B
    ON SUBSTR(A.LAND_KEY, 1, 6) = B.SECTION_KEY
  JOIN R2_OWNER O
    ON O.OWNER_ID = A.OWNER_ID
 WHERE O.OWNER_NAME LIKE '%商行%'
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS""",
    },
    {
        "id": "S04",
        "name": "DISTINCT + 前置萬用字元，無 Oracle 依據的 AI 建議不得顯示",
        "cost": 56800,
        "expected_patterns": ["LEADING_WILDCARD_LIKE"],
        "forbidden_patterns": ["DISTINCT_REMOVAL"],
        "sql": """SELECT DISTINCT A.CASE_NO, O.OWNER_NAME, N.NOTICE_TYPE
  FROM R2_TAX_CASE A
  JOIN R2_OWNER O ON O.OWNER_ID = A.OWNER_ID
  LEFT JOIN R2_NOTICE N ON N.CASE_NO = A.CASE_NO
 WHERE O.OWNER_NAME LIKE '%公司%'
   AND A.TAX_YEAR BETWEEN :YEAR_FROM AND :YEAR_TO
   AND A.STATUS = :STATUS""",
    },
    {
        "id": "S05",
        "name": "TRUNC 日期條件只能提供有前提的白話方向",
        "cost": 48100,
        "expected_patterns": ["TRUNC_EQ_TO_RANGE"],
        "forbidden_patterns": [],
        "sql": """SELECT A.CASE_NO, A.RECEIVE_DATE, A.TAX_AMOUNT
  FROM R2_RECEIPT A
 WHERE TRUNC(A.RECEIVE_DATE) = :TARGET_DATE
   AND A.STATUS = :STATUS
   AND A.DISTRICT_ID = :DISTRICT_ID""",
    },
    {
        "id": "S06",
        "name": "TO_CHAR 年度條件不得自行發明日期界線",
        "cost": 44600,
        "expected_patterns": ["PREDICATE_FUNCTION_GENERIC"],
        "forbidden_patterns": [],
        "sql": """SELECT A.CASE_NO, A.APPROVE_DATE, A.TAX_AMOUNT
  FROM R2_APPROVAL A
 WHERE TO_CHAR(A.APPROVE_DATE, 'YYYY') = :YEAR_TEXT
   AND A.STATUS = :STATUS
   AND A.DISTRICT_ID = :DISTRICT_ID""",
    },
    {
        "id": "S07",
        "name": "重複相關 MAX 只用可能性語氣",
        "cost": 76100,
        "expected_patterns": ["LATEST_ROW_CORRELATED_MAX"],
        "forbidden_patterns": [],
        "sql": """SELECT V.VEHICLE_ID,
       V.OWNER_ID,
       (SELECT MAX(H.CHANGE_DATE)
          FROM R2_VEHICLE_HISTORY H
         WHERE H.VEHICLE_ID = V.VEHICLE_ID
           AND H.STATUS = 'A') AS LAST_CHANGE_DATE,
       (SELECT MAX(H.CHANGE_TIME)
          FROM R2_VEHICLE_HISTORY H
         WHERE H.VEHICLE_ID = V.VEHICLE_ID
           AND H.STATUS = 'A') AS LAST_CHANGE_TIME
  FROM R2_VEHICLE V
 WHERE V.STATUS = :STATUS
   AND V.TAX_YEAR = :TAX_YEAR""",
    },
    {
        "id": "S08",
        "name": "重複統計子查詢 + 串接代碼，兩張建議卡各自有依據",
        "cost": 80400,
        "expected_patterns": ["REPEATED_SCALAR_AGGREGATE", "STRING_CONCAT_PREDICATE_SPLIT"],
        "forbidden_patterns": [],
        "sql": """SELECT A.CASE_NO,
       (SELECT COUNT(*)
          FROM R2_DETAIL D1
         WHERE D1.CASE_NO = A.CASE_NO
           AND D1.KIND = 'A') AS CNT_A,
       (SELECT SUM(D2.AMOUNT)
          FROM R2_DETAIL D2
         WHERE D2.CASE_NO = A.CASE_NO
           AND D2.KIND = 'B') AS AMT_B
  FROM R2_TAX_CASE A
 WHERE A.TAX_CD || A.SUBTAX_CD = :FULL_TAX_CODE
   AND A.TAX_YEAR = :TAX_YEAR
   AND A.STATUS = :STATUS""",
    },
    {
        "id": "S09",
        "name": "長型 UNION ALL + 固定前綴 SUBSTR 壓力案例",
        "cost": 89200,
        "expected_patterns": ["SUBSTR_EQ_TO_LIKE", "REPEATED_SOURCE_UNION_BRANCH"],
        "forbidden_patterns": [],
        "sql": """SELECT C.DISTRICT_ID, 'R1' BUCKET, COUNT(*) CNT, SUM(L.BALANCE) AMT
  FROM R2_LEDGER L JOIN R2_TAX_CASE C ON C.CASE_NO=L.CASE_NO
 WHERE SUBSTR(C.AREA_CODE,1,2)='TN' AND C.STATUS='A' AND C.TAX_YEAR=:Y
   AND L.BALANCE BETWEEN 1 AND 1000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'R2' BUCKET, COUNT(*) CNT, SUM(L.BALANCE) AMT
  FROM R2_LEDGER L JOIN R2_TAX_CASE C ON C.CASE_NO=L.CASE_NO
 WHERE SUBSTR(C.AREA_CODE,1,2)='TN' AND C.STATUS='A' AND C.TAX_YEAR=:Y
   AND L.BALANCE BETWEEN 1001 AND 5000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'R3' BUCKET, COUNT(*) CNT, SUM(L.BALANCE) AMT
  FROM R2_LEDGER L JOIN R2_TAX_CASE C ON C.CASE_NO=L.CASE_NO
 WHERE SUBSTR(C.AREA_CODE,1,2)='TN' AND C.STATUS='A' AND C.TAX_YEAR=:Y
   AND L.BALANCE BETWEEN 5001 AND 10000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'R4' BUCKET, COUNT(*) CNT, SUM(L.BALANCE) AMT
  FROM R2_LEDGER L JOIN R2_TAX_CASE C ON C.CASE_NO=L.CASE_NO
 WHERE SUBSTR(C.AREA_CODE,1,2)='TN' AND C.STATUS='A' AND C.TAX_YEAR=:Y
   AND L.BALANCE BETWEEN 10001 AND 20000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'R5' BUCKET, COUNT(*) CNT, SUM(L.BALANCE) AMT
  FROM R2_LEDGER L JOIN R2_TAX_CASE C ON C.CASE_NO=L.CASE_NO
 WHERE SUBSTR(C.AREA_CODE,1,2)='TN' AND C.STATUS='A' AND C.TAX_YEAR=:Y
   AND L.BALANCE BETWEEN 20001 AND 50000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'R6' BUCKET, COUNT(*) CNT, SUM(L.BALANCE) AMT
  FROM R2_LEDGER L JOIN R2_TAX_CASE C ON C.CASE_NO=L.CASE_NO
 WHERE SUBSTR(C.AREA_CODE,1,2)='TN' AND C.STATUS='A' AND C.TAX_YEAR=:Y
   AND L.BALANCE BETWEEN 50001 AND 100000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'R7' BUCKET, COUNT(*) CNT, SUM(L.BALANCE) AMT
  FROM R2_LEDGER L JOIN R2_TAX_CASE C ON C.CASE_NO=L.CASE_NO
 WHERE SUBSTR(C.AREA_CODE,1,2)='TN' AND C.STATUS='A' AND C.TAX_YEAR=:Y
   AND L.BALANCE BETWEEN 100001 AND 200000
 GROUP BY C.DISTRICT_ID
UNION ALL
SELECT C.DISTRICT_ID, 'R8' BUCKET, COUNT(*) CNT, SUM(L.BALANCE) AMT
  FROM R2_LEDGER L JOIN R2_TAX_CASE C ON C.CASE_NO=L.CASE_NO
 WHERE SUBSTR(C.AREA_CODE,1,2)='TN' AND C.STATUS='A' AND C.TAX_YEAR=:Y
   AND L.BALANCE > 200000
 GROUP BY C.DISTRICT_ID""",
    },
    {
        "id": "S10",
        "name": "UPPER 大小寫轉換 + 前置萬用字元",
        "cost": 49700,
        "expected_patterns": ["UPPER_CASE_FOLD_REMOVAL", "LEADING_WILDCARD_LIKE"],
        "forbidden_patterns": [],
        "sql": """SELECT A.CASE_NO, A.CONTACT_CODE, A.REMARK
  FROM R2_CONTACT A
 WHERE UPPER(A.CONTACT_CODE) = :CONTACT_CODE
   AND A.REMARK LIKE '%ABC%'
   AND A.STATUS = :STATUS
   AND A.TAX_YEAR = :TAX_YEAR""",
    },
]

UNSUPPORTED_RE = re.compile(
    r"Full\s*Table\s*Scan|全(?:資料)?表掃描|索引失效|已使用索引|未使用索引|"
    r"改善後\s*COST|執行計畫顯示|Execution\s*Plan\s*(?:shows|顯示)|"
    r"(?:提升|改善|加快)\s*\d+\s*%",
    re.IGNORECASE,
)
ABSOLUTE_RE = re.compile(r"每筆資料都會|每筆都會|保證會|必然會|肯定會|絕對會|百分之百會")
DATE_LITERAL_RE = re.compile(r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")
SIMPLIFIED_CHARS = set("数据库让说后优记录动态执")


def post_analyze(case: dict[str, Any], suffix: str = "main") -> dict[str, Any]:
    payload = {
        "application_no": f"ROUND2-{case['id']}-{suffix}",
        "cost": case["cost"],
        "sql": case["sql"],
        "execution_plan": None,
        "include_ai": True,
    }
    req = urllib.request.Request(
        BASE_URL + "/api/analyze",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ai_prose(result: dict[str, Any]) -> str:
    ai = result.get("ai") or {}
    parts = [str(ai.get("summary") or "")]
    for item in ai.get("advice") or []:
        if isinstance(item, dict):
            parts.extend([str(item.get("title") or ""), str(item.get("explanation") or "")])
    suggested = ai.get("suggested_sql") or {}
    if isinstance(suggested, dict):
        parts.append(str(suggested.get("reason") or ""))
    return "\n".join(parts)


def evaluate(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    ai = result.get("ai") or {}
    advice = [x for x in ai.get("advice") or [] if isinstance(x, dict)]
    evidence = [x for x in result.get("performance_evidence") or [] if isinstance(x, dict)]
    evidence_by_id = {str(x.get("evidence_id")): x for x in evidence}
    patterns = [str(x.get("pattern_id") or "") for x in advice]
    problems: list[str] = []

    if ai.get("status") != "ok":
        problems.append(f"AI 未完成：status={ai.get('status')} degrade={ai.get('degrade_code')}")

    if len(advice) > 3:
        problems.append(f"AI 建議超過 3 項：{len(advice)}")
    if len(patterns) != len(set(patterns)):
        problems.append("同一 pattern 重複出現多張 AI 建議卡")

    for idx, item in enumerate(advice, start=1):
        pid = str(item.get("pattern_id") or "")
        eids = [str(x) for x in item.get("evidence_ids") or []]
        if not pid:
            problems.append(f"第 {idx} 項建議缺少 pattern_id")
        if not eids:
            problems.append(f"第 {idx} 項建議沒有 Oracle evidence_ids")
        for eid in eids:
            ev = evidence_by_id.get(eid)
            if ev is None:
                problems.append(f"第 {idx} 項 evidence {eid} 未出現在 API Oracle 依據")
                continue
            if str(ev.get("pattern_id")) != pid:
                problems.append(f"第 {idx} 項 evidence {eid} 與 pattern {pid} 不一致")
            if "Oracle" not in str(ev.get("source_label") or ""):
                problems.append(f"第 {idx} 項 evidence {eid} 不是 Oracle 官方來源標示")

    actual = set(patterns)
    for expected in case["expected_patterns"]:
        if expected not in actual:
            problems.append(f"缺少預期建議 pattern：{expected}")
    for forbidden in case["forbidden_patterns"]:
        if forbidden in actual:
            problems.append(f"不應出現的建議 pattern：{forbidden}")

    prose = ai_prose(result)
    if UNSUPPORTED_RE.search(prose):
        problems.append("出現無依據的資料庫行為／效能斷言")
    if ABSOLUTE_RE.search(prose):
        problems.append("出現過度肯定的重複處理／效能語氣")
    simplified = sorted({ch for ch in prose if ch in SIMPLIFIED_CHARS})
    if simplified:
        problems.append("疑似簡體字：" + "".join(simplified))

    # Case-specific semantic traps from round 1.
    by_pattern = {str(x.get("pattern_id") or ""): x for x in advice}
    if case["id"] == "S01":
        blob = "\n".join(
            str(x.get("title") or "") + "\n" + str(x.get("explanation") or "")
            for x in advice
        )
        if "NVL" in blob or "空值" in blob:
            problems.append("aggregate NVL 再次被當成 predicate 改善建議")
    elif case["id"] == "S03":
        comp = by_pattern.get("COMPOSITE_KEY_EXPRESSION_JOIN") or {}
        like = by_pattern.get("LEADING_WILDCARD_LIKE") or {}
        if "JOIN" not in str(comp.get("explanation") or ""):
            problems.append("加工 JOIN 建議沒有保持 JOIN 主題")
        if "萬用字元" in str(comp.get("explanation") or ""):
            problems.append("加工 JOIN 建議被 LIKE 文案串線")
        if "前置萬用字元" not in str(like.get("explanation") or ""):
            problems.append("LIKE 建議沒有使用對應的 server-owned 文案")
    elif case["id"] == "S05":
        item = by_pattern.get("TRUNC_EQ_TO_RANGE") or {}
        if "TRUNC()" not in str(item.get("explanation") or ""):
            problems.append("TRUNC 建議與 pattern 內容不一致")
    elif case["id"] == "S06":
        item = by_pattern.get("PREDICATE_FUNCTION_GENERIC") or {}
        exp = str(item.get("explanation") or "")
        if "TO_CHAR()" not in exp:
            problems.append("TO_CHAR 建議與 pattern 內容不一致")
        if DATE_LITERAL_RE.search(exp):
            problems.append("TO_CHAR 建議自行發明日期常數")
    elif case["id"] == "S07":
        item = by_pattern.get("LATEST_ROW_CORRELATED_MAX") or {}
        if "可能" not in str(item.get("explanation") or ""):
            problems.append("重複 MAX 建議沒有使用可能性語氣")
    elif case["id"] == "S09":
        if ai.get("degrade_code") == "output_truncated":
            problems.append("長型案例仍發生 output_truncated")
    elif case["id"] == "S10":
        upper = by_pattern.get("UPPER_CASE_FOLD_REMOVAL") or {}
        if "UPPER()" not in str(upper.get("explanation") or ""):
            problems.append("UPPER 建議與 pattern 內容不一致")

    return {
        "id": case["id"],
        "name": case["name"],
        "ai_status": ai.get("status"),
        "degrade_code": ai.get("degrade_code"),
        "advice_count": len(advice),
        "patterns": patterns,
        "evidence_count": len(evidence),
        "suggested_outcome": (ai.get("suggested_sql") or {}).get("outcome"),
        "problems": problems,
        "pass": not problems,
    }


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    (out / "final_api").mkdir(exist_ok=True)
    (out / "reliability").mkdir(exist_ok=True)
    (out / "cases.json").write_text(json.dumps(CASES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows: list[dict[str, Any]] = []
    for case in CASES:
        print(f"[ROUND2] {case['id']} {case['name']}", flush=True)
        started = time.perf_counter()
        transport_error = None
        try:
            result = post_analyze(case)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            result = {}
            transport_error = type(exc).__name__
        elapsed = round(time.perf_counter() - started, 2)
        if result:
            (out / "final_api" / f"{case['id']}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            row = evaluate(case, result)
        else:
            row = {
                "id": case["id"], "name": case["name"], "ai_status": None,
                "degrade_code": None, "advice_count": 0, "patterns": [],
                "evidence_count": 0, "suggested_outcome": None,
                "problems": ["沒有 API 結果"], "pass": False,
            }
        row["elapsed_seconds"] = elapsed
        row["transport_error"] = transport_error
        if transport_error:
            row["problems"].append("transport=" + transport_error)
            row["pass"] = False
        rows.append(row)
        print(
            f"[DONE] {case['id']} pass={row['pass']} ai={row['ai_status']} "
            f"patterns={row['patterns']} t={elapsed}s",
            flush=True,
        )

    # Reliability stress: repeat the long case three more times.
    long_case = next(case for case in CASES if case["id"] == "S09")
    reliability: list[dict[str, Any]] = []
    for repeat in range(1, 4):
        print(f"[RELIABILITY] S09 r{repeat}", flush=True)
        started = time.perf_counter()
        try:
            result = post_analyze(long_case, suffix=f"reliability-{repeat}")
            transport_error = None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            result = {}
            transport_error = type(exc).__name__
        elapsed = round(time.perf_counter() - started, 2)
        if result:
            (out / "reliability" / f"S09_r{repeat}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            verdict = evaluate(long_case, result)
        else:
            verdict = {"pass": False, "problems": ["沒有 API 結果"]}
        reliability.append(
            {
                "repeat": repeat,
                "elapsed_seconds": elapsed,
                "transport_error": transport_error,
                "pass": verdict["pass"],
                "problems": verdict["problems"],
                "ai_status": (result.get("ai") or {}).get("status") if result else None,
                "degrade_code": (result.get("ai") or {}).get("degrade_code") if result else None,
            }
        )

    (out / "acceptance.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "reliability.json").write_text(json.dumps(reliability, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md = [
        "# SQLCheck Round 2 — OpenRouter / Gemma 4 31B machine acceptance",
        "",
        "| 案例 | AI | 建議 patterns | Oracle 依據 | 機器初篩 |",
        "|---|---|---|---:|---|",
    ]
    for row in rows:
        md.append(
            f"| {row['id']} {row['name']} | {row['ai_status']} | "
            f"{', '.join(row['patterns']) or '—'} | {row['evidence_count']} | "
            f"{'PASS' if row['pass'] else 'FAIL'} |"
        )
    md += ["", "## 異常"]
    failures = [row for row in rows if not row["pass"]]
    if failures:
        for row in failures:
            md.append(f"- **{row['id']}**：" + "；".join(row["problems"]))
    else:
        md.append("- 10/10 無機器驗收異常。")
    md += ["", "## S09 長型案例額外重跑"]
    for item in reliability:
        md.append(
            f"- r{item['repeat']}: {'PASS' if item['pass'] else 'FAIL'}, "
            f"ai={item['ai_status']}, degrade={item['degrade_code']}, {item['elapsed_seconds']}s"
        )

    (out / "API_MACHINE_REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    all_pass = all(row["pass"] for row in rows) and all(item["pass"] for item in reliability)
    return 0 if all_pass else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(main(args.out))
