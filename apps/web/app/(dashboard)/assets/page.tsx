"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Switch } from "@/components/ui/switch";
import {
  Music,
  Video,
  FileText,
  Rss,
  Plus,
  Trash2,
  Upload,
  Star,
  Play,
  Loader2,
  Pencil,
  Newspaper,
  TrendingUp,
  Globe,
  X,
  Save,
  Check,
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { generalSettingsApi, GeneralSettings, systemPromptsApi, SystemPrompt } from "@/lib/api-client";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Asset {
  id: string;
  name: string;
  originalName: string;
  type: "music" | "video";
  path: string;
  size: number;
  mimeType: string;
  createdAt: string;
  updatedAt: string;
}

interface Source {
  id: string;
  name: string;
  type: "rss" | "news_api" | "hot_topics" | "custom";
  url: string;
  keywords: string[];
  enabled: boolean;
  lastFetch: string;
}

interface Document {
  id: string;
  name: string;
  filename: string;
  size: number;
  createdAt: string;
}

const typeIcons = {
  rss: Rss,
  news_api: Newspaper,
  hot_topics: TrendingUp,
  custom: Globe,
};

const ACCEPTED_MUSIC_TYPES = ".mp3,.wav,.ogg,.m4a";
const ACCEPTED_VIDEO_TYPES = ".mp4,.mov,.avi,.webm";
const ACCEPTED_DOCUMENT_TYPES = ".pdf,.txt,.md,.doc,.docx";

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

const mockSources: Source[] = [
  {
    id: "1",
    name: "TechCrunch",
    type: "rss",
    url: "https://techcrunch.com/feed/",
    keywords: ["AI", "startup", "tech"],
    enabled: true,
    lastFetch: "2024-03-20 09:00",
  },
  {
    id: "2",
    name: "OpenAI Blog",
    type: "rss",
    url: "https://openai.com/blog/rss.xml",
    keywords: ["GPT", "AI"],
    enabled: true,
    lastFetch: "2024-03-20 08:30",
  },
];

const mockDocuments: Document[] = [];

const PROMPTS_STORAGE_KEY = "systemPrompts";

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [sources, setSources] = useState<Source[]>(mockSources);
  const [prompts, setPrompts] = useState<SystemPrompt[]>([]);
  const [documents, setDocuments] = useState<Document[]>(mockDocuments);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [generalSettings, setGeneralSettings] = useState<GeneralSettings | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");

  const [showSourceForm, setShowSourceForm] = useState(false);
  const [showPromptForm, setShowPromptForm] = useState(false);
  const [editingPrompt, setEditingPrompt] = useState<SystemPrompt | null>(null);
  const [promptForm, setPromptForm] = useState({ name: "", content: "" });
  const [sourceForm, setSourceForm] = useState({
    name: "",
    type: "rss" as Source["type"],
    url: "",
    keywords: "",
  });
  const [playingAudioId, setPlayingAudioId] = useState<string | null>(null);
  const { toast } = useToast();

  const musicAssets = assets.filter(
    (a) => a.type === "music" || a.mimeType?.startsWith("audio/")
  );
  const videoAssets = assets.filter(
    (a) => a.type === "video" || a.mimeType?.startsWith("video/")
  );

  const fetchAssets = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/assets");
      const data = await response.json();
      setAssets(data);
    } catch (error) {
      console.error("Failed to fetch assets:", error);
      toast({
        title: "Error",
        description: "Failed to fetch assets",
        variant: "destructive",
      });
    }
    setLoading(false);
  }, [toast]);

  const fetchGeneralSettings = useCallback(async () => {
    const response = await generalSettingsApi.get();
    if (response.success && response.data) {
      setGeneralSettings(response.data);
    }
  }, []);

  const fetchPrompts = useCallback(async () => {
    const response = await systemPromptsApi.list();
    if (response.success && response.data) {
      setPrompts(response.data);
    }
  }, []);

  useEffect(() => {
    fetchAssets();
    fetchGeneralSettings();
    fetchPrompts();
  }, [fetchAssets, fetchGeneralSettings, fetchPrompts]);

  const handleUpload = async (
    e: React.ChangeEvent<HTMLInputElement>,
    type: "music" | "video" | "document"
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    const formData = new FormData();
    formData.append("file", file);
    formData.append("type", type);

    try {
      const response = await fetch("/api/assets", {
        method: "POST",
        body: formData,
      });
      if (response.ok) {
        toast({
          title: "Success",
          description: "File uploaded successfully",
        });
        fetchAssets();
      } else {
        throw new Error("Upload failed");
      }
    } catch (error) {
      console.error("Upload failed:", error);
      toast({
        title: "Error",
        description: "Failed to upload file",
        variant: "destructive",
      });
    }
    setUploading(false);
    e.target.value = "";
  };

  const handleDeleteAsset = async (id: string) => {
    if (!confirm("Are you sure you want to delete this asset?")) return;
    try {
      await fetch(`/api/assets/${id}`, { method: "DELETE" });
      toast({
        title: "Success",
        description: "Asset deleted successfully",
      });
      fetchAssets();
    } catch (error) {
      console.error("Delete failed:", error);
      toast({
        title: "Error",
        description: "Failed to delete asset",
        variant: "destructive",
      });
    }
  };

  const handleRename = async (id: string) => {
    if (!editingName.trim()) return;

    try {
      const response = await fetch(`/api/assets/${id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ name: editingName }),
      });

      if (response.ok) {
        toast({
          title: "Success",
          description: "Asset renamed successfully",
        });
        setEditingId(null);
        setEditingName("");
        fetchAssets();
      } else {
        throw new Error("Rename failed");
      }
    } catch (error) {
      console.error("Failed to rename asset:", error);
      toast({
        title: "Error",
        description: "Failed to rename asset",
        variant: "destructive",
      });
    }
  };

  const handleSetDefaultMusic = async (filename: string) => {
    if (!generalSettings) return;
    const response = await generalSettingsApi.update({
      default_background_music: filename,
    });
    if (response.success && response.data) {
      setGeneralSettings(response.data);
      toast({
        title: "Success",
        description: "Default music updated",
      });
    }
  };

  const toggleSource = (id: string) => {
    setSources(
      sources.map((source) =>
        source.id === id ? { ...source, enabled: !source.enabled } : source
      )
    );
  };

  const handleAddSource = () => {
    const newSource: Source = {
      id: Date.now().toString(),
      name: sourceForm.name,
      type: sourceForm.type,
      url: sourceForm.url,
      keywords: sourceForm.keywords.split(",").map((k) => k.trim()).filter(Boolean),
      enabled: true,
      lastFetch: "-",
    };
    setSources([...sources, newSource]);
    setSourceForm({ name: "", type: "rss", url: "", keywords: "" });
    setShowSourceForm(false);
    toast({
      title: "Success",
      description: "Source added successfully",
    });
  };

  const handleDeleteSource = (id: string) => {
    setSources(sources.filter((s) => s.id !== id));
    toast({
      title: "Success",
      description: "Source deleted",
    });
  };

  const handleAddPrompt = async () => {
    const response = await systemPromptsApi.create({
      name: promptForm.name,
      content: promptForm.content,
      is_default: prompts.length === 0,
    });
    if (response.success) {
      fetchPrompts();
      setPromptForm({ name: "", content: "" });
      setShowPromptForm(false);
      toast({
        title: "Success",
        description: "Prompt added successfully",
      });
    } else {
      toast({
        title: "Error",
        description: response.error || "Failed to add prompt",
        variant: "destructive",
      });
    }
  };

  const handleUpdatePrompt = async () => {
    if (!editingPrompt) return;
    const response = await systemPromptsApi.update(editingPrompt.id, {
      name: promptForm.name,
      content: promptForm.content,
    });
    if (response.success) {
      fetchPrompts();
      setEditingPrompt(null);
      setPromptForm({ name: "", content: "" });
      setShowPromptForm(false);
      toast({
        title: "Success",
        description: "Prompt updated successfully",
      });
    } else {
      toast({
        title: "Error",
        description: response.error || "Failed to update prompt",
        variant: "destructive",
      });
    }
  };

  const handleSetDefaultPrompt = async (id: string) => {
    const response = await systemPromptsApi.setDefault(id);
    if (response.success) {
      fetchPrompts();
      toast({
        title: "Success",
        description: "Default prompt updated",
      });
    }
  };

  const handleDeletePrompt = async (id: string) => {
    if (!confirm("Are you sure you want to delete this prompt?")) return;
    const response = await systemPromptsApi.delete(id);
    if (response.success) {
      fetchPrompts();
      toast({
        title: "Success",
        description: "Prompt deleted",
      });
    }
  };

  const startEditPrompt = (prompt: SystemPrompt) => {
    setEditingPrompt(prompt);
    setPromptForm({ name: prompt.name, content: prompt.content });
    setShowPromptForm(true);
  };

  const startEditing = (asset: Asset) => {
    setEditingId(asset.id);
    setEditingName(asset.name);
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditingName("");
  };

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Assets</h1>
        <p className="text-muted-foreground">
          Manage your background music, videos, prompts, documents, and content sources
        </p>
      </div>

      <Tabs defaultValue="music" className="space-y-6">
        <TabsList>
          <TabsTrigger value="music" className="flex items-center gap-2">
            <Music className="h-4 w-4" />
            Background Music
          </TabsTrigger>
          <TabsTrigger value="videos" className="flex items-center gap-2">
            <Video className="h-4 w-4" />
            Background Videos
          </TabsTrigger>
          <TabsTrigger value="prompts" className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Prompts
          </TabsTrigger>
          <TabsTrigger value="documents" className="flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Documents
          </TabsTrigger>
          <TabsTrigger value="sources" className="flex items-center gap-2">
            <Rss className="h-4 w-4" />
            Content Sources
          </TabsTrigger>
        </TabsList>

        <TabsContent value="music" className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Background Music</CardTitle>
                  <CardDescription>
                    Upload and manage background music for your videos
                  </CardDescription>
                </div>
                <div>
                  <input
                    type="file"
                    id="music-upload"
                    accept={ACCEPTED_MUSIC_TYPES}
                    className="hidden"
                    onChange={(e) => handleUpload(e, "music")}
                  />
                  <Button
                    onClick={() => document.getElementById("music-upload")?.click()}
                    disabled={uploading}
                  >
                    {uploading ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Upload className="h-4 w-4 mr-2" />
                    )}
                    Upload Music
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {loading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : musicAssets.length === 0 ? (
                <div className="p-8 text-center text-muted-foreground">
                  No music files uploaded. Click &quot;Upload Music&quot; to add background music.
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Size</TableHead>
                      <TableHead>Added</TableHead>
                      <TableHead>Default</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {musicAssets.map((asset) => (
                      <TableRow key={asset.id}>
                        <TableCell className="font-medium">
                          {editingId === asset.id ? (
                            <div className="flex items-center gap-2">
                              <Input
                                value={editingName}
                                onChange={(e) => setEditingName(e.target.value)}
                                className="w-48"
                              />
                              <Button
                                size="icon"
                                variant="ghost"
                                onClick={() => handleRename(asset.id)}
                              >
                                <Check className="h-4 w-4 text-green-600" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                onClick={cancelEditing}
                              >
                                <X className="h-4 w-4" />
                              </Button>
                            </div>
                          ) : (
                            <div className="flex items-center gap-2">
                              <Music className="h-4 w-4 text-muted-foreground" />
                              {asset.name}
                            </div>
                          )}
                        </TableCell>
                        <TableCell>{formatFileSize(asset.size)}</TableCell>
                        <TableCell>{new Date(asset.createdAt).toLocaleDateString()}</TableCell>
                        <TableCell>
                          {generalSettings?.default_background_music === asset.originalName ? (
                            <Badge variant="default" className="bg-yellow-600">
                              <Star className="h-3 w-3 mr-1" />
                              Default
                            </Badge>
                          ) : (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleSetDefaultMusic(asset.originalName)}
                            >
                              Set as Default
                            </Button>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-2">
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => {
                                if (playingAudioId === asset.id) {
                                  setPlayingAudioId(null);
                                } else {
                                  setPlayingAudioId(asset.id);
                                }
                              }}
                            >
                              {playingAudioId === asset.id ? (
                                <X className="h-4 w-4" />
                              ) : (
                                <Play className="h-4 w-4" />
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => startEditing(asset)}
                              disabled={editingId === asset.id}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleDeleteAsset(asset.id)}
                            >
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                          {playingAudioId === asset.id && (
                            <div className="mt-2">
                              <audio
                                autoPlay
                                controls
                                className="w-full max-w-[200px]"
                                onEnded={() => setPlayingAudioId(null)}
                              >
                                <source src={asset.path} type={asset.mimeType} />
                              </audio>
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="videos" className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Background Videos</CardTitle>
                  <CardDescription>
                    Upload and manage background videos for your content
                  </CardDescription>
                </div>
                <div>
                  <input
                    type="file"
                    id="video-upload"
                    accept={ACCEPTED_VIDEO_TYPES}
                    className="hidden"
                    onChange={(e) => handleUpload(e, "video")}
                  />
                  <Button
                    onClick={() => document.getElementById("video-upload")?.click()}
                    disabled={uploading}
                  >
                    {uploading ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Upload className="h-4 w-4 mr-2" />
                    )}
                    Upload Video
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {loading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : videoAssets.length === 0 ? (
                <div className="p-8 text-center text-muted-foreground">
                  No video files uploaded. Click &quot;Upload Video&quot; to add background videos.
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Size</TableHead>
                      <TableHead>Added</TableHead>
                      <TableHead>Default</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {videoAssets.map((asset) => (
                      <TableRow key={asset.id}>
                        <TableCell className="font-medium">
                          {editingId === asset.id ? (
                            <div className="flex items-center gap-2">
                              <Input
                                value={editingName}
                                onChange={(e) => setEditingName(e.target.value)}
                                className="w-48"
                              />
                              <Button
                                size="icon"
                                variant="ghost"
                                onClick={() => handleRename(asset.id)}
                              >
                                <Check className="h-4 w-4 text-green-600" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                onClick={cancelEditing}
                              >
                                <X className="h-4 w-4" />
                              </Button>
                            </div>
                          ) : (
                            <div className="flex items-center gap-2">
                              <Video className="h-4 w-4 text-muted-foreground" />
                              {asset.name}
                            </div>
                          )}
                        </TableCell>
                        <TableCell>{formatFileSize(asset.size)}</TableCell>
                        <TableCell>{new Date(asset.createdAt).toLocaleDateString()}</TableCell>
                        <TableCell>
                          <Button variant="ghost" size="sm">
                            <Star className="h-3 w-3 mr-1" />
                            Set Default
                          </Button>
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-2">
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => startEditing(asset)}
                              disabled={editingId === asset.id}
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleDeleteAsset(asset.id)}
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

        <TabsContent value="prompts" className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>System Prompts</CardTitle>
                  <CardDescription>
                    Manage system prompts for content generation
                  </CardDescription>
                </div>
                <Button onClick={() => { setEditingPrompt(null); setPromptForm({ name: "", content: "" }); setShowPromptForm(true); }}>
                  <Plus className="h-4 w-4 mr-2" />
                  Add Prompt
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <Dialog open={showPromptForm} onOpenChange={setShowPromptForm}>
                <DialogContent className="sm:max-w-[500px]">
                  <DialogHeader>
                    <DialogTitle>{editingPrompt ? "Edit Prompt" : "Add New Prompt"}</DialogTitle>
                    <DialogDescription>
                      {editingPrompt ? "Update the system prompt details below." : "Create a new system prompt for content generation."}
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4 py-4">
                    <div className="space-y-2">
                      <Label>Prompt Name</Label>
                      <Input
                        placeholder="e.g., Default System Prompt"
                        value={promptForm.name}
                        onChange={(e) =>
                          setPromptForm({ ...promptForm, name: e.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Prompt Content</Label>
                      <Textarea
                        placeholder="Enter your system prompt..."
                        value={promptForm.content}
                        onChange={(e) =>
                          setPromptForm({ ...promptForm, content: e.target.value })
                        }
                        rows={6}
                      />
                    </div>
                  </div>
                  <DialogFooter>
                    <Button
                      variant="outline"
                      onClick={() => {
                        setShowPromptForm(false);
                        setEditingPrompt(null);
                        setPromptForm({ name: "", content: "" });
                      }}
                    >
                      Cancel
                    </Button>
                    <Button
                      onClick={editingPrompt ? handleUpdatePrompt : handleAddPrompt}
                      disabled={!promptForm.name || !promptForm.content}
                    >
                      <Save className="h-4 w-4 mr-2" />
                      {editingPrompt ? "Update" : "Add"} Prompt
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>

              {prompts.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  No prompts configured. Click &quot;Add Prompt&quot; to create one.
                </div>
              ) : (
                prompts.map((prompt) => (
                  <div
                    key={prompt.id}
                    className="flex items-start justify-between p-4 border rounded-lg"
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="font-medium">{prompt.name}</span>
                        {prompt.is_default && (
                          <Badge variant="default" className="bg-yellow-600">
                            <Star className="h-3 w-3 mr-1" />
                            Default
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground line-clamp-2">
                        {prompt.content}
                      </p>
                      <p className="text-xs text-muted-foreground mt-2">
                        Updated: {new Date(prompt.updated_at).toLocaleString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 ml-4">
                      {!prompt.is_default && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleSetDefaultPrompt(prompt.id)}
                        >
                          Set Default
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => startEditPrompt(prompt)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDeletePrompt(prompt.id)}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="documents" className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Documents</CardTitle>
                  <CardDescription>
                    Upload PDF and text documents for content reference
                  </CardDescription>
                </div>
                <div>
                  <input
                    type="file"
                    id="document-upload"
                    accept={ACCEPTED_DOCUMENT_TYPES}
                    className="hidden"
                    onChange={(e) => handleUpload(e, "document")}
                  />
                  <Button
                    onClick={() => document.getElementById("document-upload")?.click()}
                    disabled={uploading}
                  >
                    {uploading ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Upload className="h-4 w-4 mr-2" />
                    )}
                    Upload Document
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {documents.length === 0 ? (
                <div className="p-8 text-center text-muted-foreground">
                  No documents uploaded. Click &quot;Upload Document&quot; to add reference materials.
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Size</TableHead>
                      <TableHead>Added</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {documents.map((doc) => (
                      <TableRow key={doc.id}>
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-2">
                            <FileText className="h-4 w-4 text-muted-foreground" />
                            {doc.name}
                          </div>
                        </TableCell>
                        <TableCell>{formatFileSize(doc.size)}</TableCell>
                        <TableCell>{new Date(doc.createdAt).toLocaleDateString()}</TableCell>
                        <TableCell className="text-right">
                          <Button variant="ghost" size="icon">
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="sources" className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Content Sources</CardTitle>
                  <CardDescription>
                    Configure RSS feeds, news APIs, and hot topics sources
                  </CardDescription>
                </div>
                <Button onClick={() => setShowSourceForm(true)} disabled={showSourceForm}>
                  <Plus className="h-4 w-4 mr-2" />
                  Add Source
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {showSourceForm && (
                <>
                  <div className="grid grid-cols-2 gap-4 p-4 border rounded-lg bg-muted/50">
                    <div className="space-y-2">
                      <Label>Source Name</Label>
                      <Input
                        placeholder="Enter source name"
                        value={sourceForm.name}
                        onChange={(e) =>
                          setSourceForm({ ...sourceForm, name: e.target.value })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Source Type</Label>
                      <Select
                        value={sourceForm.type}
                        onValueChange={(value: Source["type"]) =>
                          setSourceForm({ ...sourceForm, type: value })
                        }
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="rss">RSS Feed</SelectItem>
                          <SelectItem value="news_api">News API</SelectItem>
                          <SelectItem value="hot_topics">Hot Topics</SelectItem>
                          <SelectItem value="custom">Custom</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="col-span-2 space-y-2">
                      <Label>URL / Endpoint</Label>
                      <Input
                        placeholder="https://example.com/feed/"
                        value={sourceForm.url}
                        onChange={(e) =>
                          setSourceForm({ ...sourceForm, url: e.target.value })
                        }
                      />
                    </div>
                    <div className="col-span-2 space-y-2">
                      <Label>Keywords (comma separated)</Label>
                      <Input
                        placeholder="AI, startup, tech"
                        value={sourceForm.keywords}
                        onChange={(e) =>
                          setSourceForm({ ...sourceForm, keywords: e.target.value })
                        }
                      />
                    </div>
                    <div className="col-span-2 flex gap-2">
                      <Button onClick={handleAddSource}>Add Source</Button>
                      <Button variant="outline" onClick={() => setShowSourceForm(false)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                  <Separator />
                </>
              )}

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>URL</TableHead>
                    <TableHead>Keywords</TableHead>
                    <TableHead>Last Fetch</TableHead>
                    <TableHead>Enabled</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sources.map((source) => {
                    const TypeIcon = typeIcons[source.type];
                    return (
                      <TableRow key={source.id}>
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-2">
                            <TypeIcon className="h-4 w-4 text-muted-foreground" />
                            {source.name}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{source.type}</Badge>
                        </TableCell>
                        <TableCell className="max-w-xs truncate">
                          {source.url}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {source.keywords.map((keyword) => (
                              <Badge key={keyword} variant="secondary">
                                {keyword}
                              </Badge>
                            ))}
                          </div>
                        </TableCell>
                        <TableCell>{source.lastFetch}</TableCell>
                        <TableCell>
                          <Switch
                            checked={source.enabled}
                            onCheckedChange={() => toggleSource(source.id)}
                          />
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-2">
                            <Button variant="ghost" size="icon">
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleDeleteSource(source.id)}
                            >
                              <Trash2 className="h-4 w-4 text-destructive" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}