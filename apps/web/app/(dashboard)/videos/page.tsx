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
  Share2,
  Ban,
  RotateCcw,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { GenerateVideoModal } from "@/components/GenerateVideoModal";
import {
  videosApi,
  publishersApi,
  seriesApi,
  publishingApi,
  VideoTask,
  PublisherAccount,
  Series,
  PublishJob,
} from "@/lib/api-client";

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
    case "cancelled":
      return "已取消";
    default:
      return "等待中";
  }
}

export default function VideosPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [tasks, setTasks] = useState<VideoTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishTask, setPublishTask] = useState<VideoTask | null>(null);
  const [publishers, setPublishers] = useState<PublisherAccount[]>([]);
  const [publishPlatform, setPublishPlatform] = useState<string>("");
  const [publishFolderId, setPublishFolderId] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [publishJobs, setPublishJobs] = useState<PublishJob[]>([]);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [seriesList, setSeriesList] = useState<Series[]>([]);
  const [seriesFilter, setSeriesFilter] = useState<string>("all");

  const fetchTasks = useCallback(async () => {
    const response = await videosApi.list(seriesFilter === "all" ? undefined : seriesFilter);
    if (response.success && response.data) {
      setTasks(response.data);
    }
    setLoading(false);
  }, [seriesFilter]);

  useEffect(() => {
    seriesApi.list().then((res) => {
      if (res.success && res.data) setSeriesList(res.data as unknown as Series[]);
    });
  }, []);

  useEffect(() => {
    fetchTasks();
    const applyList = (list: VideoTask[]) => {
      setTasks(seriesFilter === "all" ? list : list.filter((t) => t.series_id === seriesFilter));
      setLoading(false);
    };
    const es = new EventSource(videosApi.eventsUrl());
    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        if (parsed?.success && parsed.data) applyList(parsed.data as VideoTask[]);
      } catch {}
    };
    // Slow fallback poll in case SSE is unavailable
    const interval = setInterval(fetchTasks, 10000);
    return () => {
      es.close();
      clearInterval(interval);
    };
  }, [fetchTasks, seriesFilter]);

  const handleCancel = async (task: VideoTask) => {
    if (!confirm("确定取消这个生成任务吗？")) return;
    await videosApi.cancel(task.id);
    fetchTasks();
  };

  const handleRetry = async (task: VideoTask) => {
    const res = await videosApi.retry(task.id);
    if (!res.success) alert(res.error || "重试失败");
    fetchTasks();
  };

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

  const openPublish = async (task: VideoTask) => {
    setPublishTask(task);
    setPublishOpen(true);
    const [res, jobs] = await Promise.all([
      publishersApi.list(),
      videosApi.listPublishJobs(task.id),
    ]);
    if (res.success && res.data) setPublishers(res.data as unknown as PublisherAccount[]);
    if (jobs.success && jobs.data) setPublishJobs(jobs.data);
  };

  const handleReview = async (task: VideoTask, decision: "approve" | "reject") => {
    setReviewing(task.id);
    try {
      const res = await videosApi.review(task.id, decision);
      if (!res.success) alert(res.error || "审核失败");
      fetchTasks();
    } finally {
      setReviewing(null);
    }
  };

  const handlePublish = async () => {
    if (!publishTask || !publishPlatform) return;
    setPublishing(true);
    try {
      const res = await videosApi.publish(publishTask.id, {
        platforms: [publishPlatform],
        folder_id: publishFolderId || undefined,
        title: publishTask.request.title,
      });
      if (res.success) {
        const jobs = await videosApi.listPublishJobs(publishTask.id);
        if (jobs.success && jobs.data) setPublishJobs(jobs.data);
      } else {
        alert(`发布失败: ${res.error}`);
      }
    } finally {
      setPublishing(false);
    }
  };

  const handleRetryPublish = async (jobId: string) => {
    const res = await publishingApi.retry(jobId);
    if (!res.success) alert(res.error || "重试失败");
    if (publishTask) {
      const jobs = await videosApi.listPublishJobs(publishTask.id);
      if (jobs.success && jobs.data) setPublishJobs(jobs.data);
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
        <div className="flex items-center gap-3">
          <Select value={seriesFilter} onValueChange={setSeriesFilter}>
            <SelectTrigger className="w-52">
              <SelectValue placeholder="全部系列" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部系列</SelectItem>
              {seriesList.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button onClick={() => setModalOpen(true)}>
            <Plus className="h-4 w-4 mr-2" />
            生成视频
          </Button>
        </div>
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
                    {task.series_name && <Badge variant="outline">{task.series_name}</Badge>}
                    {task.status === "completed" && (
                      <Badge
                        variant={
                          task.review_status === "approved"
                            ? "default"
                            : task.review_status === "rejected"
                              ? "destructive"
                              : "secondary"
                        }
                      >
                        {task.review_status === "approved"
                          ? "已审核"
                          : task.review_status === "rejected"
                            ? "已拒绝"
                            : "待审核"}
                      </Badge>
                    )}
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
                      {task.review_status !== "approved" && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleReview(task, "approve")}
                          disabled={reviewing === task.id}
                          title="审核通过"
                        >
                          <CheckCircle2 className="h-4 w-4 mr-1" /> 通过
                        </Button>
                      )}
                      {task.review_status === "approved" && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openPublish(task)}
                          title="发布到平台"
                        >
                          <Share2 className="h-4 w-4 mr-1" /> 发布
                        </Button>
                      )}
                      {task.review_status !== "rejected" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleReview(task, "reject")}
                          disabled={reviewing === task.id}
                          title="拒绝"
                        >
                          <XCircle className="h-4 w-4 text-destructive" />
                        </Button>
                      )}
                    </>
                  )}
                  {(task.status === "pending" || task.status === "processing") && (
                    <Button variant="outline" size="sm" onClick={() => handleCancel(task)} title="取消任务">
                      <Ban className="h-4 w-4 mr-1" /> 取消
                    </Button>
                  )}
                  {(task.status === "failed" || task.status === "cancelled") && (
                    <Button variant="outline" size="sm" onClick={() => handleRetry(task)} title="重试">
                      <RotateCcw className="h-4 w-4 mr-1" /> 重试
                    </Button>
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

      <Dialog open={publishOpen} onOpenChange={setPublishOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>发布视频到平台</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {publishTask && (
              <p className="text-sm text-muted-foreground truncate">视频：{publishTask.request.title}</p>
            )}
            <div className="space-y-2">
              <Label>选择平台账号</Label>
              <Select value={publishPlatform} onValueChange={setPublishPlatform}>
                <SelectTrigger>
                  <SelectValue placeholder="选择已配置的发布账号" />
                </SelectTrigger>
                <SelectContent>
                  {publishers.map((p) => (
                    <SelectItem key={p.id} value={p.platform}>
                      {p.name} ({p.platform}) {p.folder_name ? `· ${p.folder_name}` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {publishers.length === 0 && (
                <p className="text-xs text-muted-foreground">暂无账号，请先到 Publishers 页面添加并登录</p>
              )}
            </div>
            <div className="space-y-2">
              <Label>文件夹 / Playlist ID（可选）</Label>
              <Input
                placeholder="留空使用账号默认，YouTube=playlistId，Douyin=合集ID"
                value={publishFolderId}
                onChange={(e) => setPublishFolderId(e.target.value)}
              />
            </div>

            {publishJobs.length > 0 && (
              <div className="space-y-2 border-t pt-3">
                <Label>发布记录</Label>
                {publishJobs.map((job) => (
                  <div key={job.id} className="flex items-center justify-between text-xs border rounded px-2 py-1">
                    <span className="flex items-center gap-2">
                      <Badge
                        variant={
                          job.status === "completed"
                            ? "default"
                            : job.status === "failed"
                              ? "destructive"
                              : "secondary"
                        }
                      >
                        {job.status}
                      </Badge>
                      {job.platform}
                      {job.post_url && (
                        <a href={job.post_url} target="_blank" rel="noreferrer" className="text-primary underline">
                          链接
                        </a>
                      )}
                      {job.error && <span className="text-destructive truncate max-w-[180px]">{job.error}</span>}
                    </span>
                    {job.status === "failed" && (
                      <Button variant="ghost" size="sm" onClick={() => handleRetryPublish(job.id)}>
                        <RotateCcw className="h-3 w-3" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setPublishOpen(false)}>
                关闭
              </Button>
              <Button onClick={handlePublish} disabled={publishing || !publishPlatform}>
                {publishing ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Share2 className="h-4 w-4 mr-2" />}
                加入发布队列
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
