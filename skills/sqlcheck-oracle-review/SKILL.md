---
name: sqlcheck-oracle-review
description: Governance rules for how SQLCheck (Taiwan local-tax Oracle SQL review tool) reasons about SQL optimization knowledge — when a rewrite may be treated as proven, when it must stay advice-only, and what SQLCheck must never claim about indexes, execution plans, or Oracle statistics it cannot see. Load this before proposing or reasoning about ANY SQL rewrite/optimization change in this repository.
version: 1
---

# SQLCheck Oracle Review — SQLCheck Oracle Knowledge v1

SQLCheck is Oracle-focused, but it is **not an Oracle DBA tool**. It reviews
one submitted SQL statement's text; it has no database connection, no
execution plan, no index metadata, no statistics. Everything in this skill
exists to stop a coding agent (or the AI advice pipeline this Handoff.md
describes) from pretending otherwise.

## The one file that matters: the Pattern Catalog

`backend/app/knowledge/pattern_catalog.yaml` is the single machine-readable
source of truth for SQL optimization pattern knowledge — what a pattern is,
its classification, why, and what it may/may not claim. This SKILL.md and its
`references/` explain **how to use** that catalog; they do not duplicate its
content. If you find yourself copying pattern rationale out of the catalog
into prose here, stop — link the pattern id instead.

Read `references/project-boundaries.md` first — it states the authority order
and the compliance/optimization boundary. Then:

- Deciding whether a rewrite can be shown as verified → `references/safe-rewrites.md`
- Explaining an ADVICE_ONLY direction → `references/advice-only-patterns.md`
- Checking what the model/agent must never say → `references/forbidden-claims.md`
- The Detect→Classify→...→Learn workflow → `references/methodology.md`

## Five things to hold in your head

1. **SQLCheck 是 Oracle-focused，但不是 Oracle DBA 工具。** No CREATE INDEX,
   no execution plan reasoning, no "this will be faster" — see
   `references/forbidden-claims.md`.
2. **`pattern_catalog.yaml` 才是 optimization pattern 的 Source of Truth.**
   Not this SKILL.md, not `docs/sql-optimization-skill-applicability.md`
   — those explain and index it, they don't replace it.
3. **Compliance rules ≠ optimization knowledge.** `backend/app/config/rules.yaml`
   / `important_tables.yaml` (fed by 正式中心規範) decide BLOCK/NOTICE/PASS.
   Generic SQL-optimization opinions — including everything in the external
   `github/awesome-copilot` sql-optimization skill — never upgrade a pattern
   into a compliance finding. "SELECT * is bad practice" does not make
   SELECT * "不符合中心規範."
4. **Deterministic Python authority beats the LLM.** Order:
   正式中心規範 > `rule_engine.py` > `rewrite_rules.py` > this catalog > Gemma.
   Gemma is never the compliance authority and never the semantic-equivalence
   authority — it explains and drafts; deterministic code verifies.
5. **When in doubt about equivalence, classify down, not up.** A rewrite
   moves from ADVICE_ONLY to VERIFIED_REWRITE only when
   `backend/app/services/rewrite_rules.py` proves it without an unchecked
   precondition (with its own positive/negative/boundary tests) — never by
   adding an entry to the catalog alone, never because an external skill
   calls it safe, and never merely because a runtime rule already derives
   it. Where the runtime already does more than governance certifies (TRUNC,
   NVL, SUBSTR's prefix-range form), the catalog records a `runtime_gap`;
   read it before relying on that runtime rule.

## Phase boundary (read before touching Runtime code)

This skill and the catalog it documents are a **knowledge layer only**. As of
this Phase, nothing here is wired into `ai_service.py`'s prompt assembly,
gating, or the Ollama request path — see `references/project-boundaries.md`
for the exact list of what must not change. If a task asks you to make the
Runtime *use* this catalog (a "Pattern Selector"), that is explicitly a
**future phase**, not this one.
