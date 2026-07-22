#!/usr/bin/env bash
set -euo pipefail

command -v docker >/dev/null || { echo "Docker Engine is required inside Ubuntu/WSL2."; exit 1; }
command -v foundryctl >/dev/null || { echo "Install Foundry: curl -fsSL https://signoz.io/foundry.sh | bash"; exit 1; }
command -v pnpm >/dev/null || corepack enable

test -f .env || cp .env.example .env
mkdir -p secrets missions/baseline missions/adversarial missions/regressions data/demo-output

foundryctl cast -f casting.yaml
docker compose -f infra/docker-compose.yaml up --build -d
docker compose -f infra/docker-compose.yaml exec -T ollama ollama pull qwen3:8b
python demo/wait_for_services.py
python demo/run_hero_demo.py --phase seed
echo "ORBITAL Sigma ready at http://localhost:3000"
