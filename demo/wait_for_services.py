from __future__ import annotations

import os
import time

import httpx

HOSTS = [
    (os.getenv("CONTROL_PLANE_URL", "http://localhost:8001"), "/health"),
    (os.getenv("AGENT_RUNTIME_URL", "http://localhost:8002"), "/health"),
    (os.getenv("ACTION_GATEWAY_URL", "http://localhost:8003"), "/health"),
    (os.getenv("EVIDENCE_RECONCILER_URL", "http://localhost:8004"), "/health"),
    (os.getenv("CAPSULE_BUILDER_URL", "http://localhost:8005"), "/health"),
    (os.getenv("REPLAY_ORCHESTRATOR_URL", "http://localhost:8006"), "/health"),
    (os.getenv("ADVERSARIAL_FOUNDRY_URL", "http://localhost:8007"), "/health"),
    (os.getenv("CAUSAL_ENGINE_URL", "http://localhost:8008"), "/health"),
    (os.getenv("CERTIFIER_URL", "http://localhost:8009"), "/health"),
    (os.getenv("WATCHTOWER_URL", "http://localhost:8010"), "/health"),
    (os.getenv("WATCHTOWER_RELAY_URL", "http://watchtower-relay:8000"), "/health"),
    (os.getenv("MOCK_MCP_URL", "http://localhost:8011"), "/health"),
    (os.getenv("MOCK_REFUND_URL", "http://localhost:8012"), "/health"),
]

for base_url, path in HOSTS:
    url = f"{base_url.rstrip('/')}{path}"
    for _attempt in range(60):
        try:
            response = httpx.get(url, timeout=1)
            if response.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        raise SystemExit(f"Service did not become healthy: {url}")

print("All ORBITAL services are healthy.")
