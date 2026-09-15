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
