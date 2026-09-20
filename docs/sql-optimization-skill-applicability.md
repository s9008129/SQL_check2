> **文件狀態：REFERENCE**  
> 本文件是外部 sql-optimization skill 的適用性研究，不是現行 runtime 規格。Pattern Catalog、SQLCheck skill 與 deterministic runtime 才是現行治理來源。

# Awesome Copilot `sql-optimization` skill — applicability to SQLCheck

Source reviewed: `github/awesome-copilot`, `skills/sql-optimization/SKILL.md`
(single file; no `references/` subfolder). It is treated as **generic SQL
optimization knowledge**, not as an Oracle authority, not as a compliance
source, and not as evidence that any of its recommended rewrites are safe to
apply automatically — see
`skills/sqlcheck-oracle-review/references/project-boundaries.md`.

The source document's own methodology is Identify → Analyze → Optimize →
Test → Monitor → Iterate, against a live database the assistant can query
directly. Many of its examples are presented as direct `❌ BAD` / `✅ GOOD`
pairs (for example correlated subquery → window function, OFFSET → cursor
pagination, `SELECT *` → explicit columns). The examples do not state the
conditions under which the rewritten query returns the same rows — NULL
handling, duplicate rows, outer-join row preservation, datatype or collation
— which is the semantic-equivalence proof SQLCheck needs before treating a
rewrite as safe. That gap is why SQLCheck keeps its own governance layer
instead of adopting the source verbatim.

Rows that name a catalog id map to that
`backend/app/knowledge/pattern_catalog.yaml` entry; that file is the
authoritative rationale, this table is the index. Rows marked **Not currently
modeled / candidate only** have no catalog entry yet: their classification
column is a proposed disposition, not a governance decision.

## Query rewriting patterns

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| Subquery → JOIN conversion | Partially modeled (IN/EXISTS and NOT IN subquery forms only; general subquery → JOIN has no catalog entry) | Yes | B (`IN_SUBQUERY_TO_EXISTS`, `NOT_IN_SUBQUERY_TO_NOT_EXISTS`) | Duplicate rows if joined table isn't 1:1; NULL semantics differ for NOT IN | Advice only | `complexity_flags: not_in_subquery` |
| Correlated subquery → window functions | Advice only, and blocked at candidate stage | Yes | B (`CORRELATED_SUBQUERY_TO_JOIN_OR_WINDOW`) | PARTITION BY/ORDER BY NULL-grouping and tie-break may not match original correlation | Advice only; already in `ai_gate.candidate_forbidden_complexity_flags` (`correlated_subquery`) so no full-rewrite candidate is even generated | `complexity_flags: correlated_subquery`; `app.yaml ai_gate.candidate_forbidden_complexity_flags` |
| OR condition → UNION / UNION ALL | Advice only (cross-column); verified rewrite exists for the same-column special case | Yes | B (`OR_CROSS_COLUMN_TO_UNION_ALL`) for cross-column; **A** (`OR_SAME_COLUMN_TO_IN`) for same-column OR→IN, which is a *different* transform | Row duplication (UNION ALL) or dedup cost/semantics change (UNION) if branches overlap | Advice only for the general case; same-column OR→IN is already a proven, tested rewrite for up to 1000 values (Oracle IN-list limit, enforced by the runtime since 2026-09-18) | `rules.yaml` R006 (family signal only: fires on any OR, cannot tell cross-column from same-column); cross-column case detected only by prompt check (5); same-column case by `rewrite_rules.py::_rule_or_eq_to_in` |

## Index strategy techniques

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| Composite indexing / column order | Not supported, and must not be | Yes (concept) | **D** (`INDEX_ADVISORY`) | N/A — this is a correctness-safe topic, but SQLCheck has zero index metadata to reason from | Out of scope; requires DBA / test-environment confirmation | none |
| Covering indexes | Not supported | Yes | **D** (`INDEX_ADVISORY`) | N/A | Out of scope | none |
| Partial / filtered indexes | Not supported | Yes | **D** (`INDEX_ADVISORY`) | N/A | Out of scope | none |
| "Column order matters" index design principle | Not supported | Yes | **D** (`INDEX_ADVISORY`) | N/A | Out of scope | none |

## JOIN optimization

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| INNER vs LEFT/RIGHT JOIN type choice | Advice only | Yes | B (`LEFT_JOIN_TO_INNER_JOIN`) | **Unsafe for automatic rewrite**: silently drops main-table rows with no matching side row | Advice only; `_revalidate_suggested_sql`'s `join_sides` structural comparison already rejects any full-rewrite that changes JOIN type | `complexity_flags: outer_join` (family signal only: fires on LEFT/RIGHT/FULL/(+)); `ai_service._revalidate_suggested_sql` (`join_sides`) guards full rewrites |
| Filtering conditions moved into JOIN vs WHERE | Not currently modeled / candidate only | Yes | Candidate only — likely B if added as `JOIN_CONDITION_PLACEMENT`; no catalog entry today | Changes which outer-side rows survive for OUTER JOIN; safe for INNER JOIN | Advice only for OUTER JOIN; candidate for a dedicated catalog entry in a future phase | none yet |

## Pagination strategies

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| Cursor-based / ID-based pagination | Not currently modeled / candidate only | Yes (concept) | Candidate only — likely B if added as `CURSOR_BASED_PAGINATION`; no catalog entry today | Needs a stable unique monotonic sort key; also an application-layer change beyond the submitted SQL text | Advice only if ever added; do not treat as SQL-text-verifiable | none |

## Data access patterns

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| Explicit column selection (avoid `SELECT *`) | Already supported (informational) | Yes | **C** (`SELECT_STAR`) | None — but "faster" is not provable from SQL text alone | Informational only | `complexity_flags: select_star` |
| `EXISTS` instead of `IN` for subqueries | Advice only | Yes | B (`IN_SUBQUERY_TO_EXISTS`, and `NOT_IN_SUBQUERY_TO_NOT_EXISTS` for the NOT IN case) | NOT IN + possible NULL in subquery = zero rows ever (three-valued logic); DISTINCT/set-op subqueries can also differ | Advice only | `complexity_flags: not_in_subquery` |
| Conditional aggregation (CASE WHEN) to replace multiple queries | Not currently modeled / candidate only | Yes | Candidate only — likely B if added as `CONDITIONAL_AGGREGATION_CASE_WHEN`; no catalog entry today (`GROUP_BY_STRUCTURAL_REWRITE` covers a different transform) | Requires knowing the original multiple queries agreed on filters/timing, which SQLCheck cannot see from one submitted statement | Advice only | none |
| Batch INSERT over row-by-row | Not currently modeled; out of scope | Yes (concept) | Would be **D** (application/transaction redesign, not a single-statement rewrite); no catalog entry today | N/A | Out of scope | none |

## Query structure optimization

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| Function call avoidance in WHERE clauses | Already supported (advice) | Yes | B (`PREDICATE_FUNCTION_GENERIC`, `TRUNC_EQ_TO_RANGE`, `NVL_EQ_TO_OR_IS_NULL`); the only proven form is **A** `SUBSTR_EQ_TO_LIKE` (canonical LIKE form only) | Blanket function removal is a classic semantic trap (`UPPER_CASE_FOLD_REMOVAL`); TRUNC→range needs a time-free right-hand side and NVL→plain comparison differs for CHAR columns — the runtime stopped deriving both on 2026-09-18 | Advice only, except SUBSTR equality → canonical LIKE | `rules.yaml` R005 (family signal); `rewrite_rules.py` |
| Early filtering in WHERE clauses | Not currently a catalog entry | Yes (concept) | Candidate — likely **C** (informational; too generic to verify per-case) | None specific | Candidate to add as informational only | none |
| Temporary table for complex multi-step calculations | Not currently modeled / candidate only | Yes (concept) | Candidate only — likely **C** if added as `TEMP_TABLE_FOR_COMPLEX_CALC`; no catalog entry today | None specific; readability suggestion only | Candidate to add as informational only | none |

## Performance monitoring

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| Execution plan examination | Not supported, and must not be | Yes (concept) | **D** (`EXECUTION_PLAN_CLAIM`, `FULL_TABLE_SCAN_CLAIM`) | N/A — SQLCheck has no plan access | Out of scope | `app.yaml ai_guard.forbidden_phrases` |
| Slow query log analysis (MySQL-specific) | Not applicable | **No** (MySQL, not Oracle) | Would be **D** if added as `MONITORING_AND_PROFILING`; no catalog entry today | N/A | Out of scope / not applicable to Oracle | none |
| DB-specific monitoring views (`pg_stat_statements`, `sys.dm_exec_query_stats`) | Not applicable | **No** (PostgreSQL/SQL Server, not Oracle) | Would be **D**; no catalog entry today | N/A | Out of scope / not applicable to Oracle | none |

## Summary

- **Already supported** (as informational or advice, with a catalog entry):
  function-avoidance-in-WHERE (only SUBSTR → canonical LIKE is proven),
  SELECT *, EXISTS-vs-IN family, LEFT/RIGHT JOIN caution.
- **Candidate to add** (plausible catalog entries not yet written; not
  authorized for this Phase to add proactively — flag for a future PR):
  dedicated `JOIN_CONDITION_PLACEMENT`, `CONDITIONAL_AGGREGATION_CASE_WHEN`,
  `TEMP_TABLE_FOR_COMPLEX_CALC`, `EARLY_FILTERING_IN_WHERE`,
  `CURSOR_BASED_PAGINATION`, `MONITORING_AND_PROFILING` as standalone ids.
- **Advice only** (Class B, cannot be proven from SQL text): subquery↔JOIN
  family, OR↔UNION (cross-column), JOIN type changes, DISTINCT removal,
  GROUP BY restructuring, string-concat predicate splitting.
- **Informational only** (Class C): SELECT *, important-table usage,
  structural complexity, large result sets.
- **Out of scope** (Class D in the catalog): all index advisory, execution
  plan / FTS / cardinality / statistics / actual-runtime / post-rewrite-COST
  claims, partition and physical/host tuning. Also out of scope but with no
  catalog entry yet: batch-DML redesign and non-Oracle monitoring tooling.
- **Unsafe for automatic rewrite** even where SQLCheck does offer advice:
  LEFT JOIN→INNER JOIN, DISTINCT removal, NOT IN→NOT EXISTS, OR→UNION,
  correlated subquery→window function — every one of these has a documented
  semantic trap in `skills/sqlcheck-oracle-review/references/advice-only-patterns.md`.
- **Verified rewrite** (Class A, proven and tested today): SUBSTR equality →
  canonical LIKE, and same-column OR → IN with 1–1000 values (an Oracle 19c
  IN list holds at most 1000 expressions). These are the *only* patterns from
  either the external skill or SQLCheck's own history that meet the bar for
  automatic-rewrite-eligible status — and even they are not wired to
  automatic application in this Phase (see `project-boundaries.md`).
- **Runtime gaps closed on 2026-09-18** (Runtime Correctness v1): the
  runtime no longer derives TRUNC equality → range or NVL equality →
  conditional (both need facts SQL text cannot show), no longer accepts
  SUBSTR's p=1 prefix-range form (collation-dependent), and refuses
  same-column OR → IN beyond 1000 values with an explicit count guard. No
  `runtime_gap` is open. See
  `skills/sqlcheck-oracle-review/references/safe-rewrites.md`.
