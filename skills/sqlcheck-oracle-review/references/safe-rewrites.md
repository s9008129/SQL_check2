# Safe rewrites (Class A — VERIFIED_REWRITE)

These are the only patterns where SQLCheck may ever show a rewrite as
"verified"/"corrected" rather than a hedged suggestion, and the only class a
future Pattern Selector could ever wire to automatic application — this
Phase does not wire anything.

Every one of these is implemented and tested in
`backend/app/services/rewrite_rules.py`, not merely declared in the catalog.
A catalog entry with `classification: VERIFIED_REWRITE` but no matching
`rewrite_rules.py` function is a bug — `tests/test_pattern_catalog.py::test_rewrite_rule_ids_reference_known_rewrite_rules_module_rules`
catches this.

| Catalog id | rewrite_rules.py rule | What it proves |
|---|---|---|
| `SUBSTR_EQ_TO_LIKE` | `substr_eq_to_like` | `SUBSTR(col,p,n)='v'` ⇔ `col LIKE '<p-1 underscores>v%'` (length/wildcard-checked) |
| `TRUNC_EQ_TO_RANGE` | `trunc_eq_to_range` | `TRUNC(col)=X` ⇔ `col>=X AND col<X+1`, **with the stated assumption that X has no time component** |
| `NVL_EQ_TO_OR_IS_NULL` | `nvl_eq` | `NVL(col,'a')='b'` ⇔ `(col='b' OR col IS NULL)` when a==b, else `col='b'` |
| `OR_SAME_COLUMN_TO_IN` | `or_eq_to_in` | `col=a OR col=b [...]` (same column, all equality) ⇔ `col IN (a,b,...)` |

To read the equivalence argument for any of these, read the rule function's
docstring in `rewrite_rules.py` — that is the proof, not this file. This file
only indexes which catalog id maps to which proof.

## Do NOT add a pattern here just because it "looks obviously safe"

The 2026-09-17 incident that created `rewrite_rules.py` (see its module
docstring) was exactly this: the model proposed
`SUBSTR(MANAGE_CD,6,3)='551'` → `MANAGE_CD LIKE '__%551%'`, which is *not*
equivalent (matches "551" anywhere after position 2, not "551" specifically
at position 6). "The model said it's fine" and "an external optimization
skill calls this pattern safe" are never sufficient evidence — only a
deterministic Python proof with its own positive/negative/boundary tests is.
If you cannot write that proof, the pattern belongs in
`advice-only-patterns.md`, not here.
