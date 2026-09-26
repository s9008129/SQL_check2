#!/usr/bin/env python3
"""Round-2 1920x1080 live dashboard acceptance."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"
REPRESENTATIVE_IDS = ("R2-01", "R2-03", "R2-04", "R2-09")


def wait_done(page, timeout_ms: int = 240_000) -> None:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        button = page.locator("button.primary")
        try:
            if button.inner_text(timeout=1500).strip() == "開始檢核" and not button.is_disabled():
                if page.locator(".hero").count():
                    return
        except Exception:
            pass
        page.wait_for_timeout(700)
    raise PlaywrightTimeoutError("analysis timeout")


def fill_sql(page, value: str) -> None:
    editor = page.locator('[aria-label="SQL 輸入"]')
    editor.click()
    editor.fill(value)


def metrics(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const read = (sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const s = getComputedStyle(el);
            return {selector: sel, fontSize: s.fontSize, fontWeight: s.fontWeight,
                    lineHeight: s.lineHeight, text: (el.textContent || "").trim().slice(0,220)};
          };
          const root = document.documentElement;
          return {
            viewport: {width: innerWidth, height: innerHeight, dpr: devicePixelRatio},
            horizontalOverflow: root.scrollWidth > root.clientWidth + 2,
            typography: [
              ".hero h1", ".result-overview-title", ".result-overview-detail",
              ".card-title", ".card-desc", ".system-evidence-box p",
              ".advice-title-row h4", ".advice-box p", ".advice-oracle-evidence",
              ".evidence-source-note"
            ].map(read).filter(Boolean),
            linkedEvidenceCount: document.querySelectorAll(".advice-oracle-evidence").length,
            adviceCount: document.querySelectorAll('[data-testid="ai-advice-badge"]').length,
            oracleSectionCount: document.querySelectorAll('[data-testid="performance-evidence"]').length,
          };
        }"""
    )


def main(cases_path: Path, out: Path) -> int:
    cases = {x["id"]: x for x in json.loads(cases_path.read_text(encoding="utf-8"))}
    out.mkdir(parents=True, exist_ok=True)
    shots = out / "screenshots"
    shots.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    failed = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page = context.new_page()
        page.set_default_timeout(20_000)

        for case_id in REPRESENTATIVE_IDS:
            case = cases[case_id]
            page.goto(BASE_URL, wait_until="networkidle", timeout=60_000)
            page.locator("#appNo").fill(f"UI-{case_id}")
            page.locator("#costInput").fill(str(case["cost"]))
            fill_sql(page, case["sql"])
            page.get_by_role("button", name="開始檢核").click()

            execution_problem: str | None = None
            try:
                wait_done(page)
                page.wait_for_timeout(700)
            except PlaywrightTimeoutError:
                execution_problem = "等待 AI 完成逾時"
                failed = True

            top = shots / f"{case_id}_1920x1080_top.png"
            full = shots / f"{case_id}_1920x1080_full.png"
            page.screenshot(path=str(top), full_page=False)
            page.screenshot(path=str(full), full_page=True)
            text = page.locator("#resultArea").inner_text()
            (out / f"{case_id}_visible_text.txt").write_text(text+"\n", encoding="utf-8")

            m = metrics(page)
            problems: list[str] = []
            if execution_problem:
                problems.append(execution_problem)
            if m["horizontalOverflow"]:
                problems.append("1920px 視窗出現整頁水平溢位")
            sizes = {
                x["selector"]: float(x["fontSize"].replace("px", ""))
                for x in m["typography"] if x.get("fontSize")
            }
            if sizes.get(".hero h1", 0) < 28:
                problems.append("頁面主標題小於 28px")
            if sizes.get(".card-title", 0) < 20:
                problems.append("區塊標題小於 20px")
            for selector in (".system-evidence-box p", ".advice-box p", ".advice-oracle-evidence"):
                if selector in sizes and sizes[selector] < 14:
                    problems.append(f"{selector} 小於 14px")
            if m["adviceCount"] > 0 and m["linkedEvidenceCount"] < m["adviceCount"]:
                problems.append(
                    f"AI 建議 {m['adviceCount']} 項，但畫面只顯示 {m['linkedEvidenceCount']} 個一對一 Oracle 依據"
                )
            if "Oracle 依據與注意事項" not in text:
                problems.append("未顯示 Oracle 依據與注意事項")
            if "為什麼這樣可能比較快" in text:
                problems.append("仍使用會把所有 evidence 誤解成速度證明的舊標題")

            rows.append({
                "case_id": case_id,
                "problems": problems,
                "metrics": m,
                "top_screenshot": top.name,
                "full_screenshot": full.name,
            })
            failed |= bool(problems)
            print(f"[UI] {case_id} {'PASS' if not problems else 'FAIL'} {problems}", flush=True)

        browser.close()

    (out / "ui_metrics.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    report = ["# SQLCheck Round-2 1920×1080 UI machine acceptance", ""]
    for row in rows:
        report.append(f"## {row['case_id']}")
        if row["problems"]:
            report.extend(f"- FAIL: {p}" for p in row["problems"])
        else:
            report.append("- PASS：無水平溢位；主要文字尺寸符合門檻；每張 AI 建議都有畫面上的 Oracle 依據連結。")
        report.append(f"- 截圖：{row['top_screenshot']}、{row['full_screenshot']}")
        report.append("")
    (out / "UI_MACHINE_REPORT.md").write_text("\n".join(report)+"\n", encoding="utf-8")
    return 2 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(main(args.cases, args.out))
