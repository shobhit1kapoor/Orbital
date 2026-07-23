# Privacy and Limitations

## Privacy controls

- Synthetic customer, order, tenant, payment, and identity records only.
- Collector-side allowlists for assurance attributes.
- Hashing of stable identifiers before telemetry export.
- Redaction and payload-size limits.
- No raw private prompts, capability tokens, credentials, payment data, or customer identity in SigNoz.
- Trace-aware sampling retains all critical, mismatch, certificate, drift, and irreversible-action traces; 20% of medium-risk and 5% of successful low-risk traces.
- OBI observes only the project’s local containers and native Ubuntu demo VM.

## Execution labels

Mission Control and final evidence distinguish:

- `live`
- `recorded_replay`
- `deterministic_simulation`
- `counterfactual`
- `UNKNOWN`

These labels are part of the evidence contract. A deterministic result is never described as a live model observation.

## Limitations

1. All consequential effects are local synthetic fixtures.
2. The mission corpus is representative by construction, not sampled from a production customer population.
3. Bounded causal attribution estimates contribution within the implemented fixture; it is not a universal causal claim about Qwen3.
4. The hero minimizer supports one reproducible refund failure.
5. Recorded replay and deterministic fallback are used when the laptop-hosted Ollama endpoint is unavailable.
6. Native OBI sees protocol and network behavior. Exact business semantics require correlated SDK and receipt evidence.
7. Development Ed25519 keys are not production key management.
8. The Azure VM is a reproducibility host, not a hardened production deployment.
9. Confidence intervals and thresholds are contract-specific.
10. Long-term cross-organization trust, hardware attestation, production HSM integration, and broader mission domains remain future work.
