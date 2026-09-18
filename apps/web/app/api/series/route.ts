import { NextRequest, NextResponse } from "next/server";

const WORKER_URL = (process.env.WORKER_URL || "http://localhost:8000").replace(/\/$/, "");
const getHeaders = () => ({ "Content-Type": "application/json", "User-Agent": "openclaw" });

export async function GET() {
  const r = await fetch(`${WORKER_URL}/api/series`, { headers: getHeaders(), cache: "no-store" });
  return NextResponse.json(await r.json(), { status: r.status });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const r = await fetch(`${WORKER_URL}/api/series`, {
    method: "POST",
    headers: getHeaders(),
    body: JSON.stringify(body),
  });
  return NextResponse.json(await r.json(), { status: r.status });
}
