# Awesome Copilot `sql-optimization` skill — applicability to SQLCheck

Source reviewed: `github/awesome-copilot`, `skills/sql-optimization/SKILL.md`
(single file; no `references/` subfolder). It is treated as **generic SQL
optimization knowledge**, not as an Oracle authority, not as a compliance
source, and not as evidence that any of its recommended rewrites are safe to
apply automatically — see
`skills/sqlcheck-oracle-review/references/project-boundaries.md`.

The source document's own methodology is Identify → Analyze → Optimize →
Test → Monitor → Iterate, against a live database the assistant can query
directly. It states its rewrites (subquery→JOIN, correlated subquery→window
function, OR→UNION, etc.) as universally applicable improvements with **no
equivalence caveats or correctness warnings** — this is exactly why SQLCheck
needs its own governance layer instead of adopting the source verbatim.

Every row below maps to a `backend/app/knowledge/pattern_catalog.yaml` entry;
that file is the authoritative rationale, this table is the index.

## Query rewriting patterns

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| Subquery → JOIN conversion | Advice only | Yes | B (`IN_SUBQUERY_TO_EXISTS` covers IN/EXISTS side; general subquery→JOIN has no dedicated catalog id beyond `NOT_IN_SUBQUERY_TO_NOT_EXISTS`) | Duplicate rows if joined table isn't 1:1; NULL semantics differ for NOT IN | Advice only | `complexity_flags: not_in_subquery` |
| Correlated subquery → window functions | Advice only, and blocked at candidate stage | Yes | B (`CORRELATED_SUBQUERY_TO_JOIN_OR_WINDOW`) | PARTITION BY/ORDER BY NULL-grouping and tie-break may not match original correlation | Advice only; already in `ai_gate.candidate_forbidden_complexity_flags` (`correlated_subquery`) so no full-rewrite candidate is even generated | `complexity_flags: correlated_subquery`; `app.yaml ai_gate.candidate_forbidden_complexity_flags` |
| OR condition → UNION / UNION ALL | Advice only (cross-column); verified rewrite exists for the same-column special case | Yes | B (`OR_CROSS_COLUMN_TO_UNION_ALL`) for cross-column; **A** (`OR_SAME_COLUMN_TO_IN`) for same-column OR→IN, which is a *different* transform | Row duplication (UNION ALL) or dedup cost/semantics change (UNION) if branches overlap | Advice only for the general case; same-column OR→IN is already a proven, tested rewrite | `rules.yaml` R006; `rewrite_rules.py::_rule_or_eq_to_in` |

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
| INNER vs LEFT/RIGHT JOIN type choice | Advice only | Yes | B (`LEFT_JOIN_TO_INNER_JOIN`) | **Unsafe for automatic rewrite**: silently drops main-table rows with no matching side row | Advice only; `_revalidate_suggested_sql`'s `join_sides` structural comparison already rejects any full-rewrite that changes JOIN type | `complexity_flags: outer_join`; `ai_service._revalidate_suggested_sql` (`join_sides`) |
| Filtering conditions moved into JOIN vs WHERE | Advice only | Yes | B (`JOIN_CONDITION_PLACEMENT` concept folded into general OUTER JOIN caution — no separate catalog id yet; candidate to add) | Changes which outer-side rows survive for OUTER JOIN; safe for INNER JOIN | Advice only for OUTER JOIN; candidate for a dedicated catalog entry in a future phase | none yet |

## Pagination strategies

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| Cursor-based / ID-based pagination | Not supported | Yes (concept) | Informational only, not currently a catalog entry (candidate to add as Class B if a detector is built) | Needs a stable unique monotonic sort key; also an application-layer change beyond the submitted SQL text | Advice only if ever added; do not treat as SQL-text-verifiable | none |

## Data access patterns

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| Explicit column selection (avoid `SELECT *`) | Already supported (informational) | Yes | **C** (`SELECT_STAR`) | None — but "faster" is not provable from SQL text alone | Informational only | `complexity_flags: select_star` |
| `EXISTS` instead of `IN` for subqueries | Advice only | Yes | B (`IN_SUBQUERY_TO_EXISTS`, and `NOT_IN_SUBQUERY_TO_NOT_EXISTS` for the NOT IN case) | NOT IN + possible NULL in subquery = zero rows ever (three-valued logic); DISTINCT/set-op subqueries can also differ | Advice only | `complexity_flags: not_in_subquery` |
| Conditional aggregation (CASE WHEN) to replace multiple queries | Advice only | Yes | B (`CONDITIONAL_AGGREGATION_CASE_WHEN` — candidate to add; folded conceptually under `GROUP_BY_STRUCTURAL_REWRITE` today) | Requires knowing the original multiple queries agreed on filters/timing, which SQLCheck cannot see from one submitted statement | Advice only | none |
| Batch INSERT over row-by-row | Not supported, and must not be | Yes (concept) | **D** — out of scope (application/transaction redesign, not a single-statement rewrite) | N/A | Out of scope | none |

## Query structure optimization

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| Function call avoidance in WHERE clauses | Already supported (advice) | Yes | B (`PREDICATE_FUNCTION_GENERIC`; specific proven forms are **A**: `SUBSTR_EQ_TO_LIKE`, `TRUNC_EQ_TO_RANGE`, `NVL_EQ_TO_OR_IS_NULL`) | Blanket function removal is a classic semantic trap (`UPPER_CASE_FOLD_REMOVAL`) | Advice only except the three proven SUBSTR/TRUNC/NVL forms | `rules.yaml` R005; `rewrite_rules.py` |
| Early filtering in WHERE clauses | Not currently a catalog entry | Yes (concept) | Candidate — likely **C** (informational; too generic to verify per-case) | None specific | Candidate to add as informational only | none |
| Temporary table for complex multi-step calculations | Already supported (informational) | Yes | **C** (`LARGE_RESULT_SET_NO_LIMIT` is a related but distinct informational entry; a dedicated `TEMP_TABLE_FOR_COMPLEX_CALC` id is a candidate to add) | None specific; readability suggestion only | Informational only | none |

## Performance monitoring

| External pattern | SQLCheck support | Oracle applicable | Classification | Semantic risk | Recommendation | Related rule/flag |
|---|---|---|---|---|---|---|
| Execution plan examination | Not supported, and must not be | Yes (concept) | **D** (`EXECUTION_PLAN_CLAIM`, `FULL_TABLE_SCAN_CLAIM`) | N/A — SQLCheck has no plan access | Out of scope | `app.yaml ai_guard.forbidden_phrases` |
| Slow query log analysis (MySQL-specific) | Not applicable | **No** (MySQL, not Oracle) | **D** (`MONITORING_AND_PROFILING` — candidate to add; not yet in catalog) | N/A | Out of scope / not applicable to Oracle | none |
| DB-specific monitoring views (`pg_stat_statements`, `sys.dm_exec_query_stats`) | Not applicable | **No** (PostgreSQL/SQL Server, not Oracle) | **D** | N/A | Out of scope / not applicable to Oracle | none |

## Summary

- **Already supported** (as informational or advice, with existing rule/flag
  linkage): function-avoidance-in-WHERE (partially proven), SELECT *,
  EXISTS-vs-IN family, temp-table guidance, LEFT/RIGHT JOIN caution.
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
- **Out of scope** (Class D): all index advisory, execution plan / FTS /
  cardinality / statistics / actual-runtime / post-rewrite-COST claims,
  partition and physical/host tuning, batch-DML redesign, and
  non-Oracle-specific monitoring tooling.
- **Unsafe for automatic rewrite** even where SQLCheck does offer advice:
  LEFT JOIN→INNER JOIN, DISTINCT removal, NOT IN→NOT EXISTS, OR→UNION,
  correlated subquery→window function — every one of these has a documented
  semantic trap in `skills/sqlcheck-oracle-review/references/advice-only-patterns.md`.
- **Verified rewrite** (Class A, proven and tested today): SUBSTR equality→
  LIKE/range, TRUNC equality→range, NVL equality→conditional, same-column
  OR→IN. These are the *only* patterns from either the external skill or
  SQLCheck's own history that meet the bar for automatic-rewrite-eligible
  status — and even they are not wired to automatic application in this
  Phase (see `project-boundaries.md`).
