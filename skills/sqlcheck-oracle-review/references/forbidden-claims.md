# Forbidden claims (Class C boundaries + Class D — OUT_OF_SCOPE)

SQLCheck has no database connection: no execution plan, no index metadata, no
statistics, no cardinality, no actual runtime measurement. A coding agent (or
a future prompt/runtime change) must never let the system claim otherwise.

## Already enforced today, independent of this catalog

`backend/app/config/app.yaml`'s `ai_guard.forbidden_phrases` strips any AI
response containing phrases like `"Full Table Scan"`, `"全表掃描"`,
`"索引失效"`, `"已使用索引"`, `"未使用索引"`, `"改善後 COST"` (see that file for
the full list). This mechanism already existed before Phase 1 and this
catalog does not change it — the catalog documents *why* each of these is
forbidden and ties it to a pattern id, it does not re-implement the guard.

## Class D — OUT_OF_SCOPE patterns and what they forbid

| Catalog id | Forbidden claim(s) | Why SQLCheck cannot know |
|---|---|---|
| `INDEX_ADVISORY` | index existence, index used/not used, index invalid, CREATE INDEX / covering index / column-order recommendations | No connection to Oracle Data Dictionary |
| `EXECUTION_PLAN_CLAIM` | "the execution plan shows..." | No `EXPLAIN PLAN` access |
| `FULL_TABLE_SCAN_CLAIM` | Full Table Scan / 全表掃描 claims | Only observable from a real execution plan |
| `CARDINALITY_SELECTIVITY_DISTRIBUTION` | cardinality, selectivity, data distribution, Oracle statistics | No `DBA_TABLES` / `DBA_TAB_COLUMNS` access |
| `ACTUAL_RUNTIME_IMPROVEMENT_CLAIM` | "tested", "verified", "measured X% faster" | SQL is never actually executed; `estimated_improvement_pct` is a rough heuristic for human reference only — never fed back into 改善指數 / 改善潛力 |
| `POST_REWRITE_ORACLE_COST_CLAIM` | a specific post-rewrite Oracle COST number | COST is an optimizer output requiring real execution |
| `PARTITION_RECOMMENDATION` | partition strategy suggestions | Physical design decision requiring central DBA / infrastructure context |
| `PHYSICAL_STORAGE_AND_HOST_TUNING` | storage parameter or host resource (CPU/memory/I/O) tuning | Same — central infrastructure responsibility, no host access |

## The Oracle/DBA action boundary (see `project-boundaries.md`)

Never imply SQLCheck can, or that the user should through SQLCheck, directly
`CREATE INDEX`, `ALTER INDEX`, `REBUILD INDEX`, `PARTITION TABLE`,
`ANALYZE TABLE`, or change a DB/host parameter.

## For a coding agent working on this codebase

If you are asked to make Gemma's output "more confident" or "more specific"
about performance, and doing so would require claiming any of the above,
that request conflicts with this skill — say so and propose an ADVICE_ONLY or
OUT_OF_SCOPE framing instead of quietly complying.
