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

test("shows SQL Developer F6/F10 guidance and accepts pasted plan text", () => {
  const onChange = vi.fn();
  render(<ExecutionPlanInput value="" onChange={onChange} />);

  expect(screen.getByText(/F6 Autotrace/)).toBeInTheDocument();
  expect(screen.getByText(/F10 Explain Plan/)).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("SQL Developer 執行計畫"), {
    target: { value: "| Id | Operation | Name |" },
  });
  expect(onChange).toHaveBeenCalledWith("| Id | Operation | Name |");
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
