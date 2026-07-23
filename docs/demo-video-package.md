# Demo Video Package

## Title and thumbnail

**Title:** ORBITAL Σ — Flight Assurance for Autonomous Agents
**Thumbnail copy:** THE AGENT SAID “STORE CREDIT.” THE SYSTEM SAW A $900 REFUND.

## Target

Two minutes and forty-five seconds. Record the real application at 1366×768 after the authoritative validation sequence. Do not splice in fabricated values.

## Narration and shot list

| Time | Shot / exact action | Narration | Caption |
|---:|---|---|---|
| 0:00 | Title, then terminal at repository root | “An agent can return the right answer while doing the wrong thing. ORBITAL Σ certifies what the system actually observes.” | Flight assurance for autonomous agents |
| 0:10 | Run `make final-demo` | “This is one local, reproducible workflow. Every effect and identity is synthetic.” | Live + replay + deterministic + counterfactual, explicitly labeled |
| 0:22 | Launch Console; point to candidate comparison and sensors | “The candidate is faster and cheaper in deterministic replay, with the evidence plane online.” | Candidate performance |
| 0:38 | Click **Evidence Parity** | “The agent declares store credit. OBI and the verified local receipt observe a nine-hundred-dollar refund. PARALLAX returns contradicted.” | `store_credit` ≠ `issue_refund` · CONTRADICTED |
| 0:58 | Click **Replay Theater**, then **Causal Graph** | “The failure is reproducible. FORK intervenes on prompt, retrieval, schema, authorization, and execution, reports confidence intervals, and reduces seventeen elements to seven.” | Counterfactual attribution · 17 → 7 |
| 1:20 | Click **Authority Frontier** | “More authority helps only through level three. Beyond that, risk increases without enough verified completion.” | Maximum safe authority: level 3 |
| 1:38 | Click **Safety Case**, then **Certificate** | “CLEARANCE deterministically issues a restricted Ed25519 certificate. The language model never decides certification.” | Signed · restricted · evidence-linked |
| 1:58 | Click the SigNoz alert link; show alert history and trace | “SigNoz is the source of truth. Artifact drift fires a signed alert to WATCHTOWER.” | Live SigNoz alert |
| 2:15 | Return to Certificate rollback section | “The certificate is suspended, canary traffic becomes zero, and the last certified baseline is restored idempotently.” | SUSPENDED · 0% CANARY · BASELINE RESTORED |
| 2:32 | Scroll to delegation chain | “A parent without refund authority cannot delegate around the boundary. OPA denies, GATE refuses a capability, and no effect occurs.” | Authority laundering blocked |
| 2:47 | End card with repository | “ORBITAL Σ: trust, but independently verify.” | github.com/Shobhit1Kapoor/Orbital |

## Exact click sequence

1. Terminal: `make final-demo`
2. Browser: `http://localhost:3000`
3. Launch Console
4. Evidence Parity
5. Replay Theater
6. Causal Graph
7. Authority Frontier
8. Safety Case
9. Certificate
10. **Open in SigNoz** for the contradiction trace
11. SigNoz **Alerts** → **ORBITAL Artifact Drift** → firing history
12. Back to Certificate → rollback and delegation evidence

## Caption file

Use the [WebVTT captions](assets/demo-captions.vtt) as a timing baseline and retime it to the actual recording.

## Fallback recording plan

1. Keep the validated stack running and capture all seven Mission Control screens with `make capture-assets`.
2. Save the terminal output and `data/demo-output/final-demo.json`.
3. Record the Mission Control sequence first.
4. Record SigNoz trace and alert-history shots separately while the live evidence remains available.
5. If a live network tunnel drops, use the captured screenshots only as clearly labeled evidence from the same validated run; do not invent replacement values.
6. Keep the terminal summary visible for the closing shot.

## Recording checklist

- Browser zoom 100%, viewport 1366×768
- Reduced motion off for the main take; verify reduced-motion mode separately
- No `.env`, terminal history, Azure portal identifiers, IP addresses, or passwords on screen
- Close unrelated tabs and notifications
- Verify every shown trace ID exists in SigNoz
- Run from a clean reset twice before recording
