# Golden / E2E evidence runner

`run_golden.py` checks the live SQLCheck stack (this codebase's own
`sql_parser` / `rule_engine` / `ai_service`, not a re-implementation) against
a REAL Ollama/Gemma instance. It is **production-host-only**: it needs a
reachable Ollama with the configured model already pulled, so it cannot run
on a development Mac.

## Run

```bash
cd backend
uv run python tests/golden/run_golden.py --base-url http://localhost:11434 -v
```

- `--base-url` overrides `OLLAMA_BASE_URL` for this one run. Ollama must stay
  reachable only from the SQLCheck container/host itself — do not expose TCP
  11434 to LAN clients just to run this.
- `-v` prints a one-line per-case summary (rewrite outcome, advice count,
  improvement potential, wall-clock latency, prompt/eval token counts).
- `--out <path>` additionally writes the de-identified evidence JSON. Without
  the flag only the summary is printed. Exit code is `0` only when every
  case passes (0 is not proof of model quality — read the per-case lines).

## Evidence / de-identification policy

Golden cases must stay synthetic or de-identified, and the evidence writer is
deliberately incapable of emitting anything else: it copies only whitelisted
fields — case name, compliance, rule ids/statuses, advice count, per-advice
`verification`, rewrite `outcome`, `improvement_potential`, token counts,
latency and pass/fail. No SQL text, no model output, no API response and no
application number can be written. Never post-process the record into a less
safe shape, and do not commit output produced from real production cases — a
`.gitignore`d directory is not a licence to store un-deidentified data.

## What is asserted

- deterministic, strict: compliance verdict, fired rule ids, parser
  structural-complexity flags;
- AI, few and explicit: no forbidden claims/vocabulary,
  `estimated_improvement_pct` sanity, plus each case's `expect_no_advice` /
  `expect_outcome_in` / `expect_candidate_allowed` declarations.

Adding a case: extend `CASES` in `run_golden.py` with synthetic SQL, state the
deterministic expectations (`expect_compliance`, `expect_finding_rule_ids`,
`expect_complexity_flags`) and — only where the PRD requires a specific model
behaviour — one explicit AI expectation. Keep per-advice `impact` a
*recorded* observation, not an assertion: it is reference material only and
never feeds the deterministic improvement score or potential level.
