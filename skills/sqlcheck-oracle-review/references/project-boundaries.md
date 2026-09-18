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

## Pattern Selector + Compact Context boundary

The Runtime has two narrowly-scoped catalog consumers:

1. `pattern_selector.py` maps **already-existing deterministic facts** to
   catalog ids.
   - **exact** — the catalog's specific detector matched (rule id, rewrite
     rule, parser complexity flag, or the existing many-tables threshold).
   - **family_signal** — only a broader family signal matched. This is
     ambiguous by definition and is never a confirmed pattern.
2. `context_adapter.py` may turn only `exact` matches into a small
   `knowledge_context` list sent to Gemma.

Compact-context safety rules are hard boundaries, not prompt suggestions:

- family_signal is never injected;
- OUT_OF_SCOPE is never injected even if a future detector is added;
- context is filtered to the one representative statement sent to Gemma;
- priority is VERIFIED_REWRITE → ADVICE_ONLY → INFORMATIONAL;
- top-N and total-character limits are enforced before payload construction;
- only static catalog `model_guidance_zh_tw` is injected — never SQL,
  literals, table names, findings text, model output, or external-source prose;
- missing/drifted catalog guidance causes empty/fewer context, not a wider
  guess;
- selector/context failures are fail-open for AI availability.

The following remain explicitly out of scope unless a later, separately
reviewed PR authorizes them:

- letting selector/context output change `_compute_gates`, compliance,
  rewrite verification, improvement score, or improvement-potential semantics
- treating ADVICE_ONLY as verified or letting Gemma override deterministic
  rewrite validation
- injecting family signals or OUT_OF_SCOPE catalog content
- dynamically fetching external skill/web content at request time
- Ollama parameters: `num_ctx`, `num_predict`, `think` default,
  `Semaphore(1)`, timeout
- Frontend / API response schema for pattern selection
- Firewall / deploy behavior
- Any new Oracle connection, application DB, vector DB, embeddings, RAG,
  LangChain/LangGraph, or fine-tuning

A `family_signal` must first gain a specific deterministic detector (and the
catalog entry must be updated) before it can ever be treated as matched model
knowledge.
