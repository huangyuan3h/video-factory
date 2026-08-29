import { NextResponse } from 'next/server';

const WORKER_BASE = (process.env.WORKER_URL?.trim() || 'http://127.0.0.1:8000').replace(/\/$/, '');

export async function GET() {
  try {
    const res = await fetch(`${WORKER_BASE}/api/tts-settings/status`, {
      headers: { 'User-Agent': 'openclaw' },
      cache: 'no-store',
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch {
    return NextResponse.json({ success: false, error: 'Failed to fetch TTS status' }, { status: 500 });
  }
}
