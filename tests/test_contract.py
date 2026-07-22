from copy import deepcopy

import yaml
from orbital_contract import compile_contract


def load_contract():
    with open("contracts/refund-agent.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_contract_compilation_is_deterministic_across_mapping_order():
    original = load_contract()
    reordered = {key: deepcopy(original[key]) for key in reversed(list(original))}
    first = compile_contract(original)
    second = compile_contract(reordered)
    assert first.contract_digest == second.contract_digest
    assert first.normalized_json == second.normalized_json
    assert len(first.span_matrix) == 12


def test_contract_compiles_all_operational_outputs():
    compiled = compile_contract(load_contract())
    assert compiled.opa_data["orbital"]["contract_digest"] == compiled.contract_digest
    assert compiled.authority_tiers[-1]["name"] == "AUTONOMOUS_IRREVERSIBLE"
    assert compiled.openfeature_rules["maximum_canary_percentage"] == 5
    assert "UNKNOWN" not in compiled.ci_acceptance["accepted_verdicts"]
