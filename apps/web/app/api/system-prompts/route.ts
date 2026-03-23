import { NextResponse } from "next/server";

const WORKER_URL = process.env.WORKER_URL || "http://localhost:8000";

const getHeaders = () => ({
  "Content-Type": "application/json",
  "User-Agent": "openclaw",
});

export async function GET() {
  try {
    const response = await fetch(`${WORKER_URL}/api/system-prompts`, {
      headers: getHeaders(),
    });
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Error fetching system prompts:", error);
    return NextResponse.json(
      {
        success: false,
        error: `Failed to fetch system prompts: ${error instanceof Error ? error.message : "Unknown error"}`,
      },
      { status: 500 },
    );
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const response = await fetch(`${WORKER_URL}/api/system-prompts`, {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify(body),
    });
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Error creating system prompt:", error);
    return NextResponse.json(
      {
        success: false,
        error: `Failed to create system prompt: ${error instanceof Error ? error.message : "Unknown error"}`,
      },
      { status: 500 },
    );
  }
}
