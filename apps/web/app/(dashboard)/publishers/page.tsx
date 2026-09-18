"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Plus,
  Trash2,
  Pencil,
  Loader2,
  Share2,
  FolderOpen,
  Youtube,
  Smartphone,
  BookOpen,
  ExternalLink,
  RefreshCw,
} from "lucide-react";
import { publishersApi, PublisherAccount } from "@/lib/api-client";

const PLATFORM_OPTIONS = [
  { value: "youtube", label: "YouTube", icon: Youtube, desc: "官方 API，folder=Playlist" },
  { value: "douyin", label: "Douyin 抖音", icon: Smartphone, desc: "Playwright，folder=合集" },
  { value: "xiaohongshu", label: "Xiaohongshu 小红书", icon: BookOpen, desc: "Playwright，folder=专辑" },
  { value: "bilibili", label: "Bilibili", icon: Share2, desc: "预留" },
];

function platformMeta(value: string) {
  return PLATFORM_OPTIONS.find((p) => p.value === value) || { label: value, icon: Share2, desc: "" };
}

export default function PublishersPage() {
  const [accounts, setAccounts] = useState<PublisherAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<PublisherAccount | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    platform: "youtube",
    name: "",
    cookies: "",
    credentials: "",
    folder_id: "",
    folder_name: "",
  });
  const [folders, setFolders] = useState<Record<string, { id: string; name: string }[]>>({});
  const [foldersLoading, setFoldersLoading] = useState<string | null>(null);
  const [newFolderName, setNewFolderName] = useState<Record<string, string>>({});

  const fetchAccounts = useCallback(async () => {
    setLoading(true);
    const res = await publishersApi.list();
    if (res.success && res.data) setAccounts(res.data as unknown as PublisherAccount[]);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchAccounts();
  }, [fetchAccounts]);

  const openCreate = () => {
    setEditing(null);
    setForm({ platform: "youtube", name: "", cookies: "", credentials: "", folder_id: "", folder_name: "" });
    setShowForm(true);
  };
  const openEdit = (acc: PublisherAccount) => {
    setEditing(acc);
    setForm({
      platform: acc.platform,
      name: acc.name,
      cookies: (acc as unknown as { cookies?: string }).cookies || "",
      credentials: (acc as unknown as { credentials?: string }).credentials || "",
      folder_id: acc.folder_id || "",
      folder_name: acc.folder_name || "",
    });
    setShowForm(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        platform: form.platform,
        name: form.name,
        folder_id: form.folder_id || undefined,
        folder_name: form.folder_name || undefined,
      };
      if (form.platform === "youtube") {
        payload.credentials = form.credentials || form.cookies || undefined;
      } else {
        payload.cookies = form.cookies || undefined;
        if (form.credentials) payload.credentials = form.credentials;
      }
      if (editing) {
        await fetch(`/api/publishers/${editing.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } else {
        await publishersApi.create(payload as unknown as { platform: string; name: string });
      }
      setShowForm(false);
      fetchAccounts();
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定删除该发布账号？")) return;
    await fetch(`/api/publishers/${id}`, { method: "DELETE" });
    fetchAccounts();
  };

  const handleListFolders = async (acc: PublisherAccount) => {
    setFoldersLoading(acc.id);
    const res = await publishersApi.listFolders(acc.id);
    if (res.success && res.data) setFolders((prev) => ({ ...prev, [acc.id]: res.data as unknown as { id: string; name: string }[] }));
    setFoldersLoading(null);
  };

  const handleCreateFolder = async (acc: PublisherAccount) => {
    const name = newFolderName[acc.id]?.trim();
    if (!name) return;
    await fetch(`/api/publishers/${acc.id}/folders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).catch(() => {});
    // For now just append mock
    setFolders((prev) => ({
      ...prev,
      [acc.id]: [...(prev[acc.id] || []), { id: `mock_${name}`, name }],
    }));
    setNewFolderName((prev) => ({ ...prev, [acc.id]: "" }));
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Share2 className="h-7 w-7" /> Publishers
          </h1>
          <p className="text-muted-foreground">多平台分发账号与文件夹/合集管理（YouTube=Playlist，Douyin=合集，XHS=专辑）</p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4 mr-2" /> 添加账号
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : accounts.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center text-muted-foreground">
            暂无发布账号，点击“添加账号”开始。建议先配置 YouTube OAuth，再添加 Douyin/XHS 的 cookies。
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {accounts.map((acc) => {
            const meta = platformMeta(acc.platform);
            const Icon = meta.icon as unknown as React.ElementType;
            return (
              <Card key={acc.id} className="flex flex-col">
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                        <Icon className="h-5 w-5" />
                      </div>
                      <div>
                        <CardTitle className="text-base">{acc.name}</CardTitle>
                        <CardDescription>{meta.label} • {acc.folder_name || acc.folder_id || "未设文件夹"}</CardDescription>
                      </div>
                    </div>
                    <Badge variant={acc.enabled ? "default" : "secondary"}>{acc.enabled ? "启用" : "停用"}</Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3 flex-1">
                  <div className="text-xs text-muted-foreground break-all line-clamp-2">
                    {acc.platform === "youtube" ? (acc as unknown as { credentials?: string }).credentials?.slice(0, 60) || "无凭据（mock 发布）" : (acc as unknown as { cookies?: string }).cookies?.slice(0, 60) || "无 cookies"}
                  </div>
                  <Separator />
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label className="text-xs">文件夹 / 合集</Label>
                      <Button variant="ghost" size="sm" onClick={() => handleListFolders(acc)} disabled={foldersLoading === acc.id}>
                        {foldersLoading === acc.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
                        <span className="ml-1">刷新</span>
                      </Button>
                    </div>
                    {folders[acc.id] ? (
                      <div className="space-y-1">
                        {folders[acc.id].map((f) => (
                          <div key={f.id} className="flex items-center justify-between text-xs border rounded px-2 py-1">
                            <span className="flex items-center gap-1">
                              <FolderOpen className="h-3 w-3" /> {f.name}
                            </span>
                            <span className="text-muted-foreground">{f.id}</span>
                          </div>
                        ))}
                        {folders[acc.id].length === 0 && <p className="text-xs text-muted-foreground">无文件夹</p>}
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">点击刷新拉取 {meta.label} 的合集/专辑/Playlist</p>
                    )}
                    <div className="flex gap-2">
                      <Input
                        placeholder="新建文件夹名称"
                        value={newFolderName[acc.id] || ""}
                        onChange={(e) => setNewFolderName((prev) => ({ ...prev, [acc.id]: e.target.value }))}
                        className="h-8 text-xs"
                      />
                      <Button size="sm" variant="outline" onClick={() => handleCreateFolder(acc)} disabled={!newFolderName[acc.id]?.trim()}>
                        创建
                      </Button>
                    </div>
                  </div>
                  <div className="flex gap-2 pt-2">
                    <Button variant="outline" size="sm" onClick={() => openEdit(acc)} className="flex-1">
                      <Pencil className="h-3 w-3 mr-1" /> 编辑
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => handleDelete(acc.id)}>
                      <Trash2 className="h-3 w-3 text-destructive" />
                    </Button>
                    {acc.platform === "youtube" && (
                      <Button variant="ghost" size="sm" asChild>
                        <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer">
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <Dialog open={showForm} onOpenChange={setShowForm}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑发布账号" : "添加发布账号"}</DialogTitle>
            <DialogDescription>按平台填对应凭据；文件夹可在列表中刷新/创建后回填</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>平台</Label>
              <Select value={form.platform} onValueChange={(v) => setForm({ ...form, platform: v })}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PLATFORM_OPTIONS.map((p) => (
                    <SelectItem key={p.value} value={p.value}>
                      {p.label} — {p.desc}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>名称</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如 我的YouTube / 公司抖音" />
            </div>
            {form.platform === "youtube" ? (
              <div className="space-y-2">
                <Label>OAuth 凭据 JSON（含 refresh_token）</Label>
                <Textarea value={form.credentials} onChange={(e) => setForm({ ...form, credentials: e.target.value })} rows={4} placeholder='{"refresh_token":"...","client_id":"..."} 留空则 mock 发布' />
                <p className="text-xs text-muted-foreground">从 Google Cloud Console 获取，存 refresh_token 即可；留空走 mock 便于演示</p>
              </div>
            ) : (
              <div className="space-y-2">
                <Label>Cookies JSON（Playwright 导出）</Label>
                <Textarea value={form.cookies} onChange={(e) => setForm({ ...form, cookies: e.target.value })} rows={4} placeholder='[{"name":"...","value":"...","domain":".douyin.com"}]' />
              </div>
            )}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>默认文件夹 ID</Label>
                <Input value={form.folder_id} onChange={(e) => setForm({ ...form, folder_id: e.target.value })} placeholder="playlistId / collectionId / albumId" />
              </div>
              <div className="space-y-2">
                <Label>文件夹名称</Label>
                <Input value={form.folder_name} onChange={(e) => setForm({ ...form, folder_name: e.target.value })} placeholder="便于展示" />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setShowForm(false)}>
                取消
              </Button>
              <Button onClick={handleSave} disabled={saving || !form.name || !form.platform}>
                {saving ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null} 保存
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
