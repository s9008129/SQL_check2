#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from playwright.sync_api import sync_playwright

def parse_px(value: str | None) -> float:
    try:
        return float((value or "0").replace("px", "").strip())
    except Exception:
        return 0.0

def parse_weight(value: str | None) -> int:
    table = {"normal": 400, "bold": 700}
    if value in table:
        return table[value]
    try:
        return int(float(value or 0))
    except Exception:
        return 0

def rgb_luminance(value: str) -> float:
    import re
    m = re.search(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", value or "")
    if not m:
        return 1.0
    rgb = [int(m.group(i)) / 255 for i in range(1, 4)]
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = [lin(c) for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    payload = json.loads(args.results.read_text(encoding="utf-8"))
    cases = payload["cases"]
    out = args.out
    (out / "screenshots").mkdir(parents=True, exist_ok=True)
    ui_rows = []
    overall = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            color_scheme="light",
        )
        page = context.new_page()
        current = {"case": None}

        def route_analyze(route):
            item = current["case"]
            if item is None:
                route.abort()
                return
            try:
                body = json.loads(route.request.post_data or "{}")
            except Exception:
                body = {}
            response = item["final"] if body.get("include_ai") else item["baseline"]
            route.fulfill(
                status=200,
                content_type="application/json; charset=utf-8",
                body=json.dumps(response, ensure_ascii=False),
            )

        page.route("**/api/analyze", route_analyze)

        for item in cases:
            current["case"] = item
            case_id = item["id"]
            page.goto(args.base_url, wait_until="networkidle")
            page.locator("#appNo").fill(f"E2E-{case_id}")
            page.locator("#costInput").fill(str(item["cost"]))
            sql_editor = page.get_by_label("SQL 輸入")
            sql_editor.fill(item["sql"])
            page.get_by_role("button", name="開始檢核").click()
            page.get_by_role("heading", name="SQL 效能檢核結果").wait_for(timeout=15000)
            page.locator(".card-ai").wait_for(timeout=15000)
            page.wait_for_timeout(250)

            # Capture exactly what a 1920x1080 16:9 workstation viewport sees,
            # plus a full-page evidence image for independent review.
            page.screenshot(path=str(out / "screenshots" / f"{case_id}_viewport_1920x1080.png"), full_page=False)
            page.screenshot(path=str(out / "screenshots" / f"{case_id}_full.png"), full_page=True)

            metrics = page.evaluate(
                """
                () => {
                  const style = (sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    const s = getComputedStyle(el);
                    const r = el.getBoundingClientRect();
                    return {
                      selector: sel,
                      text: (el.textContent || '').trim().slice(0, 160),
                      fontSize: s.fontSize,
                      fontWeight: s.fontWeight,
                      lineHeight: s.lineHeight,
                      color: s.color,
                      backgroundColor: s.backgroundColor,
                      top: r.top, bottom: r.bottom, left: r.left, right: r.right,
                      clientWidth: el.clientWidth, scrollWidth: el.scrollWidth,
                      clientHeight: el.clientHeight, scrollHeight: el.scrollHeight,
                    };
                  };
                  const selectors = [
                    '.hero h1',
                    '.hero p',
                    '.result-overview-title',
                    '.result-overview-detail',
                    '.m-label',
                    '.m-value',
                    '.m-sub',
                    '.card-title',
                    '.card-desc',
                    '.a-item p',
                    '.system-evidence-box p',
                    '.rule'
                  ];
                  const typography = selectors.map(style).filter(Boolean);
                  const colorSelectors = [
                    '.result-overview',
                    '.metric:nth-of-type(1)',
                    '.metric:nth-of-type(2)',
                    '.metric:nth-of-type(3)',
                    '.metric:nth-of-type(4)',
                    '.card-ai',
                    '.system-evidence-box',
                    '.rule-list'
                  ];
                  const colors = colorSelectors.map(sel => {
                    const el = document.querySelector(sel);
                    if (!el) return null;
                    const s = getComputedStyle(el);
                    return {selector: sel, backgroundColor: s.backgroundColor, borderColor: s.borderColor};
                  }).filter(Boolean);
                  const clipped = Array.from(document.querySelectorAll(
                    '.result-overview-title,.result-overview-detail,.m-label,.m-value,.m-sub,.card-title,.card-desc,.a-item p,.system-evidence-box p,.rule'
                  )).filter(el => el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).whiteSpace !== 'pre')
                    .map(el => ({className: el.className, text: (el.textContent || '').trim().slice(0,100)}));
                  const bodyStyle = getComputedStyle(document.body);
                  const summary = document.querySelector('.summary')?.getBoundingClientRect();
                  return {
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    documentScrollWidth: document.documentElement.scrollWidth,
                    documentScrollHeight: document.documentElement.scrollHeight,
                    horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 2,
                    bodyBackground: bodyStyle.backgroundColor,
                    typography,
                    colors,
                    clipped,
                    summaryCardCount: document.querySelectorAll('.summary .metric').length,
                    oracleEvidenceCount: document.querySelectorAll('.system-evidence-box').length,
                    aiCardCount: document.querySelectorAll('.card-ai').length,
                    overviewCount: document.querySelectorAll('.result-overview').length,
                    summaryBottom: summary ? summary.bottom : null,
                    screenshotContentText: (document.querySelector('#resultArea')?.textContent || '').trim().slice(0,3000)
                  };
                }
                """
            )

            problems = []
            if metrics["horizontalOverflow"]:
                problems.append("1920px 寬度發生整頁水平溢位")
            if metrics["summaryCardCount"] != 4:
                problems.append(f"摘要圖卡不是 4 張：{metrics['summaryCardCount']}")
            if metrics["aiCardCount"] != 1:
                problems.append(f"AI 建議卡數量異常：{metrics['aiCardCount']}")
            if metrics["overviewCount"] != 1:
                problems.append("缺少「先看結論」Dashboard 區塊")
            if len(item.get("observed_evidence") or []) > 0 and metrics["oracleEvidenceCount"] < 1:
                problems.append("模型/API 已有 Oracle evidence，但畫面沒有 Oracle 依據圖卡")
            if not metrics["screenshotContentText"]:
                problems.append("截圖頁面沒有 SQLCheck 結果內容")

            type_map = {x["selector"]: x for x in metrics["typography"]}
            thresholds = {
                ".hero h1": (28, 700),
                ".result-overview-title": (22, 700),
                ".card-title": (20, 700),
                ".m-label": (14, 700),
                ".m-sub": (13, 400),
                ".a-item p": (14, 400),
                ".system-evidence-box p": (14, 400),
                ".rule": (13, 400),
            }
            for sel, (min_size, min_weight) in thresholds.items():
                row = type_map.get(sel)
                if not row:
                    if sel in {".a-item p", ".system-evidence-box p"}:
                        continue
                    problems.append(f"找不到必要文字元素 {sel}")
                    continue
                size = parse_px(row["fontSize"])
                weight = parse_weight(row["fontWeight"])
                if size < min_size:
                    problems.append(f"{sel} 字級 {size}px 小於驗收下限 {min_size}px")
                if weight < min_weight:
                    problems.append(f"{sel} 字重 {weight} 小於驗收下限 {min_weight}")

            if metrics["clipped"]:
                problems.append(f"非程式碼文字有裁切/不換行：{len(metrics['clipped'])} 處")

            backgrounds = {x["backgroundColor"] for x in metrics["colors"] if x.get("backgroundColor")}
            if len(backgrounds) < 3:
                problems.append("主要區塊色系區分不足")
            if rgb_luminance(metrics["bodyBackground"]) < 0.82:
                problems.append(f"整體背景不是明亮淺色系：{metrics['bodyBackground']}")

            row = {
                "id": case_id,
                "title": item["title"],
                "viewport": "1920x1080",
                "metrics": metrics,
                "problems": problems,
                "passed_ui": not problems,
            }
            ui_rows.append(row)
            overall.extend(f"{case_id}: {p}" for p in problems)

        context.close()
        browser.close()

    summary = {
        "case_count": len(ui_rows),
        "ui_pass_count": sum(1 for x in ui_rows if x["passed_ui"]),
        "all_ui_pass": all(x["passed_ui"] for x in ui_rows),
        "problems": overall,
    }
    (out / "ui_results.json").write_text(
        json.dumps({"summary": summary, "cases": ui_rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# SQLCheck 1920×1080 Browser UI 驗收",
        "",
        f"- 案例數：{len(ui_rows)}",
        f"- UI 自動檢查通過：{summary['ui_pass_count']}/{len(ui_rows)}",
        "- 視窗：1920×1080、light color scheme、Chromium headless",
        "- 證據：每案 viewport screenshot + full-page screenshot + computed-style JSON",
        "",
        "## 案例",
        "",
        "| 案例 | Dashboard/圖卡 | 字級階層 | 水平溢位 | Oracle 依據圖卡 | 結果 |",
        "|---|---|---|---|---|---|",
    ]
    for row in ui_rows:
        m = row["metrics"]
        lines.append(
            f"| {row['id']} | {m['summaryCardCount']} 張摘要卡 | 已量測 | "
            f"{'有' if m['horizontalOverflow'] else '無'} | {m['oracleEvidenceCount']} | "
            f"{'PASS' if row['passed_ui'] else 'FAIL'} |"
        )
    lines += ["", "## 問題"]
    lines.extend(f"- {p}" for p in overall) if overall else lines.append("- Browser DOM / 字級 / 基本版面自動檢查未發現問題。")
    (out / "UI_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
