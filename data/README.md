# data/ — Runtime 與測試輸出工作區

此目錄不是一般原始碼目錄。除本說明與 `.gitkeep` 外，內容預設不進 Git。

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

## 重要界線

- 不要使用 `/tmp` 或 `/var/tmp` 保存測試資料。
- 不要 commit E2E raw output、screenshots、logs 或 ZIP。
- 不要把 production source code 放進此目錄；只有「為某一次測試臨時產生的 harness / helper」才放在該 run 的 `harness/`。
- 不要刪除或修改 `data/sql_archive/`；那是應用程式 runtime archive，與 E2E artifact 分開。
