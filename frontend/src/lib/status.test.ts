import { describe, expect, it } from "vitest";
import { complianceTone, improvementTone, ruleStatusIcon, ruleStatusTone } from "./status";

describe("complianceTone", () => {
  it("maps the three ComplianceStatus values to the fixed colour semantics", () => {
    expect(complianceTone("PASS")).toBe("green");
    expect(complianceTone("REVIEW")).toBe("yellow");
    expect(complianceTone("BLOCK")).toBe("red");
  });
});

describe("ruleStatusTone", () => {
  it("maps every RuleStatus to a fixed tone", () => {
    expect(ruleStatusTone("PASS")).toBe("green");
    expect(ruleStatusTone("NOTICE")).toBe("yellow");
    expect(ruleStatusTone("REVIEW")).toBe("yellow");
    expect(ruleStatusTone("BLOCK")).toBe("red");
    expect(ruleStatusTone("NA")).toBe("gray");
  });
});

describe("ruleStatusIcon", () => {
  it("gives BLOCK and PASS visually distinct glyphs", () => {
    expect(ruleStatusIcon("PASS")).toBe("✓");
    expect(ruleStatusIcon("BLOCK")).toBe("✕");
    expect(ruleStatusIcon("PASS")).not.toBe(ruleStatusIcon("BLOCK"));
  });
});

describe("improvementTone", () => {
  it("passes the server-provided colour straight through without recomputing it", () => {
    expect(improvementTone("green")).toBe("green");
    expect(improvementTone("yellow")).toBe("yellow");
    expect(improvementTone("red")).toBe("red");
  });
});
