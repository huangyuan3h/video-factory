import { NextRequest, NextResponse } from "next/server";

const WORKER_URL = (process.env.WORKER_URL || "http://localhost:8000").replace(/\/$/, "");

async function proxy(req: NextRequest, pathParts: string[]) {
  const path = pathParts.join("/");
  const url = `${WORKER_URL}/api/series/${path}${req.nextUrl.search}`;
  const body = ["GET", "HEAD"].includes(req.method) ? undefined : await req.text();
  const headers: Record<string, string> = { "User-Agent": "openclaw" };
  const ct = req.headers.get("content-type");
  if (ct) headers["Content-Type"] = ct;
  const r = await fetch(url, { method: req.method, headers, body: body || undefined });
  const text = await r.text();
  try {
    return NextResponse.json(JSON.parse(text), { status: r.status });
  } catch {
    return new NextResponse(text, {
      status: r.status,
      headers: { "Content-Type": r.headers.get("content-type") || "text/plain" },
    });
  }
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) { return proxy(req, await ctx.params.then((p) => p.path || [])); }
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) { return proxy(req, await ctx.params.then((p) => p.path || [])); }
export async function PUT(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) { return proxy(req, await ctx.params.then((p) => p.path || [])); }
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) { return proxy(req, await ctx.params.then((p) => p.path || [])); }
