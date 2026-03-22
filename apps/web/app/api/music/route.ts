import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

const MUSIC_DIR = path.join(process.cwd(), "assets");

export async function GET() {
  try {
    if (!fs.existsSync(MUSIC_DIR)) {
      fs.mkdirSync(MUSIC_DIR, { recursive: true });
    }

    const files = fs.readdirSync(MUSIC_DIR);
    const musicFiles = files
      .filter((file) => /\.(mp3|wav|ogg|m4a)$/i.test(file))
      .map((file, index) => ({
        id: `music-${index}`,
        name: path.basename(file, path.extname(file)),
        filename: file,
      }));

    return NextResponse.json({
      success: true,
      data: musicFiles,
    });
  } catch (error) {
    console.error("Failed to list music files:", error);
    return NextResponse.json(
      { success: false, error: "Failed to list music files" },
      { status: 500 },
    );
  }
}
