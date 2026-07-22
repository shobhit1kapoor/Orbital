import { NextResponse } from "next/server";

async function safeFetch(url: string) {
  try {
    const response = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(2500) });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

export async function GET() {
  const control = process.env.CONTROL_PLANE_URL ?? "http://control-plane:8000";
  const evidence = process.env.EVIDENCE_RECONCILER_URL ?? "http://evidence-reconciler:8000";
  const watchtower = process.env.WATCHTOWER_URL ?? "http://watchtower:8000";
  const causal = process.env.CAUSAL_ENGINE_URL ?? "http://causal-engine:8000";
  const certifier = process.env.CERTIFIER_URL ?? "http://certifier:8000";
  const [summary, parity, runtime, findings, frontier] = await Promise.all([
    safeFetch(`${control}/v1/mission-control/summary`),
    safeFetch(`${evidence}/v1/evidence/parity/candidate-v2-vulnerable`),
    safeFetch(`${watchtower}/v1/runtime/status`),
    safeFetch(`${causal}/v1/causal/findings`),
    safeFetch(`${certifier}/v1/authority/frontier`),
  ]);
  return NextResponse.json({
    generatedAt: new Date().toISOString(),
    connected: Boolean(summary),
    summary,
    parity,
    runtime,
    findings: findings ?? [],
    frontier: frontier ?? [],
  });
}
