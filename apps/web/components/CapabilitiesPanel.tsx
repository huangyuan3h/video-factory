"use client";

import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Cpu, Server, Users, FolderTree, Sparkles } from "lucide-react";

interface Capabilities {
  version?: string;
  features?: {
    material_sources?: string[];
    synthetic_enabled?: boolean;
    synthetic_video_enabled?: boolean;
    tts_providers?: string[];
  };
}

interface SyntheticStatus {
  enabled: boolean;
  available: boolean;
  comfyui_url?: string;
  hint?: string;
}

export function CapabilitiesPanel() {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [image, setImage] = useState<SyntheticStatus | null>(null);
  const [video, setVideo] = useState<SyntheticStatus | null>(null);
  const [counts, setCounts] = useState({ series: 0, accounts: 0, tasks: 0 });

  useEffect(() => {
    const load = async () => {
      const safe = async (url: string) => {
        try {
          const r = await fetch(url);
          const d = await r.json();
          return d?.data ?? d;
        } catch {
          return null;
        }
      };
      const [c, si, sv, series, publishers, tasks] = await Promise.all([
        safe("/api/capabilities"),
        safe("/api/synthetic/status"),
        safe("/api/synthetic/video/status"),
        safe("/api/series"),
        safe("/api/publishers"),
        safe("/api/videos/tasks"),
      ]);
      if (c) setCaps(c);
      if (si) setImage(si);
      if (sv) setVideo(sv);
      setCounts({
        series: Array.isArray(series) ? series.length : 0,
        accounts: Array.isArray(publishers) ? publishers.length : 0,
        tasks: Array.isArray(tasks) ? tasks.length : 0,
      });
    };
    load();
  }, []);

  const badge = (ok: boolean | undefined, on: string, off: string) => (
    <Badge variant={ok ? "default" : "secondary"}>{ok ? on : off}</Badge>
  );

  return (
    <Card className="mb-6">
      <CardContent className="p-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Server className="h-4 w-4" /> 后端
          </div>
          <p className="text-xs text-muted-foreground">Version {caps?.version || "?"}</p>
          <p className="text-xs text-muted-foreground">
            TTS: {(caps?.features?.tts_providers || []).join(", ") || "edge-tts"}
          </p>
        </div>
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Sparkles className="h-4 w-4" /> ComfyUI
          </div>
          <div className="flex gap-2">
            {badge(image?.enabled, "图片开", "图片关")}
            {badge(video?.enabled, "动画开", "动画关")}
          </div>
          <p className="text-xs text-muted-foreground truncate" title={image?.comfyui_url}>
            {image?.comfyui_url || ""}
          </p>
        </div>
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <FolderTree className="h-4 w-4" /> 系列 / 视频
          </div>
          <p className="text-sm">
            {counts.series} 系列 · {counts.tasks} 视频
          </p>
        </div>
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Users className="h-4 w-4" /> 发布账号
          </div>
          <p className="text-sm">{counts.accounts} 个账号</p>
          <p className="text-xs text-muted-foreground">
            素材源：{(caps?.features?.material_sources || []).join(", ") || "-"}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
