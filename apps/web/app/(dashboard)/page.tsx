"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Video,
  Loader2,
  ClipboardCheck,
  Send,
  CheckCircle2,
  XCircle,
  FolderTree,
  Share2,
  Plus,
} from "lucide-react";
import {
  videosApi,
  seriesApi,
  publishingApi,
  VideoTask,
  Series,
  PublishJob,
} from "@/lib/api-client";

function statusBadge(task: VideoTask) {
  switch (task.status) {
    case "completed":
      return task.review_status === "approved" ? "已审核" : "待审核";
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

function formatDate(dateStr?: string) {
  if (!dateStr) return "";
  return new Date(dateStr).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function DashboardPage() {
  const [tasks, setTasks] = useState<VideoTask[]>([]);
  const [series, setSeries] = useState<Series[]>([]);
  const [jobs, setJobs] = useState<PublishJob[]>([]);
  const [loading, setLoading] = useState(true);

  const loadMeta = useCallback(async () => {
    const [sRes, jRes] = await Promise.all([seriesApi.list(), publishingApi.list()]);
    if (sRes.success && sRes.data) setSeries(sRes.data as unknown as Series[]);
    if (jRes.success && jRes.data) setJobs(jRes.data as unknown as PublishJob[]);
  }, []);

  const loadTasks = useCallback(async () => {
    const res = await videosApi.list();
    if (res.success && res.data) setTasks(res.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    loadTasks();
    loadMeta();
    const es = new EventSource(videosApi.eventsUrl());
    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        if (parsed?.success && parsed.data) {
          setTasks(parsed.data as VideoTask[]);
          setLoading(false);
        }
      } catch {}
    };
    const interval = setInterval(loadMeta, 8000);
    return () => {
      es.close();
      clearInterval(interval);
    };
  }, [loadTasks, loadMeta]);

  const generating = tasks.filter((t) => t.status === "processing" || t.status === "pending").length;
  const review = tasks.filter((t) => t.status === "completed" && t.review_status !== "approved").length;
  const approved = tasks.filter((t) => t.status === "completed" && t.review_status === "approved").length;
  const failed = tasks.filter((t) => t.status === "failed" || t.status === "cancelled").length;
  const publishedJobs = jobs.filter((j) => j.status === "completed").length;
  const pendingJobs = jobs.filter((j) => j.status === "pending" || j.status === "processing").length;

  const stages: {
    key: string;
    title: string;
    value: number;
    icon: typeof Loader2;
    href: "/videos" | "/publishers";
    tone: string;
  }[] = [
    { key: "generating", title: "生成中", value: generating, icon: Loader2, href: "/videos", tone: "text-primary" },
    { key: "review", title: "待审核", value: review, icon: ClipboardCheck, href: "/videos", tone: "text-amber-500" },
    { key: "approved", title: "已审核", value: approved, icon: CheckCircle2, href: "/videos", tone: "text-green-600" },
    { key: "published", title: "已发布", value: publishedJobs, icon: Send, href: "/publishers", tone: "text-green-600" },
    { key: "queue", title: "发布队列", value: pendingJobs, icon: Share2, href: "/publishers", tone: "text-primary" },
    { key: "failed", title: "失败", value: failed, icon: XCircle, href: "/videos", tone: "text-destructive" },
  ];

  const recent = [...tasks].slice(0, 6);

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">Dashboard</h1>
          <p className="text-muted-foreground">流水线总览：生成 → 审核 → 发布</p>
        </div>
        <Button asChild>
          <Link href="/series">
            <Plus className="h-4 w-4 mr-2" /> 新建视频
          </Link>
        </Button>
      </div>

      <div className="grid gap-4 grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {stages.map((stage) => (
          <Link key={stage.key} href={stage.href}>
            <Card className="hover:border-primary transition-colors">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">{stage.title}</CardTitle>
                <stage.icon className={`h-4 w-4 ${stage.tone}`} />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{loading ? "-" : stage.value}</div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3 mt-8">
        <div className="lg:col-span-2">
          <h2 className="text-xl font-semibold mb-4">最近视频</h2>
          <Card>
            <CardContent className="p-0">
              {recent.length === 0 ? (
                <p className="p-6 text-sm text-muted-foreground">还没有视频，去「系列」生成第一个吧。</p>
              ) : (
                <div className="divide-y">
                  {recent.map((task) => (
                    <div key={task.id} className="flex items-center justify-between p-4">
                      <div className="flex items-center gap-3 min-w-0">
                        <Video className="h-5 w-5 text-muted-foreground shrink-0" />
                        <div className="min-w-0">
                          <p className="font-medium truncate">{task.request?.title}</p>
                          <p className="text-xs text-muted-foreground truncate">
                            {task.series_name || "_unsorted"} · {formatDate(task.created_at)}
                          </p>
                        </div>
                      </div>
                      <Badge
                        variant={
                          task.status === "failed"
                            ? "destructive"
                            : task.status === "completed"
                              ? "default"
                              : "secondary"
                        }
                      >
                        {statusBadge(task)}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div>
          <h2 className="text-xl font-semibold mb-4">系列</h2>
          <Card>
            <CardContent className="p-4">
              {series.length === 0 ? (
                <p className="text-sm text-muted-foreground">暂无系列</p>
              ) : (
                <div className="space-y-3">
                  {series.slice(0, 6).map((s) => (
                    <Link
                      key={s.id}
                      href={`/series/${s.id}`}
                      className="flex items-center justify-between hover:underline"
                    >
                      <span className="flex items-center gap-2 text-sm">
                        <FolderTree className="h-4 w-4" /> {s.name}
                      </span>
                      <span className="text-xs text-muted-foreground font-mono">{s.slug}</span>
                    </Link>
                  ))}
                </div>
              )}
              <Separator className="my-4" />
              <Button variant="outline" className="w-full" asChild>
                <Link href="/series">管理系列</Link>
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
