import { NextRequest, NextResponse } from "next/server";

const WORKER_URL = process.env.WORKER_URL || "http://localhost:8000";

const getHeaders = () => ({
  "Content-Type": "application/json",
  "User-Agent": "openclaw",
});

interface GenerateVideoRequest {
  title: string;
  content?: string;
  textContent?: string;
  text_content?: string;
  text?: string;
  systemPrompt?: string;
  system_prompt?: string;
  backgroundMusic?: string;
  background_music?: string;
  generateSubtitle?: boolean;
  generate_subtitle?: boolean;
  subtitleColor?: string;
  subtitle_color?: string;
  subtitleFont?: string;
  subtitle_font?: string;
  voice?: string;
  voiceRate?: string;
  voice_rate?: string;
  backgroundSource?: string;
  background_source?: string;
  resolution?: string;
  orientation?: string;
  aspectRatio?: string;
  aspect_ratio?: string;
  resolutionWidth?: number;
  resolution_width?: number;
  resolutionHeight?: number;
  resolution_height?: number;
  width?: number;
  height?: number;
  videoResolution?: { width: number; height: number };
  fps?: number;
  generateCover?: boolean;
  [key: string]: unknown;
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

    // minimal required: title + content (accept multiple aliases)
    const content =
      (body.content as string) ||
      (body.textContent as string) ||
      (body.text_content as string) ||
      (body.text as string) ||
      "";
    if (!body.title || !content) {
      return NextResponse.json(
        { success: false, error: "title and content (or textContent) are required" },
        { status: 400 },
      );
    }

    // resolution: prefer explicit preset/orientation, else infer from width/height
    const resolution = (body.resolution as string) || undefined;
    const orientation = (body.orientation as string) || undefined;
    const aspectRatio = (body.aspectRatio as string) || (body.aspect_ratio as string) || undefined;
    const width =
      (body.resolutionWidth as number) ??
      (body.resolution_width as number) ??
      (body.width as number) ??
      body.videoResolution?.width;
    const height =
      (body.resolutionHeight as number) ??
      (body.resolution_height as number) ??
      (body.height as number) ??
      body.videoResolution?.height;

    const subtitleColorRaw = (body.subtitleColor as string) || (body.subtitle_color as string) || "&H00FFFFFF";
    const subtitleColor = hexToAssColor(subtitleColorRaw);

    // Forward all optional knobs; worker has defaults and extra=ignore
    const payload: Record<string, unknown> = {
      title: body.title,
      content,
      system_prompt: (body.systemPrompt as string) || (body.system_prompt as string) || "",
      background_music: (body.backgroundMusic as string) || (body.background_music as string) || null,
      generate_subtitle: (body.generateSubtitle as boolean) ?? (body.generate_subtitle as boolean) ?? true,
      subtitle_color: subtitleColor,
      subtitle_font: (body.subtitleFont as string) || (body.subtitle_font as string) || "Microsoft YaHei",
      voice: body.voice || "zh-CN-XiaoxiaoNeural",
      voice_rate: (body.voiceRate as string) || (body.voice_rate as string) || "+0%",
      background_source: (body.backgroundSource as string) || (body.background_source as string) || "both",
      fps: body.fps ?? 30,
      generate_cover: (body.generateCover as boolean) ?? true,
    };
    if (resolution) payload.resolution = resolution;
    if (orientation) payload.orientation = orientation;
    if (aspectRatio) payload.aspect_ratio = aspectRatio;
    if (width) payload.resolution_width = width;
    if (height) payload.resolution_height = height;

    // pass through any other optional fields verbatim
    if (body.subtitle_style) payload.subtitle_style = body.subtitle_style;
    const seriesId = (body.series_id as string) || (body.seriesId as string);
    if (seriesId) payload.series_id = seriesId;

    const response = await fetch(`${WORKER_URL}/api/videos/generate`, {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
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
    const seriesId = searchParams.get("series_id");
    const qs = seriesId ? `?series_id=${encodeURIComponent(seriesId)}` : "";
    const response = await fetch(`${WORKER_URL}/api/videos/tasks${qs}`, {
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
