import { NextResponse } from "next/server";

/** Prefer 127.0.0.1 over localhost to avoid IPv6 (::1) vs IPv4 bind mismatches on some systems. */
const WORKER_BASE = (
  process.env.WORKER_URL?.trim() || "http://127.0.0.1:8000"
).replace(/\/$/, "");

const getHeaders = () => ({
  "Content-Type": "application/json",
  "User-Agent": "openclaw",
});

function formatUnknownError(error: unknown): string {
  if (error instanceof Error) {
    const msg = error.message;
    if (error.cause instanceof Error) {
      return `${msg}: ${error.cause.message}`;
    }
    return msg;
  }
  return "Unknown error";
}

function isUpstreamUnreachable(error: unknown): boolean {
  if (!(error instanceof Error) || !(error.cause instanceof Error)) {
    return false;
  }
  const code = (error.cause as NodeJS.ErrnoException).code;
  return (
    code === "ECONNREFUSED" ||
    code === "ENOTFOUND" ||
    code === "EAI_AGAIN" ||
    code === "ECONNRESET"
  );
}

async function readUpstreamError(response: Response): Promise<string> {
  const raw = await response.text().catch(() => "");
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (parsed.detail !== undefined) {
      return typeof parsed.detail === "string"
        ? parsed.detail
        : JSON.stringify(parsed.detail);
    }
  } catch {
    // not JSON
  }
  return raw || `HTTP ${response.status}`;
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const response = await fetch(`${WORKER_BASE}/api/tts-settings/test`, {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify(body),
      cache: "no-store",
    });

    if (!response.ok) {
      const detail = await readUpstreamError(response);
      const status =
        response.status >= 400 && response.status < 500
          ? response.status
          : 502;
      return NextResponse.json(
        { success: false, error: `TTS test failed: ${detail}` },
        { status },
      );
    }

    const audioBuffer = await response.arrayBuffer();
    if (audioBuffer.byteLength === 0) {
      return NextResponse.json(
        { success: false, error: "Received empty audio from TTS engine" },
        { status: 502 },
      );
    }

    return new NextResponse(audioBuffer, {
      headers: {
        "Content-Type": "audio/mpeg",
        "Content-Disposition": 'attachment; filename="tts_test.mp3"',
      },
    });
  } catch (error) {
    if (isUpstreamUnreachable(error)) {
      return NextResponse.json(
        {
          success: false,
          error: `Cannot reach worker at ${WORKER_BASE}. Start the worker (e.g. \`cd apps/worker && uv run uvicorn src.main:app --reload\`) or set WORKER_URL.`,
        },
        { status: 503 },
      );
    }
    return NextResponse.json(
      {
        success: false,
        error: `Failed to test TTS voice: ${formatUnknownError(error)}`,
      },
      { status: 500 },
    );
  }
}
