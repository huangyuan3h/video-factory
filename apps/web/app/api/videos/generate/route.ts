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
}

export async function POST(request: NextRequest) {
  try {
    const body: GenerateVideoRequest = await request.json();

    const response = await fetch(`${WORKER_URL}/api/videos/generate`, {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify({
        title: body.title,
        system_prompt: body.systemPrompt || "",
        text_content: body.textContent,
        background_music: body.backgroundMusic || null,
        generate_subtitle: body.generateSubtitle ?? true,
        subtitle_color: body.subtitleColor || "&H00FFFFFF",
        subtitle_font: body.subtitleFont || "Microsoft YaHei",
        voice: body.voice || "zh-CN-XiaoxiaoNeural",
        voice_rate: body.voiceRate || "+0%",
        background_source: body.backgroundSource || "both",
        resolution_width: body.resolutionWidth || 1080,
        resolution_height: body.resolutionHeight || 1920,
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
