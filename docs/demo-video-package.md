# ORBITAL Σ Three-Minute Demo Package

## Recording target

- **Final duration:** 2:55 maximum
- **Format:** 1920×1080, 30 fps, H.264 MP4
- **Application viewport:** Mission Control at 1366×768 browser content size
- **Narrative:** contradiction → independent evidence → rollback → causal explanation → bounded authority → signed certificate → blocked delegation
- **Golden rule:** show actual system behavior. If a live dependency fails, use a clearly introduced captured-evidence fallback; never present a static capture as live.

The committed clean rehearsal completed in 27.730 seconds excluding infrastructure startup, leaving time for narration and evidence inspection.

## One-take runbook

Run before recording:

```bash
make reset-demo
make final-demo
```

Open these tabs in order:

1. Mission Control — Launch Console
2. Mission Control — Evidence Parity
3. SigNoz — evidence trace
4. SigNoz — alert history
5. Mission Control — Replay Theater
6. Mission Control — Causal Graph
7. Mission Control — Authority Frontier
8. Mission Control — Safety Case
9. Mission Control — Certificate

Keep terminal output available but not dominant. Use the fresh trace and certificate IDs emitted by `make final-demo`; do not type the committed example IDs into a live claim.

## Exact timeline, clicks, and narration

| Time | Screen and action | Expected visible state | Narration |
|---|---|---|---|
| **0:00–0:08** | Title card over Launch Console. No click. | ORBITAL Σ, track, sensor status, live campaign summary. | “An agent can say it performed a safe action while a different effect crosses the system boundary. ORBITAL trusts evidence, not self-report.” |
| **0:08–0:24** | On Launch Console, click the completed hero mission. | Candidate comparison is labeled deterministic simulation; mission is linked to a live local trace. | “This synthetic refund candidate appears faster and cheaper in a deterministic local comparison. Those performance numbers are labeled simulation. The action evidence is live.” |
| **0:24–0:43** | Click **Evidence Parity**. Pause over the semantic and observed lanes. | Semantic action `store_credit`; OBI-observed local effect `issue_refund`; verdict `CONTRADICTED`. | “The application span declares store credit. Native OBI independently observes a refund request to our local fixture. OPA and the effect receipt complete the chain. PARALLAX marks the action CONTRADICTED.” |
| **0:43–0:57** | Click **Open in SigNoz** for the contradiction. | Correlated trace with mission, policy, capability/tool, receipt, and OBI evidence. | “This is not a hardcoded UI result. The decision drills into the correlated SigNoz trace. If the required OBI sensor were missing, the state would be UNKNOWN—not confirmed.” |
| **0:57–1:12** | Switch to SigNoz alert history. Select the newest mismatch or drift event. | Alert-history event with supporting query/trace context. | “SigNoz turns the evidence into an operational event. The normalized alert is signed before delivery to WATCHTOWER.” |
| **1:12–1:27** | Switch to Certificate. Point to status, traffic, and baseline. | Certificate suspended; candidate traffic `0`; certified baseline restored. | “WATCHTOWER verifies and deduplicates the webhook, suspends the certificate, reduces candidate traffic to zero, and restores the last certified baseline. Repeating the webhook produces the same state.” |
| **1:27–1:40** | Click **Replay Theater**. Scrub once from declared action to observed effect. | Steps labeled live, replay, synthetic, or counterfactual; contradiction remains linked. | “The incident becomes a replay investigation. Every execution mode is labeled, so recorded replay and counterfactual evidence are never presented as live traffic.” |
| **1:40–1:58** | Click **Causal Graph**. Hover the strongest contribution and the minimized capsule. | Contribution estimate and 95% interval; earliest commitment point; original `17`, minimized `7`. | “FORK runs controlled single and pairwise interventions. The bounded analysis stored 256 branches, estimates contribution with confidence intervals, and reduces the same verified failure from seventeen units to seven.” |
| **1:58–2:15** | Click **Authority Frontier**. Move pointer across levels 0–5 and stop on level 3. | Six authority levels; safe-frontier marker at level 3; higher levels fail safety/restriction criteria. | “FRONTIER measures completion, escaped effects, refusals, escalation, evidence parity, policy completeness, cost, latency, and uncertainty. The evidence supports level three: low-value external actions, and no higher.” |
| **2:15–2:29** | Click **Safety Case**, then expand one claim. | Claim connected to evidence, assumption, restriction, and residual-risk nodes. | “CLEARANCE does not ask the LLM for a verdict. Deterministic thresholds build a safety case whose claims link back to SigNoz evidence and explicit assumptions.” |
| **2:29–2:42** | Return to **Certificate** and point to signature/restrictions. | Ed25519 signature valid for the evaluated bundle; verdict `CONDITIONAL`; authority restriction shown. | “The resulting Ed25519 certificate is CONDITIONAL, artifact-bound, expiring, and restricted to the measured frontier. Drift invalidates it.” |
| **2:42–2:52** | On Certificate, open the delegation evidence card or delegation trace link. | Parent lacks refund permission; child denied; OPA denial; GATE refusal; no effect. | “Authority cannot be laundered through another agent. A parent without refund permission delegates to a child; OPA denies it, GATE refuses the capability, and no effect occurs.” |
| **2:52–2:55** | End card with repository and tagline. | `github.com/Shobhit1Kapoor/Orbital` and release `v1.0.1`. | “ORBITAL Sigma: trust what the agent does, not only what it says.” |

Total scripted runtime: **2:55**.

## Evidence that must appear

The recording is complete only if the viewer can read or clearly infer:

- `store_credit` as the semantic declaration;
- `issue_refund` as the independently observed local effect;
- `CONTRADICTED` as the evidence state;
- at least one actual SigNoz trace view;
- actual SigNoz alert history;
- certificate suspension;
- candidate traffic at zero;
- certified baseline restored;
- causal contribution with a 95% confidence interval;
- minimization from 17 to 7;
- all six authority levels and the level-3 boundary;
- certificate verdict `CONDITIONAL`, signature status, and restrictions;
- delegation denial and no effect;
- execution-mode labels; and
- repository release `v1.0.1`.

## Dependency-specific fallback plan

Every fallback must begin with a spoken or on-screen label such as **“Captured evidence from the validated release run.”**

| Live dependency | Detection before recording | Approved fallback | What must not be claimed |
|---|---|---|---|
| Mission Control unavailable | `curl -fsS http://localhost:3000` fails | Use the seven committed Mission Control captures in [presentation-assets.md](presentation-assets.md#mission-control) | Do not call the images a live UI session |
| SigNoz UI unavailable | `curl -fsS http://localhost:8080` fails | Use the four committed SigNoz captures and quote the committed trace IDs from the Phase 8 report | Do not imply the current run created the captured trace |
| Foundry-managed MCP unhealthy | `curl -fsS http://localhost:8000/livez` fails | Continue only with already provisioned, captured evidence; state that MCP deployment health is unavailable | Do not claim idempotent provisioning was reverified in that take |
| Native OBI unavailable | Sensor health is absent or failed | Use [obi-native-ubuntu.md](obi-native-ubuntu.md) plus the committed evidence-trace capture | Do not relabel SDK or receipt evidence as OBI |
| Ollama unavailable | Agent health reports fallback mode | Use deterministic fallback and keep its mode label visible | Do not call the run live Qwen inference |
| Alert does not transition in time | No new history event appears by the planned shot | Use the committed alert-history capture and Phase 2 validation result | Do not claim a fresh alert fired during recording |
| Campaign SSE disconnects | UI shows disconnected state | Keep the disconnected label visible, then use the committed Launch Console capture for the expected state | Do not hide the disconnected sensor or edit it into “live” |
| Browser animation stutters | Dropped frames or unreadable graph movement | Enable reduced motion and record static state transitions | Do not speed up footage until evidence labels become unreadable |

## Exact fallback asset order

1. [Launch Console](assets/mission-control/01-launch-console.png)
2. [Evidence Parity](assets/mission-control/02-evidence-parity.png)
3. [SigNoz evidence trace](assets/signoz/01-evidence-trace.png)
4. [SigNoz alert history](assets/signoz/04-alert-history.png)
5. [Replay Theater](assets/mission-control/03-replay-theater.png)
6. [Causal Graph](assets/mission-control/04-causal-graph.png)
7. [Authority Frontier](assets/mission-control/05-authority-frontier.png)
8. [Safety Case](assets/mission-control/06-safety-case.png)
9. [Certificate](assets/mission-control/07-certificate.png)

These are actual captured project states. Preserve the words “captured evidence” in the edit.

## Pre-record checklist

- [ ] Checkout release `v1.0.1`; working tree clean.
- [ ] Run `make reset-demo`.
- [ ] Run `make final-demo` once as a rehearsal and retain the fresh IDs.
- [ ] Confirm `curl -fsS http://localhost:8000/livez`.
- [ ] Confirm Mission Control loads at `http://localhost:3000`.
- [ ] Confirm SigNoz loads at `http://localhost:8080`.
- [ ] Confirm native OBI sensor status if the take will claim live OBI.
- [ ] Confirm all seven Mission Control screens render at 1366×768.
- [ ] Confirm the newest alert appears in alert history.
- [ ] Confirm certificate suspension, zero candidate traffic, and baseline restoration.
- [ ] Confirm 17→7, six authority levels, level 3, `CONDITIONAL`, and delegation denial are visible.
- [ ] Close unrelated tabs, notifications, terminals, and personal applications.
- [ ] Remove browser bookmarks bar and any account-identifying overlays.
- [ ] Use a fresh synthetic run; no real customer or third-party data.
- [ ] Set browser zoom to 100%.
- [ ] Disable cursor highlighting if it obscures trace attributes.
- [ ] Record ten seconds of silence for noise profiling.

## Audio checklist

- [ ] Microphone peaks between -12 dB and -6 dB.
- [ ] No clipping on “CONTRADICTED,” “WATCHTOWER,” or “Ed25519.”
- [ ] Background noise remains below narration.
- [ ] Narration says “synthetic local fixture” at least once.
- [ ] Narration distinguishes the deterministic performance comparison from live action evidence.
- [ ] Narration calls the certificate `CONDITIONAL`, not `GO`.
- [ ] Narration calls causal attribution bounded and approximate.
- [ ] Captions match spoken terminology and IDs shown on screen.
- [ ] Music, if any, remains below -28 LUFS under speech and has cleared usage rights.

## Edit checklist

- [ ] Final cut is 2:55 or shorter.
- [ ] No cut fabricates a state transition or combines IDs from different runs without a label.
- [ ] Live footage, deterministic simulation, replay, counterfactual, and captured evidence remain distinguishable.
- [ ] All trace IDs shown are synthetic and belong to the project run.
- [ ] Alert history is visible long enough to read.
- [ ] The signature and `CONDITIONAL` verdict are visible together.
- [ ] The 17→7 and level-3 claims have supporting screens.
- [ ] No Windows-local paths, shell history, secrets, private keys, tokens, public IPs, or unrelated Azure details appear.
- [ ] Captions use [assets/demo-captions.vtt](assets/demo-captions.vtt) as a starting point and are retimed to the final narration.
- [ ] Repository URL and release tag are visible on the end card.

## Export checklist

- [ ] MP4, H.264, 1920×1080, 30 fps, progressive scan.
- [ ] AAC audio, 48 kHz, stereo, 192 kbps or higher.
- [ ] Video bitrate 12–20 Mbps.
- [ ] Captions exported as both burned-in readable captions and a separate WebVTT file when the platform permits.
- [ ] Thumbnail exported at 1280×720.
- [ ] Watch the exported file from beginning to end with headphones.
- [ ] Check the export on a second screen at 100% scale.
- [ ] Verify every link written in the video description.
- [ ] Record SHA-256 of the final MP4 in private submission notes; do not claim it is repository evidence unless committed.

## Title, thumbnail, and description copy

**Video title**

> ORBITAL Σ — When an AI Agent's Trace and Its Real Action Disagree

**Thumbnail copy**

> THE TRACE SAID “STORE CREDIT”<br>
> OBI SAW “REFUND”

**Short description**

> ORBITAL Σ turns SigNoz execution evidence into bounded authority for AI agents. Watch a synthetic semantic-versus-OBI contradiction trigger signed rollback, causal analysis, a level-3 authority frontier, restricted certification, and a blocked delegation chain.
