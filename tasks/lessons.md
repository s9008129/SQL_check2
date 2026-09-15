# Lessons

（尚無；於修正或事後檢討時新增：失敗模式 / 偵測訊號 / 預防規則）

## 2026-09-15 sqlglot 30.18 實測發現（寫 rule_engine.py 前的驗證性 spike）

- **失敗模式**：計畫原假設 `parse_one(sql, error_level=ErrorLevel.RAISE)` 對壞掉的 SQL 會 raise `ParseError`，可用 try/except 判斷 `parse_status`。
- **偵測訊號**：實測 `"SELEKT * FRM T"`、`"asdkjfh asldkjf"` 這類「關鍵字打錯但 token 形狀像運算式」的輸入，`RAISE` 完全不會 raise，而是悄悄解析成 `Alias(Mul(Column(SELEKT), Column(FRM)), alias=T)` 之類的垃圾表達式（把打錯的關鍵字當欄位名、`*` 當乘法）。只有語法結構性不可能（如括號不成對、`SELECT FROM WHERE`）才會真的 raise。
- **預防規則**：`sql_parser.py` 除了 try/except ParseError，**必須再檢查頂層節點型別**是否為 `exp.Select/Update/Delete/Insert/Merge/Union/Except/Intersect` 之一；不是的話一律視為 `parse_status=failed`，不可只憑「沒 raise」判定為 ok。已寫成 `tests/_spike_sqlglot2.py` 區塊 B 可重現。

- **失敗模式**：計畫原假設「用 `isinstance(node, exp.Func)` 找 WHERE 內函數」可安全用來判斷 R005（條件欄位使用函數）。
- **偵測訊號**：實測發現 `exp.And` / `exp.Or` 的 MRO 是 `And -> Connector -> Binary -> Func -> Condition`，兩者都是 `exp.Func` 的子類別！單純 `isinstance(node, exp.Func)` 會把整個 `WHERE ... AND ...` 布林運算式也誤判成一個函數呼叫。
- **預防規則**：改用 `exp.Predicate`（EQ/NEQ/GT/GTE/LT/LTE/Like/ILike/In/Between/Is 的共同基底類別，且 `And/Or` 不是其子類別）鎖定「WHERE/HAVING/ON 內的比較運算」，只檢查每個 predicate 的直接運算元（`.this`/`.expression`，或 Between/In 的 `.this`）是否為 `exp.Func`，而不是「WHERE 子樹裡任何地方出現過函數」。已寫成 `tests/_spike_sqlglot2.py` 區塊 A/A-bis 可重現，並在 `test_rule_engine.py` 加入 `WHERE A=1 AND B=2` 不得觸發 R005 的迴歸測試。

- **附帶發現（非失敗，是簡化機會）**：`exp.Hint` 在 SELECT/UPDATE/DELETE/INSERT 都會被解析出來，但 MERGE 不會；`--+` 單行 hint 根本不會進 `exp.Hint`，而是落在 `.comments`；hint 內容有時是 `exp.Expression`、有時直接是 Python `str`（INSERT 的 `APPEND PARALLEL(...)` 是 str）。結論：R003 改成**純文字／token 正則**判斷（掃描 `/*+...*/` 與 `--+...` 兩種 comment span，對內容套 `\bPARALLEL(_INDEX)?\b`），不依賴 AST hint 節點，反而更簡單、更一致，parse 失敗時也能判。

## 2026-09-15 開發機終端機中文顯示

- **現象**：`uv run python -c "print(...)"` 印出的繁體中文在這個 Bash 工具的終端機顯示為亂碼（`�` 序列）。
- **確認非資料錯誤**：直接讀取檔案 bytes 並 `decode('utf-8')` 成功，`file` 指令也回報 UTF-8 text；亂碼只在「印到終端機」這一步發生，Python 內部字串與寫入檔案的內容都是正確的 UTF-8。
- **預防規則**：往後若需要在終端機直接肉眼檢查中文輸出，於指令前加 `PYTHONIOENCODING=utf-8`（例如 `PYTHONIOENCODING=utf-8 uv run python -c "..."`）。真正要驗證中文內容正確性時，優先用 pytest 斷言字串相等，或用 Read 工具開檔案看，不要單憑終端機肉眼判讀。

## 2026-09-15 Phase 2（附件擷取／SQL 辨識）除錯記錄

- **失敗模式**：`charset_normalizer.from_bytes(content).best()` 對短的 Big5 中文字串（如「備註」「測試」）誤判成 CP949（韓文），且加上 `cp_isolation=['utf_8','big5','cp950']` 限縮候選集後反而完全找不到匹配（回傳 None），比不限縮更差。
  **預防規則**：`_decode_text` 改為 UTF-8 → **明確嘗試 `cp950` 嚴格解碼** → charset_normalizer 一般偵測 → `cp950` errors=replace 兜底。CP950 嚴格解碼本身就是很強的訊號（不是 Big5 編碼的 bytes 通常會直接 raise），不需要靠統計偵測器對短中文字串瞎猜。

- **失敗模式**：PDF 掃描偵測門檻設 20（每頁有效字元數），但像 `"SELECT * FROM T1 WHERE X=1"` 這種偏短但完全合法的 SQL 只有 19 個英數字元，被誤判為「掃描影像」。
  **預防規則**：門檻下修為 10（`file_extract._extract_pdf`），並在程式碼註解說明這是刻意壓低以避免誤傷短 SQL，真正掃描頁清除頁首頁尾後應接近 0 字元。

- **失敗模式**：`sql_detect.py` 把多個獨立偵測到的 SQL 候選（CSV 多列、Markdown 多個 fence、純文字多個區塊）直接用 `"\n\n"` 串接，若使用者原文沒有分號，`sql_parser.py` 的分號切割器會把它們誤判成「一段無法解析的 SQL」而不是「兩段」。
  **預防規則**：新增 `_join_candidates()`，串接多個候選前先確保每段都以 `;` 結尾。

- **失敗模式**：純文字附件若完全沒有 SQL 關鍵字（例如一段純中文說明文字），`detect_sql` 的 `.txt` 分支會 fallback 把「整段原文」丟給 parser 嘗試解析；即使解析失敗，`sql_parser.py` 仍會把它視為 1 個 `statement_type="UNKNOWN"` 的片段計入清單，導致「未辨識到 SQL」被誤判成「已辨識 1 段 SQL」。
  **預防規則**：`_validated_statement_count` 改為只計算 `statement_type != "UNKNOWN"` 的片段。

- **失敗模式（連帶發現）**：純文字候選區塊擷取（`_candidate_blocks`）原本「找到下一個關鍵字前都算同一段」，導致 SQL 後面緊接的中文說明句（沒有分號分隔）被整段吞進候選 SQL。
  **預防規則**：新增 `_trim_trailing_prose`：以空行分段，只有「下一段開頭是 WHERE/AND/FROM/JOIN 等子句延續關鍵字」才視為同一段落延續，否則在該空行處截斷。

- **環境細節補充**：先前記錄的「終端機中文顯示亂碼」不只影響輸出，**也會影響透過 `bash -c` 直接輸入含中文的指令字串**（曾在指令列打的中文字面值被送進 Python 前就已經損毀，導致 `.encode('big5')` 對到錯的碼點而丟例外）。
  **預防規則**：任何需要用到中文字面值的除錯／驗證腳本，一律先用 Write 工具寫成 `.py` 檔案再執行，不要把中文直接打在 `bash -c "..."` 裡。

## 2026-09-15 安全性：main.py SPA fallback 路徑穿越（自動化安全掃描發現）

- **失敗模式**：`main.py` 的 `_spa_fallback` 路由（`@app.get("/{full_path:path}")`）直接用
  `_STATIC_DIR / full_path` 組出檔案路徑並檢查 `is_file()`，未限制結果必須落在靜態目錄內。
  FastAPI 的 `{full_path:path}` converter 會接受任意路徑片段（含 `..`），此路由又是公開、
  無需驗證即可存取，理論上可被用來讀取靜態目錄以外的檔案（路徑穿越 / Path Traversal）。
- **偵測訊號**：由背景自動化安全掃描（非本次任務手動觸發）標記為 HIGH。
- **預防規則**：新增獨立、可單元測試的 `_safe_static_path(static_root, requested_path)`，
  用 `.resolve()` + `Path.is_relative_to()` 確認結果沒有跳出 `static_root` 才回傳，否則回傳
  `None`（呼叫端一律 fallback 回 `index.html`，不洩漏任何目錄外內容）。已在
  `tests/test_main.py` 補上 6 項測試（含 Windows 上「絕對路徑片段」這種 `Path.__truediv__`
  可能直接吃掉 base path 的邊界案例）。
- **通用教訓**：任何用 FastAPI/Starlette 的 `{param:path}` 或類似「吃掉整段路徑」的路由參數
  去組檔案系統路徑時，一律要先做 containment check，不能只檢查副檔名或 `is_file()`。
