from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import Header, HTTPException, Query, Request
from orbital_contract import compile_contract
from orbital_shared.api import create_service
from orbital_shared.campaigns import TERMINAL_STATES, CampaignRepository
from orbital_shared.database import (
    CampaignRecord,
    CapsuleRecord,
    ObjectStore,
    RolloutState,
)
from orbital_shared.models import ArtifactIdentity, utcnow
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

app = create_service("ORBITAL Σ Control Plane", "orbital-control-plane")
store = ObjectStore()
campaigns = CampaignRepository()
SERVICES = {
    "certifier": os.getenv("CERTIFIER_URL", "http://certifier:8000"),
    "watchtower": os.getenv("WATCHTOWER_URL", "http://watchtower:8000"),
    "replay": os.getenv("REPLAY_ORCHESTRATOR_URL", "http://replay-orchestrator:8000"),
}


class ContractBody(BaseModel):
    yaml_text: str | None = None


class CampaignBody(BaseModel):
    candidate_id: str
    artifact_digest: str = "sha256:phase3-local"
    capsule_ids: list[str] = Field(default_factory=list)
    mutation_ids: list[str] = Field(default_factory=list)
    submission_key: str = "control-plane"
    job_delay_ms: int = 0
    fail_once_indices: list[int] = Field(default_factory=list)
    start_paused: bool = False
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


@app.post("/v1/campaigns")
async def create_campaign(body: CampaignBody) -> dict[str, Any]:
    payload = body.model_dump(exclude={"live_runs", "generated_runs", "adaptive_attacks"})
    if not payload["capsule_ids"]:
        with Session(store.engine) as session:
            payload["capsule_ids"] = list(
                session.scalars(
                    select(CapsuleRecord.capsule_id)
                    .order_by(CapsuleRecord.created_at)
                    .limit(body.live_runs)
                ).all()
            )
    if not payload["capsule_ids"]:
        raise HTTPException(422, "no persisted capsules are available")
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{SERVICES['replay']}/v1/campaigns", json=payload)
        if response.status_code >= 400:
            raise HTTPException(response.status_code, response.text)
        return response.json()


@app.get("/v1/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict[str, Any]:
    with Session(campaigns.engine) as session:
        campaign = session.get(CampaignRecord, campaign_id)
        if not campaign:
            raise HTTPException(404, "campaign not found")
        payload = campaigns.campaign_payload(session, campaign)
        session.commit()
        return payload


@app.get("/v1/campaigns/{campaign_id}/events")
async def stream_campaign(
    request: Request,
    campaign_id: str,
    after: int = Query(default=0, ge=0),
    once: bool = False,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    get_campaign(campaign_id)
    cursor = int(last_event_id or after)

    async def events():
        nonlocal cursor
        while True:
            rows = campaigns.events(campaign_id, cursor)
            for event in rows:
                cursor = event["sequence"]
                yield {
                    "id": str(cursor),
                    "event": event["event_type"],
                    "data": json.dumps(event),
                }
            snapshot = get_campaign(campaign_id)
            if once:
                if not rows:
                    yield {
                        "id": str(cursor),
                        "event": "campaign.snapshot",
                        "data": json.dumps(snapshot),
                    }
                break
            if snapshot["status"] in TERMINAL_STATES and not rows:
                break
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.5)

    return EventSourceResponse(events(), ping=5)


@app.post("/v1/certifications")
async def certify(payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{SERVICES['certifier']}/v1/certificates/issue",
            json=payload,
        )
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
    with Session(campaigns.engine) as session:
        campaign_rows = session.scalars(
            select(CampaignRecord).order_by(CampaignRecord.created_at.desc()).limit(5)
        ).all()
        campaign_payloads = [
            campaigns.campaign_payload(session, campaign) for campaign in campaign_rows
        ]
        session.commit()
    certificates = store.list("certificate", 5)
    rollout_value = store.get("active-rollout")
    return {
        "campaigns": campaign_payloads,
        "certificates": certificates,
        "rollout": rollout_value,
    }
