"use client";

import { useState, useEffect, useCallback } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Music, Video, FileText, Rss } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import {
  generalSettingsApi,
  GeneralSettings,
  systemPromptsApi,
  SystemPrompt,
} from "@/lib/api-client";
import {
  MusicAssets,
  VideoAssets,
  DocumentsAssets,
  SystemPrompts,
  Sources,
} from "./components";
import { Asset, Source } from "./types";

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

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [sources, setSources] = useState<Source[]>(mockSources);
  const [prompts, setPrompts] = useState<SystemPrompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [generalSettings, setGeneralSettings] =
    useState<GeneralSettings | null>(null);
  const { toast } = useToast();

  const musicAssets = assets.filter(
    (a) => a.type === "music" || a.mimeType?.startsWith("audio/")
  );
  const videoAssets = assets.filter(
    (a) => a.type === "video" || a.mimeType?.startsWith("video/")
  );
  const documentAssets = assets.filter(
    (a) =>
      a.type === "document" ||
      a.mimeType?.startsWith("text/") ||
      a.mimeType?.startsWith("application/pdf") ||
      a.mimeType?.includes("word")
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

  const handleRename = async (id: string, name: string) => {
    if (!name.trim()) return;

    try {
      const response = await fetch(`/api/assets/${id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ name }),
      });

      if (response.ok) {
        toast({
          title: "Success",
          description: "Asset renamed successfully",
        });
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

  const handleAddSource = (source: Omit<Source, "id">) => {
    const newSource: Source = {
      ...source,
      id: Date.now().toString(),
    };
    setSources([...sources, newSource]);
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

  const handleToggleSource = (id: string) => {
    setSources(
      sources.map((source) =>
        source.id === id ? { ...source, enabled: !source.enabled } : source
      )
    );
  };

  const handleAddPrompt = async (name: string, content: string) => {
    const response = await systemPromptsApi.create({
      name,
      content,
      is_default: prompts.length === 0,
    });
    if (response.success) {
      fetchPrompts();
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

  const handleUpdatePrompt = async (
    id: string,
    name: string,
    content: string
  ) => {
    const response = await systemPromptsApi.update(id, { name, content });
    if (response.success) {
      fetchPrompts();
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

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Assets</h1>
        <p className="text-muted-foreground">
          Manage your background music, videos, prompts, documents, and content
          sources
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
          <MusicAssets
            assets={musicAssets}
            loading={loading}
            uploading={uploading}
            defaultBackgroundMusic={generalSettings?.default_background_music ?? undefined}
            onUpload={handleUpload}
            onDelete={handleDeleteAsset}
            onRename={handleRename}
            onSetDefault={handleSetDefaultMusic}
          />
        </TabsContent>

        <TabsContent value="videos" className="space-y-6">
          <VideoAssets
            assets={videoAssets}
            loading={loading}
            uploading={uploading}
            onUpload={handleUpload}
            onDelete={handleDeleteAsset}
            onRename={handleRename}
          />
        </TabsContent>

        <TabsContent value="prompts" className="space-y-6">
          <SystemPrompts
            prompts={prompts}
            onAdd={handleAddPrompt}
            onUpdate={handleUpdatePrompt}
            onDelete={handleDeletePrompt}
            onSetDefault={handleSetDefaultPrompt}
          />
        </TabsContent>

        <TabsContent value="documents" className="space-y-6">
          <DocumentsAssets
            assets={documentAssets}
            uploading={uploading}
            onUpload={handleUpload}
            onDelete={handleDeleteAsset}
          />
        </TabsContent>

        <TabsContent value="sources" className="space-y-6">
          <Sources
            sources={sources}
            onAdd={handleAddSource}
            onDelete={handleDeleteSource}
            onToggle={handleToggleSource}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
