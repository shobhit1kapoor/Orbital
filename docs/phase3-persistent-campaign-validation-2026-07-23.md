# Phase 3 Persistent Campaign Infrastructure Validation — 2026-07-23

## Verdict

**PASS — PHASE 3 COMPLETE**

Phase 3 is accepted based on implementation commit `a7b492b` and the
subsequent verified repository audit at `6110895`. This report formalizes
evidence already produced by that audit. No Phase 3 command was rerun, no
backend behavior was extended, and no implementation file was modified while
creating this report.

The validation used only synthetic, project-owned fixtures and the
authoritative native Ubuntu Azure VM. OBI observed only ORBITAL-owned local
containers.

## Accepted implementation

The Phase 3 checkpoint provides:

- PostgreSQL persistence for campaigns, replay jobs, mission capsules, storage
  objects, campaign events, effect receipts, retries, timings, results, and
  SigNoz trace references
- deterministic capsule identity, content hashing, duplicate prevention, and
  corrupted-capsule rejection
- versioned and checksummed MinIO objects for mission capsules, mutations,
  replay branches, minimized regressions, certificate bundles, and campaign
  exports
- Redis-backed Celery group/chord replay execution with late acknowledgement,
  stable task identity, retry safety, and idempotent result persistence
- the `CREATED`, `QUEUED`, `RUNNING`, `PAUSED`, `PARTIAL`, `FAILED`,
  `COMPLETED`, and `CANCELLED` campaign states
- pause, resume, retry, cancellation, recovery, and duplicate-delivery
  controls
- reconnectable, database-backed campaign SSE using event cursors and
  `Last-Event-ID`
- explicit unavailable-storage and `UNKNOWN` reporting
- OpenTelemetry traces, metrics, and logs for the persistent campaign
  lifecycle
- the Persistent Campaigns SigNoz dashboard and idempotent repository-driven
  dashboard and alert provisioning
- `make campaign`, `make pause-campaign`, `make resume-campaign`,
  `make recover-campaign`, and `make verify-campaign`

## Authoritative campaign acceptance

`make verify-campaign` passed against the unchanged `a7b492b`
implementation.

| Evidence | Result |
| --- | --- |
| Campaign ID | `campaign_f667ace1b18c029d272d` |
| Final state | `COMPLETED` |
| Replay jobs | 24 total, 24 completed, 0 failed |
| Idempotent retries | 2 |
| Cancelled jobs | 0 |
| Capsule records | 120 |
| Effect receipts | 24 |
| Persisted campaign rows | 2, including prior preserved audit state |
| Storage-object metadata rows | 2,305 |
| Verified MinIO objects for the campaign dataset | 2,274 |
| Campaign events | 65 |
| Reconnected SSE events | 65 |
| SigNoz replay traces | 24 |
| Verification duration reported by the verifier | 32.356 seconds |

The campaign honestly labels replay outcomes as
`deterministic_simulation`. All capsules and mutation fixtures are synthetic
and local.

## Persistence evidence

Representative versioned MinIO paths verified by the acceptance workflow:

- `campaign-exports/v1/campaign_f667ace1b18c029d272d/aee3e27357300b63c226269b1828d81dfcefedefe1e9e2ea0392bb7d6c6390f8/campaign.json`
- `mission-capsules/v1/cap_076375cdc6d4604c461e/105116a230efdf7bff4ee5711f0f9dace429023e122326da8a21b57d7d540eaa/manifest.json`
- `mission-capsules/v1/cap_076375cdc6d4604c461e/2a68d1dba65135a3e35155c760e5eaa8bbd7e1c69aad49f64a11f95c30ef99c9/privacy-map.json`
- `mission-capsules/v1/cap_076375cdc6d4604c461e/40f34433cb69d97fe26f3f63d566bc6f8f2035c448f2662b582a2005059a848c/reference-telemetry.json`
- `mission-capsules/v1/cap_076375cdc6d4604c461e/4aa4e699a3a5b0d045e4d941e279c37c43e0c1d0c7c3be55bf857a818239944b/prompt-snapshot.json`
- `mission-capsules/v1/cap_076375cdc6d4604c461e/636831adee7a93424f4c4d3e1cb771e35404fe49f0f5fb787fc073f6d96cbdfa/database-fixtures.json`
- `mission-capsules/v1/cap_076375cdc6d4604c461e/740c940e506a6685fbdc16ef70bc5487c402b6363f2ba5e53d04617bdf97f31e/policy-bundle.json`
- `mission-capsules/v1/cap_076375cdc6d4604c461e/75ace8b4de004a51390c9f66cedad3a630e7dd02927d489110a457de5b959e0d/expected-invariants.json`

Object metadata and payload checksums matched. The acceptance workflow also
confirmed that unavailable MinIO state was surfaced rather than silently
treated as successful storage.

## Recovery and idempotency evidence

The live acceptance workflow exercised and passed:

1. Campaign pause and resume
2. Redis restart
3. Celery worker restart
4. Replay FastAPI restart
5. PostgreSQL restart
6. MinIO unavailability and restart
7. Campaign recovery
8. Duplicate task delivery
9. SSE reconnection from the stored event cursor

The 13 Phase 3 tests additionally cover duplicate campaign submission, worker
crash, partial chord completion, task timeout, cancellation, checksum
mismatch, and corrupted capsule rejection. Retries retained stable mission,
replay, trace, candidate, and mutation identities and did not duplicate replay
results or effect receipts.

## SigNoz trace evidence

The verifier found all 24 replay traces in SigNoz:

```text
85441c120be10af32353bc94628bb358
8012cc64689860761a5487813f21c77d
7846c93a69b39432686f7402468ce2fd
6a27acb5eeb7f76e25f3e5bd3864dbe3
73d66207a8da6f80f07745c0b930a03a
b3fc6aeea1d63d7d23a31965534f43f4
1485861ed5889395c77e3b5b4182fac5
ac79fdc9fcfb7893a7bd88a439621668
46d1536bb7f815eeff4033f76e13b7b5
9462dafe3f585a5377bcdd6b631d91e1
c701a0a3bdc9f3c813ce755ef1dfcc96
5817a8b415ff946be87dea0f1c7d16f1
b5e54ed86609c9bc14bc815b113d1154
96ca122e9bfa66a1e11dd2af0a714495
8667b6a9344668117c7d8f62bf54f607
b585ce1e6c64d9c8364e826e288fe50c
e15a9729a79d636cc4249d360b3f542f
881f27cd8cfd3088e38463ed532c3797
ff4f10050dc6bf9247753d32b854d3fc
d31c73ce682d34925f30fcc6a1c44476
32331d371139ba09d98f69be7bfcdd75
5ad024380ac5f372f747b4c86c424dbf
f036d1f83567e32268102da907d81f43
f80c31ef185a952eb45d5abc4fa2a03d
```

The Persistent Campaigns dashboard definition includes queue depth, campaign
completion, worker utilization, replay duration, retry rate, failed jobs,
MinIO persistence latency, and PostgreSQL write failures.

## Repository-wide regression gates

The verified audit recorded:

- `make verify`: PASS
  - Pytest: 30 passed
  - Ruff: PASS
  - ESLint: PASS
  - TypeScript: PASS
  - Next.js production build: PASS
  - Docker Compose validation: PASS
  - OpenTelemetry Collector validation: PASS
- `make verify-obi`: PASS
  - Native OBI trace: `f620f27995b67aea23b06470661dfea1`
- `make verify-alerts`: PASS
  - Eight critical SigNoz alert histories
  - Signed Watchtower webhook delivery
  - Duplicate-delivery idempotency
  - Certificate suspension, zero canary traffic, and baseline restoration
- `make hero-demo`: PASS
  - Seed, certification, and drift stages completed

## Mission Control deferral

The campaign SSE API, durable cursor semantics, reconnection behavior, and
backend counters are complete and accepted in Phase 3.

**Visualization of campaign SSE in Mission Control and additional frontend
counts for queued, running, failed, and retried jobs are explicitly deferred
to the Mission Control phase.** This frontend work is not a Phase 3 acceptance
failure and does not reopen the persistent campaign backend.

## Limitations and closure

The full ORBITAL Sigma roadmap remains authoritative. Phase 3 completion does
not claim completion of later work such as full Playwright coverage, the
1,000-mission statistical recertification campaign, complete trace-matching
asset provisioning, encryption of all object bundles, or SQLAlchemy/Alembic
adoption across every service.

After verification, WSL2 project containers were stopped without deleting
persistent volumes, the SSH tunnel was closed, and the Azure VM was
deallocated. No background verification command or project container remained
running.

Phase 3 is closed. Phase 4 was not started by this validation.
