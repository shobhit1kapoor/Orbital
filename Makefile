SHELL := /bin/bash
COMPOSE := docker compose --env-file .env -f infra/docker-compose.yaml

.PHONY: bootstrap dev down seed certify hero-demo inject-drift verify reset-demo test build signoz provision-signoz

bootstrap:
	./demo/bootstrap.sh

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

reset-demo:
	$(COMPOSE) down --remove-orphans
	-docker volume rm infra_postgres-data infra_redis-data infra_minio-data
	-docker compose -f pours/deployment/compose.yaml down -v --remove-orphans
	rm -rf data/demo-output missions/baseline/*.json missions/regressions/*.json
