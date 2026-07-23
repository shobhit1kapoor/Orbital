# Native Azure validation — 2026-07-22

This is the authoritative native-Linux OBI acceptance record for the isolated
ORBITAL Sigma fixture. It supplements, and does not replace, the original plan.

## Environment

- Subscription: Azure for Students (`Enabled`, spending limit `On`). The
  Sponsorship portal reported no active Sponsorship balance, so Azure did not
  expose a numeric remaining-credit value. A $75 monthly subscription budget
  with an Owner notification at 100% was installed as a second guardrail.
- VM: `orbital-sigma-vm`, `Standard_E4as_v4` (4 vCPU, 32 GiB), West US 2.
  Central US was rejected by the student-subscription deployment policy and
  South Central US lacked capacity. The resource group is
  `orbital-sigma-rg`.
- Host: Ubuntu 24.04.4 LTS, Azure kernel `6.17.0-1020-azure`, readable kernel
  BTF, mounted bpffs, Docker Engine 29.6.2, Compose 5.3.1.
- OBI: official `otel/ebpf-instrument:v0.10.0`, limited to the project's VM
  and local containers.
- LLM: laptop Ollama `qwen3:8b`, digest
  `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`,
  reached through the authenticated SSH reverse tunnel. No Ollama process or
  model was installed on the VM.

## Acceptance evidence

Positive `make verify-obi` completed in 73 seconds. Trace
`70952b892594fce2a7af5cf0a8c9b154` recorded the declared semantic
`store_credit` action, independently observed local `issue_refund` effect,
missing policy decision, verified Ed25519 receipt, and final
`CONTRADICTED` evidence state. All required sensors reported `PASS`.

For the negative test, `infra-obi-1` was paused and the freshness interval was
allowed to expire. `/v1/health/sensors` returned `obi: false`,
`complete: false`, and `state: UNKNOWN`; the OBI verifier exited 1 because the
refund effect was not independently observed. OBI was then unpaused.

The full local hero workflow completed successfully in 42 seconds with seed,
certification, and drift phases complete. `make verify` completed in 13
seconds: 15 tests passed, Ruff passed, Mission Control built, Compose rendered,
and the Collector configuration validated.

## Operations and cost controls

Azure auto-shutdown is an enabled `ComputeVmShutdownTask` at 06:00 UTC, which
deallocates the VM. SSH is the only NSG ingress and is restricted to the
operator's current public `/32`; `scripts/azure/start.ps1` refreshes that rule.
Use `scripts/azure/deallocate.ps1` immediately after validation. After the
hackathon, delete the entire resource group with
`scripts/azure/delete.ps1 -ConfirmDelete` to stop disk and public-IP charges.
