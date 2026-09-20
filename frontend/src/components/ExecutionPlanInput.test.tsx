import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import ExecutionPlanInput from "./ExecutionPlanInput";

vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {},
  extractPlan: vi.fn(),
}));

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
