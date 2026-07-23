from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import yaml
from fastapi import HTTPException
from orbital_contract import compile_contract
from orbital_shared.api import create_service
from orbital_shared.database import ObjectStore, RolloutState
from orbital_shared.models import ArtifactIdentity, utcnow
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

app = create_service("ORBITAL Σ Control Plane", "orbital-control-plane")
store = ObjectStore()
campaign_events: dict[str, asyncio.Queue[dict[str, Any]]] = {}
SERVICES = {
    "certifier": os.getenv("CERTIFIER_URL", "http://certifier:8000"),
    "watchtower": os.getenv("WATCHTOWER_URL", "http://watchtower:8000"),
}


class ContractBody(BaseModel):
    yaml_text: str | None = None


class CampaignBody(BaseModel):
    candidate_id: str
    live_runs: int = 120
    generated_runs: int = 880
    adaptive_attacks: int = 64


class RolloutBody(BaseModel):
    candidate_id: str
    certificate_id: str
    percentage: int


@app.post("/v1/contracts/compile")
def compile_mission_contract(body: ContractBody) -> dict[str, Any]:
    if body.yaml_text:
        raw = yaml.safe_load(body.yaml_text)
    else:
        path = Path(os.getenv("MISSION_CONTRACT", "/workspace/contracts/refund-agent.yaml"))
        if not path.exists():
            path = Path("contracts/refund-agent.yaml")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    result = compile_contract(raw)
    store.put(
        result.contract_digest,
        "contract",
        result.as_dict(),
        result.contract.created_at,
    )
    return result.as_dict()


@app.post("/v1/candidates/register")
def register_candidate(artifact: ArtifactIdentity) -> dict[str, Any]:
    candidate_id = f"candidate-{artifact.agent_commit[:8]}-{artifact.prompt_hash[-6:]}"
    payload = {"candidate_id": candidate_id, "artifact": artifact.model_dump(mode="json")}
    store.put(candidate_id, "candidate", payload, artifact.created_at)
    return payload


async def _simulate_campaign(campaign_id: str, body: CampaignBody) -> None:
    queue = campaign_events[campaign_id]
    phases = [
        ("CAPSULE", body.live_runs),
        ("RANGE", body.generated_runs),
        ("ADAPTIVE", body.adaptive_attacks),
        ("FORK", 5),
        ("FRONTIER", 6),
        ("CLEARANCE", 1),
    ]
    completed = 0
    total = sum(count for _, count in phases)
    for phase, count in phases:
        await queue.put(
            {"phase": phase, "status": "started", "completed": completed, "total": total}
        )
        await asyncio.sleep(0.05)
        completed += count
        await queue.put(
            {"phase": phase, "status": "completed", "completed": completed, "total": total}
        )
    payload = store.get(campaign_id) or {}
    payload["status"] = "completed"
    payload["completed_at"] = utcnow().isoformat()
    store.put(campaign_id, "campaign", payload, utcnow())
    await queue.put({"phase": "DONE", "status": "completed", "completed": total, "total": total})


@app.post("/v1/campaigns")
async def create_campaign(body: CampaignBody) -> dict[str, Any]:
    campaign_id = f"campaign_{uuid4().hex[:12]}"
    campaign_events[campaign_id] = asyncio.Queue()
    payload = {
        "campaign_id": campaign_id,
        "status": "running",
        "candidate_id": body.candidate_id,
        "live_runs": body.live_runs,
        "generated_runs": body.generated_runs,
        "adaptive_attacks": body.adaptive_attacks,
        "created_at": utcnow().isoformat(),
    }
    store.put(campaign_id, "campaign", payload, utcnow())
    asyncio.create_task(_simulate_campaign(campaign_id, body))
    return payload


@app.get("/v1/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict[str, Any]:
    campaign = store.get(campaign_id)
    if not campaign:
        raise HTTPException(404, "campaign not found")
    return campaign


@app.get("/v1/campaigns/{campaign_id}/events")
async def stream_campaign(campaign_id: str) -> EventSourceResponse:
    if campaign_id not in campaign_events:
        raise HTTPException(404, "campaign not found")

    async def events():
        queue = campaign_events[campaign_id]
        while True:
            event = await queue.get()
            yield {"event": "campaign", "data": json.dumps(event)}
            if event["phase"] == "DONE":
                break

    return EventSourceResponse(events())


@app.post("/v1/certifications")
async def certify(payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{SERVICES['certifier']}/v1/certificates/issue", json=payload)
        response.raise_for_status()
        return response.json()


@app.get("/v1/certificates/{certificate_id}")
def certificate(certificate_id: str) -> dict[str, Any]:
    value = store.get(certificate_id)
    if not value:
        raise HTTPException(404, "certificate not found")
    return value


@app.post("/v1/rollouts")
async def rollout(body: RolloutBody) -> dict[str, Any]:
    if not 0 <= body.percentage <= 100:
        raise HTTPException(422, "percentage must be between 0 and 100")
    payload = body.model_dump() | {"updated_at": utcnow().isoformat()}
    store.put("active-rollout", "rollout", payload, utcnow())
    with Session(store.engine) as session:
        state = session.get(RolloutState, "orbital.candidate.enabled")
        if state is None:
            state = RolloutState(
                flag="orbital.candidate.enabled",
                candidate_id=body.candidate_id,
                enabled=body.percentage > 0,
                percentage=body.percentage,
                certificate_id=body.certificate_id,
            )
            session.add(state)
        else:
            state.candidate_id = body.candidate_id
            state.enabled = body.percentage > 0
            state.percentage = body.percentage
            state.certificate_id = body.certificate_id
        session.commit()
    return payload


@app.get("/v1/mission-control/summary")
def summary() -> dict[str, Any]:
    campaigns = store.list("campaign", 5)
    certificates = store.list("certificate", 5)
    rollout = store.get("active-rollout")
    return {"campaigns": campaigns, "certificates": certificates, "rollout": rollout}
