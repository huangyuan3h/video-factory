import { NextResponse } from 'next/server';

const WORKER_BASE = (process.env.WORKER_URL?.trim() || 'http://127.0.0.1:8000').replace(/\/$/, '');

export async function POST(request: Request) {
  // Forward multipart form directly
  const form = await request.formData();
  const res = await fetch(`${WORKER_BASE}/api/tts-settings/voices/register`, {
    method: 'POST',
    headers: { 'User-Agent': 'openclaw' },
    body: form as unknown as BodyInit,
  });
  const data = await res.json().catch(async () => ({ detail: await res.text() }));
  return NextResponse.json(data, { status: res.status });
}
