import { NextResponse } from 'next/server';

const WORKER_URL = process.env.WORKER_URL || 'http://localhost:8000';

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const taskId = searchParams.get('taskId');
  const page = searchParams.get('page') || '1';
  const pageSize = searchParams.get('pageSize') || '20';

  try {
    const params = new URLSearchParams({ page, pageSize });
    if (taskId) params.append('taskId', taskId);

    const response = await fetch(`${WORKER_URL}/api/runs?${params}`);
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: 'Failed to fetch runs' },
      { status: 500 }
    );
  }
}