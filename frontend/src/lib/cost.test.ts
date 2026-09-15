import { describe, expect, it } from "vitest";
import { formatCost, formatCostInputOnBlur, parseCostInput } from "./cost";

describe("parseCostInput", () => {
  it("parses a plain digit string", () => {
    expect(parseCostInput("68420")).toBe(68420);
  });

  it("parses a comma-formatted string", () => {
    expect(parseCostInput("68,420")).toBe(68420);
  });

  it("tolerates surrounding whitespace", () => {
    expect(parseCostInput("  68,420  ")).toBe(68420);
  });

  it("accepts zero", () => {
    expect(parseCostInput("0")).toBe(0);
  });

  it("rejects blank input", () => {
    expect(parseCostInput("")).toBeNull();
    expect(parseCostInput("   ")).toBeNull();
  });

  it("rejects negative numbers", () => {
    expect(parseCostInput("-100")).toBeNull();
  });

  it("rejects non-numeric input", () => {
    expect(parseCostInput("abc")).toBeNull();
    expect(parseCostInput("68,42a")).toBeNull();
  });

  it("rejects decimals", () => {
    expect(parseCostInput("68420.5")).toBeNull();
  });
});

describe("formatCost", () => {
  it("adds thousands separators", () => {
    expect(formatCost(68420)).toBe("68,420");
  });

  it("formats small numbers without separators", () => {
    expect(formatCost(0)).toBe("0");
    expect(formatCost(999)).toBe("999");
  });
});

describe("formatCostInputOnBlur", () => {
  it("reformats a valid raw value with commas", () => {
    expect(formatCostInputOnBlur("68420")).toBe("68,420");
  });

  it("re-normalizes an already comma-formatted value", () => {
    expect(formatCostInputOnBlur("1,234,567")).toBe("1,234,567");
  });

  it("leaves invalid input untouched so the user can keep editing", () => {
    expect(formatCostInputOnBlur("abc")).toBe("abc");
  });
});
