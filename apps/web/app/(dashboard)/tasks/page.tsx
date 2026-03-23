"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Plus,
  Play,
  Pause,
  Trash2,
  Edit,
  ListTodo,
  FileText,
  Loader2,
  X,
} from "lucide-react";
import {
  tasksApi,
  runsApi,
  sourcesApi,
  Task,
  Run,
  Source,
  TaskCreate,
} from "@/lib/api-client";

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getStatusBadgeVariant(status: string) {
  switch (status) {
    case "completed":
    case "success":
      return "default";
    case "processing":
    case "running":
      return "warning";
    case "failed":
    case "error":
      return "destructive";
    default:
      return "secondary";
  }
}

function getLogLevelBadgeVariant(level: string) {
  switch (level) {
    case "success":
      return "default";
    case "warning":
      return "warning";
    case "error":
      return "destructive";
    default:
      return "secondary";
  }
}

const CRON_PRESETS = [
  { label: "每天 9:00", value: "0 9 * * *" },
  { label: "每天 18:00", value: "0 18 * * *" },
  { label: "每周一 10:00", value: "0 10 * * 1" },
  { label: "每小时", value: "0 * * * *" },
];

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState("tasks");
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [formData, setFormData] = useState<TaskCreate>({
    name: "",
    source_id: "",
    schedule: "0 9 * * *",
    enabled: true,
  });

  const fetchData = useCallback(async () => {
    const [tasksRes, sourcesRes, runsRes] = await Promise.all([
      tasksApi.list(),
      sourcesApi.list(),
      runsApi.list({ page: 1, page_size: 50 }),
    ]);

    if (tasksRes.success && tasksRes.data) {
      setTasks(tasksRes.data);
    }
    if (sourcesRes.success && sourcesRes.data) {
      setSources(sourcesRes.data);
    }
    if (runsRes.success && runsRes.data) {
      setRuns(runsRes.data.items);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleToggleEnabled = async (task: Task) => {
    await tasksApi.update(task.id, { enabled: !task.enabled });
    fetchData();
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除这个任务吗？")) return;
    await tasksApi.delete(id);
    fetchData();
  };

  const handleRun = async (task: Task) => {
    await tasksApi.run(task.id);
    fetchData();
  };

  const handleSubmit = async () => {
    if (!formData.name || !formData.source_id || !formData.schedule) {
      alert("请填写所有必填字段");
      return;
    }

    if (editingTask) {
      await tasksApi.update(editingTask.id, {
        name: formData.name,
        schedule: formData.schedule,
        enabled: formData.enabled,
      });
    } else {
      await tasksApi.create(formData);
    }

    setShowCreateForm(false);
    setEditingTask(null);
    setFormData({
      name: "",
      source_id: "",
      schedule: "0 9 * * *",
      enabled: true,
    });
    fetchData();
  };

  const handleEdit = (task: Task) => {
    setEditingTask(task);
    setFormData({
      name: task.name,
      source_id: task.source_id,
      schedule: task.schedule,
      enabled: task.enabled,
    });
    setShowCreateForm(true);
  };

  const handleCancel = () => {
    setShowCreateForm(false);
    setEditingTask(null);
    setFormData({
      name: "",
      source_id: "",
      schedule: "0 9 * * *",
      enabled: true,
    });
  };

  const getSourceName = (sourceId: string) => {
    const source = sources.find((s) => s.id === sourceId);
    return source?.name || sourceId;
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
          <h1 className="text-3xl font-bold">Tasks & Logs</h1>
          <p className="text-muted-foreground">管理任务和查看执行日志</p>
        </div>
        {activeTab === "tasks" && !showCreateForm && (
          <Button onClick={() => setShowCreateForm(true)}>
            <Plus className="h-4 w-4 mr-2" />
            创建任务
          </Button>
        )}
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="mb-6">
          <TabsTrigger value="tasks" className="gap-2">
            <ListTodo className="h-4 w-4" />
            任务
          </TabsTrigger>
          <TabsTrigger value="logs" className="gap-2">
            <FileText className="h-4 w-4" />
            日志
          </TabsTrigger>
        </TabsList>

        <TabsContent value="tasks">
          {showCreateForm && (
            <Card className="mb-8">
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle>{editingTask ? "编辑任务" : "创建新任务"}</CardTitle>
                <Button variant="ghost" size="icon" onClick={handleCancel}>
                  <X className="h-4 w-4" />
                </Button>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="name">任务名称</Label>
                    <Input
                      id="name"
                      placeholder="输入任务名称"
                      value={formData.name}
                      onChange={(e) =>
                        setFormData({ ...formData, name: e.target.value })
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="source">内容来源</Label>
                    <Select
                      value={formData.source_id}
                      onValueChange={(value) =>
                        setFormData({ ...formData, source_id: value })
                      }
                      disabled={!!editingTask}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="选择来源" />
                      </SelectTrigger>
                      <SelectContent>
                        {sources
                          .filter((s) => s.enabled)
                          .map((source) => (
                            <SelectItem key={source.id} value={source.id}>
                              {source.name} ({source.type})
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                    {sources.length === 0 && (
                      <p className="text-xs text-muted-foreground">
                        暂无可用来源，请先创建来源
                      </p>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="schedule">执行计划 (Cron)</Label>
                    <Input
                      id="schedule"
                      placeholder="0 9 * * *"
                      value={formData.schedule}
                      onChange={(e) =>
                        setFormData({ ...formData, schedule: e.target.value })
                      }
                    />
                    <div className="flex flex-wrap gap-1 mt-1">
                      {CRON_PRESETS.map((preset) => (
                        <Button
                          key={preset.value}
                          variant="outline"
                          size="sm"
                          className="text-xs"
                          onClick={() =>
                            setFormData({ ...formData, schedule: preset.value })
                          }
                        >
                          {preset.label}
                        </Button>
                      ))}
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label>状态</Label>
                    <div className="flex items-center gap-2 pt-2">
                      <Switch
                        checked={formData.enabled}
                        onCheckedChange={(checked) =>
                          setFormData({ ...formData, enabled: checked })
                        }
                      />
                      <span className="text-sm">
                        {formData.enabled ? "启用" : "禁用"}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button onClick={handleSubmit}>
                    {editingTask ? "保存" : "创建"}
                  </Button>
                  <Button variant="outline" onClick={handleCancel}>
                    取消
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardContent className="p-0">
              {tasks.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16">
                  <ListTodo className="h-16 w-16 text-muted-foreground mb-4" />
                  <p className="text-muted-foreground mb-4">暂无任务</p>
                  <Button onClick={() => setShowCreateForm(true)}>
                    <Plus className="h-4 w-4 mr-2" />
                    创建第一个任务
                  </Button>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>名称</TableHead>
                      <TableHead>来源</TableHead>
                      <TableHead>执行计划</TableHead>
                      <TableHead>创建时间</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>启用</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {tasks.map((task) => (
                      <TableRow key={task.id}>
                        <TableCell className="font-medium">
                          {task.name}
                        </TableCell>
                        <TableCell>{getSourceName(task.source_id)}</TableCell>
                        <TableCell>
                          <code className="text-sm bg-muted px-2 py-1 rounded">
                            {task.schedule}
                          </code>
                        </TableCell>
                        <TableCell>{formatDate(task.created_at)}</TableCell>
                        <TableCell>
                          <Badge variant="secondary">空闲</Badge>
                        </TableCell>
                        <TableCell>
                          <Switch
                            checked={task.enabled}
                            onCheckedChange={() => handleToggleEnabled(task)}
                          />
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-2">
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleRun(task)}
                              title="立即执行"
                            >
                              <Play className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleEdit(task)}
                              title="编辑"
                            >
                              <Edit className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleDelete(task.id)}
                              title="删除"
                            >
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="logs">
          <Card>
            <CardContent className="p-0">
              {runs.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16">
                  <FileText className="h-16 w-16 text-muted-foreground mb-4" />
                  <p className="text-muted-foreground">暂无执行记录</p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[180px]">执行时间</TableHead>
                      <TableHead className="w-[100px]">状态</TableHead>
                      <TableHead className="w-[200px]">任务</TableHead>
                      <TableHead>信息</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {runs.map((run) => (
                      <TableRow key={run.id}>
                        <TableCell className="font-mono text-sm text-muted-foreground">
                          {formatDate(run.created_at)}
                        </TableCell>
                        <TableCell>
                          <Badge variant={getStatusBadgeVariant(run.status)}>
                            {run.status === "completed"
                              ? "完成"
                              : run.status === "processing"
                                ? "处理中"
                                : run.status === "failed"
                                  ? "失败"
                                  : "等待中"}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-medium">
                          {run.task?.name || run.task_id}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {run.error || run.video_path || "-"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
