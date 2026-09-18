import { NextRequest, NextResponse } from "next/server";

const WORKER_URL = (process.env.WORKER_URL || "http://localhost:8000").replace(/\/$/, "");
const headers = { "Content-Type": "application/json", "User-Agent": "openclaw" };

export async function GET(_req: NextRequest, ctx: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await ctx.params;
  const r = await fetch(`${WORKER_URL}/api/videos/tasks/${taskId}/publish`, { headers, cache: "no-store" });
  return NextResponse.json(await r.json(), { status: r.status });
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await ctx.params;
  const body = await req.text();
  const r = await fetch(`${WORKER_URL}/api/videos/tasks/${taskId}/publish`, {
    method: "POST",
    headers,
    body,
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
