import { NextResponse } from 'next/server';

const WORKER_URL = process.env.WORKER_URL || 'http://localhost:8000';

const getHeaders = () => ({
  'Content-Type': 'application/json',
  'User-Agent': 'openclaw',
});

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const response = await fetch(`${WORKER_URL}/api/tts-settings/test`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      return NextResponse.json(
        { success: false, error: 'TTS test failed' },
        { status: 500 }
      );
    }

    // Return the audio file directly
    const audioBuffer = await response.arrayBuffer();
    return new NextResponse(audioBuffer, {
      headers: {
        'Content-Type': 'audio/mpeg',
        'Content-Disposition': 'attachment; filename="tts_test.mp3"',
      },
    });
  } catch (error) {
    return NextResponse.json(
      { success: false, error: 'Failed to test TTS voice' },
      { status: 500 }
    );
  }
}