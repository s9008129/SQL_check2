#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.api import analyze
from app.schemas import AnalyzeRequest
from app.services import llm_provider

CASES: list[dict[str, Any]] = [
    {"id":"PII01","scenario":"中文姓名字串","sql":"SELECT A.ID FROM PERSON_DATA A WHERE A.NAME = '測試甲'","forbidden":["測試甲"],"required":[":STR_001"],"expected_hint":None},
    {"id":"PII02","scenario":"身分證樣式字串（刻意使用無效合成值）","sql":"SELECT A.ID FROM PERSON_DATA A WHERE A.IDNO = 'A000000000'","forbidden":["A000000000"],"required":[":STR_001"],"expected_hint":None},
    {"id":"PII03","scenario":"手機號碼字串","sql":"SELECT A.ID FROM PERSON_DATA A WHERE A.MOBILE = '0900-000-003'","forbidden":["0900-000-003"],"required":[":STR_001"],"expected_hint":None},
    {"id":"PII04","scenario":"Email 字串","sql":"SELECT A.ID FROM PERSON_DATA A WHERE A.EMAIL = 'pii04@example.invalid'","forbidden":["pii04@example.invalid"],"required":[":STR_001"],"expected_hint":None},
    {"id":"PII05","scenario":"地址字串","sql":"SELECT A.ID FROM PERSON_DATA A WHERE A.ADDRESS = '測試市虛構區不存在路10號'","forbidden":["測試市虛構區不存在路10號"],"required":[":STR_001"],"expected_hint":None},
    {"id":"PII06","scenario":"Oracle DATE typed literal","sql":"SELECT A.ID FROM PERSON_DATA A WHERE A.BIRTH_DATE = DATE '2099-12-31'","forbidden":["2099-12-31"],"required":["DATE :STR_001"],"expected_hint":"date"},
    {"id":"PII07","scenario":"長數字案件識別碼","sql":"SELECT A.ID FROM PERSON_DATA A WHERE A.CASE_NO = 999999999999","forbidden":["999999999999"],"required":[":NUM_001"],"expected_hint":None},
    {"id":"PII08","scenario":"Line comment 內姓名與手機","sql":"SELECT A.ID FROM PERSON_DATA A WHERE A.ID = :ID -- 姓名：測試乙，手機：0900-000-008","forbidden":["測試乙","0900-000-008"],"required":["SELECT A.ID FROM PERSON_DATA A WHERE A.ID = :ID"],"expected_hint":None},
    {"id":"PII09","scenario":"Block comment 內證號與地址","sql":"SELECT A.ID FROM PERSON_DATA A /* 身分證：B000000000；地址：測試市虛構路9號 */ WHERE A.ID = :ID","forbidden":["B000000000","測試市虛構路9號"],"required":["WHERE A.ID = :ID"],"expected_hint":None},
    {"id":"PII10","scenario":"Optimizer hint + PII comment + 短業務碼","sql":"SELECT /*+ INDEX(A IDX_TAX_CD) */ A.ID FROM TAX_DATA A /* 承辦備註：測試丙，email: pii10@example.invalid */ WHERE A.TAX_CD = '55'","forbidden":["測試丙","pii10@example.invalid"],"required":["/*+ INDEX(A IDX_TAX_CD) */","'55'"],"expected_hint":None},
]

CURRENT: dict[str, Any] = {}
CAPTURES: list[dict[str, Any]] = []
ORIGINAL_GENERATE = llm_provider.generate_structured_json

def extract_payload(user_content: str) -> dict[str, Any]:
    prefix = "<SQL_DATA>\n"
    suffix = "\n</SQL_DATA>"
    if not user_content.startswith(prefix) or not user_content.endswith(suffix):
        raise RuntimeError("provider user_content is not a single SQL_DATA envelope")
    return json.loads(user_content[len(prefix):-len(suffix)])

def assert_payload_safe(case: dict[str, Any], user_content: str, payload: dict[str, Any]) -> None:
    for value in case["forbidden"]:
        if value in user_content:
            raise RuntimeError(f"{case['id']}: synthetic PII would leak to provider: {value}")
    if "reverse_map" in payload:
        raise RuntimeError(f"{case['id']}: reverse_map must remain server-private")
    sanitized_sql = str(payload.get("sanitized_sql") or "")
    for fragment in case["required"]:
        if fragment not in sanitized_sql:
            raise RuntimeError(f"{case['id']}: required sanitized structure missing: {fragment}")
    hints_text = json.dumps(payload.get("literal_hints") or {}, ensure_ascii=False)
    for value in case["forbidden"]:
        if value in hints_text:
            raise RuntimeError(f"{case['id']}: literal_hints leaked synthetic PII: {value}")
    expected_hint = case.get("expected_hint")
    if expected_hint:
        hints = list((payload.get("literal_hints") or {}).values())
        if not any(isinstance(h, dict) and h.get("oracle_literal_type") == expected_hint for h in hints):
            raise RuntimeError(f"{case['id']}: expected oracle_literal_type={expected_hint} missing")

async def capturing_generate(*args, **kwargs):
    case = CURRENT["case"]
    user_content = kwargs.get("user_content", "")
    payload = extract_payload(user_content)
    assert_payload_safe(case, user_content, payload)
    reply = await ORIGINAL_GENERATE(*args, **kwargs)
    try:
        raw_json = json.loads(reply.content)
    except Exception:
        raw_json = None
    CAPTURES.append({
        "case_id": case["id"],
        "provider": reply.provider,
        "model": reply.model,
        "finish_reason": reply.finish_reason,
        "prompt_tokens": reply.prompt_tokens,
        "output_tokens": reply.output_tokens,
        "total_tokens": reply.total_tokens,
        "total_duration_ms": reply.total_duration_ms,
        "payload": payload,
        "raw_text": reply.content,
        "raw_json": raw_json,
    })
    return reply

def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

async def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    for sub in ("payloads","raw_model","final_api"):
        (out/sub).mkdir(parents=True, exist_ok=True)
    llm_provider.generate_structured_json = capturing_generate

    rows: list[dict[str, Any]] = []
    failures: list[str] = []

    for case in CASES:
        CURRENT.clear()
        CURRENT["case"] = case
        before = len(CAPTURES)
        try:
            result = await analyze(AnalyzeRequest(
                application_no=f"CLOUD-PRIVACY-{case['id']}",
                cost=1000,
                sql=case["sql"],
                include_ai=True,
            ))
        except Exception as exc:
            failures.append(f"{case['id']}: analyze raised {type(exc).__name__}")
            continue

        final = result.model_dump(mode="json")
        captures = CAPTURES[before:]
        if not captures:
            failures.append(f"{case['id']}: no provider call captured")
            continue
        capture = captures[-1]
        payload = capture["payload"]
        raw_text = capture["raw_text"]
        final_text = json.dumps(final.get("ai") or {}, ensure_ascii=False)

        raw_echo = [v for v in case["forbidden"] if v in raw_text]
        final_echo = [v for v in case["forbidden"] if v in final_text]
        ai = final.get("ai") or {}
        provider_ok = capture.get("provider") == "ollama_cloud"
        model_ok = capture.get("model") == "gemma4:31b"

        if raw_echo:
            failures.append(f"{case['id']}: model echoed synthetic PII: {raw_echo}")
        if final_echo:
            failures.append(f"{case['id']}: final API echoed synthetic PII: {final_echo}")
        if ai.get("status") != "ok":
            failures.append(f"{case['id']}: final AI status={ai.get('status')}")
        if not provider_ok:
            failures.append(f"{case['id']}: provider={capture.get('provider')}")
        if not model_ok:
            failures.append(f"{case['id']}: model={capture.get('model')}")

        dump_json(out/"payloads"/f"{case['id']}.json", payload)
        dump_json(out/"raw_model"/f"{case['id']}.json", {
            "provider":capture["provider"],"model":capture["model"],
            "finish_reason":capture["finish_reason"],"prompt_tokens":capture["prompt_tokens"],
            "output_tokens":capture["output_tokens"],"total_tokens":capture["total_tokens"],
            "total_duration_ms":capture["total_duration_ms"],"raw_json":capture["raw_json"],
            "raw_text":capture["raw_text"],
        })
        dump_json(out/"final_api"/f"{case['id']}.json", final)

        sanitized_sql = str(payload.get("sanitized_sql") or "")
        row_pass = (
            not raw_echo and not final_echo and ai.get("status") == "ok"
            and provider_ok and model_ok
            and all(v not in json.dumps(payload, ensure_ascii=False) for v in case["forbidden"])
            and all(fragment in sanitized_sql for fragment in case["required"])
        )
        rows.append({
            "case_id":case["id"],"scenario":case["scenario"],
            "payload_pii_absent":all(v not in json.dumps(payload, ensure_ascii=False) for v in case["forbidden"]),
            "required_structure_preserved":all(fragment in sanitized_sql for fragment in case["required"]),
            "raw_model_echo_absent":not raw_echo,"final_api_echo_absent":not final_echo,
            "ai_status":ai.get("status"),"provider":capture.get("provider"),
            "model":capture.get("model"),"finish_reason":capture.get("finish_reason"),
            "result":"PASS" if row_pass else "FAIL",
        })

    if rows:
        with (out/"pii_matrix.csv").open("w",newline="",encoding="utf-8-sig") as fh:
            writer=csv.DictWriter(fh,fieldnames=list(rows[0].keys()))
            writer.writeheader(); writer.writerows(rows)

    passed=sum(1 for r in rows if r["result"]=="PASS")
    verdict="PASS" if not failures and len(rows)==len(CASES) and passed==len(CASES) else "FAIL"
    report=[
        "# SQLCheck 2.0 隱私去識別化 Cloud E2E 報告","",
        f"- Verdict: **{verdict}**",
        "- Live provider: ollama_cloud",
        "- Live model: gemma4:31b",
        f"- Synthetic PII scenarios: {len(CASES)}",
        f"- PASS: {passed}/{len(CASES)}",
        "- 測試資料：全部為人工合成，不代表真實個人。",
        "- Fail-closed：每次真正呼叫 Ollama Cloud 前先檢查 provider payload；若仍含該案例 synthetic PII，立即中止，不外送該 request。",
        "","## 測試矩陣","",
        "| 案例 | 情境 | Payload 無 PII | SQL 結構保留 | Model 未回吐 | Final API 未回吐 | 結果 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        report.append(
            f"| {row['case_id']} | {row['scenario']} | "
            f"{'PASS' if row['payload_pii_absent'] else 'FAIL'} | "
            f"{'PASS' if row['required_structure_preserved'] else 'FAIL'} | "
            f"{'PASS' if row['raw_model_echo_absent'] else 'FAIL'} | "
            f"{'PASS' if row['final_api_echo_absent'] else 'FAIL'} | **{row['result']}** |"
        )
    report += [
        "","## 隱私政策驗證","",
        "- 長字串、非 ASCII 字串、Oracle DATE/TIMESTAMP value 與 6+ digits numeric literal：placeholder 遮罩。",
        "- 一般 -- ... 與 /* ... */ 自由文字註解：model-facing SQL 中移除。",
        "- Oracle optimizer hint --+ ... / /*+ ... */：保留。",
        "- reverse_map：只留 server memory，不序列化到 SQL_DATA。",
        "- literal_hints：只保留型態、長度、wildcard/shape 等結構資訊，不含原值。",
        "- 短 ASCII 業務碼：沿用既有政策保留，以維持 SQL 靜態判讀能力。",
        "","## Failures",
    ]
    report += [f"- {x}" for x in failures] if failures else ["- 無。"]
    report += [
        "","## Evidence","",
        "- pii_matrix.csv：10 案摘要。",
        "- payloads/：實際送往 provider 的 SQL_DATA 解析內容。",
        "- raw_model/：Live Ollama Cloud 回應與 token/latency metadata。",
        "- final_api/：SQLCheck final API 結果。",
    ]
    (out/"PRIVACY_REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    dump_json(out/"privacy_summary.json",{
        "verdict":verdict,"cases":len(CASES),"passed":passed,
        "failures":failures,"run_id":os.environ.get("GITHUB_RUN_ID"),
    })
    return 0 if verdict=="PASS" else 2

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    raise SystemExit(asyncio.run(main(args.out)))
