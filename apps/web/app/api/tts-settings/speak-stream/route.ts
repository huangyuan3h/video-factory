import { NextResponse } from 'next/server';

const WORKER_BASE = (process.env.WORKER_URL?.trim() || 'http://127.0.0.1:8000').replace(/\/$/, '');

export async function POST(request: Request) {
  const body = await request.text();
  const res = await fetch(`${WORKER_BASE}/api/tts-settings/speak-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'User-Agent': 'openclaw' },
    body,
  });
  if (!res.ok || !res.body) {
    const err = await res.text().catch(() => 'stream failed');
    return NextResponse.json({ success: false, error: err }, { status: res.status || 500 });
  }
  return new NextResponse(res.body, {
    headers: {
      'Content-Type': 'application/octet-stream',
      'Cache-Control': 'no-store',
    },
  });
}
