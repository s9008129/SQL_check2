import { describe, expect, it } from "vitest";
import { validateAnalyzeInput } from "./validate";
import { APPLICATION_NO_REQUIRED_ERROR, COST_FRIENDLY_ERROR, SQL_REQUIRED_ERROR } from "./copy";

describe("validateAnalyzeInput", () => {
  it("requires an application number", () => {
    expect(
      validateAnalyzeInput({ applicationNo: "", cost: "68420", sql: "SELECT 1 FROM DUAL" }),
    ).toBe(APPLICATION_NO_REQUIRED_ERROR);
    expect(
      validateAnalyzeInput({ applicationNo: "   ", cost: "68420", sql: "SELECT 1 FROM DUAL" }),
    ).toBe(APPLICATION_NO_REQUIRED_ERROR);
  });

  it("requires SQL", () => {
    expect(
      validateAnalyzeInput({ applicationNo: "115000218", cost: "68420", sql: "" }),
    ).toBe(SQL_REQUIRED_ERROR);
    expect(
      validateAnalyzeInput({ applicationNo: "115000218", cost: "68420", sql: "   " }),
    ).toBe(SQL_REQUIRED_ERROR);
  });

  it("requires a valid non-negative COST", () => {
    expect(
      validateAnalyzeInput({ applicationNo: "115000218", cost: "", sql: "SELECT 1" }),
    ).toBe(COST_FRIENDLY_ERROR);
    expect(
      validateAnalyzeInput({ applicationNo: "115000218", cost: "-5", sql: "SELECT 1" }),
    ).toBe(COST_FRIENDLY_ERROR);
    expect(
      validateAnalyzeInput({ applicationNo: "115000218", cost: "not-a-number", sql: "SELECT 1" }),
    ).toBe(COST_FRIENDLY_ERROR);
  });

  it("passes when everything is valid, comma-formatted COST included", () => {
    expect(
      validateAnalyzeInput({ applicationNo: "115000218", cost: "68,420", sql: "SELECT 1" }),
    ).toBeNull();
  });

  it("checks application number and SQL before COST", () => {
    // Application number is empty *and* COST is invalid — the application
    // number error should win so the user fixes one thing at a time.
    expect(
      validateAnalyzeInput({ applicationNo: "", cost: "-5", sql: "" }),
    ).toBe(APPLICATION_NO_REQUIRED_ERROR);
  });
});
