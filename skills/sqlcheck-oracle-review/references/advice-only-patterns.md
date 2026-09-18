# Advice-only patterns (Class B — ADVICE_ONLY)

These are plausible improvement directions SQLCheck cannot prove equivalent
from SQL text alone. They may be **explained** and **suggested as a
direction**; they must never be shown as a "verified" or "corrected" rewrite,
and never auto-applied. See `pattern_catalog.yaml` for each pattern's full
`rationale_zh_tw` — this file is an index of *why each one is a trap*, not a
duplicate of the catalog.

| Catalog id | Semantic trap if treated as "always safe" |
|---|---|
| `PREDICATE_FUNCTION_GENERIC` | Only the SUBSTR equality → canonical LIKE form is proven (see `safe-rewrites.md`); other functions (TRIM, TO_CHAR, custom) have their own NULL/type/format semantics that must be checked case by case |
| `TRUNC_EQ_TO_RANGE` | `TRUNC(col)=:X` → `col>=:X AND col<:X+1` only holds if `:X` has no time component; with `:X` = 10:00 the original matches nothing and the range matches 24 hours of rows. It also needs a DATE column: on a NUMBER column `TRUNC(n)=0` is `-1<n<1`, the range is `0<=n<1`. The runtime stopped deriving it on 2026-09-18 |
| `NVL_EQ_TO_OR_IS_NULL` | NVL on character data returns VARCHAR2 (nonpadded comparison), a CHAR column vs a text literal is blank-padded: `CHAR(3)` value `'b  '` makes `NVL(col,'x')='b'` false but `col='b'` true. SQLCheck cannot see column types; the runtime stopped deriving it on 2026-09-18 |
| `UPPER_CASE_FOLD_REMOVAL` | `WHERE UPPER(email)='ABC'` → `WHERE email='abc'` changes matched rows whenever real data has mixed case |
| `IMPLICIT_TYPE_CONVERSION_MIXED_QUOTING` | Inconsistent quoting across similar columns (`COLL_YR = 107` vs `LEVY_TP = '1'`) may hide an implicit type conversion SQLCheck cannot see the actual column type to confirm |
| `NOT_IN_SUBQUERY_TO_NOT_EXISTS` | `NOT IN` returns zero rows if the subquery can produce a `NULL` (three-valued logic); `NOT EXISTS` does not have this failure mode — but only matters if NULL is actually possible, which SQLCheck cannot confirm |
| `IN_SUBQUERY_TO_EXISTS` | Usually equivalent, but subqueries with `DISTINCT`, set operations, or multi-column correlation can differ; "which is faster" also depends on the optimizer (Class D) |
| `OR_CROSS_COLUMN_TO_UNION_ALL` | If a row can satisfy both OR branches, `UNION ALL` duplicates it; `UNION` avoids that but changes performance and de-dup semantics — SQLCheck cannot tell from SQL text whether the branches overlap |
| `LEFT_JOIN_TO_INNER_JOIN` | Only safe if the joined-to table is guaranteed to have a matching row; otherwise this silently drops main-table rows — a result-set change, not an optimization |
| `CORRELATED_SUBQUERY_TO_JOIN_OR_WINDOW` | `PARTITION BY`/`ORDER BY` NULL-grouping and tie-break behavior may not match the original correlated condition; this pattern is additionally blocked at the candidate stage today (`app.yaml ai_gate.candidate_forbidden_complexity_flags` includes `correlated_subquery`) |
| `DISTINCT_REMOVAL` | Safe only when the pre-DISTINCT result is already proven unique (e.g. by a JOIN key); SQLCheck has no uniqueness proof capability |
| `GROUP_BY_STRUCTURAL_REWRITE` | Splitting a concatenated `GROUP BY` key (`a\|\|b` → `a, b`) can change grouping when values overlap across the split point (`'1','23'` vs `'12','3'`) |
| `STRING_CONCAT_PREDICATE_SPLIT` | Splitting a concatenated-column literal (e.g. `'551'` for `TAX_CD\|\|SUBTAX_CD`) requires knowing each column's width — a business assumption, not something derivable from the literal |
| `LEADING_WILDCARD_LIKE` | A pattern starting with `%` or `_` has no equivalent rewrite. Narrowing to `'xxx%'` when business rules allow changes the condition, so it needs business confirmation; index suggestions are out of scope (`INDEX_ADVISORY`). Trailing wildcards are outside R004; whether they need improving depends on the actual database environment |
| `CARTESIAN_JOIN_MISSING_CONDITION` | The missing join key must come from business knowledge; SQLCheck can flag the missing condition but cannot guess which columns to join on |

If you ever find yourself about to mark one of these as `verified` in the UI
or archive, stop — that requires a `rewrite_rules.py` proof
(`safe-rewrites.md`), not a plausibility argument.
