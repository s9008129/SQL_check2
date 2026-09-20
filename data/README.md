# data/ — Runtime 與測試輸出工作區

此目錄不是一般原始碼目錄。除本說明與 `.gitkeep` 外，內容預設不進 Git。

## Manual Live Cloud E2E

真正 Ollama Cloud / Gemma 的永久入口是 GitHub Actions 的 `Manual Live Cloud E2E`。它是手動執行，不會每次 PR 自動跑；workflow 產生的 evidence 仍需遵守本文件的資料最小化與證據有效性原則。

## E2E / 回歸測試

每一次獨立測試請建立自己的子目錄：

```text
data/<test-scope>_YYYYMMDD_HHMMSS/
```

例如：

```text
data/e2e_post_pr20_20260920_143000/
```

該次測試產生的所有內容都必須集中在此子目錄，不可散落於 `/tmp`、repository root 或其他暫存路徑。至少包含適用的：

```text
REPORT.md
matrix.csv
model_adherence.csv
confidence_stats.csv
forbidden_scan.txt
environment.txt
git_state.txt
raw_model/
final_api/
baseline/
screenshots/
print/
logs/
harness/
```

測試結束後，先移除非證據的 cache / scratch file，再檢查不得含 API key、密碼、可識別個資或未遮罩 production SQL，最後將整個 run directory 打包成：

```text
data/<same-run-name>.zip
```

ZIP 必須可正常解壓、包含完整報告與 manifest，並作為交付給獨立 reviewer 的唯一附件。

## 證據有效性

- `browser_dom/*.json` 必須保存**實際 DOM 查詢結果**與 assertion outcome；不能只把預期文字寫進 JSON。
- `screenshots/TCxx.png` 若不是 SQLCheck 該案例的實際畫面（例如桌布、terminal、錯誤視窗），該案例 UI 不得標 PASS。
- `print/TCxx.png` 只有真正的 Chrome native Print Preview 才能作為 print PASS。Computer Use error、terminal 或普通網頁截圖都只能標示 NOT PROVEN / FAIL。
- 測試工具故障時，報告要保留 failure evidence，不得用 API PASS 推論 UI / Print 也 PASS。

## 重要界線

- 不要使用 `/tmp` 或 `/var/tmp` 保存測試資料。
- 不要 commit E2E raw output、screenshots、logs 或 ZIP。
- 不要把 production source code 放進此目錄；只有「為某一次測試臨時產生的 harness / helper」才放在該 run 的 `harness/`。
- 不要刪除或修改 `data/sql_archive/`；那是應用程式 runtime archive，與 E2E artifact 分開。
