import { NextResponse } from "next/server";
import { writeFile, mkdir } from "fs/promises";
import { existsSync } from "fs";
import path from "path";

const ASSETS_DIR = path.join(process.cwd(), "assets");

async function ensureAssetsDir() {
  if (!existsSync(ASSETS_DIR)) {
    await mkdir(ASSETS_DIR, { recursive: true });
  }
}

export async function GET() {
  try {
    await ensureAssetsDir();
    const { readdir, stat } = await import("fs/promises");

    const files = await readdir(ASSETS_DIR);
    const assets = await Promise.all(
      files.map(async (file) => {
        const filePath = path.join(ASSETS_DIR, file);
        const stats = await stat(filePath);
        const ext = path.extname(file).toLowerCase();
        const mimeType = getMimeType(ext);
        const type = getTypeFromMime(mimeType);

        return {
          id: Buffer.from(file).toString("base64"),
          name: path.basename(file, ext),
          originalName: file,
          type,
          path: `/api/assets/files/${file}`,
          size: stats.size,
          mimeType,
          createdAt: stats.birthtime.toISOString(),
          updatedAt: stats.mtime.toISOString(),
        };
      }),
    );

    return NextResponse.json(assets);
  } catch (error) {
    console.error("Failed to fetch assets:", error);
    return NextResponse.json(
      { error: "Failed to fetch assets" },
      { status: 500 },
    );
  }
}

export async function POST(request: Request) {
  try {
    await ensureAssetsDir();
    const formData = await request.formData();
    const file = formData.get("file") as File;
    const type = formData.get("type") as string;

    if (!file) {
      return NextResponse.json({ error: "No file provided" }, { status: 400 });
    }

    const bytes = await file.arrayBuffer();
    const buffer = Buffer.from(bytes);

    const fileName = file.name;
    const filePath = path.join(ASSETS_DIR, fileName);

    await writeFile(filePath, buffer);

    const ext = path.extname(fileName).toLowerCase();
    const mimeType = getMimeType(ext);

    return NextResponse.json({
      id: Buffer.from(fileName).toString("base64"),
      name: path.basename(fileName, ext),
      originalName: fileName,
      type: type || getTypeFromMime(mimeType),
      path: `/api/assets/files/${fileName}`,
      size: file.size,
      mimeType,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });
  } catch (error) {
    console.error("Failed to upload asset:", error);
    return NextResponse.json(
      { error: "Failed to upload asset" },
      { status: 500 },
    );
  }
}

function getMimeType(ext: string): string {
  const mimeTypes: Record<string, string> = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".webm": "video/webm",
  };
  return mimeTypes[ext] || "application/octet-stream";
}

function getTypeFromMime(mimeType: string): "music" | "video" {
  if (mimeType.startsWith("audio/")) return "music";
  if (mimeType.startsWith("video/")) return "video";
  return "video";
}
