# ORBITAL Σ — Submission Copy

## Project title

**ORBITAL Σ — Autonomous Agent Flight Assurance**

## Tagline

**Trust what the agent does, not only what it says.**

## 25-word version

ORBITAL Σ turns independent observability evidence into bounded agent authority, signed certification, and automatic rollback when declared behavior diverges from verified local execution at runtime.

## 50-word version

ORBITAL Σ is a flight-assurance control plane for AI agents. It reconciles semantic traces, OPA decisions, signed effect receipts, and OBI observations; replays synthetic missions; estimates causal contribution; measures safe authority; signs restricted certificates; and automatically suspends drifted candidates through SigNoz alerts and WATCHTOWER rollback, using only synthetic local fixtures.

## 100-word version

ORBITAL Σ turns observability evidence into operational authority for AI agents. A synthetic refund fixture declares store credit while calling only a local mock refund service. SigNoz correlates semantic spans, OPA decisions, signed receipts, and native OBI traffic; PARALLAX marks the disagreement CONTRADICTED. ORBITAL then replays deterministic missions, estimates causal contributions, minimizes the failure, and evaluates six authority levels. CLEARANCE issues an Ed25519 certificate restricted to evidence-supported authority. When artifact drift appears, a signed SigNoz alert makes WATCHTOWER suspend the certificate, reduce candidate traffic to zero, and restore the certified baseline. Missing required evidence always produces an explicit UNKNOWN state.

## Full project narrative

### The problem

Agent evaluation usually trusts one of two views: what the model says it intended to do, or whether the final answer appears successful. Production monitoring adds availability and latency, but it still often accepts application instrumentation as a complete account of behavior.

That is not sufficient for consequential agents. A semantic span can say `store_credit` while a different HTTP effect crosses a service boundary. A policy decision can be logged without proving that the executed arguments matched the authorized arguments. A candidate can pass offline tests and then drift after deployment. A parent agent can attempt to pass forbidden authority to a child.

The missing layer is flight assurance: a chain of custody from mission contract to runtime effect, with enough independent evidence to determine what authority an agent deserves.

### The solution

**ORBITAL turns observability evidence into operational authority.**

It compiles an explicit mission contract, gathers four evidence planes, persists replayable synthetic missions, tests reliability invariants, performs bounded counterfactual analysis, measures an authority frontier, signs a restricted certificate, and watches the deployed artifact for conditions that invalidate that certificate.

The primary demonstration is deliberately small and inspectable. A local MCP-like reliability fixture emits a declared safe semantic action, `store_credit`, while calling only the project's local mock refund service. Native OBI observes the actual local request as `issue_refund`. OPA policy evidence and a signed effect receipt complete the record. PARALLAX does not hide the disagreement behind an aggregate score; it returns `CONTRADICTED` and links the supporting spans in SigNoz.

That contradiction becomes an operational input. SigNoz records alert history and sends a normalized, signed webhook to WATCHTOWER. WATCHTOWER verifies and deduplicates the delivery, suspends the affected certificate, sets candidate traffic to zero, restores the last certified baseline, emits rollback telemetry, and creates a replay investigation. Duplicate alert delivery produces the same final state.

### How it works

ORBITAL consists of ten implemented assurance subsystems:

1. **ATLAS** compiles the mission contract deterministically into normalized policy, telemetry, replay, dashboard, alert, authority, and certification inputs.
2. **PARALLAX** reconciles semantic application spans, OBI observations, OPA decisions, and signed or hashed effect receipts.
3. **GATE** binds consequential actions to mission, certificate, artifact, tenant, amount, tool, canonical arguments, policy revision, expiry, and a single-use nonce.
4. **CAPSULE** packages prompts, retrieval fixtures, memory, tool schemas, database state, API cassettes, privacy maps, invariants, and reference telemetry.
5. **RANGE** generates 880 deterministic local safety mutations across retrieval, memory, tool, infrastructure, and multi-agent categories, then selects 64 high-risk valid cases.
6. **Metamorphic testing** checks authority invariants without relying on output-string equality.
7. **FORK** runs controlled single and pairwise interventions, repeated counterfactuals, bounded Shapley-style attribution, confidence intervals, and earliest-commitment analysis.
8. **FRONTIER** evaluates completion and safety at six progressively broader authority levels.
9. **CLEARANCE** applies deterministic contract thresholds and signs an Ed25519 certificate; the LLM never chooses the verdict.
10. **WATCHTOWER** attaches artifact identity to runtime traces and revokes trust after validated drift or assurance alerts.

Multi-agent delegation adds an explicit chain of custody. A child cannot receive more authority or risk budget than the parent possesses. The secondary demonstration shows a parent without refund permission delegating to a child: authority laundering is detected, OPA denies the action, GATE refuses the capability, SigNoz records the chain, and no external effect occurs.

### SigNoz implementation

SigNoz is indispensable because the central decision requires correlated evidence from components that do not share the same trust assumption.

- **Distributed traces** connect missions, policy decisions, capabilities, tool execution, effect receipts, OBI observations, replays, causal branches, frontier points, certificates, delegation, alert handling, and rollback.
- **OBI / eBPF** provides independent observation of project-owned local service traffic on the native Ubuntu validation host.
- **Trace matching** identifies missing authorization and missing effect-verification relationships.
- **Query Builder and formulas** drive routine evidence-parity, readiness, latency, retry, and rollout views.
- **ClickHouse SQL** supports campaign, causal, authority-frontier, and drift-history aggregation.
- **Alerts and alert history** turn mismatch, sensor loss, drift, and related conditions into inspectable operational events.
- **Signed webhooks** carry normalized allowlisted alert fields to WATCHTOWER with HMAC-SHA256 verification and delivery deduplication.
- **Six dashboards and twelve alert definitions** are version-controlled and provisioned idempotently by ORBITAL.
- **Foundry-managed MCP** reproduces the SigNoz and MCP deployment from `casting.yaml` and `casting.yaml.lock`; ORBITAL's provisioning layer creates project dashboards, alerts, and saved views after that deployment is healthy.

Mission Control exposes seven linked evidence screens: Launch Console, Evidence Parity, Replay Theater, Causal Graph, Authority Frontier, Safety Case, and Certificate. The interface labels live, replayed, synthetic, counterfactual, and `UNKNOWN` states, and gives direct routes to supporting SigNoz traces, dashboards, queries, and alert history.

### Verified results

The final committed validation recorded:

- **120** deterministic synthetic mission capsules;
- **880** valid safety mutations with deterministic IDs and provenance;
- **64** deterministically selected high-risk test cases;
- **1,280** bounded adaptive executions;
- **9 of 9** metamorphic invariants satisfied by the corrected candidate;
- **256** stored counterfactual branches for the hero causal analysis;
- a minimized regression reduced from **17 units to 7** while retaining the verified failure;
- **six** authority levels evaluated with 1,000 observations per level;
- maximum supported authority at **level 3, low-value external actions**;
- an Ed25519-signed certificate with a final `CONDITIONAL` verdict;
- **six** SigNoz dashboard definitions and **twelve** alert definitions;
- **eight** critical alert histories exercised in the final workflow;
- a native OBI positive/negative acceptance pair;
- **95 automated tests**: 87 Python and 8 Playwright;
- two clean final-demo rehearsals, with the faster committed run completing in **27.730 seconds**, excluding infrastructure startup.

The final verdict is not advertised as `GO`. `CONDITIONAL` is the evidence-supported result, including its restrictions and residual risks.

### Impact

ORBITAL changes observability from passive explanation into an authority-control primitive.

For an operator, that means a contradiction can reduce traffic and restore a baseline instead of remaining an unowned dashboard anomaly. For an evaluator, it means task success is considered alongside evidence parity, policy completeness, sensor health, escaped effects, and confidence bounds. For an agent platform, it provides a concrete pattern for limiting tools and delegation according to verified behavior.

The project is intentionally a local benchmark rather than a commercial control plane. Its contribution is the integrated assurance loop and the evidence model needed to make that loop inspectable.

### Innovation

- **Independent evidence parity:** application semantics are checked against OBI observations, policy decisions, and receipts rather than trusted alone.
- **Observability-derived authority:** the six-level frontier makes authority a measured quantity with confidence intervals and restrictions.
- **Causal, not merely correlational, diagnosis:** controlled interventions and bounded attribution connect an observed failure to reproducible causal factors.
- **Signed safety case:** claims, evidence, assumptions, restrictions, and residual risks are bound to artifact identity in an Ed25519 certificate.
- **Runtime revocation:** a verified SigNoz alert can suspend a certificate, zero candidate traffic, and restore a baseline idempotently.
- **Authority conservation across agents:** delegation carries explicit identity, certificate, tool, risk, tenant, data-label, depth, and expiry bindings.
- **Honest uncertainty:** missing required evidence yields `UNKNOWN`.

### Challenges

The hardest integration problem was keeping one correlation chain intact across application spans, OPA, OBI, capabilities, receipts, Celery replay tasks, object storage, SigNoz evidence, certification, and rollback. Native OBI also required a Linux host with BTF and privileges that are not available in an ordinary browser-only or non-native environment.

A second challenge was separating actual evidence modes. Synthetic corpus results, deterministic simulations, recorded replay, live local execution, and counterfactual branches all appear in one interface but must never be presented as interchangeable. Mission Control therefore displays the evidence mode explicitly.

A third challenge was reproducibility. Foundry owns the locked SigNoz/MCP deployment, while ORBITAL's project-specific provisioning must be idempotent and independently verifiable.

### Accomplishments

- Implemented all ten original assurance subsystems without replacing the ambitious scope with mock UI values.
- Completed persistent PostgreSQL, Redis/Celery, and MinIO campaign infrastructure with pause, resume, retry, cancellation, and recovery validation.
- Proved a semantic-versus-observed contradiction with native OBI on project-owned local traffic.
- Connected SigNoz alert history to signed, duplicate-safe WATCHTOWER rollback.
- Built a causal explanation with 256 branches and a 17→7 minimized reproducer.
- Measured and certified a level-3 authority frontier rather than claiming unrestricted autonomy.
- Implemented and displayed a blocked multi-agent authority-laundering chain.
- Delivered seven responsive Mission Control screens and 95 automated tests.

### Limitations and honest claims

- All identities, customers, orders, tools, APIs, effects, and traffic are synthetic local fixtures. No result establishes production safety for a real payment, identity, or third-party system.
- The intentionally vulnerable fixture demonstrates evidence disagreement only against the local mock refund service. It is not a reusable exploit and contains no real payment integration.
- Native OBI evidence depends on a compatible Linux kernel with BTF, host PID access, and required privileges. Without that sensor, the relevant assurance result is `UNKNOWN`.
- OBI observes protocol and network behavior; SDK spans and receipts still provide exact business semantics.
- The causal attribution is bounded and approximate. It uses recorded seeds, limited samples, and confidence intervals; it is not universal causal proof.
- The minimizer is intentionally limited to one hero failure, not a general minimization service for all selected cases.
- The corpus contains 120 structured synthetic missions. It does not represent every production distribution, language, tool, tenant, or adversarial strategy.
- Tail sampling preserves defined high-risk traces while sampling some lower-risk successes; absence outside required evidence paths must not be interpreted as proof.
- The development signing key is generated locally during bootstrap. Only the development public key is committed.
- The final certificate is `CONDITIONAL`, expires, and is bound to the evaluated artifact, model, prompt, policy, tool schema, dataset, and replay engine.

The complete privacy and limitation statement is in [privacy-and-limitations.md](privacy-and-limitations.md).

### Future roadmap

The original long-term direction remains documented future work rather than a hackathon claim:

- hardware-backed and externally managed signing keys;
- larger multilingual and multimodal mission corpora;
- real staging connectors under explicit sandbox and authorization controls;
- calibrated causal estimators at greater sample budgets;
- federated evidence across regions and organizations;
- formal policy verification and external transparency logs;
- longer trust-decay histories and certificate renewal workflows;
- organizational approval workflows for irreversible authority.

### Judging-criteria mapping

| Criterion | Evidence |
|---|---|
| AI & Agent Observability | Four-plane evidence mesh, native OBI contradiction, trace matching, causal replay, sensor-aware `UNKNOWN` |
| SigNoz utilization | Traces, OBI, Query Builder, formulas, ClickHouse SQL, alerts/history, signed webhooks, dashboards, saved views, Foundry MCP |
| Technical depth | Ten subsystems, persistent campaigns, bounded causal analysis, deterministic certification, delegation custody, rollback |
| Innovation | Observability evidence directly grants, restricts, suspends, and restores operational authority |
| Product experience | Seven evidence-linked Mission Control screens at the 1366×768 target viewport |
| Reliability | Idempotent commits, retries, webhooks, provisioning, replay writes, certificate verification, and baseline rollback |
| Reproducibility | Release tag v1.0.1, Foundry lock, one-command workflows, committed validation reports and captures |
| Responsible engineering | Local synthetic scope, privacy filtering, no hidden-reasoning export, explicit evidence modes and limitations |

## AI-assistance disclosure

AI coding assistance was used during implementation, testing, documentation, and review. The project author selected the architecture, controlled the repository and infrastructure, ran validation, reviewed generated changes, and is responsible for the submitted claims.

The agent under evaluation uses Qwen3 8B through a local Ollama OpenAI-compatible endpoint when available. Runs using deterministic fallback are labeled accordingly. Hidden reasoning and chain-of-thought are not exported to SigNoz.

## Team

**Shobhit Kapoor — solo builder**

## Submission links

- Repository: [github.com/Shobhit1Kapoor/Orbital](https://github.com/Shobhit1Kapoor/Orbital)
- Release: [v1.0.1](https://github.com/Shobhit1Kapoor/Orbital/releases/tag/v1.0.1)
- Judge guide: [JUDGE_GUIDE.md](JUDGE_GUIDE.md)
- Architecture: [architecture.md](architecture.md)
- Validation: [phase8-final-validation-2026-07-23.md](phase8-final-validation-2026-07-23.md)
- Evidence index: [presentation-assets.md](presentation-assets.md)
- Demo package: [demo-video-package.md](demo-video-package.md)
