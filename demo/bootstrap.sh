#!/usr/bin/env bash
set -euo pipefail

command -v docker >/dev/null || { echo "Docker Engine is required inside Ubuntu/WSL2."; exit 1; }
command -v foundryctl >/dev/null || { echo "Install Foundry: curl -fsSL https://signoz.io/foundry.sh | bash"; exit 1; }

test -f .env || cp .env.example .env
mkdir -p secrets missions/baseline missions/adversarial missions/regressions data/demo-output

replace_placeholder() {
  local key="$1"
  local placeholder="$2"
  local value="$3"
  if grep -q "^${key}=${placeholder}$" .env; then
    sed -i "s|^${key}=.*$|${key}=${value}|" .env
  fi
}

replace_placeholder "MINIO_SECRET_KEY" "change-me" "$(openssl rand -hex 24)"
replace_placeholder "ORBITAL_WEBHOOK_SECRET" "change-me" "$(openssl rand -hex 32)"
replace_placeholder "LOCAL_FIXTURE_KEY" "change-me-local-fixture-only" "$(openssl rand -hex 32)"
replace_placeholder \
  "SIGNOZ_ADMIN_PASSWORD" \
  "replace-with-bootstrap-generated-password" \
  "Orbital!$(openssl rand -hex 20)A1"
if ! grep -q '^SIGNOZ_ADMIN_PASSWORD=' .env; then
  printf 'SIGNOZ_ADMIN_PASSWORD=Orbital!%sA1\n' "$(openssl rand -hex 20)" >> .env
fi

compose=(docker compose --env-file .env -f infra/docker-compose.yaml)

foundryctl cast -f casting.yaml
"${compose[@]}" up --build -d
"${compose[@]}" --profile tools build demo-runner
"${compose[@]}" --profile tools run --rm \
  -e SIGNOZ_URL=http://orbital-signoz-0:8080 \
  -e ORBITAL_ENV_FILE=/workspace/.env \
  demo-runner python /workspace/demo/bootstrap_signoz.py
"${compose[@]}" up -d --force-recreate signoz-mcp
"${compose[@]}" exec -T ollama ollama pull qwen3:8b
"${compose[@]}" --profile tools run --rm \
  demo-runner python /workspace/demo/wait_for_services.py
"${compose[@]}" --profile tools run --rm \
  -e SIGNOZ_MCP_URL=http://signoz-mcp:8000/mcp \
  demo-runner python /workspace/demo/provision_signoz.py
"${compose[@]}" --profile tools run --rm \
  demo-runner python /workspace/demo/run_hero_demo.py --phase seed
echo "ORBITAL Sigma ready at http://localhost:3000"
