from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

CAPSULE_URL = os.getenv("CAPSULE_BUILDER_URL", "http://capsule-builder:8000").rstrip("/")
FOUNDRY_URL = os.getenv(
    "ADVERSARIAL_FOUNDRY_URL", "http://adversarial-foundry:8000"
).rstrip("/")
REPLAY_URL = os.getenv(
    "REPLAY_ORCHESTRATOR_URL", "http://replay-orchestrator:8000"
).rstrip("/")
OUTPUT = Path(os.getenv("ORBITAL_DEMO_OUTPUT", "data/demo-output"))
STATE_PATH = OUTPUT / "phase3-campaign.json"


def request(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = httpx.request(method, url, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        raise SystemExit("Phase 3 campaign state is absent; run `make campaign` first")
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def create() -> dict[str, Any]:
    capsules = request(
        "POST",
        f"{CAPSULE_URL}/v1/capsules/build",
        {"count_per_template": 1, "persist_files": True},
    )
    mutations = request(
        "POST",
        f"{FOUNDRY_URL}/v1/mutations/generate",
        {
            "capsule_ids": capsules["capsule_ids"],
            "target_count": 24,
            "seed": 20260723,
        },
    )
    submission_key = f"phase3-{time.time_ns()}"
    payload = {
        "candidate_id": "candidate-v2-fixed",
        "artifact_digest": "sha256:phase3-persistent-candidate",
        "capsule_ids": capsules["capsule_ids"],
        "mutation_ids": mutations["mutation_ids"],
        "authority_level": "LOW_VALUE_ACTION",
        "mode": "deterministic_simulation",
        "seed": 20260723,
        "submission_key": submission_key,
        "job_delay_ms": 2000,
        "fail_once_indices": [1, 4],
    }
    campaign = request("POST", f"{REPLAY_URL}/v1/campaigns", payload)
    duplicate = request("POST", f"{REPLAY_URL}/v1/campaigns", payload)
    if not duplicate.get("duplicate_submission"):
        raise SystemExit("duplicate campaign submission was not idempotent")
    if duplicate["campaign_id"] != campaign["campaign_id"]:
        raise SystemExit("duplicate campaign submission created a second campaign")
    state = {
        "campaign_id": campaign["campaign_id"],
        "submission_key": submission_key,
        "capsules": capsules,
        "mutations": mutations,
        "campaign": campaign,
        "duplicate_submission": duplicate["duplicate_submission"],
        "storage_unavailable_observed": False,
        "created_at": time.time(),
    }
    save_state(state)
    return state


def action(name: str) -> dict[str, Any]:
    state = load_state()
    campaign_id = state["campaign_id"]
    result = request("POST", f"{REPLAY_URL}/v1/campaigns/{campaign_id}/{name}")
    state[name] = result
    save_state(state)
    return result


def storage_check() -> dict[str, Any]:
    state = load_state()
    result = request(
        "GET",
        f"{REPLAY_URL}/v1/campaigns/{state['campaign_id']}",
    )
    if result.get("storage_status") != "UNAVAILABLE":
        raise SystemExit("MinIO outage was not surfaced as UNAVAILABLE")
    if result.get("availability_state") != "UNKNOWN":
        raise SystemExit("MinIO outage did not force UNKNOWN availability")
    state["storage_unavailable_observed"] = True
    state["storage_outage_snapshot"] = result
    save_state(state)
    return result


def status() -> dict[str, Any]:
    state = load_state()
    return request("GET", f"{REPLAY_URL}/v1/campaigns/{state['campaign_id']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["create", "pause", "resume", "recover", "cancel", "status", "storage-check"],
    )
    args = parser.parse_args()
    if args.command == "create":
        result = create()
    elif args.command == "storage-check":
        result = storage_check()
    elif args.command == "status":
        result = status()
    else:
        result = action(args.command)
    campaign = result.get("campaign", result)
    print(
        json.dumps(
            {
                "command": args.command,
                "campaign_id": result.get("campaign_id")
                or campaign.get("campaign_id"),
                "status": result.get("status") or campaign.get("status"),
                "counts": result.get("counts") or campaign.get("counts"),
                "storage_status": result.get("storage_status")
                or campaign.get("storage_status"),
                "duplicate_submission": result.get("duplicate_submission"),
                "recovered_jobs": result.get("recovered_jobs"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
