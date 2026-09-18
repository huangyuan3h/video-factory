const WORKER_URL = (process.env.WORKER_URL || "http://localhost:8000").replace(/\/$/, "");

export async function GET() {
  const upstream = await fetch(`${WORKER_URL}/api/videos/events`, {
    headers: { "User-Agent": "openclaw", Accept: "text/event-stream" },
    cache: "no-store",
  });
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

export const dynamic = "force-dynamic";
