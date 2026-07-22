from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import httpx

BASE_URL = os.getenv("SIGNOZ_URL", "http://localhost:8080").rstrip("/")
EMAIL = os.getenv("SIGNOZ_ADMIN_EMAIL", "orbital-admin@example.local")
PASSWORD = os.getenv("SIGNOZ_ADMIN_PASSWORD", "Orbital-Local-Admin!2026")
ACCOUNT_NAME = "orbital-mcp"
ENV_FILE = Path(os.getenv("ORBITAL_ENV_FILE", "/workspace/.env"))


def request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, f"{BASE_URL}{path}", headers=headers, **kwargs)
    if response.is_error:
        raise RuntimeError(
            f"SigNoz API {method} {path} failed with {response.status_code}: {response.text}"
        )
    if not response.content:
        return {}
    body = response.json()
    if body.get("status") == "error":
        raise RuntimeError(body["error"].get("message", f"SigNoz API failed: {path}"))
    return body


def wait_for_signoz(client: httpx.Client) -> dict[str, Any]:
    for _ in range(120):
        try:
            return request(client, "GET", "/api/v1/version")
        except (httpx.HTTPError, RuntimeError):
            time.sleep(1)
    raise RuntimeError("SigNoz did not become ready within 120 seconds")


def replace_env(name: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8-sig").splitlines()
    replacement = f"{name}={value}"
    for index, line in enumerate(lines):
        if line.startswith(f"{name}="):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def key_is_valid(client: httpx.Client, key: str) -> bool:
    if not key or key.startswith("replace-"):
        return False
    response = client.get(
        f"{BASE_URL}/api/v1/dashboards",
        headers={"SIGNOZ-API-KEY": key},
    )
    return response.status_code == 200


def main() -> None:
    with httpx.Client(timeout=30) as client:
        version = wait_for_signoz(client)
        setup_complete = bool(version.get("setupCompleted"))
        if not setup_complete:
            registered = request(
                client,
                "POST",
                "/api/v1/register",
                json={
                    "email": EMAIL,
                    "orgDisplayName": "ORBITAL Sigma Local",
                    "password": PASSWORD,
                },
            )
            org_id = registered["data"]["orgId"]
        else:
            context = request(
                client,
                "GET",
                "/api/v2/sessions/context",
                params={"email": EMAIL, "ref": BASE_URL},
            )
            organizations = context.get("data", {}).get("orgs", [])
            if not organizations:
                raise RuntimeError(f"SigNoz is initialized but {EMAIL} is not registered")
            org_id = organizations[0]["id"]

        login = request(
            client,
            "POST",
            "/api/v2/sessions/email_password",
            json={"email": EMAIL, "password": PASSWORD, "orgId": org_id},
        )
        token = login["data"]["accessToken"]
        current_key = os.getenv("SIGNOZ_API_KEY", "")
        if key_is_valid(client, current_key):
            print("SigNoz local admin and service-account key are ready.")
            return

        accounts = request(client, "GET", "/api/v1/service_accounts", token=token)["data"]
        account = next((item for item in accounts if item["name"] == ACCOUNT_NAME), None)
        if account is None:
            account = request(
                client,
                "POST",
                "/api/v1/service_accounts",
                token=token,
                json={"name": ACCOUNT_NAME},
            )["data"]

        roles = request(client, "GET", "/api/v1/roles", token=token)["data"]
        admin_role = next(role for role in roles if role["name"] == "signoz-admin")
        assigned = request(
            client,
            "GET",
            f"/api/v1/service_accounts/{account['id']}/roles",
            token=token,
        )["data"]
        if admin_role["id"] not in {role["id"] for role in assigned}:
            request(
                client,
                "POST",
                f"/api/v1/service_accounts/{account['id']}/roles",
                token=token,
                json={"id": admin_role["id"]},
            )

        created_key = request(
            client,
            "POST",
            f"/api/v1/service_accounts/{account['id']}/keys",
            token=token,
            json={"name": f"orbital-bootstrap-{int(time.time())}", "expiresAt": 0},
        )["data"]["key"]
        replace_env("SIGNOZ_API_KEY", created_key)
        print("SigNoz local admin and service-account key are ready.")


if __name__ == "__main__":
    main()
