# Safe rewrites (Class A — VERIFIED_REWRITE)

These are the only patterns where SQLCheck's governance treats a rewrite as
proven for every input, and the only class a future Pattern Selector could
ever consider for automatic application. No selector exists yet.

A Class A entry needs a proof in `backend/app/services/rewrite_rules.py`
that does **not** rest on an unchecked precondition (column datatype, a bind
value having no time component, collation, …), and the rewritten SQL must
be executable on Oracle (e.g. at most 1000 expressions in one IN list).

| Catalog id | rewrite_rules.py rule | Authorized form |
|---|---|---|
| `SUBSTR_EQ_TO_LIKE` | `substr_eq_to_like` | `SUBSTR(col,p,n)='v'` ⇔ `col LIKE '<p-1 underscores>v%'` (len(v)=n, no wildcard in v, quotes doubled). Canonical LIKE form **only**. |
| `OR_SAME_COLUMN_TO_IN` | `or_eq_to_in` | `col=a OR col=b [...]` (same column, all equality) ⇔ `col IN (a,b,...)`, **1–1000 values only** (`authorized_boundary`: an Oracle 11g IN list holds at most 1000 expressions) |

To read the equivalence argument, read the rule function's docstring in
`rewrite_rules.py`. This file only indexes which catalog id maps to which
runtime rule.

## Runtime and governance agree (2026-09-18, Runtime Correctness v1)

Since 2026-09-18 the runtime certifies exactly the two forms above; there
is no open `runtime_gap`:

- TRUNC equality → range and NVL equality → plain comparison are no longer
  runtime rules. Their equivalence needs facts SQL text cannot show (a
  time-free right-hand side and a DATE column; a non-CHAR column), so such
  fragments are `unverified` and full rewrites that change them are
  rejected. Both stay ADVICE_ONLY.
- SUBSTR no longer accepts the p=1 prefix-range form
  `col >= 'v' AND col < next(v)` (collation-dependent); a fragment written
  that way is corrected to the canonical LIKE, a full rewrite is rejected.
- OR→IN refuses chains longer than 1000 values through an explicit count
  guard (`rewrite_rules.ORACLE_IN_LIST_MAX_EXPRESSIONS`), and OR chains are
  flattened iteratively, so the Python recursion limit plays no part.

## Tests that keep this honest

- `tests/test_pattern_catalog.py` checks both directions: every catalog
  `rewrite_rule_id` exists in `rewrite_rules._RULES`, and every rule in
  `_RULES` has exactly one catalog entry (of any class). A runtime rule
  classified below VERIFIED_REWRITE must declare a `runtime_gap`.
- Synthetic probes (SUBSTR range, TRUNC, NVL, a 1001-value IN list) are run
  through the real `verify_fragment`; a pattern must declare a
  `runtime_gap` exactly when the runtime certifies its probe.
- An IN-producing VERIFIED_REWRITE must declare `max_in_list_expressions`
  ≤ 1000, and the runtime limit may not exceed it.
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
