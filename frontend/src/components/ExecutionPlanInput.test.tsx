import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import ExecutionPlanInput from "./ExecutionPlanInput";
import { ApiError, extractPlan } from "../api/client";

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  extractPlan: vi.fn(),
}));

// A synthetic SQL Developer PLAN_TABLE grid export (CSV): OPERATION and
// OPTIONS are separate columns, as SQL Developer writes them.
const PLAN_CSV = [
  "Id,Operation,Options,Object_Name,Cardinality,Cost,Filter_Predicates",
  "0,SELECT STATEMENT,,,25,14,",
  "1,TABLE ACCESS,FULL,TAX_CASE,25,14,TRUNC(A.CASE_DATE)=DATE_VALUE",
].join("\n");

const extractPlanMock = vi.mocked(extractPlan);

test("explains that SQL Developer F10 is optional context for AI", () => {
  const onChange = vi.fn();
  render(<ExecutionPlanInput value="" onChange={onChange} />);

  expect(screen.getByText("SQL Developer F10 執行計畫（選填）")).toBeInTheDocument();
  expect(screen.getByText("協助 AI 判讀")).toBeInTheDocument();
  const guidance = document.querySelector(".plan-guidance");
  expect(guidance?.textContent).toContain("系統會整理重點提供給 AI 參考");
  expect(guidance?.textContent).toContain("讓改善建議更貼近這支 SQL");
  expect(screen.getByText(/原始執行計畫不會保存，也不會顯示在檢核結果/)).toBeInTheDocument();
  expect(screen.queryByText(/E-Rows|A-Rows|Predicate|COST 較高/)).toBeNull();
  expect(screen.queryByTestId("plan-ai-ready")).toBeNull();

  fireEvent.change(screen.getByLabelText("SQL Developer 執行計畫"), {
    target: { value: "| Id | Operation | Name |" },
  });
  expect(onChange).toHaveBeenCalledWith("| Id | Operation | Name |");
});

test("shows a simple ready state when F10 context is present", () => {
  render(<ExecutionPlanInput value="| Id | Operation | Name |" onChange={vi.fn()} />);

  expect(screen.getByTestId("plan-ai-ready")).toHaveTextContent("已加入本次 AI 分析參考");
});

test("uploads a CSV export straight into the plan textarea", async () => {
  const onChange = vi.fn();
  extractPlanMock.mockResolvedValueOnce({
    status: "ok",
    filename: "plan.csv",
    plan_text: PLAN_CSV,
    truncated: false,
    message: "已讀取執行計畫文字，可確認內容後開始檢核。",
  });
  render(<ExecutionPlanInput value="" onChange={onChange} />);

  const file = new File([PLAN_CSV], "plan.csv", { type: "text/csv" });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });

  await waitFor(() => expect(onChange).toHaveBeenCalledWith(PLAN_CSV));
  expect(screen.getByText(/已讀取執行計畫文字/)).toBeInTheDocument();
});

test("shows the backend's own message when the upload is rejected", async () => {
  const onChange = vi.fn();
  const rejection = new ApiError(400, "");
  // The mocked ApiError class only needs to satisfy `instanceof`; the
  // component reads `.detail`, which the mock constructor does not set.
  rejection.status = 400;
  rejection.detail = "執行計畫附件請使用 SQL Developer 匯出的 TXT 或 CSV，或直接貼上文字。";
  extractPlanMock.mockRejectedValueOnce(rejection);
  render(<ExecutionPlanInput value="" onChange={onChange} />);

  const file = new File(["%PDF-1.4"], "plan.pdf", { type: "application/pdf" });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });

  await waitFor(() =>
    expect(screen.getByText(/請使用 SQL Developer 匯出的 TXT 或 CSV/)).toBeInTheDocument(),
  );
  expect(onChange).not.toHaveBeenCalled();
});
