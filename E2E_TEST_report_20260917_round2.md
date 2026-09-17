# SQLCheck 2.0 E2E 第二輪（2026-09-17 下午）：驗證「AI 都說寫法良好」是否屬實

## 一句話總結

使用者實測後懷疑 AI 一律說「寫法良好」。用 10 個藏了細微缺陷的 SQL 當對照組驗證：模型對
7 案給出正確改寫、1 案給附假設的方向，**證明模型有辨別能力，使用者那幾份 SQL 確實寫得好**。
但對照組同時暴露一個藏了兩天的根因（Gemma4 思考模式吃光輸出額度 → 「暫時無法使用」）與
兩個判斷品質問題，皆已修正並用真實模型驗證，待正式主機重新部署。

## 對照組結果（正式主機、真實 Gemma4、修正前）

| 案例 | 缺陷 | 修正前結果 | 評語 |
|---|---|---|---|
| F1 `UPPER(欄位)='ABC'` | 條件套函數 | 改寫 ✓ | 正確 |
| F2 `SUBSTR(APPR_DATE,1,3)='114'` | 條件套函數 | 改寫，但補成 `'1140101'~'1150101'` | **語意錯誤**（假設了日期格式） |
| F3 `COLL_YR = 107`（其餘皆用引號） | 隱含型別轉換 | 無需改寫，reason 宣稱「無隱含型別轉換」 | **漏判且宣稱無法驗證的事** |
| F4 `LIKE '%明'` | 前置萬用字元 | advice_only | 正確，但 example 編造佔位符 |
| F5 `NOT IN (子查詢)` | NULL 陷阱 | **暫時無法使用**（116 秒） | 失敗 |
| F6 `A OR B`（跨欄位） | OR | **暫時無法使用**（85 秒） | 失敗 |
| F7 `BA_TAX + 0 = 1000` | 欄位運算 | 改寫 ✓ | 正確 |
| F8 `NVL(欄位,'1')='1'` | 條件套函數 | 改寫 ✓ | 正確 |
| F9 台糖 SQL 加 `TRIM()` | 條件套函數 | 改寫 ✓ | 正確 |
| F10 `TO_CHAR(日期,'YYYY')='2024'` | 條件套函數 | 改寫 ✓ | 正確 |

## 根因：Gemma4 思考模式

直接對正式主機 Ollama 重送 F6 的原始請求，取得未經後端處理的回應：

| | 預設（思考開） | `think:false` |
|---|---|---|
| 耗時 | 85.7 秒 | **14.4 秒** |
| done_reason | length | stop |
| eval_count | 3072（＝num_predict 上限） | 429 |
| message.thinking | **8,431 字** | 0 |
| message.content | **空白** | 完整 JSON，含改寫 |

模型把整個輸出額度花在內部推理，JSON 一個字都沒產出；後端只看 content，判定為截斷而降級。
這也解釋了為什麼每次回應要 40–90 秒。

## 本次修正（皆已用本機程式碼直連正式主機 Gemma4 驗證）

1. **關閉思考模式**：`app.yaml ollama.think_default=false`，環境變數 `OLLAMA_THINK` 可覆寫；
   log 新增 `thinking_chars`，截斷時若有思考內容會明確提示。
2. **結構事實入 payload**：新增 `structure_flags`（not_in_subquery、distinct、outer_join、
   cartesian_join、select_star…），模型不必從文字猜。
3. **「寫法良好」必須有證據**：prompt 要求選 not_needed 前逐項檢查五類規則引擎抓不到的細微
   寫法，reason 必須列出實際檢查過的項目，且只能列從 SQL 文字看得出來的事（不可宣稱「無隱含
   型別轉換」——模型看不到欄位型別）。
4. **語意不保證相同的改寫一律「僅提供方向」**：NOT IN→NOT EXISTS、OR→UNION ALL、GROUP BY
   拆分、移除 DISTINCT、新增／移除子查詢。程式端 `_revalidate_suggested_sql` 同步新增結構
   旗標相等比對作為最後防線。
5. **前綴改寫語意修正**：`SUBSTR(col,1,3)='114'` → `col >= '114' AND col < '115'`，不得自行
   補成日期格式；`LIKE '114%'` 本身不改（效能相同，改了只會誤導）。

## 修正後真實模型驗證（9 案，本機 pipeline 直連正式主機 Ollama）

| 案例 | outcome | 耗時 | 結果 |
|---|---|---|---|
| F2 SUBSTR 前綴 | provided | 12.6s | `>= '114' AND < '115'`，語意正確 |
| F3 型別混用 | advice_only | 10.7s | 「若 COLL_YR 為文字欄位，建議 '107'」，不再宣稱已確認 |
| F5 NOT IN | advice_only | 11.1s | NOT EXISTS 範例＋NULL 差異說明（原本失敗） |
| F6 OR 跨欄位 | advice_only | 11.9s | UNION ALL 範例＋去重條件（原本失敗） |
| F4 前置萬用字元 | advice_only | 9.6s | 「若只需比對開頭可改 LIKE '明%'」 |
| S1 TRUNC | provided | 13.9s | 正確改寫 |
| 台糖（真實） | not_needed | 9.3s | 附 DISTINCT 確認建議 |
| 自用住宅（真實） | not_needed | 6.0s | reason 列出 6 項檢查，不再做無效益的 LIKE 改寫 |
| 地價稅（真實） | advice_only | 13.0s | GROUP BY 拆分改為方向（原本被複核擋下） |

後端 283 項測試、ruff 全過。

## 附帶發現：安全缺口（待處理，未在本次修正）

正式主機 Ollama 11434 埠可從開發機（區網 10.97.15.54）直接連線成功。`deploy.ps1` 建立的
規則只放行 WSL 介面，代表另有一條放行規則（疑為 Ollama 安裝程式自建），與 PRD §46「不對
一般區網開放」不符。建議在正式主機執行下列指令找出來源後補一條 Block 規則（LocalSubnet），
並在 deploy.ps1 加入自動驗證與回滾：

```powershell
Get-NetFirewallRule | Where-Object { $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' } |
  Get-NetFirewallPortFilter | Where-Object LocalPort -eq 11434
```

## 下一步

1. 正式主機 `git pull` → `deploy.ps1`（.env 不需改，think 預設已在 app.yaml 關閉）。
2. 重新貼一次含 `NOT IN` 子查詢或 `A OR B` 的 SQL，確認不再出現「暫時無法使用」，且回應
   時間降到 10–20 秒。
3. 處理上述 11434 防火牆缺口。
