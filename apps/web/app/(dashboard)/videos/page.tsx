"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Video,
  Play,
  Download,
  Trash2,
  Plus,
  Loader2,
  FolderOpen,
} from "lucide-react";
import { GenerateVideoModal } from "@/components/GenerateVideoModal";
import { videosApi, VideoTask } from "@/lib/api-client";

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getStatusBadgeVariant(status: VideoTask["status"]) {
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

function getStatusLabel(status: VideoTask["status"]) {
  switch (status) {
    case "completed":
      return "已完成";
    case "processing":
      return "生成中";
    case "failed":
      return "失败";
    default:
      return "等待中";
  }
}

export default function VideosPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [tasks, setTasks] = useState<VideoTask[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchTasks = useCallback(async () => {
    const response = await videosApi.list();
    if (response.success && response.data) {
      setTasks(response.data);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 3000);
    return () => clearInterval(interval);
  }, [fetchTasks]);

  const handleDelete = async (taskId: string) => {
    if (!confirm("确定要删除这个视频任务吗？")) return;
    await videosApi.delete(taskId);
    fetchTasks();
  };

  const handleDownload = async (task: VideoTask) => {
    if (!task.video_path) return;
    const response = await fetch(
      `/api/videos/download?path=${encodeURIComponent(task.video_path)}`,
    );
    if (response.ok) {
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${task.request.title}.mp4`;
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  const handleOpenFolder = async (task: VideoTask) => {
    if (task.task_dir) {
      await fetch(
        `/api/videos/open-folder?path=${encodeURIComponent(task.task_dir)}`,
      );
    }
  };

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">Videos</h1>
          <p className="text-muted-foreground">浏览和管理生成的视频</p>
        </div>
        <Button onClick={() => setModalOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          生成视频
        </Button>
      </div>

      <GenerateVideoModal
        open={modalOpen}
        onOpenChange={(open) => {
          setModalOpen(open);
          if (!open) fetchTasks();
        }}
      />

      {tasks.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <Video className="h-16 w-16 text-muted-foreground mb-4" />
            <p className="text-muted-foreground mb-4">暂无视频</p>
            <Button onClick={() => setModalOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              生成第一个视频
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
                          <Play className="h-6 w-6 mr-2" />
                          播放
                        </a>
                      </Button>
                    </div>
                  </>
                ) : task.status === "processing" ? (
                  <div className="flex flex-col items-center gap-2">
                    <Loader2 className="h-12 w-12 animate-spin text-primary" />
                    <p className="text-sm text-muted-foreground">
                      {task.step_name || task.message}
                    </p>
                    <div className="w-32 h-2 bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary transition-all"
                        style={{ width: `${Math.round(task.progress * 100)}%` }}
                      />
                    </div>
                  </div>
                ) : task.status === "failed" ? (
                  <div className="flex flex-col items-center gap-2 text-destructive">
                    <Video className="h-12 w-12" />
                    <p className="text-sm">生成失败</p>
                    {task.error && (
                      <p className="text-xs text-muted-foreground max-w-[200px] truncate">
                        {task.error}
                      </p>
                    )}
                  </div>
                ) : (
                  <Video className="h-12 w-12 text-muted-foreground" />
                )}
              </div>
              <CardContent className="p-4">
                <h3 className="font-medium truncate">{task.request.title}</h3>
                <div className="flex items-center justify-between mt-2">
                  <div className="flex items-center gap-2">
                    <Badge variant={getStatusBadgeVariant(task.status)}>
                      {getStatusLabel(task.status)}
                    </Badge>
                    <span className="text-sm text-muted-foreground">
                      {task.request.voice
                        .split("-")
                        .pop()
                        ?.replace("Neural", "") || "Default"}
                    </span>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {formatDate(task.created_at)}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-3">
                  {task.status === "completed" && (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1"
                        onClick={() => handleDownload(task)}
                      >
                        <Download className="h-4 w-4 mr-1" />
                        下载
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleOpenFolder(task)}
                      >
                        <FolderOpen className="h-4 w-4" />
                      </Button>
                    </>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleDelete(task.id)}
                  >
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
