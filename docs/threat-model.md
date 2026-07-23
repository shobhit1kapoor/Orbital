# Threat Model

## Scope

ORBITAL Σ protects a synthetic autonomous refund agent and its locally owned supporting services. The security boundary includes the agent artifact, prompts, model parameters, policy bundle, tool schemas, capability issuer, local tools, telemetry pipeline, certificate, and rollout state.

External services, real payment providers, real customer records, public targets, and third-party credentials are explicitly out of scope.

## Assets

- authority to perform consequential actions
- tenant and data-label isolation
- single-use capability nonces
- action and effect integrity
- certificate signing identity
- artifact identity and rollout state
- mission capsules and replay provenance
- assurance telemetry and evidence links

## Threats and controls

| Threat | Primary controls |
|---|---|
| Prompt attempts to expand authority | OPA policy, GATE binding, certificate restrictions |
| Declared action differs from effect | semantic spans + OBI + signed/hashed receipt reconciliation |
| Duplicate effect after timeout/retry | canonical action hash, nonce, idempotency key, original receipt replay |
| Tool-schema or artifact drift | artifact identity on root span, certificate verification, WATCHTOWER suspension |
| Missing authorization telemetry | trace matching, evidence completeness threshold, fail-closed `UNKNOWN` |
| Cross-tenant memory contamination | tenant and data-label policy, metamorphic isolation test |
| Authority laundering through delegation | parent/child certificate verification, authority conservation, OPA + GATE denial |
| Cycles and excessive delegation depth | chain cycle detection and maximum-depth policy |
| Evidence tampering or omission | independent planes, canonical digests, trace-linked decision records |
| Alert replay or duplicate delivery | signed webhook verification and idempotent rollback |
| Private data leakage to telemetry | Collector allowlist, hashing, redaction, payload limits |

## Trust assumptions

- the development host and Docker daemon are trusted for the hackathon demonstration
- the committed public key corresponds to the locally generated development private key
- SigNoz and ClickHouse are reachable and required sensors report healthy
- synthetic fixture clocks are sufficiently synchronized for short-lived capabilities
- MinIO and PostgreSQL checksums accurately reflect persisted local artifacts

If required evidence is absent or a required sensor is unhealthy, ORBITAL Σ returns `UNKNOWN` or refuses certification; it does not infer success.
