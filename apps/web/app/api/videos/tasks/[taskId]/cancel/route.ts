import { NextRequest, NextResponse } from "next/server";

const WORKER_URL = (process.env.WORKER_URL || "http://localhost:8000").replace(/\/$/, "");

export async function POST(_req: NextRequest, ctx: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await ctx.params;
  const r = await fetch(`${WORKER_URL}/api/videos/tasks/${taskId}/cancel`, {
    method: "POST",
    headers: { "User-Agent": "openclaw" },
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
