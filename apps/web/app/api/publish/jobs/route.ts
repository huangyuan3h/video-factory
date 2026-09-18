import { NextRequest, NextResponse } from "next/server";

const WORKER_URL = (process.env.WORKER_URL || "http://localhost:8000").replace(/\/$/, "");

export async function GET(req: NextRequest) {
  const status = req.nextUrl.searchParams.get("status");
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const r = await fetch(`${WORKER_URL}/api/publish/jobs${qs}`, {
    headers: { "User-Agent": "openclaw" },
    cache: "no-store",
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
