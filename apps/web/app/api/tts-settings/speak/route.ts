import { NextResponse } from 'next/server';

const WORKER_BASE = (process.env.WORKER_URL?.trim() || 'http://127.0.0.1:8000').replace(/\/$/, '');

export async function POST(request: Request) {
  const body = await request.text();
  const res = await fetch(`${WORKER_BASE}/api/tts-settings/speak`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'User-Agent': 'openclaw' },
    body,
  });
  if (!res.ok) {
    const err = await res.text();
    return NextResponse.json({ success: false, error: err }, { status: res.status });
  }
  const buf = await res.arrayBuffer();
  const ct = res.headers.get('content-type') || 'audio/wav';
  return new NextResponse(buf, { headers: { 'Content-Type': ct, 'Cache-Control': 'no-store' } });
}
