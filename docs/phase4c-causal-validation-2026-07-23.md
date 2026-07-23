# Phase 4C Causal Analysis and Hero Minimization Validation — 2026-07-23

Status: **PASS**

Phase 4C was exercised entirely against owned synthetic fixtures in the local
WSL2 Docker environment. No external target, identity, tool, API, or dataset
was accessed. Counterfactual branches and the minimizer are labeled
`deterministic_simulation`.

## Source evidence

The analysis selected the highest-ranked reproducible refund reliability
failure from the persisted Phase 4B selection:

- Campaign: `range_39a97c1385cf1d8d49de`
- Safety mutation: `mut_8bca8eddb491fa452bee06d6`
- Source branch: `branch_c07d9b2b535948d69414`
- Source trace: `94cad57cd47f6923dbd3d6fddbeb4d72`
- Failure: `refund_declaration_authorization_mismatch`
- Phase 4B selection digest:
  `sha256:a31f7cb48756d77e6d7959b7480c431a77fc93cfcf4a8a0ab2068ffec8f2366b`

Both the selection manifest and source branch were loaded from MinIO and
verified against their stored SHA-256 digests before the causal campaign was
accepted.

## Causal result

- Analysis: `analysis_243d752c8b4c767741ec`
- Verdict: `CONFIRMED`
- Controlled intervention sets: 16
  - Baseline: 1
  - Single-factor: 5
  - Pairwise: 10
- Repeats per intervention set: 16
- Completed counterfactual branches: 256 of 256
- Recorded seeds: 16, beginning at `20260723`
- Approximate attribution samples: 64
- Bootstrap samples: 500
- Earliest causal commitment point: `prompt_compression`
- Model stochasticity estimate: `0.0`
- Finding digest:
  `sha256:1b0c064aa1953117bc476a34f28cf01d1ee354fb1cdd868a93a5d20ed1dfea73`

The fixed model parameters were `qwen3:8b`, temperature `0`, context window
`8192`, maximum output tokens `1024`, and execution mode
`deterministic_simulation`.

### Bounded attribution

| Causal factor | Contribution | 95% confidence interval |
| --- | ---: | ---: |
| `deterministic_authorization` | 0.268125 | 0.264062–0.272664 |
| `prompt_compression` | 0.241250 | 0.234836–0.247812 |
| `tool_schema_change` | 0.230625 | 0.224523–0.237187 |
| `stale_retrieval` | 0.184375 | 0.180000–0.188602 |
| `final_tool_execution` | 0.075625 | 0.073438–0.077352 |

All five single-factor estimates and all ten pairwise estimates include
bootstrap 95% confidence intervals in the persisted finding. The analysis
returns `UNKNOWN` when its Phase 4B source evidence is missing, incomplete, or
fails checksum verification; the live missing-evidence acceptance probe
confirmed this behavior.

## Persistence, recovery, and observability

PostgreSQL contains the analysis, all 256 branch records, the finding,
minimization run, and 19 reduction-attempt records. Versioned artifacts were
verified in MinIO under:

- `causal-branches/v1/`
- `causal-findings/v1/analysis_243d752c8b4c767741ec/`
- `minimization-attempts/v1/minhero_1b9cafaf3cf5026eaa71/`
- `hero-minimizations/v1/minhero_1b9cafaf3cf5026eaa71/`
- `minimized-regressions/v1/regression_bdabb8287e06b78dd74a5483/`

The initial Celery run revealed that causal tasks shared the replay worker's
default queue. A dedicated `causal` queue and worker were added. Idempotent
resubmission recovered the incomplete analysis by dispatching only the 230
missing branches after 26 had already completed. The final database count is
256 unique completed branches, with no duplicate result records or changed
digests. Explicit branch and minimization redelivery probes also preserved the
original records and digests.

The acceptance workflow found the analysis, completion, minimization, and ten
sampled branch traces in SigNoz. Primary trace references are:

- Analysis creation: `f75fb0b653eb4fdc58e17ad9e266c552`
- Chord completion: `8b38489f3712c71061a5d02e7818d8a9`
- Hero minimization: `2446813796113bdb290ad534a63bc6ff`

## Bounded hero minimizer

- Minimization: `minhero_1b9cafaf3cf5026eaa71`
- Verdict: `CONFIRMED`
- Deterministic reduction attempts: 19
- Original elements: 17
- Minimized elements: 7
- Maximum timebox: 10,800 seconds
- Measured minimizer execution: 0.000807 seconds
- Regression capsule: `regression_bdabb8287e06b78dd74a5483`
- Regression digest:
  `sha256:71115a745dd3a72dbc251f6c55de510eae0df3a6ddaa182fda7e2d1cdd7fbb3c`

The 1-minimal capsule preserves the verified failure signature and retains all
five causal factors. It contains only the required user-message fragments,
stale retrieval fixture, tool-schema fields, and relevant local environment
state. It is committed at
`missions/regressions/regression_bdabb8287e06b78dd74a5483.json` and stored in
MinIO with the same digest. No general-purpose minimization platform was
created.

## Commands and repository verification

The following commands completed successfully:

```text
make causal-analysis
make minimize-hero-failure
make verify-causal
make verify
```

`make verify-causal` confirmed PostgreSQL and MinIO persistence, SigNoz trace
availability, confidence intervals, bounded attribution, earliest commitment,
`UNKNOWN` handling, retry idempotency, and regression-capsule creation.

The final repository verification passed:

- Pytest: 65 passed
- Ruff: passed
- Mission Control ESLint: passed
- Mission Control TypeScript: passed
- Next.js production build: passed
- Docker Compose validation: passed
- OpenTelemetry Collector configuration validation: passed

Machine-readable local evidence is retained under `data/demo-output/` and is
excluded from source control.

## Scope boundary

Phase 4C implements causal analysis for the primary refund reliability failure
and one bounded hero minimizer only. Attribution is deliberately limited to 64
deterministic local samples. FRONTIER, CLEARANCE, multi-agent custody, Mission
Control work, and final submission work were not started.
