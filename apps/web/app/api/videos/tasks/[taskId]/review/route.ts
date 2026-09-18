import { NextRequest, NextResponse } from "next/server";

const WORKER_URL = (process.env.WORKER_URL || "http://localhost:8000").replace(/\/$/, "");

export async function POST(req: NextRequest, ctx: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await ctx.params;
  const body = await req.text();
  const r = await fetch(`${WORKER_URL}/api/videos/tasks/${taskId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "User-Agent": "openclaw" },
    body,
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
