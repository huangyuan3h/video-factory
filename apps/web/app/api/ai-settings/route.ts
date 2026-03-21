import { NextResponse } from 'next/server';

const WORKER_URL = process.env.WORKER_URL || 'http://localhost:8000';

const getHeaders = () => ({
  'Content-Type': 'application/json',
  'User-Agent': 'openclaw',
});

export async function GET() {
  try {
    const response = await fetch(`${WORKER_URL}/api/ai-settings`, {
      headers: getHeaders(),
    });
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { success: false, error: 'Failed to fetch AI settings' },
      { status: 500 }
    );
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const response = await fetch(`${WORKER_URL}/api/ai-settings`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(body),
    });
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { success: false, error: 'Failed to create AI setting' },
      { status: 500 }
    );
  }
}