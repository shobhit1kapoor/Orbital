# ORBITAL Σ Privacy Controls and Honest Limitations

## Scope statement

ORBITAL Σ is a defensive, isolated software-quality and reliability benchmark.

All agents, identities, customers, tenants, orders, prompts, retrieval documents, memories, policies, tool schemas, APIs, credentials, databases, effects, and traffic used by the project are synthetic local fixtures owned by the project author. The intentionally vulnerable MCP-like behavior calls only the local mock refund service. It is present to prove observability and policy enforcement; it is not a reusable exploit and includes no real payment integration.

No validation result in this repository should be read as permission to test, scan, exploit, or interact with an external or third-party system.

## Data classification

| Data class | Example in ORBITAL | Export/persistence rule |
|---|---|---|
| Public project metadata | subsystem name, schema version, synthetic candidate ID | May appear in repository, PostgreSQL, MinIO, SigNoz, and screenshots |
| Synthetic operational identifiers | mission, action, replay, trace, certificate IDs | Persisted for correlation; not real customer identity |
| Synthetic business fixture | mock order amount, tenant fixture, local tool result | Business semantics may be represented with hashed or non-identifying fixture IDs |
| Sensitive execution input | raw prompt, memory text, retrieval payload | Stored only where the versioned local capsule requires it; not exported as raw telemetry |
| Security material | capability token, webhook secret, signing private key, mock credentials | Generated locally; never committed; prohibited from telemetry |
| Hidden model reasoning | chain-of-thought or hidden reasoning | Not collected or exported |

## Implemented privacy controls

### Synthetic-only fixtures

Corpus records and demo effects are deterministic local data. Screenshots and validation identifiers are project-run evidence, not production customer or payment data.

### Collector redaction

The OpenTelemetry Collector configuration deletes these attributes before export:

```text
raw_prompt
chain_of_thought
capability_token
payment_credentials
customer_email
customer_name
```

This is a targeted denylist for known prohibited attributes. It must not be described as a general content-aware data-loss-prevention system or a complete allowlist.

### Payload-size claim

The committed Collector configuration does not establish a separate, general application-payload size limit that this release validated. ORBITAL therefore makes no public claim that oversized or deeply nested sensitive payloads are automatically bounded by the Collector. Production hardening would need explicit per-signal size limits, rejection metrics, and tests in addition to the current targeted redaction.

### Identifier hashing in the corpus privacy map

The synthetic capsule builder records SHA-256 hashes for tenant and order identifiers in each privacy map. This reduces direct identifier propagation in derived corpus artifacts. It is not a claim that every identifier in every subsystem is automatically anonymized.

### Webhook normalization and authentication

The SigNoz-to-WATCHTOWER relay normalizes defined alert fields rather than forwarding an arbitrary alert body into control logic. It accepts a bounded set of labels and annotations, derives a canonical delivery identity, and attaches an HMAC-SHA256 signature. WATCHTOWER verifies the signature and deduplicates delivery before changing certificate or rollout state.

This protects the local control path against malformed, unauthenticated, and duplicate delivery under the demo's shared-secret trust model. It is not equivalent to a public multi-tenant webhook gateway or hardware-backed attestation.

### Risk-adaptive tail sampling

Collector policy retains:

- 100% of high-risk, contradiction, violation, certificate, drift, rollback, causal, frontier, campaign, and irreversible-action traces covered by the configured rules;
- 20% of medium-risk traces; and
- 5% of verified successful low-risk traces.

Sampling limits telemetry volume while preserving the evidence paths required by the safety case. Because some lower-risk successes are sampled, their absence from SigNoz cannot be interpreted as proof that they never happened.

### No hidden reasoning export

Telemetry contains decision boundaries, selected actions, tool calls, execution mode, policy results, effect evidence, timing, and outcome metadata. It does not intentionally export chain-of-thought or hidden model reasoning.

### Local secrets and keys

Bootstrap generates development secrets and the Ed25519 private development key locally. Only the development public key is committed. Capability tokens expire after 20 seconds and are single-use, but the token itself remains prohibited telemetry.

## Evidence integrity is not privacy completeness

ORBITAL's strongest contribution is evidence reconciliation. A `CONFIRMED` action means the required evidence planes agreed under the configured local contract and sensor state. It does **not** mean:

- every possible sensitive field was discovered and removed;
- a real user consented to the processing;
- the deployment meets a specific regulatory regime;
- the model output is free of memorized content;
- the host or storage layer cannot be compromised; or
- the action is universally safe outside the synthetic mission distribution.

Privacy and assurance are related but distinct claims.

## `UNKNOWN` behavior

Missing evidence is not success.

ORBITAL reports `UNKNOWN` when a required sensor, trace reference, storage source, certificate basis, or counterfactual branch is unavailable or insufficient. Examples include:

- native OBI is unavailable for a consequential action whose contract requires independent observation;
- SigNoz evidence cannot be retrieved;
- a capsule or branch checksum cannot be verified;
- required sensor health is incomplete during certification;
- delegation ownership or certificate evidence is missing; or
- the causal sample does not support a bounded estimate.

`UNOBSERVED` is used when an expected effect or receipt is absent while the required observation path is otherwise available. `CONTRADICTED` is used when evidence planes disagree. These states must not be collapsed into a single generic error or pass.

## Threat-model boundaries

The detailed threat model is in [threat-model.md](threat-model.md). The implemented demonstration assumes:

- the repository, local fixture definitions, and bootstrap process are controlled by the project author;
- the development signing key and webhook secret are generated and retained locally;
- PostgreSQL, MinIO, Redis, SigNoz, OPA, and the Collector run inside the owned environment;
- native OBI is limited to project container traffic on the configured local service port;
- an attacker does not control the host kernel, SigNoz storage, signing key, and application simultaneously; and
- the judge is evaluating the documented local release, not an unreviewed production deployment.

If the host, signing key, Collector, OBI sensor, and evidence store are jointly compromised, ORBITAL cannot establish an independent chain of custody.

## Technical limitations

### Synthetic mission distribution

The 120-capsule corpus and 880 mutations are structured and reproducible, but they do not represent every language, domain, tenant pattern, model behavior, tool topology, infrastructure fault, or adversarial strategy. Reported rates are valid for the versioned local dataset and configuration.

### Local mock effects

The refund, order, CRM, payment-like, and MCP-like services are local fixtures. GATE's binding, replay protection, and duplicate-effect tests demonstrate the contract against those fixtures. Real financial systems would require vendor-specific idempotency, reconciliation, authentication, audit, regulatory, and failure-handling integration.

### OBI semantic boundary

OBI independently observes protocol and network behavior; it does not infer every business meaning by itself. SDK spans and signed receipts still carry the exact action and effect semantics. The assurance result is based on reconciliation, not a claim that eBPF replaces application instrumentation.

Native OBI validation requires a compatible Linux kernel with BTF, host PID access, and required privileges. A non-native or incompatible environment cannot honestly reproduce that evidence plane.

### TLS and payload visibility

The demo is designed around owned local service traffic and known fixture semantics. The project does not claim universal visibility into arbitrary encrypted third-party payloads. The OBI evidence claim is limited to the validated local topology.

### Causal estimation

The Phase 4C result uses controlled interventions, recorded seeds and parameters, single and pairwise effects, repeated runs, bounded approximate Shapley-style samples, and bootstrap confidence intervals. It is an estimate under the selected intervention model, not proof of all causal mechanisms.

### Bounded minimization

Delta debugging is implemented only for the primary refund failure. It reduced the committed reproducer from 17 units to 7 while preserving the verified failure. The project does not claim a stable general minimizer for all 64 selected cases.

### Certification

CLEARANCE's deterministic thresholds make the decision reproducible; they do not make the contract complete. The certificate:

- applies only to the bound artifact, model, prompt, policy, tool schema, dataset, replay engine, and assumptions;
- expires;
- restricts authority;
- can be suspended after drift or other revocation evidence; and
- had a final committed verdict of `CONDITIONAL`, not `GO`.

The development Ed25519 key is appropriate for a local hackathon demonstration, not production key governance.

### Sequential and confidence-bound interpretation

Confidence intervals describe uncertainty in the evaluated samples. They do not cover misspecified missions, unmodeled dependencies, or distribution shift. Additional trials near a threshold reduce sampling ambiguity but cannot prove the threshold itself is correct.

### Campaign durability

The project validates restart and recovery behavior for PostgreSQL, Redis, MinIO, Celery workers, FastAPI, retries, partial chords, cancellation, and SSE reconnection in the owned stack. It does not claim regional disaster recovery, Byzantine fault tolerance, or exactly-once delivery from arbitrary external systems.

### Mission Control

Mission Control is a read model. It links aggregates to backend and SigNoz evidence but is not an independent evidence store. A UI bug, stale browser cache, or disconnected SSE client must not override the underlying durable and telemetry state.

### Alerting and rollback

Twelve alert definitions are version-controlled. The committed final workflow exercised eight critical alert histories. That does not mean every alert rule was fired in the same run. Rollback is validated against the local OpenFeature provider and certified-baseline fixture, not a real global traffic network.

### Privacy filtering

The targeted Collector deletion, corpus identifier hashing, and webhook field normalization are concrete controls. They are not a formal information-flow proof, a substitute for secrets scanning at every boundary, or a regulatory compliance certification.

### Model reproducibility

Qwen3 8B runs through local Ollama when available with pinned settings. Hardware, model image, and runtime details can still affect output. Deterministic fallback is used for bounded workflows when Ollama is unavailable and is labeled distinctly from live model execution.

## Operational limitations

- Infrastructure startup is excluded from the under-three-minute demo target.
- Native Ubuntu validation and Azure resource availability can differ from WSL2 development behavior.
- Ollama remains on the RTX laptop and is not run on the native validation VM.
- Public-IP and disk charges continue until the Azure resource group is deleted; deallocation stops compute but not every resource charge.
- Foundry reproduces SigNoz and its managed MCP server; ORBITAL's separate idempotent provisioning step creates project dashboards, alerts, and saved views.
- Release screenshots are captured evidence. New runs generate new trace, campaign, finding, and certificate identifiers.

## Claims ORBITAL deliberately does not make

ORBITAL does not claim:

- universal AI safety;
- formal verification of model behavior;
- production readiness for real financial, medical, identity, or legal decisions;
- complete prompt-injection prevention;
- a zero false-positive or false-negative rate;
- causal certainty outside the tested intervention set;
- privacy or regulatory certification;
- exactly-once behavior across arbitrary third-party systems;
- that all twelve alert rules fired in the final run;
- that deterministic simulation is live production performance; or
- that a screenshot is equivalent to a fresh live run.

## Responsible interpretation

The defensible conclusion is:

> In the versioned, synthetic, local ORBITAL environment, independently correlated SigNoz evidence detected a semantic-versus-observed action contradiction, supported bounded causal and authority analysis, drove deterministic restricted certification, and triggered an idempotent rollback path.

For exact committed results and identifiers, see [phase8-final-validation-2026-07-23.md](phase8-final-validation-2026-07-23.md). For the shortest evidence review, see [JUDGE_GUIDE.md](JUDGE_GUIDE.md).
