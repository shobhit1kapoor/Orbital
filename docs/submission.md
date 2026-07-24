# Hackathon Submission Copy

## Project title

ORBITAL Σ — Autonomous Agent Flight Assurance

## Tagline

Trust what the agent does, not only what it says.

## 50-word summary

ORBITAL Σ uses SigNoz as an independent evidence plane for autonomous agents. It reconstructs missions, generates safety mutations, reconciles semantic and eBPF observations, explains failures counterfactually, measures safe authority, issues signed certificates, and automatically suspends drifted agents—while linking every decision to live traces, metrics, logs, and alerts.

## Project description

Autonomous-agent evaluation usually ends at answer quality. ORBITAL Σ treats deployment like flight certification: define the mission contract, replay representative missions, challenge authority boundaries, compare declared actions with independently observed effects, explain failures, measure the maximum safe authority, issue a signed certificate, and continuously attest the deployed artifact.

The hero scenario is a fully local refund fixture. A vulnerable MCP-like tool declares a safe `store_credit` action while calling only the project’s mock refund service for a synthetic `$900` effect. Semantic output appears successful. OBI, policy evidence, and the effect receipt reveal the mismatch. ORBITAL marks the mission `CONTRADICTED`, and SigNoz makes the complete chain inspectable.

## Problem

Output-only benchmarks cannot answer whether an agent’s tool actually performed the declared action, whether a retry duplicated an effect, whether delegated authority was laundered, or whether the deployed artifact still matches the tested artifact. Teams lack an evidence-backed way to decide how much autonomy an agent should receive.

## Solution

ORBITAL Σ combines ten working subsystems:

- ATLAS compiles mission contracts.
- PARALLAX reconciles semantic, eBPF, policy, and receipt evidence.
- GATE escrows consequential actions with short-lived signed capabilities.
- CAPSULE reconstructs deterministic missions.
- RANGE generates and ranks reliability test cases.
- Metamorphic testing enforces behavior invariants.
- FORK estimates causal contributions and minimizes the primary regression.
- FRONTIER measures safe authority across six levels.
- CLEARANCE issues deterministic Ed25519 flight certificates.
- WATCHTOWER suspends drifted artifacts and restores a certified baseline.

## Technical implementation

The frontend is Next.js and TypeScript with React Flow, Framer Motion, and Recharts. FastAPI services use Pydantic, SQLAlchemy, PostgreSQL, Redis/Celery, and MinIO. OPA makes authorization decisions. OpenFeature stores rollout state. Ed25519 signs capabilities and certificates. OpenTelemetry and OBI feed SigNoz and ClickHouse. Ollama exposes Qwen3 8B through an OpenAI-compatible endpoint on the developer’s GPU laptop.

The persistent benchmark contains 120 deterministic mission capsules, 880 valid safety mutations, a deterministic top-64 risk set, bounded adaptive search, seven metamorphic invariants, 256 counterfactual branches, and one bounded 17-to-7 regression minimization.

## SigNoz usage

SigNoz is the project’s execution-evidence source of truth:

- OpenTelemetry spans capture intent, action boundaries, policies, capabilities, receipts, replays, causal branches, certificates, delegation, and rollback.
- OBI independently observes local HTTP effects.
- Trace matching finds commits without authorization.
- Query Builder and formulas calculate routine assurance metrics.
- ClickHouse SQL derives evidence parity, coverage, causal aggregates, authority frontiers, and drift history.
- Five dashboards cover readiness, evidence, causal analysis, authority, and certified production.
- Critical alerts deliver signed webhooks to WATCHTOWER.
- Foundry reproduces the SigNoz and MCP deployment from `casting.yaml` and its lock file. ORBITAL's idempotent provisioning script creates the dashboards, alerts, and saved views.

Without SigNoz, ORBITAL could repeat an application’s own claims. With SigNoz, it can compare claims against independent execution evidence and attach every certificate decision to inspectable proof.

## Impact

ORBITAL turns “the agent passed a test” into an operationally useful statement: this exact artifact, model, prompt, policy, tool schema, and dataset is supported up to this authority level, under these restrictions, while these sensors remain healthy. Drift or evidence loss revokes that confidence automatically.

## Innovation

- Evidence parity compares semantic claims to independently observed effects.
- The Authority Frontier grants only the autonomy supported by confidence-bounded evidence.
- The certificate binds behavior claims to artifact identity and SigNoz evidence.
- Runtime trust decays and can be revoked through live observability signals.
- Multi-agent delegation conserves authority and responsibility across the chain.

## Challenges

- Correlating SDK spans, OBI protocol observations, OPA decisions, and receipts without exposing private payloads.
- Making Celery campaign recovery and every consequential write idempotent.
- Keeping causal analysis bounded, reproducible, and honest about uncertainty.
- Reproducing native eBPF behavior on a resource-constrained hackathon VM.
- Presenting a large assurance system as one coherent three-minute story.

## Accomplishments

- All ten planned subsystems execute real code.
- Seven Mission Control screens consume live backend and SigNoz-linked data.
- Native Ubuntu positive and negative OBI acceptance tests.
- Live critical alert history, signed webhook verification, duplicate-delivery proof, suspension, zero canary traffic, and baseline rollback.
- Persistent, recoverable replay campaigns.
- Signed certificate verification including tampering, expiry, policy/schema mismatch, and artifact drift.
- Complete blocked authority-laundering demonstration with no external effect.

## Future roadmap

- Hardware-backed production signing keys and remote attestation.
- Production identity federation and organization-level trust domains.
- Additional mission domains beyond refunds.
- Privacy-preserving cross-organization evidence exchange.
- Longer-running online frontier recalibration.
- Broader minimization beyond the one bounded hero failure.
- Formal policy proofs and regulator-oriented certificate profiles.

## Judging-criteria mapping

| Criterion | Evidence |
|---|---|
| Use of SigNoz | SDK + OBI telemetry, dashboards, trace matching, queries, ClickHouse SQL, alerts, webhooks, Foundry |
| Agent observability | Mission identity, tool actions, effects, policies, replays, causal branches, authority, certificate lifecycle |
| Functionality | Ten subsystems, seven screens, reproducible commands, live rollback |
| Technical depth | Persistent orchestration, idempotency, eBPF, cryptographic binding, confidence intervals |
| Originality | Authority Frontier + evidence-bound, revocable flight certificate |
| Presentation | Under-three-minute final workflow with direct SigNoz drill-down |
