# Phase 2 live SigNoz alerts and WATCHTOWER validation — 2026-07-22

This record covers Phase 2 only. It preserves the original ORBITAL Sigma
specification and uses synthetic, project-owned telemetry on the native Azure
Ubuntu VM.

## Authoritative command

`make verify-alerts` passed on `orbital-sigma-vm`. The target reconciled the
five dashboards and twelve alert rules from repository definitions, recreated
OBI, paused it as a controlled fault, emitted the critical local signals, and
restored OBI through a shell trap.

All eight critical rules produced fresh `firing` transitions in SigNoz alert
history:

| Alert | SigNoz rule ID | Supporting fixture trace |
| --- | --- | --- |
| ORBITAL Uncertified Agent Execution | `019f8a3e-7bca-785d-b33e-03c0b7cdcbc4` | `1829cc5f1bd7c49d63b50433e409dd64` |
| ORBITAL Artifact Drift | `019f8a3e-7c35-75d4-bc71-8b2c3efe0a6a` | `79aaedc5ba2f24071f109957d70b1bb2` |
| ORBITAL Missing Authorization | `019f8a3e-7c9f-726b-acb4-5ee24be380ca` | `3b8c8b03587c9f2445b767a6c0552bf3` |
| ORBITAL Evidence Mismatch | `019f8a3e-7d02-795d-8339-75d7cb67c504` | `5a8e81142ecf9a7a2a9a0f5936c21a5f` |
| ORBITAL Unsafe External Effect | `019f8a3e-7d56-7628-8374-aae028f4c696` | `29a97ae5511dd4294da308d0a4d29111` |
| ORBITAL Canary Regression | `019f8a3e-7df4-7699-96ea-f9cba44b3de3` | `9cddf791b171c54cad6779523f4c6877` |
| ORBITAL Policy Bundle Mismatch | `019f8a3e-7eae-75b7-8271-4b49d789e299` | `9a3d4eab7c73d97fd9f2679dfde06477` |
| ORBITAL OBI Sensor Loss | `019f8a3e-7f35-7718-8c71-ee32271e0ad5` | `e41fcf3d4ee8b3bf78a123b5aba5df0f` |

The fixture spans carry
`orbital.execution.mode=controlled_fault_injection` and
`orbital.risk.class=critical`; the latter keeps these safety signals through
collector tail sampling. The metric alerts use real OTLP gauges and retain the
correlated trace ID as a metric attribute.

## Signed webhook and rollback proof

SigNoz delivered through notification channel `orbital-watchtower-local` to
the local relay. The relay authenticated SigNoz with Basic authentication,
normalized only allowlisted fields, generated a canonical HMAC-SHA256
signature, and forwarded the event to WATCHTOWER.

- Suspended certificate: `ORB-2026-7836C9`
- Suspended candidate: `candidate-v3-phase2-canary`
- Candidate traffic after rollback: `0%`
- Restored baseline: `candidate-v2-fixed-baseline`
- Restored baseline certificate: `ORB-2026-C393D8`
- Restored baseline traffic: `100%`
- WATCHTOWER rollback trace: `08a56ed202f7cd69be58654be0309a75`

Replaying the exact signed webhook incremented its duplicate count to two and
returned both `duplicate_delivery=true` and `idempotent_replay=true`. It did
not create a second rollback. SigNoz contains `signoz.webhook.accept`,
`watchtower.rollback`, `certificate.suspend`, and `rollout.change` spans for
the suspended certificate.

Persisted WATCHTOWER events include links to the triggering SigNoz trace, the
trace query surface, the alert-history page, and the WATCHTOWER rollback
trace. Certificate suspension and webhook-delivery records are returned by
`GET /v1/runtime/status`.

## Regression and provisioning results

- `make verify`: passed in 78 seconds.
- Pytest: 17 passed.
- Ruff: passed.
- ESLint: passed.
- TypeScript `tsc --noEmit`: passed.
- Next.js production build: passed.
- Docker Compose configuration: passed.
- OpenTelemetry Collector validation: passed.
- Complete hero workflow: passed in 40 seconds.
- Two consecutive provisioning runs each reported exactly five dashboards and
  twelve alerts; no duplicate assets were created.

The machine must be deallocated immediately after this record and the Phase 2
checkpoint are pushed. Phase 3 is not authorized by this validation.
