import { NextRequest, NextResponse } from "next/server";

interface GenerateVideoRequest {
  title: string;
  systemPrompt?: string;
  textContent: string;
  backgroundMusic: string;
  generateSubtitle: boolean;
  subtitleColor: string;
  subtitleFont: string;
  voice: string;
  voiceRate: string;
  backgroundSource: string;
}

export async function POST(request: NextRequest) {
  try {
    const body: GenerateVideoRequest = await request.json();

    console.log("=".repeat(50));
    console.log("Video Generation Request");
    console.log("=".repeat(50));
    console.log("Title:", body.title);
    console.log("System Prompt:", body.systemPrompt || "(none)");
    console.log("Text Content:", body.textContent.substring(0, 100) + "...");
    console.log("Background Music:", body.backgroundMusic);
    console.log("Generate Subtitle:", body.generateSubtitle);
    if (body.generateSubtitle) {
      console.log("  - Color:", body.subtitleColor);
      console.log("  - Font:", body.subtitleFont);
    }
    console.log("Voice:", body.voice);
    console.log("Voice Rate:", body.voiceRate);
    console.log("Background Source:", body.backgroundSource);
    console.log("=".repeat(50));

    return NextResponse.json({
      success: true,
      data: {
        id: `video-${Date.now()}`,
        title: body.title,
        status: "pending",
        message: "Video generation started",
      },
    });
  } catch (error) {
    console.error("Video generation error:", error);
    return NextResponse.json(
      { success: false, error: "Failed to generate video" },
      { status: 500 },
    );
  }
}
