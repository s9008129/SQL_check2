import { describe, expect, it } from "vitest";
import { computeSqlLineDiff, looksLikeSqlFragment } from "./sqlDiff";

describe("looksLikeSqlFragment", () => {
  it("accepts SQL whose only Chinese is inside a string literal", () => {
    expect(looksLikeSqlFragment("A.NAME LIKE '%股份'")).toBe(true);
    expect(looksLikeSqlFragment("A.TXN_DATE >= :D AND A.TXN_DATE < :D + 1")).toBe(true);
  });

  it("rejects prose the model put in `example`", () => {
    expect(looksLikeSqlFragment("若業務上只需比對開頭，可改為 `A.NAME LIKE '股份%'`；若需要全文比對，建議評估建立文字索引。")).toBe(false);
    expect(looksLikeSqlFragment("確認查詢範圍")).toBe(false);
  });
});

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

import { computeAlignedDiff, computeWordDiff, locateOriginalFragment } from "./sqlDiff";

describe("computeWordDiff", () => {
  it("marks only the changed tokens", () => {
    const { left, right } = computeWordDiff("WHERE TRUNC(A.D) = :X", "WHERE A.D >= :X AND A.D < :X + 1");
    expect(left.some((t) => t.kind === "removed" && t.value.includes("TRUNC"))).toBe(true);
    expect(right.some((t) => t.kind === "added" && t.value.includes("AND A.D <"))).toBe(true);
    expect(right.filter((t) => t.kind === "same").map((t) => t.value).join("")).toContain("WHERE");
  });

  it("ignores case-only differences", () => {
    const { right } = computeWordDiff("select a from t", "SELECT a FROM t");
    expect(right.every((t) => t.kind === "same")).toBe(true);
  });
});

describe("computeAlignedDiff", () => {
  it("pairs a rewritten line and word-diffs it, keeping unchanged lines on both sides", () => {
    const rows = computeAlignedDiff("SELECT A\nFROM T\nWHERE TRUNC(D) = :X", "SELECT A\nFROM T\nWHERE D >= :X");
    expect(rows).toHaveLength(3);
    expect(rows[0].kind).toBe("same");
    expect(rows[2].kind).toBe("changed");
    expect(rows[2].left?.lineNo).toBe(3);
    expect(rows[2].right?.tokens.some((t) => t.kind === "added")).toBe(true);
  });

  it("renders an extra suggested line as an added row with an empty left side", () => {
    const rows = computeAlignedDiff("SELECT A\nFROM T", "SELECT A\nFROM T\nWHERE X = 1");
    expect(rows[2].kind).toBe("added");
    expect(rows[2].left).toBeNull();
  });
});

describe("locateOriginalFragment", () => {
  it("finds the original line sharing the most tokens with the example", () => {
    const original = "select a\nfrom t\nwhere substr(w.coll_b_date, 1, 3) = '107'\n  and w.tax_cd = '55'";
    expect(locateOriginalFragment(original, "w.coll_b_date >= '107' AND w.coll_b_date < '108'")).toContain("substr(w.coll_b_date");
  });

  it("returns null when nothing plausible matches", () => {
    expect(locateOriginalFragment("select a from t", "確認查詢範圍")).toBeNull();
  });
});
