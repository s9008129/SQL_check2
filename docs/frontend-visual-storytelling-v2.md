# SQLCheck 前端視覺化設計系統 v2

> 狀態：CURRENT  
> 更新日期：2026-09-22  
> 實作分支：`feature/frontend-visual-storytelling-v2`

## 1. 產品定位

SQLCheck 前端不是一般管理 Dashboard，而是：

> **SQL Analysis Workbench + Visual Reasoning Report**

核心閱讀順序：

```text
輸入 SQL
→ 先看結論
→ 看關鍵訊號
→ 看規則與測試機證據
→ 看改善解釋
→ 需要時再展開完整明細
```

## 2. 資訊權重

- P0：中心規範結論，使用 Decision Hero。
- P1：中心規範摘要、COST、改善指數、AI 建議狀態。
- P2：中心規則與 SQL Developer 測試機 Execution Plan。
- P3：完整規則、Plan steps、完整 SQL diff。

任何新元件都必須先回答「使用者為什麼需要在現在看到它」。

## 3. Evidence boundary

畫面必須持續區分：

- **規則引擎**：deterministic fact / derived result。
- **SQL Developer Plan**：使用者主動提供的測試機 evidence。
- **AI**：interpretation / explanation。
- **需人工確認**：目前證據不足，不得用漂亮 UI 包裝成已驗證事實。

Execution Plan 不改變中心規範判定或改善指數；測試機 Plan 不代表正式機一定相同。

## 4. 視覺語言

方向：Premium Minimalism × Editorial Layout × Data Storytelling。

主要規則：

- Primary accent 使用深藍。
- 綠 / 黃 / 紅只表示符合、需確認、需處理。
- 不以大面積漸層、霓虹或動畫建立層級。
- 主要靠 typography、whitespace、alignment、contrast。
- 卡片不是預設容器；只有需要建立資訊群組時才使用。
- 陰影維持低對比。
- 所有關鍵數值使用 tabular numerals。

## 5. Progressive disclosure

下列資訊預設不搶第一屏：

- SQL Developer 執行計畫輸入。
- 全部中心規則。
- Plan steps。
- 完整 SQL。

第一層優先顯示「答案」，第二層才顯示「證據」。

## 6. 改善指數

既有 0–100 演算法、權重與分級不變。

前端新增水平 benchmark track：

- 60：建議改善起點。
- 80：優先改善起點。

此 track 只視覺化既有分數，不新增 business logic。

## 7. Responsive

驗收寬度：

- 375
- 390
- 768
- 1024
- 1440

小螢幕資訊順序：

```text
必要輸入
→ 結論
→ Key Signals
→ 規則 / Evidence
→ 改善建議
→ SQL 明細
```

Desktop sticky workbench 在窄螢幕回到一般文件流。

## 8. Accessibility

最低方向為 WCAG 2.2 AA：

- 可見 focus。
- keyboard 可操作。
- 狀態不只依賴顏色。
- native `details/summary` 優先用於 disclosure。
- 支援 `prefers-reduced-motion`。
- 改善指數視覺化提供 aria-label。

## 9. CSS 架構

- `app.css`：既有元件基礎樣式，暫時保留以降低回歸風險。
- `tokens.css`：v2 design tokens 與 legacy variable aliases。
- `visual-storytelling.css`：新資訊層級與 visual-system override。
- `print.css`：A4 / PDF 特化。

v2 先以隔離 override 層導入；visual regression 穩定後，再進行 app.css dead rules consolidation，避免資訊架構調整與大規模 CSS 刪除同時發生。

## 10. 不變的產品邊界

本次前端優化不修改：

- 中心規範邏輯。
- COST 門檻。
- 改善指數演算法與權重。
- AI 權限。
- verified rewrite 安全規則。
- Oracle connection policy。
- SQL Archive policy。
- Execution Plan authority。
