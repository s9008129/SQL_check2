# Safe rewrites (Class A — VERIFIED_REWRITE)

These are the only patterns where SQLCheck's governance treats a rewrite as
proven for every input, and the only class a future Pattern Selector could
ever consider for automatic application. This Phase does not wire anything.

A Class A entry needs a proof in `backend/app/services/rewrite_rules.py`
that does **not** rest on an unchecked precondition (column datatype, a bind
value having no time component, collation, …). A runtime rule existing is
not enough on its own; see the runtime gaps below.

| Catalog id | rewrite_rules.py rule | Authorized form |
|---|---|---|
| `SUBSTR_EQ_TO_LIKE` | `substr_eq_to_like` | `SUBSTR(col,p,n)='v'` ⇔ `col LIKE '<p-1 underscores>v%'` (len(v)=n, no wildcard in v). Canonical LIKE form **only**. |
| `OR_SAME_COLUMN_TO_IN` | `or_eq_to_in` | `col=a OR col=b [...]` (same column, all equality) ⇔ `col IN (a,b,...)` |

To read the equivalence argument, read the rule function's docstring in
`rewrite_rules.py`. This file only indexes which catalog id maps to which
runtime rule.

## Runtime rules the catalog does NOT certify (`runtime_gap`)

`rewrite_rules.py` currently marks fragments `verified`/`corrected` for more
than governance authorizes. The catalog does not change runtime behavior; it
records each gap so a separate correctness PR can close it before Phase 2.
Until then, a future selector must not treat these as proven.

| Catalog id | Class | Gap |
|---|---|---|
| `TRUNC_EQ_TO_RANGE` | ADVICE_ONLY | `unverified_precondition`: equivalence needs the right-hand side to have no time component; the runtime only prints this as an `assumption`, never checks it. |
| `NVL_EQ_TO_OR_IS_NULL` | ADVICE_ONLY | `unverified_precondition`: NVL on character data returns VARCHAR2 (nonpadded comparison), while a CHAR column compared to a text literal is blank-padded — a `CHAR` value `'b  '` makes the two forms disagree. SQLCheck cannot see column types. |
| `SUBSTR_EQ_TO_LIKE` (prefix-range form) | form not authorized | `unauthorized_accepted_form`: for p=1 the runtime also accepts `col >= 'v' AND col < next(v)`; range comparison depends on collation, which SQLCheck does not know. |

The machine-readable version of this table is each entry's `runtime_gap`
block in `pattern_catalog.yaml`.

## Tests that keep this honest

- `tests/test_pattern_catalog.py` checks that every catalog
  `rewrite_rule_id` exists in `rewrite_rules._RULES`, and that a runtime rule
  classified below VERIFIED_REWRITE declares a `runtime_gap`.
- A VERIFIED_REWRITE entry can never carry an `unverified_precondition` gap.

## Do NOT add a pattern here just because it "looks obviously safe"

The 2026-09-17 incident that created `rewrite_rules.py` (see its module
docstring) was exactly this: the model proposed
`SUBSTR(MANAGE_CD,6,3)='551'` → `MANAGE_CD LIKE '__%551%'`, which is *not*
equivalent (matches "551" anywhere after position 2, not "551" specifically
at position 6). "The model said it's fine", "an external optimization skill
calls this pattern safe" and "rewrite_rules.py already derives it" are never
sufficient on their own — only a deterministic proof whose preconditions are
themselves checked, with positive/negative/boundary tests. If you cannot
write that proof, the pattern belongs in `advice-only-patterns.md`.
