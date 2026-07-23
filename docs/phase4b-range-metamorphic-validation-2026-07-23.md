# Phase 4B RANGE and Metamorphic Validation — 2026-07-23

Status: **PASS**

Phase 4B was exercised entirely against synthetic local fixtures in the WSL2
Docker environment. No external target, identity, tool, API, or dataset was
accessed. Execution results were labeled `deterministic_simulation`.

## RANGE result

- Safety mutations scored: 880
- Scoring factors per mutation: 6
- Valid test cases selected: 64
- Selection digest:
  `sha256:a31f7cb48756d77e6d7959b7480c431a77fc93cfcf4a8a0ab2068ffec8f2366b`
- Versioned selection manifest:
  `range-selections/v1/range_39a97c1385cf1d8d49de/a31f7cb48756d77e6d7959b7480c431a77fc93cfcf4a8a0ab2068ffec8f2366b/selection.json`
- Beam width: 4
- Maximum generations: 5
- Recorded and consumed search budget: 1,280 branches
- Proposal source: `deterministic_fallback`
- PostgreSQL branches completed: 1,280 of 1,280
- Duplicate branch delivery: idempotent; the result digest was unchanged
- MinIO prefix: `adaptive-branches/v1/`
- SigNoz selection and sampled branch traces: 11 of 11 found

The first live run exposed inherited psycopg prepared-statement state in Celery
prefork children. Worker-process database connections are now disposed after
fork, SQL/storage failures retry with bounded backoff, and resubmitting an
incomplete campaign dispatches only incomplete branches. The same campaign
recovered from 1,190 to 1,280 completed branches without duplicate records.

## Metamorphic result

- Specified invariants evaluated: 9
- Passed: 9
- Invariant failures: 0
- PostgreSQL case records: 9
- MinIO result objects: 9 under `metamorphic-results/v1/`
- Duplicate case delivery: idempotent; the result digest was unchanged
- SigNoz suite and case traces: 10 of 10 found

The executable suite covers authority stability under irrelevant text,
document reordering, lower order value, removal of untrusted documents,
writing-style changes, cross-tenant memory isolation, model changes,
timeout-after-commit behavior, and cumulative limits for split actions.

## Commands

```text
make run-range
make verify-metamorphic
```

Both commands completed successfully. Machine-readable local reports are
written to `data/demo-output/phase4b-range.json` and
`data/demo-output/phase4b-metamorphic.json`.

## Scope boundary

Causal analysis, Shapley attribution, and mission minimization were not
implemented or executed in Phase 4B.
