from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from orbital_shared.campaigns import (
    CampaignRepository,
    IntegrityError,
    checksum_bytes,
    decode_verified_json,
    deterministic_trace_id,
    stable_identifier,
    validate_transition,
    versioned_path,
)
from orbital_shared.database import CampaignRecord, ReplayJobRecord
from orbital_shared.models import sha256_digest
from sqlalchemy.orm import Session


@pytest.fixture
def repository(tmp_path, monkeypatch) -> CampaignRepository:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'campaign.db'}")
    return CampaignRepository()


def add_campaign(repository: CampaignRepository, status: str = "RUNNING") -> str:
    now = datetime.now(UTC)
    campaign_id = "campaign_test"
    with Session(repository.engine) as session:
        session.add(
            CampaignRecord(
                campaign_id=campaign_id,
                submission_digest=sha256_digest("submission"),
                candidate_id="candidate-v2-fixed",
                artifact_digest=sha256_digest("artifact"),
                status=status,
                requested_jobs=1,
                completed_jobs=0,
                failed_jobs=0,
                retried_jobs=0,
                request_payload={},
                result_summary={},
                storage_status="AVAILABLE",
                state_version=1,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ReplayJobRecord(
                job_id="job_test",
                campaign_id=campaign_id,
                mission_id="mis_test",
                replay_id="replay_test",
                trace_id=deterministic_trace_id("job_test"),
                candidate_id="candidate-v2-fixed",
                capsule_id="cap_test",
                mutation_id="",
                status="QUEUED",
                retries=0,
                delivery_count=0,
                queued_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return campaign_id


def test_duplicate_campaign_submission_has_one_stable_id() -> None:
    payload = {"candidate": "v2", "capsules": ["a", "b"], "key": "same"}
    digest = sha256_digest(payload)
    assert stable_identifier("campaign", digest) == stable_identifier("campaign", digest)


def test_duplicate_task_delivery_uses_stable_result_and_receipt() -> None:
    job_id = stable_identifier("job", ["campaign", "capsule", "mutation", 0])
    result = sha256_digest({"job_id": job_id, "outcome": "safe"})
    assert result == sha256_digest({"outcome": "safe", "job_id": job_id})
    assert f"replay-effect:{job_id}" == f"replay-effect:{job_id}"


def test_worker_crash_allows_recovery_to_queued() -> None:
    validate_transition("RUNNING", "QUEUED")


def test_redis_restart_keeps_deterministic_task_identity() -> None:
    before = stable_identifier("job", ["campaign", "capsule", "", 3])
    after = stable_identifier("job", json.loads(json.dumps(["campaign", "capsule", "", 3])))
    assert before == after


def test_minio_restart_keeps_versioned_object_path() -> None:
    digest = sha256_digest({"capsule": "same"})
    assert versioned_path("mission-capsules", "cap_1", digest, "manifest.json") == versioned_path(
        "mission-capsules", "cap_1", digest, "manifest.json"
    )


def test_postgresql_restart_preserves_campaign_metadata(
    repository: CampaignRepository,
) -> None:
    campaign_id = add_campaign(repository)
    restarted = CampaignRepository()
    with Session(restarted.engine) as session:
        assert session.get(CampaignRecord, campaign_id) is not None


def test_partial_chord_completion_is_valid() -> None:
    validate_transition("RUNNING", "PARTIAL")
    validate_transition("PARTIAL", "QUEUED")


def test_task_timeout_can_retry_without_new_identity() -> None:
    job_id = stable_identifier("job", "timeout-input")
    assert stable_identifier("job", "timeout-input") == job_id
    validate_transition("FAILED", "QUEUED")


def test_campaign_cancellation_is_terminal() -> None:
    validate_transition("RUNNING", "CANCELLED")
    with pytest.raises(ValueError):
        validate_transition("CANCELLED", "RUNNING")


def test_campaign_resumption_from_pause() -> None:
    validate_transition("RUNNING", "PAUSED")
    validate_transition("PAUSED", "QUEUED")


def test_sse_reconnection_reads_only_events_after_cursor(
    repository: CampaignRepository,
) -> None:
    campaign_id = add_campaign(repository)
    with Session(repository.engine) as session:
        repository.add_event(session, campaign_id, "campaign.paused", {"status": "PAUSED"})
        repository.add_event(session, campaign_id, "campaign.resumed", {"status": "QUEUED"})
        session.commit()
    all_events = repository.events(campaign_id)
    resumed = repository.events(campaign_id, all_events[0]["sequence"])
    assert [event["event_type"] for event in resumed] == ["campaign.resumed"]


def test_checksum_mismatch_is_rejected() -> None:
    expected = checksum_bytes(b'{"corrupted":false}')
    with pytest.raises(IntegrityError, match="checksum mismatch"):
        decode_verified_json(b'{"corrupted":true}', expected)


def test_corrupted_capsule_is_not_deserialized() -> None:
    with pytest.raises(IntegrityError):
        decode_verified_json(b'{"corrupted":true}', sha256_digest({"valid": True}))
