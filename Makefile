SHELL := /bin/bash
COMPOSE := docker compose --env-file .env -f infra/docker-compose.yaml

.PHONY: bootstrap dev down seed certify hero-demo inject-drift verify verify-obi reset-demo test build signoz provision-signoz

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
	@sleep 8
	$(COMPOSE) --profile tools build demo-runner
	$(COMPOSE) --profile tools run --rm --no-deps demo-runner python /workspace/demo/verify_obi.py

reset-demo:
	$(COMPOSE) down --remove-orphans
	-docker volume rm infra_postgres-data infra_redis-data infra_minio-data
	-docker compose -f pours/deployment/compose.yaml down -v --remove-orphans
	rm -rf data/demo-output missions/baseline/*.json missions/regressions/*.json
