# Methodology: Detect → Classify → Explain → Suggest → Verify → Present → Validate → Learn

The generic skill this project drew on (`github/awesome-copilot`
sql-optimization) uses Identify → Analyze → Optimize → Test → Monitor →
Iterate — a DBA workflow against a live database. SQLCheck reviews one
submitted SQL statement's text with no database connection, so the workflow
is reshaped around what SQLCheck can actually verify:

1. **Detect** — `sql_parser.py` (sqlglot AST) and `rule_engine.py` extract
   objective structural facts: tables, `complexity_flags`,
   `structural_signature`, rule findings (R001–R008). No judgment yet.

2. **Classify** — `pattern_catalog.yaml` decides how far a detected pattern
   may go: VERIFIED_REWRITE / ADVICE_ONLY / INFORMATIONAL / OUT_OF_SCOPE.
   This is a lookup against the catalog, never a per-request guess.

3. **Explain** — Gemma (future phase, not this one) puts the classified
   finding into plain Traditional Chinese for the reviewer. It explains; it
   does not reclassify.

4. **Suggest** — only when the catalog's `allowed_behavior.advice` is true.
   An OUT_OF_SCOPE pattern (e.g. index advice) is never suggested at all, not
   even hedged.

5. **Verify** — for anything claiming to be a rewrite, deterministic Python
   is the only verifier: `rewrite_rules.py::verify_fragment` for a fragment,
   `verify_predicate_changes` + `_revalidate_suggested_sql`'s structural
   comparison for a full statement rewrite. A classification of
   VERIFIED_REWRITE in the catalog is necessary but not sufficient — the
   actual instance still has to pass this step every time.

6. **Present** — the UI must keep verified / corrected / unverified /
   advice-only visually and textually distinct (see
   `frontend/src/components/SqlCompare.tsx`, `ImprovementAdvice.tsx`). This
   catalog does not change the UI in Phase 1, but any future UI work must
   preserve this distinction per pattern classification.

7. **Validate** — even a VERIFIED_REWRITE is a structural/logical proof, not
   a runtime measurement. `improvement_potential` and
   `estimated_improvement_pct` are explicitly not "已測試" claims (see
   `forbidden-claims.md`); real effect still needs a test-environment run.

8. **Learn** — Golden Dataset and de-identified `sql_archive` cases feed back
   into the catalog over time: a new production incident (like the 2026-09-17
   SUBSTR→LIKE mismatch) becomes a new `rewrite_rules.py` rule with tests, and
   a new catalog entry citing it as provenance — never a prompt-only patch.

## Adding a pattern

1. Decide the classification honestly. Default to ADVICE_ONLY unless you can
   point to a specific deterministic proof mechanism (a `rewrite_rules.py`
   function with tests) for VERIFIED_REWRITE, or to the OUT_OF_SCOPE list in
   `project-boundaries.md` for OUT_OF_SCOPE.
2. Append one entry to `pattern_catalog.yaml` with real provenance (an
   internal file/line or the external skill).
3. Run `cd backend && uv run pytest tests/test_pattern_catalog.py -q`.
4. If VERIFIED_REWRITE: add the rule function to `rewrite_rules.py` and
   positive/negative/boundary tests to `tests/test_rewrite_rules.py` — the
   catalog entry alone proves nothing.
5. Consider adding a synthetic semantic-trap case (see
   `backend/tests/knowledge/semantic_traps.yaml`) if the pattern has a known
   "looks safe but isn't" failure mode.
