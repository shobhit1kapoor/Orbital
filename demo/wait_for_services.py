from __future__ import annotations

import time

import httpx

PORTS = range(8001, 8013)

for port in PORTS:
    url = f"http://localhost:{port}/health"
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
