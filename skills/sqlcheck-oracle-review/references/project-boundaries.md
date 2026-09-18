# Project boundaries

## Authority order

```
正式中心規範
    ↓
Deterministic Rule Engine   (backend/app/services/rule_engine.py, backend/app/config/rules.yaml)
    ↓
Deterministic Rewrite Rules (backend/app/services/rewrite_rules.py)
    ↓
SQLCheck Pattern Catalog    (backend/app/knowledge/pattern_catalog.yaml)
    ↓
Gemma 4 31B
```

Gemma is never the compliance authority and never the SQL semantic-equivalence
authority. It explains findings in plain language and may draft a suggested
rewrite; whether that rewrite is *true* is decided by
`rewrite_rules.py::verify_fragment` / `verify_predicate_changes` and by
`ai_service.py::_revalidate_suggested_sql`'s structural comparison — never by
asking the model again, and never by this catalog alone.

The order says who decides a runtime outcome; it does not mean the catalog
must certify whatever a runtime rule does. The catalog never overrides
`rewrite_rules.py` at runtime, but it also never classifies a runtime rule
above what that rule actually proves. When a runtime rule relies on a
precondition it does not check or accepts more than governance authorizes,
the catalog classifies it lower or narrows the authorized form/boundary, and
records a `runtime_gap`. The gap is closed in `rewrite_rules.py` by a
correctness PR, not by editing the catalog — as the 2026-09-18 Runtime
Correctness fix did for TRUNC, NVL, SUBSTR's prefix-range form and OR→IN
beyond 1000 values. The runtime now converges to the catalog, never the
other way round.

## Compliance rules ≠ generic optimization knowledge

- **Compliance** (BLOCK / NOTICE / PASS / REVIEW) comes only from
  `backend/app/config/rules.yaml` and `important_tables.yaml`, and only when
  those files were populated from an actual authoritative source: 管理要點、
  正式文件、會議決議、正式通知. `rule_engine.py` is the only judge (PRD §13.1).
- **Optimization knowledge** (this catalog) is generic SQL engineering
  judgment — including everything drawn from the external
  `github/awesome-copilot` sql-optimization skill. It is informative, not
  regulatory. A pattern being ADVICE_ONLY or even VERIFIED_REWRITE says
  nothing about compliance status, and a pattern's classification must never
  be used to argue a compliance rule should change.
- Concretely: `github/awesome-copilot`'s SKILL.md calls `SELECT *` bad
  practice with no caveats. SQLCheck classifies `SELECT_STAR` as
  INFORMATIONAL — worth a note — and it must never become "不符合中心規範."
  See `docs/sql-optimization-skill-applicability.md` for every pattern's
  disposition.

## Oracle / DBA boundary

SQLCheck is a **local-tax-office SQL usage governance tool**, not central
Oracle infrastructure DBA tooling. It must never imply it can, or that a user
should, directly:

- `CREATE INDEX` / `ALTER INDEX` / `REBUILD INDEX`
- `PARTITION TABLE` / partition strategy design
- `ANALYZE TABLE` / manage Oracle statistics
- change a DB parameter or Oracle host resource (memory/CPU/I/O)

These are Class D (OUT_OF_SCOPE) in the catalog and belong to central DBA /
infrastructure responsibility, or require a real test-environment measurement
SQLCheck cannot perform.

## What this Phase explicitly did NOT change

Phase 1 (SQLCheck Oracle Knowledge v1) is a knowledge-layer-only PR. None of
the following changed, and none of the following is authorized by adding to
this skill or the catalog without a separate, explicitly-scoped PR:

- `ai_service.py` runtime prompt assembly or gating (`_compute_gates`,
  `candidate_forbidden_complexity_flags`, `_revalidate_suggested_sql`)
- `backend/app/prompts/sql_review_zh_tw.txt`
- Ollama parameters: `num_ctx`, `num_predict`, `think` default, `Semaphore(1)`,
  timeout
- `improvement_score.py` / `rules.yaml: improvement_score` (指數) or
  `ai_service.improvement_potential` (改善潛力)
- Frontend
- Firewall / deploy behavior
- Any new Oracle connection, application DB, vector DB, embeddings, RAG,
  LangChain/LangGraph, or fine-tuning

A future "Pattern Selector" phase is what would let the Runtime read this
catalog at request time. Nothing in this skill authorizes writing that
selector.
