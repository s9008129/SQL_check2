#!/usr/bin/env python3
"""Visual/browser acceptance for representative SQLCheck live results.

Runs at 1920x1080 (common 22-inch 16:9 Full-HD layout target) and captures
actual OpenRouter/Gemma-backed result screens. Synthetic SQL only.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "http://127.0.0.1:8000"
REPRESENTATIVE_IDS = ("Q01", "Q03", "Q12")


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


def collect_metrics(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const one = (sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const s = getComputedStyle(el);
            return {
              selector: sel,
              text: (el.textContent || "").trim().slice(0, 180),
              fontSize: s.fontSize,
              fontWeight: s.fontWeight,
              lineHeight: s.lineHeight,
              color: s.color,
              backgroundColor: s.backgroundColor
            };
          };
          const selectors = [
            ".hero h1",
            ".result-overview-title",
            ".result-overview-detail",
            ".m-label",
            ".m-value",
            ".card-title",
            ".card-desc",
            ".evidence-source-note",
            ".system-evidence-box p",
            ".advice-title-row h4",
            ".a p",
            ".ai-disclaimer"
          ];
          const doc = document.documentElement;
          const cards = Array.from(document.querySelectorAll(".metric, .card, .result-overview"))
            .slice(0, 20)
            .map((el) => {
              const s = getComputedStyle(el);
              return {
                className: el.className,
                backgroundColor: s.backgroundColor,
                borderColor: s.borderColor
              };
            });
          return {
            viewport: {width: innerWidth, height: innerHeight, devicePixelRatio},
            document: {
              scrollWidth: doc.scrollWidth,
              clientWidth: doc.clientWidth,
              scrollHeight: doc.scrollHeight,
              horizontalOverflow: doc.scrollWidth > doc.clientWidth + 2
            },
            typography: selectors.map(one).filter(Boolean),
            cards
          };
        }"""
    )


def fill_codemirror(page, sql: str) -> None:
    editor = page.locator('[aria-label="SQL 輸入"]')
    editor.click()
    editor.fill(sql)


def main(cases_path: Path, out: Path) -> int:
    cases = {case["id"]: case for case in json.loads(cases_path.read_text(encoding="utf-8"))}
    out.mkdir(parents=True, exist_ok=True)
    screenshots = out / "screenshots"
    screenshots.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    failed = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page = context.new_page()
        page.set_default_timeout(15_000)

        for case_id in REPRESENTATIVE_IDS:
            case = cases[case_id]
            print(f"[UI] {case_id}", flush=True)
            page.goto(BASE_URL, wait_until="networkidle", timeout=60_000)
            page.locator("#appNo").fill(f"UI-{case_id}-20260925")
            page.locator("#costInput").fill(str(case["cost"]))
            fill_codemirror(page, case["sql"])
            page.get_by_role("button", name="開始檢核").click()

            problem: str | None = None
            try:
                wait_analysis_done(page)
                page.wait_for_timeout(800)
            except PlaywrightTimeoutError:
                problem = "等待 AI 完成逾時"
                failed = True

            top_path = screenshots / f"{case_id}_1920x1080_top.png"
            full_path = screenshots / f"{case_id}_1920x1080_full.png"
            page.screenshot(path=str(top_path), full_page=False)
            page.screenshot(path=str(full_path), full_page=True)

            metrics = collect_metrics(page)
            visible_text = page.locator("#resultArea").inner_text()
            (out / f"{case_id}_visible_text.txt").write_text(visible_text + "\n", encoding="utf-8")

            typography = {x["selector"]: x for x in metrics["typography"]}
            title_px = float((typography.get(".hero h1", {}).get("fontSize") or "0px").replace("px", ""))
            card_title_px = float((typography.get(".card-title", {}).get("fontSize") or "0px").replace("px", ""))
            body_candidates = [
                x for x in metrics["typography"]
                if x["selector"] in {".result-overview-detail", ".card-desc", ".system-evidence-box p", ".a p"}
            ]
            body_sizes = [
                float(x["fontSize"].replace("px", "")) for x in body_candidates if x.get("fontSize")
            ]
            min_body_px = min(body_sizes) if body_sizes else 0.0

            auto_visual_problems: list[str] = []
            if metrics["document"]["horizontalOverflow"]:
                auto_visual_problems.append("1920px 視窗出現整頁水平溢位")
            if title_px < 28:
                auto_visual_problems.append(f"主標題偏小：{title_px}px")
            if card_title_px and card_title_px < 20:
                auto_visual_problems.append(f"區塊標題偏小：{card_title_px}px")
            if min_body_px and min_body_px < 13:
                auto_visual_problems.append(f"主要說明文字偏小：最小 {min_body_px}px")
            if "Oracle" not in visible_text:
                auto_visual_problems.append("畫面未看到 Oracle 依據文字")
            if "智慧改善建議" not in visible_text:
                auto_visual_problems.append("畫面未看到智慧改善建議區塊")

            if auto_visual_problems:
                failed = True
            rows.append(
                {
                    "case_id": case_id,
                    "problem": problem,
                    "auto_visual_problems": auto_visual_problems,
                    "metrics": metrics,
                    "top_screenshot": top_path.name,
                    "full_screenshot": full_path.name,
                }
            )

        browser.close()

    (out / "ui_metrics.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    md = [
        "# SQLCheck 1920×1080 Visual Acceptance — machine measurements",
        "",
        "說明：這是 Chromium/Linux 的客觀尺寸與溢位檢查；最終 Apple 簡約風格與人眼閱讀感受需搭配截圖人工判讀。",
        "",
    ]
    for row in rows:
        md.append(f"## {row['case_id']}")
        if row["problem"]:
            md.append(f"- 執行問題：{row['problem']}")
        if row["auto_visual_problems"]:
            md.extend(f"- {p}" for p in row["auto_visual_problems"])
        else:
            md.append("- 自動尺寸／溢位檢查：PASS")
        md.append(f"- 截圖：{row['top_screenshot']}、{row['full_screenshot']}")
        md.append("")
    (out / "UI_MACHINE_REPORT.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return 2 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(main(args.cases, args.out))
