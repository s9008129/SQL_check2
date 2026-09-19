import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

describe("print diff behavior", () => {
  it("keeps the primary fragment diff printable and hides full SQL/copy controls", () => {
    const css = readFileSync("src/styles/print.css", "utf8");
    expect(css).toContain(".full-sql-details");
    expect(css).toContain(".copy-sql-btn");
    expect(css).toContain("display: none !important");
    expect(css).toContain(".fragment-diff");
    expect(css).toContain(".evidence-explanation");
    expect(css).toContain(".card-compare .card-desc");
  });
});
