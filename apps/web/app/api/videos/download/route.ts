import { NextRequest, NextResponse } from "next/server";
import { readFile, stat } from "fs/promises";
import { existsSync } from "fs";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const videoPath = searchParams.get("path");

  if (!videoPath) {
    return NextResponse.json({ error: "Path is required" }, { status: 400 });
  }

  if (!existsSync(videoPath)) {
    return NextResponse.json({ error: "File not found" }, { status: 404 });
  }

  try {
    const file = await readFile(videoPath);
    const stats = await stat(videoPath);

    return new NextResponse(file, {
      headers: {
        "Content-Type": "video/mp4",
        "Content-Length": stats.size.toString(),
        "Content-Disposition": `attachment; filename="video.mp4"`,
      },
    });
  } catch (error) {
    return NextResponse.json({ error: "Failed to read file" }, { status: 500 });
  }
}
