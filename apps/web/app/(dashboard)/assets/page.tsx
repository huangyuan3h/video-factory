"use client";

import { useState, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import {
  Plus,
  Trash2,
  Edit,
  Music,
  Video,
  Upload,
  X,
  Check,
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";

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

const ACCEPTED_MUSIC_TYPES = ".mp3,.wav,.ogg,.m4a";
const ACCEPTED_VIDEO_TYPES = ".mp4,.mov,.avi,.webm";

function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [showUploadForm, setShowUploadForm] = useState(false);
  const [uploadType, setUploadType] = useState<"music" | "video">("music");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  const fetchAssets = async () => {
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
  };

  useEffect(() => {
    fetchAssets();
  }, []);

  const handleUpload = async () => {
    if (!uploadFile) return;

    setUploading(true);
    const formData = new FormData();
    formData.append("file", uploadFile);
    formData.append("type", uploadType);

    try {
      const response = await fetch("/api/assets", {
        method: "POST",
        body: formData,
      });

      if (response.ok) {
        toast({
          title: "Success",
          description: "Asset uploaded successfully",
        });
        setShowUploadForm(false);
        setUploadFile(null);
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
        fetchAssets();
      } else {
        throw new Error("Upload failed");
      }
    } catch (error) {
      console.error("Failed to upload asset:", error);
      toast({
        title: "Error",
        description: "Failed to upload asset",
        variant: "destructive",
      });
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Are you sure you want to delete this asset?")) return;

    try {
      const response = await fetch(`/api/assets/${id}`, {
        method: "DELETE",
      });

      if (response.ok) {
        toast({
          title: "Success",
          description: "Asset deleted successfully",
        });
        fetchAssets();
      } else {
        throw new Error("Delete failed");
      }
    } catch (error) {
      console.error("Failed to delete asset:", error);
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

  const startEditing = (asset: Asset) => {
    setEditingId(asset.id);
    setEditingName(asset.name);
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditingName("");
  };

  const typeIcons = {
    music: Music,
    video: Video,
  };

  const musicAssets = assets.filter((a) => a.type === "music");
  const videoAssets = assets.filter((a) => a.type === "video");

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">Assets</h1>
          <p className="text-muted-foreground">
            Manage background music and videos
          </p>
        </div>
        <Button onClick={() => setShowUploadForm(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Upload Asset
        </Button>
      </div>

      {showUploadForm && (
        <Card className="mb-8">
          <CardHeader>
            <CardTitle>Upload New Asset</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="type">Asset Type</Label>
                <Select
                  value={uploadType}
                  onValueChange={(value: "music" | "video") =>
                    setUploadType(value)
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="music">Music</SelectItem>
                    <SelectItem value="video">Video</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="file">File</Label>
                <Input
                  id="file"
                  type="file"
                  accept={
                    uploadType === "music"
                      ? ACCEPTED_MUSIC_TYPES
                      : ACCEPTED_VIDEO_TYPES
                  }
                  ref={fileInputRef}
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                onClick={handleUpload}
                disabled={!uploadFile || uploading}
              >
                <Upload className="h-4 w-4 mr-2" />
                {uploading ? "Uploading..." : "Upload"}
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  setShowUploadForm(false);
                  setUploadFile(null);
                  if (fileInputRef.current) {
                    fileInputRef.current.value = "";
                  }
                }}
              >
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="space-y-8">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Music className="h-5 w-5" />
              Background Music ({musicAssets.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {musicAssets.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Size</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Created</TableHead>
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
                      <TableCell>
                        <Badge variant="outline">{asset.mimeType}</Badge>
                      </TableCell>
                      <TableCell>
                        {new Date(asset.createdAt).toLocaleDateString()}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => startEditing(asset)}
                            disabled={editingId === asset.id}
                          >
                            <Edit className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleDelete(asset.id)}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">
                No music assets uploaded yet
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Video className="h-5 w-5" />
              Background Videos ({videoAssets.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {videoAssets.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Size</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Created</TableHead>
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
                      <TableCell>
                        <Badge variant="outline">{asset.mimeType}</Badge>
                      </TableCell>
                      <TableCell>
                        {new Date(asset.createdAt).toLocaleDateString()}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => startEditing(asset)}
                            disabled={editingId === asset.id}
                          >
                            <Edit className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => handleDelete(asset.id)}
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="p-8 text-center text-muted-foreground">
                No video assets uploaded yet
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
