/// <reference types="node" />
import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// This file lives at src/no-persistence.test.ts, so its own directory *is*
// the src/ root the PRD (§6.3) asks us to scan.
const SRC_DIR = dirname(fileURLToPath(import.meta.url));
const SELF_PATH = fileURLToPath(import.meta.url);

function collectSourceFiles(dir: string): string[] {
  const entries = readdirSync(dir, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectSourceFiles(full));
    } else if (/\.(ts|tsx)$/.test(entry.name)) {
      files.push(full);
    }
  }
  return files;
}

// Built via concatenation on purpose: this keeps the literal forbidden
// substrings from ever appearing contiguously in this file's own source,
// so the scan below can safely include this file without flagging itself
// (belt-and-suspenders on top of the explicit SELF_PATH exclusion below).
const FORBIDDEN_TERMS = ["local" + "Storage", "session" + "Storage", "indexed" + "DB"];

describe("no browser persistence (PRD §6.3 / §41)", () => {
  it("never references localStorage, sessionStorage, or indexedDB anywhere under src/", () => {
    const files = collectSourceFiles(SRC_DIR).filter((file) => file !== SELF_PATH);
    expect(files.length).toBeGreaterThan(0);

    const offenders: string[] = [];
    for (const file of files) {
      const text = readFileSync(file, "utf-8");
      for (const term of FORBIDDEN_TERMS) {
        if (text.includes(term)) offenders.push(`${file} references "${term}"`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
