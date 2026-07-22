SHELL := /bin/bash
COMPOSE := docker compose -f infra/docker-compose.yaml

.PHONY: bootstrap dev down seed certify hero-demo inject-drift verify reset-demo test build signoz

bootstrap:
	./demo/bootstrap.sh

signoz:
	foundryctl cast -f casting.yaml

dev:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

seed:
	python demo/run_hero_demo.py --phase seed

certify:
	python demo/run_hero_demo.py --phase certify

hero-demo:
	python demo/run_hero_demo.py --phase all

inject-drift:
	python demo/run_hero_demo.py --phase drift

test:
	pytest
	pnpm lint

build:
	pnpm build

verify: test build
	docker compose -f infra/docker-compose.yaml config --quiet

reset-demo:
	$(COMPOSE) down -v
	rm -rf data/demo-output missions/baseline/*.json missions/regressions/*.json
