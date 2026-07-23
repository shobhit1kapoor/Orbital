# ORBITAL Sigma

ORBITAL Sigma is a local, defensive flight-assurance system for autonomous agents. The original project plan remains the authoritative specification: this repository preserves all ten subsystems, the seven-screen Mission Control, the SigNoz evidence model, and the complete certification and runtime-attestation roadmap.

The current checkpoint provides a reproducible deployment foundation and an end-to-end local hero workflow. All identities, orders, customers, tools, payments, credentials, and datasets are synthetic fixtures. The intentionally vulnerable candidate can call only the local mock refund service; it contains no real payment integration or reusable external exploit logic.

## Quick start

Run this from native Docker Engine inside WSL2 Ubuntu (Docker Desktop integration is not supported for this project):

```bash
make reset-demo
make bootstrap
make hero-demo
```

`make bootstrap` generates local secrets, casts the pinned Foundry stack, starts SigNoz and the ORBITAL services, creates a local SigNoz service-account key, provisions dashboards and alerts through SigNoz MCP, pulls `qwen3:8b`, waits for health, and seeds the deterministic campaign.

Local entry points after bootstrap:

- Mission Control: <http://localhost:3000>
- SigNoz: <http://localhost:8080>
- Control Plane: <http://localhost:8001>
- OPA: <http://localhost:8181>
- MinIO console: <http://localhost:9001>
- Ollama: <http://localhost:11434>

Useful workflows:

```bash
make dev
make seed
make certify
make inject-drift
make provision-signoz
make verify
make verify-obi
make verify-alerts
make verify-campaign
make reset-demo
```

Generated campaign and provisioning evidence is written to `data/demo-output/`. Secrets and generated private keys remain ignored by Git.

## Executable checkpoint

The current local workflow executes real HTTP services and exports real OpenTelemetry spans through the project Collector into SigNoz. It demonstrates:

- deterministic ATLAS contract compilation and shared `orbital.*` conventions;
- a synthetic vulnerable trace whose declared `store_credit` action contradicts its locally observed `issue_refund` effect;
- GATE capability binding, expiry, tamper checks, single use, and idempotent local receipts;
- PARALLAX evidence reconciliation states;
- generation of 120 deterministic capsules and 880 mutation records, with an adaptive 64-attack set;
- deterministic replay, metamorphic result records, causal contributions, and a minimized regression;
- persistent PostgreSQL campaign metadata, versioned MinIO artifacts, Celery group/chord replay execution, recovery, and reconnectable SSE progress;
- six-point authority-frontier evaluation;
- Ed25519-signed CLEARANCE certificates;
- certificate-bound multi-agent delegation with authority, risk, tenant, and
  data-label conservation plus an idempotent authority-laundering denial demo;
- WATCHTOWER drift suspension and idempotent rollback;
- native Ubuntu OBI/eBPF evidence validation restricted to the project containers;
- six provisioned SigNoz dashboards and twelve alert rules;
- all seven Mission Control views backed by live APIs or explicitly labeled deterministic/replay/counterfactual results.

## Scope still under implementation

The full plan is intentionally not reduced. The following items remain advanced implementation work rather than claims of this checkpoint:

- broader SQLAlchemy/Alembic adoption and encrypted MinIO bundles across every service beyond the persistent campaign slice;
- complete OPA decision-log and signed tool-receipt parity reconstructed exclusively from queried SigNoz records;
- Qwen-guided adaptive search for all 880 mutations, 128-permutation sampled Shapley analysis, bootstrap confidence intervals, and full delta debugging;
- PostgreSQL-backed OpenFeature rollout state and complete safety-case evidence graph persistence;
- the full 1,000-mission statistical recertification run and threshold-near sequential trials;
- complete Playwright coverage and trace-matching asset provisioning.

These limitations are documented rather than silently deleting or weakening the original requirements.

## Verification

```bash
python -m pytest -q
python -m ruff check .
pnpm lint
pnpm build
docker compose --env-file .env -f infra/docker-compose.yaml config --quiet
docker exec infra-otel-collector-1 /otelcol-contrib validate --config=/etc/otelcol/config.yaml
```

The final Ubuntu OBI demo additionally requires kernel 5.8 or newer, BTF, host PID access, and the privileges declared by the `obi` Compose profile. OBI must observe only this project's local containers and VM.
