import { NextResponse } from 'next/server';

const WORKER_URL = process.env.WORKER_URL || 'http://localhost:8000';

const getHeaders = () => ({
  'Content-Type': 'application/json',
  'User-Agent': 'openclaw',
});

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { id } = await params;
    const response = await fetch(`${WORKER_URL}/api/ai-settings/${id}/activate`, {
      method: 'POST',
      headers: getHeaders(),
    });
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { success: false, error: 'Failed to activate AI setting' },
      { status: 500 }
    );
  }
}