# ORBITAL Σ Judge Guide

## The five-minute path

ORBITAL's claim is narrow and testable: **observability evidence can determine how much authority an AI agent is allowed to keep.**

Use this guide for an evidence-first review of release [v1.0.1](https://github.com/Shobhit1Kapoor/Orbital/releases/tag/v1.0.1). The screenshots and identifiers below come from the [committed final validation](phase8-final-validation-2026-07-23.md). A live run can generate new identifiers; that is expected.

### Before the clock starts

If the stack is already running:

```bash
curl -fsS http://localhost:8000/livez
make final-demo
```

Open Mission Control at `http://localhost:3000` and SigNoz at `http://localhost:8080`. If no live environment is available, use the linked captured evidence and the [Phase 8 validation report](phase8-final-validation-2026-07-23.md); do not describe a screenshot as a live run.

---

## Minute 0:00–1:00 — The problem and the trust boundary

Open [Evidence Parity](assets/mission-control/02-evidence-parity.png).

Say:

> An agent can report a safe tool call while a different effect crosses the service boundary. ORBITAL does not decide from the agent's own span alone. It reconciles semantic telemetry, OPA policy evidence, signed effect receipts, and OBI's independent observation.

Point to:

- semantic declaration: `store_credit`;
- independently observed effect: `issue_refund`;
- evidence verdict: `CONTRADICTED`;
- execution-mode labels that distinguish live, replay, synthetic, counterfactual, and `UNKNOWN`;
- “Open in SigNoz” evidence actions.

Then open the [SigNoz evidence trace](assets/signoz/01-evidence-trace.png). In the final clean rehearsal the refund trace ID was `df01b8e869896bb9b3ea45f8a6f25ef0`; the native OBI acceptance trace was `0fed347a5fc6977696e025ba0c9ffaad`.

**Claim 1 — Independently observed action contradiction**

The candidate's semantic claim and the project-owned local boundary observation disagree. PARALLAX reports `CONTRADICTED`; missing OBI evidence would produce `UNKNOWN`, not confirmation.

Evidence:

- [Evidence Parity screen](assets/mission-control/02-evidence-parity.png)
- [SigNoz trace capture](assets/signoz/01-evidence-trace.png)
- [Native OBI acceptance report](obi-native-ubuntu.md)
- [Final validation identifiers](phase8-final-validation-2026-07-23.md#final-live-evidence)

---

## Minute 1:00–2:00 — From an alert to automatic rollback

Open the [SigNoz alert history](assets/signoz/04-alert-history.png), then the [Certificate screen](assets/mission-control/07-certificate.png).

Say:

> The contradiction is not just a red panel. SigNoz records alert history and sends a normalized, signed webhook to WATCHTOWER. WATCHTOWER deduplicates the delivery, suspends the certificate, moves candidate traffic to zero, and restores the last certified baseline.

Point to:

- alert history, not merely an alert definition;
- certificate status changing to suspended;
- candidate traffic at zero;
- baseline restored;
- supporting trace, query, and alert-history links.

**Claim 2 — SigNoz alert to WATCHTOWER rollback**

The Phase 8 acceptance run verified eight critical alert histories, signed webhook delivery, duplicate-delivery idempotency, certificate suspension, zero candidate traffic, and certified-baseline restoration.

Evidence:

- [Alert-history capture](assets/signoz/04-alert-history.png)
- [Certificate screen](assets/mission-control/07-certificate.png)
- [Phase 2 live-alert validation](phase2-live-alerts-validation-2026-07-22.md)
- [Final alert acceptance result](phase8-final-validation-2026-07-23.md#validation-results)

---

## Minute 2:00–3:00 — Causality, minimization, and authority

Open the [Causal Graph](assets/mission-control/04-causal-graph.png), followed by [Authority Frontier](assets/mission-control/05-authority-frontier.png).

Say:

> ORBITAL replays controlled interventions instead of treating correlation as causation. The bounded hero analysis stored 256 counterfactual branches, confidence intervals, and an earliest commitment point. Delta debugging reduced the reproducer from 17 units to 7 while preserving the verified failure. FRONTIER then evaluated all six authority levels and found that evidence supported level 3—low-value external actions—but not broader autonomous irreversible authority.

Point to:

- causal contribution intervals and `UNKNOWN` behavior for insufficient evidence;
- original size 17 and minimized size 7;
- all six authority levels;
- the safe-frontier marker at level 3;
- the certificate restriction generated from that boundary.

**Claim 3 — Evidence-driven authority restriction**

The maximum authority is calculated from measured completion, escaped effects, refusals, escalation, evidence parity, policy completeness, latency, cost, and confidence bounds. A deterministic threshold engine—not the LLM—issues the verdict and Ed25519 certificate.

Evidence:

- [Causal Graph screen](assets/mission-control/04-causal-graph.png)
- [Authority Frontier screen](assets/mission-control/05-authority-frontier.png)
- [Safety Case screen](assets/mission-control/06-safety-case.png)
- [Certificate screen](assets/mission-control/07-certificate.png)
- [Phase 4C causal validation](phase4c-causal-validation-2026-07-23.md)
- [Phase 5 certification validation](phase5-frontier-clearance-validation-2026-07-23.md)

---

## Minute 3:00–4:00 — Inspect the SigNoz implementation depth

Use the dashboard, funnel, and alert-history captures or open their live equivalents in SigNoz.

| SigNoz capability | ORBITAL implementation | Judge-visible proof | Why it changes a decision |
|---|---|---|---|
| Traces | End-to-end correlation across mission, policy, capability, tool, effect, OBI, replay, causal, frontier, certificate, delegation, and rollback spans | [Evidence trace](assets/signoz/01-evidence-trace.png) | Establishes sequence and identity |
| OBI / eBPF | Native Ubuntu observation limited to project container traffic on service port 8000 | [OBI report](obi-native-ubuntu.md) | Supplies an evidence plane independent of SDK semantics |
| Trace matching | Finds a consequential observed effect without the required matching authorization or verification relationship | [Trace funnel](assets/signoz/03-trace-funnel.png) | Converts missing or conflicting spans into an assurance state |
| Query Builder | Routine readiness, evidence parity, latency, retries, and rollout formulas | [Flight Readiness](assets/signoz/02-flight-readiness-dashboard.png) | Tests contract thresholds without application counters |
| ClickHouse SQL | Campaign, causal, frontier, and drift aggregation | [Presentation asset index](presentation-assets.md#signoz-evidence) | Supports weighted and historical calculations at trace grain |
| Alerts | Twelve repository definitions; eight critical histories exercised in the final workflow | [Alert history](assets/signoz/04-alert-history.png) | Turns observed risk into a revocation input |
| Signed webhooks | Allowlisted alert payload, HMAC-SHA256 verification, delivery deduplication | [Phase 2 report](phase2-live-alerts-validation-2026-07-22.md) | Prevents an unauthenticated or duplicate notification from creating divergent rollback state |
| Dashboards | Six version-controlled, idempotently provisioned dashboards | [Asset index](presentation-assets.md#signoz-evidence) | Gives an operator a stable evidence-to-decision view |
| Saved views | Provisioned with dashboards and alerts by ORBITAL after Foundry starts SigNoz and MCP | [README deployment note](../README.md#why-signoz-is-indispensable) | Makes repeat investigation paths reproducible |
| Foundry-managed MCP | Enabled and locked through `casting.yaml` and `casting.yaml.lock` | [Release validation](phase8-final-validation-2026-07-23.md) | Reproduces the SigNoz/MCP deployment used by provisioning and validation |

The boundary is deliberate: Foundry reproduces SigNoz and its MCP server. ORBITAL's idempotent provisioning script creates the project dashboards, alerts, and saved views.

---

## Minute 4:00–5:00 — Reproducibility and honest limits

Open [Launch Console](assets/mission-control/01-launch-console.png) and [Safety Case](assets/mission-control/06-safety-case.png).

Say:

> This is a synthetic, local assurance benchmark. The release contains 120 deterministic capsules, 880 valid safety mutations, 64 selected cases, 95 automated tests, six dashboards, twelve alert definitions, and a locked Foundry deployment. The final verdict is CONDITIONAL. ORBITAL does not claim that a local benchmark proves universal safety.

Point to:

- sensor health and disconnected states;
- live campaign status and SSE reconnect behavior;
- claims linked to evidence, assumptions, restrictions, and residual risks;
- the `CONDITIONAL` certificate verdict;
- the blocked delegation chain, where the child cannot exceed the parent's authority.

Reproduction entry point:

```bash
git clone https://github.com/Shobhit1Kapoor/Orbital.git
cd Orbital
git checkout v1.0.1
make bootstrap
make verify
make final-demo
```

The committed final clean rehearsal completed in 27.730 seconds excluding infrastructure startup. Native OBI requires a compatible Linux kernel with BTF and the documented privileges; if that dependency is absent, the correct state is `UNKNOWN` or unavailable—not a fabricated pass.

## Three claims to remember

1. **Independent evidence catches semantic contradiction.** `store_credit` was declared; local OBI observed `issue_refund`; PARALLAX returned `CONTRADICTED`.
2. **Observability becomes a control input.** A SigNoz alert led through a signed, idempotent webhook to certificate suspension, zero candidate traffic, and baseline restoration.
3. **Evidence bounds authority.** Causal replay, minimization, and six-level frontier evaluation supported level 3 with an Ed25519-signed `CONDITIONAL` certificate.

## If only static evidence is available

Use this exact order:

1. [Evidence Parity](assets/mission-control/02-evidence-parity.png)
2. [SigNoz evidence trace](assets/signoz/01-evidence-trace.png)
3. [SigNoz alert history](assets/signoz/04-alert-history.png)
4. [Causal Graph](assets/mission-control/04-causal-graph.png)
5. [Authority Frontier](assets/mission-control/05-authority-frontier.png)
6. [Certificate](assets/mission-control/07-certificate.png)
7. [Phase 8 validation report](phase8-final-validation-2026-07-23.md)

Each capture represents an actual project state at capture time. It is not a substitute for live execution, and the label should remain “captured evidence.”
