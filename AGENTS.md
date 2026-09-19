# SQLCheck 專案憲法

本檔案是 SQLCheck repository 的 project-local constitution，補充全域
coding-agent instructions。所有修改本 repository 的 agent 都必須遵守本檔案。

## Commit message 規則（強制）

- 本專案的**每一個 commit message** 都必須使用臺灣繁體中文語義撰寫。
- commit subject 與 body 都必須使用臺灣繁體中文語義撰寫；必要的技術名詞、
  檔名、命令、API 名稱與標準縮寫可以保留原文，但整體敘述不得改成英文語義。
- 每個 commit message 都必須詳細說明下列三個部分：
  1. **意圖**：這次變更要解決什麼問題，以及為什麼需要它。
  2. **做了什麼**：實際修改的程式、測試、設定或文件，以及重要的行為邊界。
  3. **下一步建議**：後續驗證、review、部署前檢查或已知限制。
- 建議使用以下格式，並依變更內容補充驗證結果與限制：

  ```text
  <臺灣繁體中文摘要>

  意圖：
  ...

  做了什麼：
  ...

  下一步建議：
  ...

  驗證與限制：
  ...
  ```

- commit 前必須檢查 commit message 是否符合本規則；不得以縮短訊息、
  只寫英文 conventional prefix，或只列檔名來取代必要說明。
- 這項規則適用於 feature、fix、refactor、test、docs、chore 以及後續
  所有其他類型的 commit。
