# Development validation — 2026-07-22

This record captures the development checkpoint that prepared Phase 1 for its authoritative native Ubuntu run. It is not a native-VM acceptance record and does not mark Phase 1 complete.

## Clean baseline

- Commit, remote branch, and `deployment-checkpoint-1` tag: `35a3dfa5978808e5af7856cef36b480ab0a0085e`.
- `make reset-demo`: 38.40 seconds.
- `make bootstrap`: 54.52 seconds.
- `make verify`: 11.76 seconds.
- Total clean baseline: 104.68 seconds.
- Tests: 15 passed; Ruff passed; Next.js production build passed; Compose and Collector validation passed.
- All 21 ORBITAL application containers with declared health checks were healthy. SigNoz, ClickHouse, PostgreSQL, and Keeper were healthy; the SigNoz ingester was running.

The first bootstrap exposed concurrent SQLAlchemy schema creation across services. A PostgreSQL transaction-scoped advisory lock now serializes that temporary bootstrap path.

## Development OBI control

Environment: WSL2 kernel `6.18.33.2-microsoft-standard-WSL2`, x86_64, readable BTF, and mounted bpffs. WSL2 is explicitly non-authoritative.

`make verify-obi` passed in 39.6 seconds for trace `5be5b7ca3aa98bda0d905635bc1a85b9`. SigNoz stored and the reconciler derived:

- SDK semantic action: `store_credit`;
- OBI-observed local effect: `issue_refund`;
- correlated OPA decision: absent;
- Ed25519 effect receipt: verified;
- evidence state: `CONTRADICTED`;
- all required sensors: complete.

Pausing the OBI container caused `make verify-obi` to exit non-zero. After OBI was resumed, a fresh trace passed again. A complete hero workflow subsequently passed in 36.34 seconds.

Final quality gate after these changes: 15 tests passed in 0.34 seconds, Ruff passed, the production UI build passed, and Compose and Collector configuration validation passed in 12.42 seconds.

## Remaining acceptance step

Run `make verify-obi` on the dedicated native Ubuntu VM described in `docs/obi-native-ubuntu.md`. Record its kernel, BTF, capability state, container health, trace ID, SigNoz evidence link, command duration, and negative control before marking Phase 1 complete or beginning Phase 2.
