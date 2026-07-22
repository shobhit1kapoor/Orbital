from orbital_shared.models import ArtifactIdentity, sha256_digest


def test_assurance_digest_ignores_creation_time():
    payload = dict(
        agent_commit="abc",
        container_digest="sha256:container",
        prompt_hash="sha256:prompt",
        model_identifier="qwen3:8b",
        model_digest="sha256:model",
        model_parameters_hash="sha256:params",
        tool_schema_hash="sha256:tool",
        policy_bundle_hash="sha256:policy",
        collector_config_hash="sha256:collector",
        mission_dataset_hash="sha256:missions",
    )
    assert ArtifactIdentity(**payload).digest == ArtifactIdentity(**payload).digest


def test_hashing_uses_canonical_json_order():
    assert sha256_digest({"a": 1, "b": 2}) == sha256_digest({"b": 2, "a": 1})
