import { NextResponse } from "next/server";
import { unlink, rename, stat } from "fs/promises";
import { existsSync } from "fs";
import path from "path";

const ASSETS_DIR = path.join(process.cwd(), "assets");

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const fileName = Buffer.from(id, "base64").toString("utf-8");
    const filePath = path.join(ASSETS_DIR, fileName);

    if (!existsSync(filePath)) {
      return NextResponse.json({ error: "Asset not found" }, { status: 404 });
    }

    const stats = await stat(filePath);
    const ext = path.extname(fileName).toLowerCase();
    const mimeType = getMimeType(ext);
    const type = getTypeFromMime(mimeType);

    return NextResponse.json({
      id,
      name: path.basename(fileName, ext),
      originalName: fileName,
      type,
      path: `/api/assets/files/${fileName}`,
      size: stats.size,
      mimeType,
      createdAt: stats.birthtime.toISOString(),
      updatedAt: stats.mtime.toISOString(),
    });
  } catch (error) {
    console.error("Failed to fetch asset:", error);
    return NextResponse.json(
      { error: "Failed to fetch asset" },
      { status: 500 },
    );
  }
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const { name } = await request.json();

    if (!name) {
      return NextResponse.json({ error: "Name is required" }, { status: 400 });
    }

    const oldFileName = Buffer.from(id, "base64").toString("utf-8");
    const oldFilePath = path.join(ASSETS_DIR, oldFileName);

    if (!existsSync(oldFilePath)) {
      return NextResponse.json({ error: "Asset not found" }, { status: 404 });
    }

    const ext = path.extname(oldFileName);
    const newFileName = `${name}${ext}`;
    const newFilePath = path.join(ASSETS_DIR, newFileName);

    await rename(oldFilePath, newFilePath);

    const stats = await stat(newFilePath);
    const mimeType = getMimeType(ext);
    const type = getTypeFromMime(mimeType);

    return NextResponse.json({
      id: Buffer.from(newFileName).toString("base64"),
      name,
      originalName: newFileName,
      type,
      path: `/api/assets/files/${newFileName}`,
      size: stats.size,
      mimeType,
      createdAt: stats.birthtime.toISOString(),
      updatedAt: stats.mtime.toISOString(),
    });
  } catch (error) {
    console.error("Failed to update asset:", error);
    return NextResponse.json(
      { error: "Failed to update asset" },
      { status: 500 },
    );
  }
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const fileName = Buffer.from(id, "base64").toString("utf-8");
    const filePath = path.join(ASSETS_DIR, fileName);

    if (!existsSync(filePath)) {
      return NextResponse.json({ error: "Asset not found" }, { status: 404 });
    }

    await unlink(filePath);

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Failed to delete asset:", error);
    return NextResponse.json(
      { error: "Failed to delete asset" },
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
