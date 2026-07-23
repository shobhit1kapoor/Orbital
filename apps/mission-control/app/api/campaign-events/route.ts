import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const campaignId = request.nextUrl.searchParams.get("campaignId");
  if (!campaignId) {
    return Response.json({ error: "campaignId is required" }, { status: 400 });
  }
  const after = request.nextUrl.searchParams.get("after") ?? "0";
  const control = process.env.CONTROL_PLANE_URL ?? "http://control-plane:8000";
  const upstream = await fetch(
    `${control}/v1/campaigns/${encodeURIComponent(campaignId)}/events?after=${encodeURIComponent(after)}`,
    {
      cache: "no-store",
      headers: {
        accept: "text/event-stream",
        ...(request.headers.get("last-event-id")
          ? { "last-event-id": request.headers.get("last-event-id")! }
          : {}),
      },
      signal: request.signal,
    },
  );
  if (!upstream.ok || !upstream.body) {
    return Response.json(
      { error: "campaign stream unavailable" },
      { status: upstream.status || 502 },
    );
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
