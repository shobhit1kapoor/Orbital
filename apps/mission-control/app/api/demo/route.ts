import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  const body = await request.json();
  const runtime = process.env.AGENT_RUNTIME_URL ?? "http://agent-runtime:8000";
  const response = await fetch(`${runtime}/v1/missions/execute`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  return NextResponse.json(await response.json(), { status: response.status });
}
