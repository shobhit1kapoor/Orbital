import { NextResponse } from "next/server";

type SourceName =
  | "control"
  | "evidence"
  | "sensors"
  | "watchtower"
  | "causal"
  | "minimization"
  | "certifier"
  | "verification"
  | "delegation";

interface FetchResult {
  data: unknown;
  ok: boolean;
  status: number | null;
}

async function safeFetch(url: string): Promise<FetchResult> {
  try {
    const response = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(3500),
    });
    return {
      data: response.ok ? await response.json() : null,
      ok: response.ok,
      status: response.status,
    };
  } catch {
    return { data: null, ok: false, status: null };
  }
}

export async function GET() {
  const urls = {
    control: process.env.CONTROL_PLANE_URL ?? "http://control-plane:8000",
    evidence:
      process.env.EVIDENCE_RECONCILER_URL ?? "http://evidence-reconciler:8000",
    watchtower: process.env.WATCHTOWER_URL ?? "http://watchtower:8000",
    causal: process.env.CAUSAL_ENGINE_URL ?? "http://causal-engine:8000",
    certifier: process.env.CERTIFIER_URL ?? "http://certifier:8000",
    delegation: process.env.AGENT_RUNTIME_URL ?? "http://agent-runtime:8000",
  };
  const signoz = (
    process.env.SIGNOZ_PUBLIC_URL ?? "http://localhost:8080"
  ).replace(/\/$/, "");
  const requests: Array<[SourceName, string]> = [
    ["control", `${urls.control}/v1/mission-control/summary`],
    [
      "evidence",
      `${urls.evidence}/v1/evidence/parity/candidate-v2-vulnerable`,
    ],
    ["sensors", `${urls.evidence}/v1/health/sensors`],
    ["watchtower", `${urls.watchtower}/v1/runtime/status`],
    ["causal", `${urls.causal}/v1/causal/findings`],
    ["minimization", `${urls.causal}/v1/causal/latest-minimization`],
    ["certifier", `${urls.certifier}/v1/authority/frontier`],
    [
      "delegation",
      `${urls.delegation}/v1/delegations/latest`,
    ],
    [
      "verification",
      `${urls.certifier}/v1/certificate-verifications`,
    ],
  ];
  const results = await Promise.all(
    requests.map(([, url]) => safeFetch(url)),
  );
  const values = Object.fromEntries(
    requests.map(([name], index) => [name, results[index].data]),
  );
  const sources = Object.fromEntries(
    requests.map(([name], index) => [
      name,
      { ok: results[index].ok, status: results[index].status },
    ]),
  );

  return NextResponse.json({
    generatedAt: new Date().toISOString(),
    connected: results.some((result) => result.ok),
    sources,
    summary: values.control,
    parity: values.evidence,
    sensors: values.sensors,
    runtime: values.watchtower,
    findings: values.causal ?? [],
    minimization: values.minimization,
    frontier: values.certifier ?? [],
    delegation: values.delegation,
    verifications: values.verification ?? [],
    links: {
      home: signoz,
      dashboards: `${signoz}/dashboard`,
      traces: `${signoz}/traces-explorer`,
      alerts: `${signoz}/alerts`,
    },
  });
}
