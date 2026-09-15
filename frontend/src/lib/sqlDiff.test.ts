import { describe, expect, it } from "vitest";
import { computeSqlLineDiff } from "./sqlDiff";

describe("computeSqlLineDiff", () => {
  it("marks an identical pair with no highlighted lines", () => {
    const sqlText = "SELECT 1 FROM DUAL;";
    const diff = computeSqlLineDiff(sqlText, sqlText);
    expect(diff.originalLineClasses.size).toBe(0);
    expect(diff.suggestedLineClasses.size).toBe(0);
  });

  it("flags a changed WHERE line as removed on the left and added on the right", () => {
    const original = "SELECT A\nFROM T\nWHERE TRUNC(D) = :X;";
    const suggested = "SELECT A\nFROM T\nWHERE D >= :START AND D < :END;";
    const diff = computeSqlLineDiff(original, suggested);
    expect(diff.originalLineClasses.get(3)).toBe("removed");
    expect(diff.suggestedLineClasses.get(3)).toBe("added");
    expect(diff.originalLineClasses.has(1)).toBe(false);
    expect(diff.suggestedLineClasses.has(1)).toBe(false);
  });

  it("flags a brand-new trailing line as added only", () => {
    // Every real line ends with \n (including the last) in both strings so
    // the shared "SELECT A" / "FROM T" lines are byte-identical chunks and
    // only the appended third line shows up in the diff.
    const original = "SELECT A\nFROM T\n";
    const suggested = "SELECT A\nFROM T\nWHERE STATUS = :S;\n";
    const diff = computeSqlLineDiff(original, suggested);
    expect(diff.suggestedLineClasses.get(3)).toBe("added");
    expect(diff.originalLineClasses.size).toBe(0);
  });
});
