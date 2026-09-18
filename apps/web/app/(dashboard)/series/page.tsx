"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FolderTree, Plus, Pencil, Trash2, Loader2, ArrowRight } from "lucide-react";
import { seriesApi, Series, SeriesCreate } from "@/lib/api-client";

const EMPTY_FORM: SeriesCreate = {
  name: "",
  description: "",
  system_prompt: "",
  default_voice: "zh-CN-XiaoxiaoNeural",
  default_voice_rate: "+0%",
  default_resolution_width: 1920,
  default_resolution_height: 1080,
  default_background_source: "both",
};

export default function SeriesPage() {
  const [series, setSeries] = useState<Series[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Series | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<SeriesCreate>(EMPTY_FORM);

  const fetchSeries = useCallback(async () => {
    setLoading(true);
    const res = await seriesApi.list();
    if (res.success && res.data) setSeries(res.data as unknown as Series[]);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchSeries();
  }, [fetchSeries]);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setShowForm(true);
  };

  const openEdit = (s: Series) => {
    setEditing(s);
    setForm({
      name: s.name,
      description: s.description || "",
      system_prompt: s.system_prompt || "",
      default_voice: s.default_voice || "zh-CN-XiaoxiaoNeural",
      default_voice_rate: s.default_voice_rate || "+0%",
      default_resolution_width: s.default_resolution_width || 1920,
      default_resolution_height: s.default_resolution_height || 1080,
      default_background_source: s.default_background_source || "both",
    });
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      if (editing) {
        await seriesApi.update(editing.id, form);
      } else {
        await seriesApi.create(form);
      }
      setShowForm(false);
      fetchSeries();
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (s: Series) => {
    if (!confirm(`确定删除系列「${s.name}」？已生成的视频不会被删除。`)) return;
    await seriesApi.delete(s.id);
    fetchSeries();
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <FolderTree className="h-7 w-7" /> 系列
          </h1>
          <p className="text-muted-foreground">
            将同一主题的视频归入一个系列，统一管理、统一发布
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4 mr-2" /> 新建系列
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : series.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center text-muted-foreground">
            暂无系列，点击“新建系列”开始。生成视频时即可选择归属系列。
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {series.map((s) => (
            <Card key={s.id} className="flex flex-col">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="text-base">{s.name}</CardTitle>
                    <CardDescription className="font-mono text-xs">{s.slug}</CardDescription>
                  </div>
                  <Badge variant="secondary">{s.default_resolution_width ?? 1920}×{s.default_resolution_height ?? 1080}</Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3 flex-1">
                <p className="text-sm text-muted-foreground line-clamp-2 min-h-[2.5rem]">
                  {s.description || "（无描述）"}
                </p>
                <div className="text-xs text-muted-foreground space-y-0.5">
                  <div>默认语音：{s.default_voice || "zh-CN-XiaoxiaoNeural"}</div>
                  <div>默认素材：{s.default_background_source || "both"}</div>
                </div>
                <div className="flex gap-2 pt-2">
                  <Button variant="outline" size="sm" className="flex-1" asChild>
                    <Link href={`/series/${s.id}`}>
                      查看视频 <ArrowRight className="h-3 w-3 ml-1" />
                    </Link>
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => openEdit(s)}>
                    <Pencil className="h-3 w-3" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => handleDelete(s)}>
                    <Trash2 className="h-3 w-3 text-destructive" />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑系列" : "新建系列"}</DialogTitle>
            <DialogDescription>系列默认参数会在生成视频时自动套用</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>名称</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="如 健康饮食科普"
              />
            </div>
            <div className="space-y-2">
              <Label>描述</Label>
              <Textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={2}
                placeholder="这个系列讲什么？"
              />
            </div>
            <div className="space-y-2">
              <Label>默认 System Prompt</Label>
              <Textarea
                value={form.system_prompt}
                onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
                rows={3}
                placeholder="该系列统一的脚本生成提示词"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>默认语音</Label>
                <Input
                  value={form.default_voice}
                  onChange={(e) => setForm({ ...form, default_voice: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label>语速</Label>
                <Input
                  value={form.default_voice_rate}
                  onChange={(e) => setForm({ ...form, default_voice_rate: e.target.value })}
                  placeholder="+0%"
                />
              </div>
              <div className="space-y-2">
                <Label>默认宽</Label>
                <Input
                  type="number"
                  value={form.default_resolution_width ?? 1920}
                  onChange={(e) => setForm({ ...form, default_resolution_width: Number(e.target.value) })}
                />
              </div>
              <div className="space-y-2">
                <Label>默认高</Label>
                <Input
                  type="number"
                  value={form.default_resolution_height ?? 1080}
                  onChange={(e) => setForm({ ...form, default_resolution_height: Number(e.target.value) })}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>默认素材来源</Label>
              <Input
                value={form.default_background_source}
                onChange={(e) => setForm({ ...form, default_background_source: e.target.value })}
                placeholder="both / pexels / pixabay / local / synthetic"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowForm(false)}>
                取消
              </Button>
              <Button onClick={handleSave} disabled={saving || !form.name.trim()}>
                {saving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null} 保存
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
