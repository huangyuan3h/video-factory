import { NextRequest, NextResponse } from "next/server";

const WORKER_URL = process.env.WORKER_URL || "http://localhost:8000";

const getHeaders = () => ({
  "Content-Type": "application/json",
  "User-Agent": "openclaw",
});

interface GenerateVideoRequest {
  title: string;
  systemPrompt?: string;
  textContent: string;
  backgroundMusic?: string;
  generateSubtitle?: boolean;
  subtitleColor?: string;
  subtitleFont?: string;
  voice?: string;
  voiceRate?: string;
  backgroundSource?: string;
  resolutionWidth?: number;
  resolutionHeight?: number;
  videoResolution?: { width: number; height: number };
}

function hexToAssColor(hex: string): string {
  if (hex.startsWith("&H")) return hex;
  const cleanHex = hex.replace("#", "");
  const r = cleanHex.substring(0, 2);
  const g = cleanHex.substring(2, 4);
  const b = cleanHex.substring(4, 6);
  return `&H00${b}${g}${r}`;
}

export async function POST(request: NextRequest) {
  try {
    const body: GenerateVideoRequest = await request.json();

    const resolutionWidth =
      body.videoResolution?.width || body.resolutionWidth || 1080;
    const resolutionHeight =
      body.videoResolution?.height || body.resolutionHeight || 1920;
    const subtitleColor = body.subtitleColor
      ? hexToAssColor(body.subtitleColor)
      : "&H00FFFFFF";

    const response = await fetch(`${WORKER_URL}/api/videos/generate`, {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify({
        title: body.title,
        system_prompt: body.systemPrompt || "",
        text_content: body.textContent,
        background_music: body.backgroundMusic || null,
        generate_subtitle: body.generateSubtitle ?? true,
        subtitle_color: subtitleColor,
        subtitle_font: body.subtitleFont || "Microsoft YaHei",
        voice: body.voice || "zh-CN-XiaoxiaoNeural",
        voice_rate: body.voiceRate || "+0%",
        background_source: body.backgroundSource || "both",
        resolution_width: resolutionWidth,
        resolution_height: resolutionHeight,
      }),
    });

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Video generation error:", error);
    return NextResponse.json(
      { success: false, error: "Failed to generate video" },
      { status: 500 },
    );
  }
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const taskId = searchParams.get("taskId");
  const action = searchParams.get("action");

  if (taskId && action === "log") {
    try {
      const response = await fetch(
        `${WORKER_URL}/api/videos/tasks/${taskId}/log`,
        {
          headers: getHeaders(),
        },
      );
      const data = await response.json();
      return NextResponse.json(data);
    } catch (error) {
      console.error("Failed to get task log:", error);
      return NextResponse.json(
        { success: false, error: "Failed to get task log" },
        { status: 500 },
      );
    }
  }

  if (taskId) {
    try {
      const response = await fetch(`${WORKER_URL}/api/videos/tasks/${taskId}`, {
        headers: getHeaders(),
      });
      const data = await response.json();
      return NextResponse.json(data);
    } catch (error) {
      console.error("Failed to get task status:", error);
      return NextResponse.json(
        { success: false, error: "Failed to get task status" },
        { status: 500 },
      );
    }
  }

  try {
    const response = await fetch(`${WORKER_URL}/api/videos/tasks`, {
      headers: getHeaders(),
    });
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Failed to list tasks:", error);
    return NextResponse.json(
      { success: false, error: "Failed to list tasks" },
      { status: 500 },
    );
  }
}

export async function DELETE(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const taskId = searchParams.get("taskId");

  if (!taskId) {
    return NextResponse.json(
      { success: false, error: "Task ID is required" },
      { status: 400 },
    );
  }

  try {
    const response = await fetch(`${WORKER_URL}/api/videos/tasks/${taskId}`, {
      method: "DELETE",
      headers: getHeaders(),
    });
    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Failed to delete task:", error);
    return NextResponse.json(
      { success: false, error: "Failed to delete task" },
      { status: 500 },
    );
  }
}
