"use client";

import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Video,
  Play,
  Download,
  Trash2,
  ExternalLink,
  Plus,
} from "lucide-react";
import { GenerateVideoModal } from "@/components/GenerateVideoModal";

interface VideoItem {
  id: string;
  title: string;
  thumbnail: string;
  duration: string;
  platform: string;
  publishedAt: string;
  status: "published" | "draft" | "scheduled";
}

const mockVideos: VideoItem[] = [
  {
    id: "1",
    title: "OpenAI Announces GPT-5",
    thumbnail: "/placeholder.jpg",
    duration: "2:30",
    platform: "Douyin",
    publishedAt: "2024-03-20 09:30",
    status: "published",
  },
  {
    id: "2",
    title: "Tech News Daily Update",
    thumbnail: "/placeholder.jpg",
    duration: "1:45",
    platform: "Xiaohongshu",
    publishedAt: "2024-03-20 10:15",
    status: "published",
  },
  {
    id: "3",
    title: "AI Weekly Highlights",
    thumbnail: "/placeholder.jpg",
    duration: "3:00",
    platform: "Draft",
    publishedAt: "-",
    status: "draft",
  },
];

export default function VideosPage() {
  const [modalOpen, setModalOpen] = useState(false);

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">Videos</h1>
          <p className="text-muted-foreground">
            Browse and manage generated videos
          </p>
        </div>
        <Button onClick={() => setModalOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Generate Video
        </Button>
      </div>

      <GenerateVideoModal open={modalOpen} onOpenChange={setModalOpen} />

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {mockVideos.map((video) => (
          <Card key={video.id} className="overflow-hidden">
            <div className="aspect-video bg-muted flex items-center justify-center relative group">
              <Video className="h-12 w-12 text-muted-foreground" />
              <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                <Button size="lg" variant="secondary">
                  <Play className="h-6 w-6 mr-2" />
                  Play
                </Button>
              </div>
              <div className="absolute bottom-2 right-2 bg-black/80 text-white text-xs px-2 py-1 rounded">
                {video.duration}
              </div>
            </div>
            <CardContent className="p-4">
              <h3 className="font-medium truncate">{video.title}</h3>
              <div className="flex items-center justify-between mt-2">
                <div className="flex items-center gap-2">
                  <Badge
                    variant={
                      video.status === "published"
                        ? "success"
                        : video.status === "scheduled"
                          ? "warning"
                          : "secondary"
                    }
                  >
                    {video.status}
                  </Badge>
                  <span className="text-sm text-muted-foreground">
                    {video.platform}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2 mt-3">
                <Button variant="outline" size="sm" className="flex-1">
                  <Download className="h-4 w-4 mr-1" />
                  Download
                </Button>
                {video.status === "published" && (
                  <Button variant="outline" size="sm">
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                )}
                <Button variant="ghost" size="sm">
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
