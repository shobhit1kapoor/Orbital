# Phase 8 Final Reproducibility and Submission Validation

**Date:** 2026-07-23

**Source baseline:** `102fcde20eeebd0d6ed02d033a4ff3f966068005`

**Release tag:** `v1.0.0`

**Result:** PASS

## Authoritative environment

Validation ran from a clean detached checkout on the native Ubuntu Azure VM:

- Azure VM: `Standard_E4as_v4`, Central US
- Ubuntu kernel: `6.17.0-1020-azure`
- Kernel BTF: readable
- Docker Engine: `29.6.2`
- Docker Compose: `5.3.1`
- SigNoz Foundry: `v0.2.16`
- Foundry inputs: committed `casting.yaml` and `casting.yaml.lock`
- Ollama mode: remote; no Ollama image, model, or container ran on the VM

Phase 8 changes were synchronized into the clean checkout before validation. Generated credentials, private signing material, PostgreSQL state, MinIO objects, and demo output remained untracked.

## Clean reproducibility

The stack was destroyed and reproduced from the committed Foundry definition. The clean bootstrap generated local secrets, applied migrations, provisioned SigNoz assets, created the deterministic corpus, and verified service health. An intentionally interrupted second bootstrap resumed through the existing idempotent recovery path and completed the remaining Celery chord without duplicate records.

Both clean-reset demonstration rehearsals passed. The first final demonstration completed in **28.677 seconds**; the final rehearsal completed in **27.730 seconds**. Both were below the three-minute target, excluding infrastructure startup.

## Validation results

| Gate | Result | Evidence |
| --- | --- | --- |
| `make verify` | PASS | 87 pytest tests; Ruff; ESLint; TypeScript; Next.js production build; Compose; Collector |
| `make verify-obi` | PASS | Native kernel observation; semantic `store_credit`; observed `issue_refund`; `CONTRADICTED` |
| `make verify-alerts` | PASS | 8 critical alert histories; signed webhook; duplicate delivery; suspension; zero traffic; baseline restoration |
| `make verify-campaign` | PASS | 1 campaign; 24/24 jobs; 2 retries; 9 recovery scenarios; 2,514 referenced MinIO paths; 24 SigNoz traces |
| `make verify-metamorphic` | PASS | 880 canonical mutations; 64 selected cases; 1,280 bounded branches; 9/9 invariants |
| `make verify-causal` | PASS | 256 branches; five single and ten pairwise interventions; 64 bounded attribution samples; 17→7 minimization |
| `make verify-clearance` | PASS | Six authority levels × 1,000 trials; level 3 maximum safe authority; all four verdicts; Ed25519 verification |
| `make verify-delegation` | PASS | Authority laundering detected; OPA denied; GATE returned 403; no effect |
| `make test-e2e` | PASS | 8/8 Playwright scenarios at 1366×768 |
| `make final-demo` | PASS twice | Complete presentation chain in 28.677 s and 27.730 s |

The automated test total is **95**: 87 pytest tests plus 8 Playwright tests. The domain acceptance gates additionally evaluated 9 metamorphic invariants, 24 replay jobs, 256 causal branches, 6,000 frontier trials, eight live critical alerts, and the native OBI positive/negative acceptance pair.

## Final live evidence

- Final refund evidence trace: `df01b8e869896bb9b3ea45f8a6f25ef0`
- Native OBI acceptance trace: `0fed347a5fc6977696e025ba0c9ffaad`
- Causal finding trace: `7e888236023d5866916f8a30074e522f`
- Delegation denial trace: `0715a3640d4471c2677922211ed7d23e`
- Persistent campaign: `campaign_21fd67d4c1b832597fdc`
- RANGE campaign: `range_39a97c1385cf1d8d49de`
- Final certificate: `ORB-2026_88F6FC3BB1E8B92F`
- Maximum safe authority: level 3, `LOW_VALUE_ACTION`
- Final certificate verdict: `CONDITIONAL`

The final workflow demonstrated:

1. A measured candidate latency reduction of 46.58% and cost reduction of 50% in deterministic simulation.
2. A live local semantic/independent mismatch: `store_credit → issue_refund`.
3. `CONTRADICTED` evidence, a real SigNoz trace, and eight live alert histories.
4. Signed Watchtower webhook delivery, duplicate-event idempotency, certificate suspension, 0% candidate traffic, and certified baseline restoration.
5. Controlled causal attribution and deterministic 17→7 regression minimization.
6. All six authority levels and the evidence-supported level-3 frontier.
7. A signed Ed25519 certificate, restrictions, tamper checks, expiration checks, and artifact-drift rejection.
8. A blocked synthetic authority-laundering delegation with OPA denial, GATE refusal, and no external effect.

Every displayed result is sourced from live local execution, recorded replay, deterministic simulation, or counterfactual analysis and is labeled with its execution mode. The Mission Control snapshot route reads persisted backend state and SigNoz references; the Playwright suite checks that the required values are not embedded in the page source.

## Presentation and submission assets

- Public README with architecture, SigNoz role, reproducibility, hero sequence, judging map, limitations, disclosure, and judge commands
- Architecture and evidence-flow documentation plus editable Mermaid source
- Seven native-run Mission Control screenshots
- Live SigNoz trace, Flight Readiness, Evidence Integrity, and Artifact Drift alert-history screenshots
- Demo script, narration, shot list, exact click path, captions, fallback plan, title, and thumbnail copy
- Complete submission copy
- Threat model, privacy model, honest limitations, and AI-assistance disclosure

See [Presentation Assets](presentation-assets.md), [Demo Video Package](demo-video-package.md), and [Submission Copy](submission.md).

## Release quality gate

The release audit checks tracked files for private keys, secret-bearing environment files, credential patterns, Windows-local paths, and broken relative Markdown links. Only `packages/certificate-schema/public-keys/development.pub` is committed; development private keys are generated during bootstrap and ignored.

## Known limitations

- OBI/eBPF acceptance requires native Linux with BTF and the documented privileges; WSL2 is not authoritative for kernel evidence.
- Qwen3 inference remains on the owner-controlled RTX laptop. The final VM validation used deterministic fallback where the remote model endpoint was intentionally unavailable.
- Payment, CRM, order, identity, and customer data are synthetic local fixtures. No real payment integration or external target is present.
- Certification statistics demonstrate the machinery and threshold behavior; they are not a claim of production safety for a real financial system.
- The minimizer is deliberately bounded to the primary refund reliability fixture.
- Screenshots and stored local URLs are evidence from an ephemeral validation deployment; judges reproduce equivalent live evidence with the documented commands.

The Azure VM is deallocated after this report and must be started again before following native-validation commands.
