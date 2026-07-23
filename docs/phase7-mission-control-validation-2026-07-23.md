# Phase 7 Mission Control Validation

Date: 2026-07-23

Scope: Phase 7 only

Environment: WSL2 Docker Engine with synthetic, locally owned fixtures

## Result

Phase 7 passed. Mission Control now renders all seven required screens from the
live ORBITAL service APIs, persistent campaign state, and SigNoz evidence
references. Production UI code contains no fixed demonstration verdicts,
metrics, trace IDs, campaign counts, causal contributions, minimization sizes,
frontier outcomes, or runtime events.

The final accepted local workflow completed:

- `make test-e2e`
- `make verify-ui`
- `make verify`
- `make hero-demo`

The final hero run reported `seed`, `certification`, and `drift` as complete.
Final video and submission work were not started.

## Implemented data path

The Next.js snapshot route concurrently reads the control plane, evidence
reconciler, agent runtime, causal engine, certifier, and Watchtower. Each source
has an independently reported health state. A partial response remains
renderable and is labeled degraded or UNKNOWN rather than being converted into
a positive result.

The campaign event route proxies the control-plane SSE stream. It forwards
`Last-Event-ID`, exposes the upstream event IDs, and disables buffering and
caching. The client retains its last cursor, reconnects with bounded delay, and
refreshes the authoritative snapshot after campaign events. The displayed
campaign counters cover queued, running, completed, failed, and retried jobs.

Read-only API additions expose existing persisted evidence without duplicating
it:

- recent evidence claims for semantic/independent action comparison
- latest delegation custody result
- latest bounded hero minimization
- recent certificate verification records
- a larger recent certificate set so all deterministic verdict states remain
  visible

All “Open in SigNoz” actions are assembled from configured SigNoz URLs and
stored trace or evidence references.

## Screen acceptance

1. **Launch Console** displays the live certificate, evidence envelope,
   nine-stage hero workflow, campaign state, SSE connection state, and the
   actual local mission response.
2. **Evidence Parity** compares semantic and independently observed actions,
   highlights `CONTRADICTED`, and shows all four reconciliation states and
   sensor health.
3. **Replay Theater** displays persisted replay jobs, queue/retry state, trace
   references, execution-mode labels, and the persisted 17-to-7 hero
   minimization.
4. **Causal Graph** renders the persisted intervention graph, contribution
   estimates, 95% confidence intervals, earliest commitment point, and source
   trace.
5. **Authority Frontier** renders all six persisted authority levels and derives
   the supported level-3 frontier from evidence.
6. **Safety Case** groups claims, evidence, assumptions, restrictions, and
   residual risks, while presenting the persisted `GO`, `CONDITIONAL`,
   `NO-GO`, and `UNKNOWN` outcomes.
7. **Certificate** displays restrictions and Ed25519 verification state, plus
   Watchtower suspension, zero candidate traffic, baseline rollback, and the
   blocked delegation chain with OPA, GATE, and no-effect evidence.

Loading, empty, service-error, degraded-source, unavailable-storage,
disconnected-sensor, and UNKNOWN states are explicit. Animations honor
`prefers-reduced-motion`. Layout and navigation were exercised at 1366×768 and
remain responsive at narrower widths.

A live 1366×768 visual inspection after the hero run confirmed that the launch
screen fits without clipping, preserves evidence hierarchy, and visibly labels
the disconnected native sensor while the nine API sources remain connected.

## Browser acceptance

Playwright executes against both a local Next.js server and the production
Docker image. The deterministic browser fixtures reproduce the shapes of the
live service contracts; they do not provide production UI fallbacks.

Eight browser tests passed:

1. full refund hero workflow
2. evidence contradiction
3. causal replay and 17-to-7 minimization
4. authority frontier and certificate verdicts
5. drift suspension and baseline rollback
6. delegation denial
7. SSE cursor reconnect
8. all seven screens at 1366×768

Observed results:

| Gate | Result | Relevant timing |
| --- | --- | --- |
| Host Playwright | 8 passed | 12.2 s |
| `make test-e2e` | 8 passed | 5.9 s test execution |
| `make verify-ui` | 8 passed | 5.6 s test execution |
| Next.js lint | passed | included in image build |
| TypeScript | passed | included in image build |
| Next.js production build | passed | five routes built |

## Repository verification

`make verify` passed after the Phase 7 changes:

- 87 Python tests passed in 5.27 seconds
- Ruff passed
- ESLint passed
- TypeScript passed
- Next.js production build passed
- Docker Compose validation passed
- OpenTelemetry Collector configuration validation passed

The post-hero live snapshot at `2026-07-23T12:25:58.279Z` reported:

- 9 of 9 service sources reachable
- 2 persisted campaigns
- 20 recent certificates
- 5 causal findings
- 7 frontier runs
- 1 certificate suspension
- 5 rollback records
- delegation evidence available
- minimization evidence available

The live evidence-parity score was `0.2`, reflecting the deliberately generated
local contradiction; it was not replaced with a presentation value.

## Hero workflow compatibility

The clean acceptance run exposed two stale orchestration assumptions. The
one-command hero target now starts the owned mock MCP and refund services before
execution. The hero driver now uses the current asynchronous causal API,
submits the bounded attribution configuration, polls persisted causal and
minimization records to terminal state, and fails on failed, cancelled, or
timed-out work.

The successful final `make hero-demo` completed in 98.9 seconds and wrote the
normal local runtime evidence. Generated runtime regression output was not
added to the Phase 7 source checkpoint.

## Limitations

- Required sensor completeness was false in this WSL2 run because the native
  OBI sensor was not attached. Mission Control correctly displayed the
  disconnected sensor state. Native OBI acceptance remains covered by the
  previously completed Ubuntu validation and was not rerun in Phase 7.
- SigNoz links target the configured local SigNoz URL. They require that local
  SigNoz deployment to be running in the viewer's environment.
- Browser workflow fixtures make UI assertions deterministic; the separate
  live snapshot and hero acceptance prove the production routes consume real
  locally persisted state.
- Final video recording and hackathon submission remain outside Phase 7.
