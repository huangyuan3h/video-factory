import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const folderPath = searchParams.get("path");

  if (!folderPath) {
    return NextResponse.json({ error: "Path is required" }, { status: 400 });
  }

  try {
    if (process.platform === "darwin") {
      spawn("open", [folderPath]);
    } else if (process.platform === "win32") {
      spawn("explorer", [folderPath]);
    } else {
      spawn("xdg-open", [folderPath]);
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    return NextResponse.json(
      { error: "Failed to open folder" },
      { status: 500 },
    );
  }
}
