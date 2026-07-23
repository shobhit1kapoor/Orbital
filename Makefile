SHELL := /bin/bash
COMPOSE := docker compose --env-file .env -f infra/docker-compose.yaml

.PHONY: bootstrap dev down seed certify hero-demo inject-drift verify verify-obi verify-alerts campaign pause-campaign resume-campaign recover-campaign verify-campaign generate-capsules run-range verify-metamorphic reset-demo test build signoz provision-signoz

bootstrap:
	bash ./demo/bootstrap.sh

signoz:
	foundryctl cast -f casting.yaml

dev:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

seed:
	$(COMPOSE) --profile tools run --rm demo-runner python /workspace/demo/run_hero_demo.py --phase seed

certify:
	$(COMPOSE) --profile tools run --rm demo-runner python /workspace/demo/run_hero_demo.py --phase certify

hero-demo:
	$(COMPOSE) --profile tools run --rm demo-runner python /workspace/demo/run_hero_demo.py --phase all

provision-signoz:
	$(COMPOSE) --profile tools run --rm -e SIGNOZ_MCP_URL=http://signoz-mcp:8000/mcp demo-runner python /workspace/demo/provision_signoz.py

inject-drift:
	$(COMPOSE) --profile tools run --rm demo-runner python /workspace/demo/run_hero_demo.py --phase drift

test:
	$(COMPOSE) --profile tools build demo-runner
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner pytest -q
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner ruff check .

build:
	$(COMPOSE) build mission-control

verify: test build
	$(COMPOSE) config --quiet
	$(COMPOSE) run --rm --no-deps otel-collector validate --config=/etc/otelcol/config.yaml

verify-obi:
	@test "$$(uname -s)" = "Linux" || (echo "OBI requires Linux"; exit 1)
	@test -r /sys/kernel/btf/vmlinux || (echo "OBI requires kernel BTF at /sys/kernel/btf/vmlinux"; exit 1)
	@mountpoint -q /sys/fs/bpf || (echo "bpffs is not mounted; run: sudo mount -t bpf bpf /sys/fs/bpf"; exit 1)
	$(COMPOSE) --profile obi up -d opa agent-runtime mock-mcp-tool mock-refund-service evidence-reconciler
	# Recreate OBI after application services so eBPF probes attach to their
	# current PIDs even when Compose replaced a Python service container.
	$(COMPOSE) --profile obi up -d --force-recreate obi
	@sleep 20
	$(COMPOSE) --profile tools build demo-runner
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner python /workspace/demo/verify_obi.py

verify-alerts:
	@test "$$(uname -s)" = "Linux" || (echo "Live SigNoz alert verification requires Linux"; exit 1)
	$(COMPOSE) --profile tools build control-plane watchtower watchtower-relay demo-runner
	$(COMPOSE) up -d control-plane watchtower watchtower-relay signoz-mcp
	$(MAKE) provision-signoz
	@set -euo pipefail; \
		$(COMPOSE) --profile obi up -d --force-recreate obi; \
		sleep 20; \
		docker pause infra-obi-1 >/dev/null; \
		trap 'docker unpause infra-obi-1 >/dev/null 2>&1 || true' EXIT; \
		$(COMPOSE) --profile tools run --rm --no-deps demo-runner \
			python /workspace/demo/verify_alerts.py

campaign:
	$(COMPOSE) up --build -d postgres redis minio otel-collector capsule-builder adversarial-foundry replay-orchestrator replay-worker
	$(COMPOSE) restart otel-collector
	$(COMPOSE) --profile tools build demo-runner
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner \
		python /workspace/demo/phase3_campaign.py create

pause-campaign:
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner \
		python /workspace/demo/phase3_campaign.py pause

resume-campaign:
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner \
		python /workspace/demo/phase3_campaign.py resume

recover-campaign:
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner \
		python /workspace/demo/phase3_campaign.py recover

verify-campaign:
	$(MAKE) campaign
	$(MAKE) pause-campaign
	@sleep 4
	$(COMPOSE) stop minio
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner \
		python /workspace/demo/phase3_campaign.py storage-check
	$(COMPOSE) start minio
	$(COMPOSE) restart redis postgres replay-worker replay-orchestrator
	$(COMPOSE) up -d --wait postgres redis minio replay-worker replay-orchestrator
	$(MAKE) resume-campaign
	@sleep 1
	$(MAKE) pause-campaign
	$(COMPOSE) restart replay-worker replay-orchestrator
	$(COMPOSE) up -d --wait replay-worker replay-orchestrator
	$(MAKE) recover-campaign
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner \
		python /workspace/demo/verify_campaign.py

generate-capsules:
	$(COMPOSE) up --build -d postgres redis minio otel-collector capsule-builder adversarial-foundry
	$(COMPOSE) --profile tools build demo-runner
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner \
		python /workspace/demo/generate_capsules.py

run-range: generate-capsules
	$(COMPOSE) up --build -d postgres redis minio otel-collector adversarial-foundry replay-orchestrator replay-worker
	$(COMPOSE) restart otel-collector
	$(COMPOSE) --profile tools build demo-runner
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner \
		python /workspace/demo/run_range.py

verify-metamorphic: run-range
	$(COMPOSE) up --build -d postgres redis minio otel-collector replay-orchestrator replay-worker
	$(COMPOSE) restart otel-collector
	$(COMPOSE) --profile tools build demo-runner
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner \
		python /workspace/demo/verify_metamorphic.py

reset-demo:
	$(COMPOSE) down --remove-orphans
	-docker volume rm infra_postgres-data infra_redis-data infra_minio-data
	-docker compose -f pours/deployment/compose.yaml down -v --remove-orphans
	rm -rf data/demo-output missions/baseline/*.json missions/regressions/*.json
