#!/usr/bin/env python3
"""1920x1080 browser acceptance for round-2 live OpenRouter results."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"
REPRESENTATIVE_IDS = ("S02", "S03", "S09")


def wait_analysis_done(page, timeout_ms: int = 240_000) -> None:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        button = page.locator("button.primary")
        try:
            text = button.inner_text(timeout=2_000).strip()
            disabled = button.is_disabled(timeout=2_000)
        except Exception:
            text = ""
            disabled = True
        if text == "開始檢核" and not disabled and page.locator(".hero").count():
            return
        page.wait_for_timeout(800)
    raise PlaywrightTimeoutError("analysis did not return to ready state")


def fill_sql(page, sql: str) -> None:
    editor = page.locator('[aria-label="SQL 輸入"]')
    editor.click()
    editor.fill(sql)


def metrics(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const pick = (sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const s = getComputedStyle(el);
            return {
              selector: sel,
              text: (el.textContent || "").trim().slice(0, 220),
              fontSize: s.fontSize,
              fontWeight: s.fontWeight,
              lineHeight: s.lineHeight,
              color: s.color,
              backgroundColor: s.backgroundColor
            };
          };
          const doc = document.documentElement;
          const selectors = [
            ".hero h1",
            ".result-overview-title",
            ".result-overview-detail",
            ".m-label",
            ".m-value",
            ".card-title",
            ".evidence-source-note",
            ".system-evidence-box p",
            ".advice-title-row h4",
            ".advice-box p",
            ".advice-oracle-links .badge"
          ];
          return {
            viewport: {width: innerWidth, height: innerHeight, devicePixelRatio},
            document: {
              scrollWidth: doc.scrollWidth,
              clientWidth: doc.clientWidth,
              scrollHeight: doc.scrollHeight,
              horizontalOverflow: doc.scrollWidth > doc.clientWidth + 2
            },
            typography: selectors.map(pick).filter(Boolean),
            oracleAdviceLinkCount: document.querySelectorAll('[data-testid="advice-oracle-evidence"]').length,
            aiAdviceCountText: (document.querySelector(".advice-badges .purple")?.textContent || "").trim()
          };
        }"""
    )


def px(value: str | None) -> float:
    if not value:
        return 0.0
    return float(value.replace("px", ""))


def main(cases_path: Path, out: Path) -> int:
    cases = {item["id"]: item for item in json.loads(cases_path.read_text(encoding="utf-8"))}
    out.mkdir(parents=True, exist_ok=True)
    shots = out / "screenshots"
    shots.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    failed = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page = context.new_page()
        page.set_default_timeout(15_000)

        for case_id in REPRESENTATIVE_IDS:
            case = cases[case_id]
            print(f"[ROUND2 UI] {case_id}", flush=True)
            page.goto(BASE_URL, wait_until="networkidle", timeout=60_000)
            page.locator("#appNo").fill(f"ROUND2-UI-{case_id}")
            page.locator("#costInput").fill(str(case["cost"]))
            fill_sql(page, case["sql"])
            page.get_by_role("button", name="開始檢核").click()

            problem: str | None = None
            try:
                wait_analysis_done(page)
                page.wait_for_timeout(800)
            except PlaywrightTimeoutError:
                problem = "等待 AI 完成逾時"
                failed = True

            top = shots / f"{case_id}_1920x1080_top.png"
            full = shots / f"{case_id}_1920x1080_full.png"
            page.screenshot(path=str(top), full_page=False)
            page.screenshot(path=str(full), full_page=True)

            m = metrics(page)
            visible = page.locator("#resultArea").inner_text()
            (out / f"{case_id}_visible_text.txt").write_text(visible + "\n", encoding="utf-8")
            by_sel = {x["selector"]: x for x in m["typography"]}

            auto: list[str] = []
            if m["document"]["horizontalOverflow"]:
                auto.append("1920px 畫面出現整頁水平溢位")
            if px((by_sel.get(".hero h1") or {}).get("fontSize")) < 28:
                auto.append("主標題小於 28px")
            if px((by_sel.get(".card-title") or {}).get("fontSize")) < 20:
                auto.append("區塊標題小於 20px")
            body_sizes = [
                px((by_sel.get(sel) or {}).get("fontSize"))
                for sel in (".result-overview-detail", ".system-evidence-box p", ".advice-box p")
                if (by_sel.get(sel) or {}).get("fontSize")
            ]
            if body_sizes and min(body_sizes) < 14:
                auto.append(f"主要內文小於 14px：{min(body_sizes)}px")
            source_px = px((by_sel.get(".evidence-source-note") or {}).get("fontSize"))
            if source_px and source_px < 14:
                auto.append(f"Oracle 來源說明小於 14px：{source_px}px")
            if "Oracle 依據：" not in visible:
                auto.append("AI 建議卡旁未看到一對一 Oracle 依據")
            if m["oracleAdviceLinkCount"] < 1:
                auto.append("找不到 advice-oracle-evidence 元件")
            if "智慧改善建議" not in visible:
                auto.append("畫面未看到智慧改善建議")

            if auto:
                failed = True
            rows.append(
                {
                    "case_id": case_id,
                    "problem": problem,
                    "auto_visual_problems": auto,
                    "metrics": m,
                    "top_screenshot": top.name,
                    "full_screenshot": full.name,
                }
            )

        browser.close()

    (out / "ui_metrics.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = [
        "# SQLCheck Round 2 — 1920×1080 visual machine acceptance",
        "",
        "檢查重點：字級、水平溢位、Oracle 依據是否直接出現在 AI 建議卡旁。",
        "",
    ]
    for row in rows:
        md.append(f"## {row['case_id']}")
        if row["problem"]:
            md.append(f"- {row['problem']}")
        if row["auto_visual_problems"]:
            md.extend(f"- {p}" for p in row["auto_visual_problems"])
        else:
            md.append("- 自動視覺檢查：PASS")
        md.append(f"- 截圖：{row['top_screenshot']} / {row['full_screenshot']}")
        md.append("")
    (out / "UI_MACHINE_REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return 2 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(main(args.cases, args.out))
