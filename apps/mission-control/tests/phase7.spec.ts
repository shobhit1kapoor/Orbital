import { expect, type Page, test } from "@playwright/test";

const trace = "11111111111111111111111111111111";
const signoz = "http://signoz.test";

const certificate = {
  certificate_id: "ORB-PHASE7",
  candidate_id: "candidate-v2-fixed",
  verdict: "CONDITIONAL",
  granted_authority: "LOW_VALUE_ACTION",
  maximum_refund_usd: 25,
  canary_percentage: 5,
  mission_coverage: 0.91,
  replay_fidelity: 0.94,
  public_key_id: "sha256:public-key",
  signature: "signed-phase-seven-certificate-value",
  restrictions: [
    "authority limited to level 3",
    "human approval required above USD 25.00",
  ],
  safety_case: {
    nodes: [
      {
        node_id: "claim-authority",
        kind: "claim",
        text: "Candidate may operate at low-value authority",
      },
      {
        node_id: "evidence-parity",
        kind: "evidence",
        text: "Evidence parity is complete",
        evidence_url: `${signoz}/trace/${trace}`,
      },
      {
        node_id: "assumption-gateway",
        kind: "assumption",
        text: "GATE remains enforced",
      },
      {
        node_id: "restriction-authority",
        kind: "restriction",
        text: "Maximum supported authority is level 3",
      },
      {
        node_id: "risk-envelope",
        kind: "residual_risk",
        text: "Outside-envelope behavior remains unknown",
      },
    ],
  },
};

const campaign = {
  campaign_id: "campaign-phase7",
  candidate_id: "candidate-v2-fixed",
  status: "RUNNING",
  counts: {
    total: 5,
    queued: 1,
    running: 1,
    completed: 2,
    failed: 1,
    retried: 1,
    cancelled: 0,
  },
  availability_state: "READY",
  jobs: [
    {
      job_id: "job-completed",
      mission_id: "mission-completed",
      mutation_id: "mutation-a",
      trace_id: trace,
      status: "COMPLETED",
      retries: 0,
    },
    {
      job_id: "job-running",
      mission_id: "mission-running",
      mutation_id: "mutation-b",
      trace_id: trace,
      status: "RUNNING",
      retries: 0,
    },
    {
      job_id: "job-queued",
      mission_id: "mission-queued",
      mutation_id: "mutation-c",
      trace_id: trace,
      status: "QUEUED",
      retries: 0,
    },
    {
      job_id: "job-failed",
      mission_id: "mission-failed",
      mutation_id: "mutation-d",
      trace_id: trace,
      status: "FAILED",
      retries: 1,
    },
  ],
};

const snapshot = {
  generatedAt: "2026-07-23T12:00:00Z",
  connected: true,
  sources: {
    control: { ok: true, status: 200 },
    evidence: { ok: true, status: 200 },
    sensors: { ok: true, status: 200 },
    watchtower: { ok: true, status: 200 },
    causal: { ok: true, status: 200 },
    minimization: { ok: true, status: 200 },
    certifier: { ok: true, status: 200 },
    delegation: { ok: true, status: 200 },
  },
  summary: {
    campaigns: [campaign],
    certificates: [
      certificate,
      { ...certificate, certificate_id: "ORB-GO", candidate_id: "candidate-go", verdict: "GO" },
      { ...certificate, certificate_id: "ORB-NOGO", candidate_id: "candidate-no-go", verdict: "NO-GO" },
      { ...certificate, certificate_id: "ORB-UNKNOWN", candidate_id: "candidate-unknown", verdict: "UNKNOWN" },
    ],
    rollout: { candidate_id: "baseline-v1", percentage: 100 },
  },
  parity: {
    candidate_id: "candidate-v2-vulnerable",
    confirmed: 0,
    contradicted: 1,
    unobserved: 0,
    unknown: 0,
    score: 0,
    recent_claims: [
      {
        claim_id: "claim-contradiction",
        claim_type: "consequential_action_parity",
        semantic_action: "store_credit",
        observed_action: "issue_refund",
        state: "CONTRADICTED",
        evidence_links: [`${signoz}/trace/${trace}`],
        correlation: { mission_id: "mission-refund", trace_id: trace },
      },
    ],
  },
  sensors: {
    semantic_sdk: true,
    policy: true,
    tool_receipts: true,
    obi: true,
    signoz: true,
    complete: true,
  },
  runtime: {
    rollout: {
      candidate_id: "baseline-v1",
      enabled: true,
      percentage: 100,
      certificate_id: "ORB-BASELINE",
    },
    rollbacks: [
      {
        certificate_id: "ORB-PHASE7",
        status: "suspended",
        candidate_traffic_percentage: 0,
        active_candidate: "baseline-v1",
        reason: "schema drift",
        watchtower_trace_id: trace,
        evidence_links: [`${signoz}/trace/${trace}`],
      },
    ],
    suspensions: [
      {
        certificate_id: "ORB-PHASE7",
        status: "suspended",
        traffic_percentage: 0,
      },
    ],
    webhooks: [],
    attestations: [],
  },
  findings: [
    {
      analysis_id: "analysis-phase7",
      source_failure: "refund_declaration_authorization_mismatch",
      earliest_commitment_point: "prompt_compression",
      shapley_samples: 64,
      completed_branch_count: 256,
      completion_trace_id: trace,
      source_evidence: { source_trace_id: trace },
      attribution: [
        {
          factor: "deterministic_authorization",
          contribution: 0.31,
          confidence_low: 0.22,
          confidence_high: 0.41,
        },
        {
          factor: "prompt_compression",
          contribution: 0.24,
          confidence_low: 0.18,
          confidence_high: 0.29,
        },
      ],
    },
  ],
  minimization: {
    minimization_id: "min-phase7",
    trace_id: trace,
    result: {
      original_size: 17,
      minimized_size: 7,
      reason: "Deterministic delta debugging preserved the verified failure",
      retained_causal_factors: [
        "prompt_compression",
        "deterministic_authorization",
      ],
    },
  },
  frontier: [
    {
      maximum_safe_authority: "LOW_VALUE_ACTION",
      maximum_safe_authority_index: 3,
      maximum_safe_authority_label: "Low-value external actions",
      trial_count_per_level: 1000,
      execution_mode: "deterministic_simulation",
      trace_id: trace,
      points: Array.from({ length: 6 }, (_, level) => ({
        level_index: level,
        authority_level: [
          "READ_ONLY",
          "DRAFT",
          "REVERSIBLE_WRITE",
          "LOW_VALUE_ACTION",
          "HUMAN_APPROVED_IRREVERSIBLE",
          "AUTONOMOUS_IRREVERSIBLE",
        ][level],
        verified_completion: 0.98 - level * 0.004,
        unsafe_attempts: level * 10,
        escaped_unsafe_effects: level === 5 ? 1 : 0,
        evidence_parity: level <= 3 ? 1 : 0.99,
        policy_completeness: level <= 3 ? 1 : 0.99,
        supported: level <= 3,
        trace_id: trace,
        evidence_references: [`${signoz}/trace/${trace}`],
      })),
    },
  ],
  delegation: {
    trace_id: trace,
    external_effect_occurred: false,
    decision: {
      evidence_state: "CONTRADICTED",
      opa_allowed: false,
      detections: ["authority_laundering"],
    },
    delegation: {
      delegator: { agent_id: "parent-agent" },
      delegate: { agent_id: "child-agent" },
      delegated_tools: ["issue_refund"],
    },
    gate: { status_code: 403, capability_issued: false },
  },
  verifications: [
    {
      certificate_id: "ORB-PHASE7",
      valid: true,
      reason: "valid",
      trace_id: trace,
    },
  ],
  links: {
    home: signoz,
    dashboards: `${signoz}/dashboard`,
    traces: `${signoz}/traces-explorer`,
    alerts: `${signoz}/alerts`,
  },
};

async function mockMissionControl(page: Page) {
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/campaign-events**", (route) =>
    route.fulfill({
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
      },
      body:
        "id: 1\n" +
        "event: job.completed\n" +
        `data: ${JSON.stringify({
          sequence: 1,
          event_type: "job.completed",
          payload: { counts: campaign.counts },
        })}\n\n`,
    }),
  );
}

test.beforeEach(async ({ page }) => {
  await mockMissionControl(page);
  await page.goto("/");
  await expect(page.getByTestId("launch-console")).toBeVisible();
});

test("full refund hero workflow renders live execution evidence", async ({ page }) => {
  await page.route("**/api/demo", (route) =>
    route.fulfill({
      status: 200,
      json: {
        correlation: { mission_id: "mission-live", trace_id: trace },
        semantic_action: "store_credit",
        proposed_amount: 900,
        model: { source: "ollama" },
        result: { evidence_state: "CONTRADICTED" },
      },
    }),
  );
  await page.getByRole("button", { name: "Run refund hero" }).click();
  const result = page.getByTestId("hero-result");
  await expect(result).toContainText("store_credit");
  await expect(result).toContainText("$900.00");
  await expect(result).toContainText("CONTRADICTED");
  await expect(result.getByRole("link", { name: "Open in SigNoz" })).toHaveAttribute(
    "href",
    `${signoz}/trace/${trace}`,
  );
});

test("evidence contradiction shows semantic and independent action", async ({ page }) => {
  await page.getByRole("button", { name: "Evidence Parity" }).click();
  const row = page.getByTestId("evidence-contradicted");
  await expect(row).toContainText("store_credit");
  await expect(row).toContainText("issue_refund");
  await expect(row).toContainText("CONTRADICTED");
});

test("causal replay and 17-to-7 minimization are evidence backed", async ({ page }) => {
  await page.getByRole("button", { name: "Replay Theater" }).click();
  await expect(page.getByTestId("mission-minimization")).toContainText("17");
  await expect(page.getByTestId("mission-minimization")).toContainText("7");
  await page.getByRole("button", { name: "Causal Graph" }).click();
  await expect(page.getByTestId("causal-graph")).toContainText(
    "deterministic authorization",
  );
  await expect(page.getByTestId("causal-graph")).toContainText("22.0% – 41.0%");
});

test("authority frontier and all certificate verdicts render", async ({ page }) => {
  await page.getByRole("button", { name: "Authority Frontier" }).click();
  await expect(page.getByTestId("authority-frontier")).toContainText("Level 3");
  await expect(page.getByTestId("authority-frontier")).toContainText(
    "AUTONOMOUS IRREVERSIBLE",
  );
  await page.getByRole("button", { name: "Safety Case" }).click();
  for (const verdict of ["GO", "CONDITIONAL", "NO-GO", "UNKNOWN"]) {
    await expect(page.getByTestId("safety-case")).toContainText(verdict);
  }
  await page.getByRole("button", { name: "Certificate" }).click();
  await expect(page.getByTestId("certificate-screen")).toContainText(
    "Ed25519 signature verified",
  );
});

test("drift suspension restores baseline with zero candidate traffic", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Certificate" }).click();
  const runtime = page.getByTestId("rollback-status");
  await expect(runtime).toContainText("suspended");
  await expect(runtime).toContainText("0%");
  await expect(runtime).toContainText("baseline-v1");
  await expect(runtime).toContainText("RESTORED");
});

test("delegation denial shows laundering, OPA, GATE, and no effect", async ({
  page,
}) => {
  await page.getByRole("button", { name: "Certificate" }).click();
  const delegation = page.getByTestId("delegation-denial");
  await expect(delegation).toContainText("authority laundering");
  await expect(delegation).toContainText("OPA DENIED");
  await expect(delegation).toContainText("GATE 403");
  await expect(delegation).toContainText("Effect NONE");
});

test("campaign SSE reconnects with its last cursor", async ({ page }) => {
  await expect(page.getByTestId("stream-status")).toHaveText(/live|reconnecting/);
  await expect(page.getByText(/Reconnects [1-9]/)).toBeVisible({ timeout: 5000 });
});

test("all seven screens remain navigable at demo resolution", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  for (const label of [
    "Evidence Parity",
    "Replay Theater",
    "Causal Graph",
    "Authority Frontier",
    "Safety Case",
    "Certificate",
  ]) {
    await page.getByRole("button", { name: label }).click();
    await expect(page.getByRole("heading", { name: label, exact: false }).first()).toBeVisible();
  }
});
