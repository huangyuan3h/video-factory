"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Video,
  Play,
  Download,
  Trash2,
  Plus,
  Loader2,
  FolderOpen,
  ArrowLeft,
  Ban,
  RotateCcw,
} from "lucide-react";
import { GenerateVideoModal } from "@/components/GenerateVideoModal";
import { seriesApi, videosApi, Series, VideoTask } from "@/lib/api-client";

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusVariant(status: VideoTask["status"]) {
  switch (status) {
    case "completed":
      return "default";
    case "processing":
      return "warning";
    case "failed":
      return "destructive";
    default:
      return "secondary";
  }
}

function statusLabel(status: VideoTask["status"]) {
  const labels: Record<VideoTask["status"], string> = {
    completed: "已完成",
    processing: "生成中",
    failed: "失败",
    pending: "等待中",
    cancelled: "已取消",
  };
  return labels[status] || "等待中";
}

export default function SeriesDetailPage() {
  const params = useParams<{ id: string }>();
  const seriesId = params?.id as string;
  const [series, setSeries] = useState<Series | null>(null);
  const [tasks, setTasks] = useState<VideoTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);

  const fetchAll = useCallback(async () => {
    if (!seriesId) return;
    const [sRes, tRes] = await Promise.all([seriesApi.get(seriesId), videosApi.list(seriesId)]);
    if (sRes.success && sRes.data) setSeries(sRes.data as unknown as Series);
    if (tRes.success && tRes.data) setTasks(tRes.data);
    setLoading(false);
  }, [seriesId]);

  useEffect(() => {
    if (!seriesId) return;
    fetchAll();
    const es = new EventSource(videosApi.eventsUrl());
    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        if (parsed?.success && parsed.data) {
          setTasks((parsed.data as VideoTask[]).filter((t) => t.series_id === seriesId));
          setLoading(false);
        }
      } catch {}
    };
    const interval = setInterval(fetchAll, 15000);
    return () => {
      es.close();
      clearInterval(interval);
    };
  }, [fetchAll, seriesId]);

  const handleCancel = async (task: VideoTask) => {
    if (!confirm("确定取消这个生成任务吗？")) return;
    await videosApi.cancel(task.id);
    fetchAll();
  };

  const handleRetry = async (task: VideoTask) => {
    const res = await videosApi.retry(task.id);
    if (!res.success) alert(res.error || "重试失败");
    fetchAll();
  };

  const handleDownload = async (task: VideoTask) => {
    if (!task.video_path) return;
    const response = await fetch(`/api/videos/download?path=${encodeURIComponent(task.video_path)}`);
    if (!response.ok) return;
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${task.request.title}.mp4`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleOpenFolder = async (task: VideoTask) => {
    if (task.task_dir) await fetch(`/api/videos/open-folder?path=${encodeURIComponent(task.task_dir)}`);
  };

  const handleDelete = async (taskId: string) => {
    if (!confirm("确定删除这个视频任务吗？")) return;
    await videosApi.delete(taskId);
    fetchAll();
  };

  const completed = tasks.filter((t) => t.status === "completed").length;
  const processing = tasks.filter((t) => t.status === "processing").length;

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-8">
      <Button variant="ghost" size="sm" className="mb-4" asChild>
        <Link href="/series">
          <ArrowLeft className="h-4 w-4 mr-1" /> 返回系列
        </Link>
      </Button>

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold">{series?.name || "系列"}</h1>
          <p className="text-muted-foreground font-mono text-sm">{series?.slug}</p>
          {series?.description && <p className="mt-2 max-w-2xl">{series.description}</p>}
          <div className="flex flex-wrap gap-2 mt-3">
            <Badge variant="secondary">共 {tasks.length} 个</Badge>
            <Badge variant="default">已完成 {completed}</Badge>
            {processing > 0 && <Badge variant="warning">生成中 {processing}</Badge>}
            {series?.default_voice && <Badge variant="outline">{series.default_voice}</Badge>}
          </div>
        </div>
        <Button onClick={() => setModalOpen(true)}>
          <Plus className="h-4 w-4 mr-2" /> 为该系列生成视频
        </Button>
      </div>

      <Separator className="mb-6" />

      <GenerateVideoModal
        open={modalOpen}
        onOpenChange={(open) => {
          setModalOpen(open);
          if (!open) fetchAll();
        }}
        initialSeriesId={seriesId}
      />

      {tasks.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Video className="h-16 w-16 text-muted-foreground mb-4" />
            <p className="text-muted-foreground mb-4">该系列还没有视频</p>
            <Button onClick={() => setModalOpen(true)}>
              <Plus className="h-4 w-4 mr-2" /> 生成第一个视频
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {tasks.map((task) => (
            <Card key={task.id} className="overflow-hidden">
              <div className="aspect-video bg-muted flex items-center justify-center relative group">
                {task.status === "completed" && task.video_path ? (
                  <>
                    <video
                      src={`/api/videos/stream?path=${encodeURIComponent(task.video_path)}`}
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                      <Button size="lg" variant="secondary" asChild>
                        <a
                          href={`/api/videos/stream?path=${encodeURIComponent(task.video_path)}`}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <Play className="h-6 w-6 mr-2" /> 播放
                        </a>
                      </Button>
                    </div>
                  </>
                ) : task.status === "processing" ? (
                  <div className="flex flex-col items-center gap-2">
                    <Loader2 className="h-12 w-12 animate-spin text-primary" />
                    <p className="text-sm text-muted-foreground">{task.step_name || task.message}</p>
                    <div className="w-32 h-2 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary transition-all"
                        style={{ width: `${Math.round((task.progress || 0) * 100)}%` }}
                      />
                    </div>
                  </div>
                ) : task.status === "failed" ? (
                  <div className="flex flex-col items-center gap-2 text-destructive">
                    <Video className="h-12 w-12" />
                    <p className="text-sm">生成失败</p>
                  </div>
                ) : (
                  <Video className="h-12 w-12 text-muted-foreground" />
                )}
              </div>
              <CardContent className="p-4">
                <h3 className="font-medium truncate">{task.request.title}</h3>
                <div className="flex items-center justify-between mt-2">
                  <Badge variant={statusVariant(task.status)}>{statusLabel(task.status)}</Badge>
                  <span className="text-xs text-muted-foreground">{formatDate(task.created_at)}</span>
                </div>
                <div className="flex items-center gap-2 mt-3">
                  {task.status === "completed" && (
                    <>
                      <Button variant="outline" size="sm" className="flex-1" onClick={() => handleDownload(task)}>
                        <Download className="h-4 w-4 mr-1" /> 下载
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => handleOpenFolder(task)}>
                        <FolderOpen className="h-4 w-4" />
                      </Button>
                    </>
                  )}
                  {(task.status === "pending" || task.status === "processing") && (
                    <Button variant="outline" size="sm" onClick={() => handleCancel(task)}>
                      <Ban className="h-4 w-4 mr-1" /> 取消
                    </Button>
                  )}
                  {(task.status === "failed" || task.status === "cancelled") && (
                    <Button variant="outline" size="sm" onClick={() => handleRetry(task)}>
                      <RotateCcw className="h-4 w-4 mr-1" /> 重试
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => handleDelete(task.id)}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
