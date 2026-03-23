"use client";

import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Loader2, Volume2, Star } from "lucide-react";
import {
  ttsSettingsApi,
  generalSettingsApi,
  systemPromptsApi,
  SystemPrompt as SystemPromptType,
} from "@/lib/api-client";

interface GenerateVideoModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const BACKGROUND_SOURCES = [
  { value: "pexels", label: "Pexels" },
  { value: "pixabay", label: "Pixabay" },
  { value: "local", label: "Local Library" },
];

const VOICE_OPTIONS = [
  { value: "zh-CN-XiaoxiaoNeural", label: "Xiaoxiao (Female, Natural)" },
  { value: "zh-CN-YunxiNeural", label: "Yunxi (Male, Sunny)" },
  { value: "zh-CN-YunjianNeural", label: "Yunjian (Male, News)" },
  { value: "zh-CN-XiaoyiNeural", label: "Xiaoyi (Female, Gentle)" },
];

const RATE_OPTIONS = [
  { value: "-20%", label: "Slow (0.8x)" },
  { value: "+0%", label: "Normal (1.0x)" },
  { value: "+20%", label: "Fast (1.2x)" },
];

const VIDEO_RESOLUTIONS = [
  { width: 1080, height: 1920, label: "竖屏 1080x1920 (手机)" },
  { width: 720, height: 1280, label: "竖屏 720x1280" },
  { width: 1920, height: 1080, label: "横屏 1920x1080 (电脑)" },
  { width: 1280, height: 720, label: "横屏 1280x720" },
];

const SUBTITLE_COLORS = [
  { value: "#FFFFFF", label: "White" },
  { value: "#FFFF00", label: "Yellow" },
  { value: "#00FF00", label: "Green" },
  { value: "#FF6B6B", label: "Red" },
  { value: "#4ECDC4", label: "Cyan" },
];

const SUBTITLE_FONTS = [
  { value: "Microsoft YaHei", label: "Microsoft YaHei" },
  { value: "SimHei", label: "SimHei" },
  { value: "KaiTi", label: "KaiTi" },
  { value: "Arial", label: "Arial" },
];

interface MusicFile {
  id: string;
  name: string;
  filename: string;
}

export function GenerateVideoModal({
  open,
  onOpenChange,
}: GenerateVideoModalProps) {
  const [title, setTitle] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [savedPrompts, setSavedPrompts] = useState<SystemPromptType[]>([]);
  const [textContent, setTextContent] = useState("");
  const [backgroundMusic, setBackgroundMusic] = useState("none");
  const [musicFiles, setMusicFiles] = useState<MusicFile[]>([]);
  const [generateSubtitle, setGenerateSubtitle] = useState(true);
  const [subtitleColor, setSubtitleColor] = useState("#FFFFFF");
  const [subtitleFont, setSubtitleFont] = useState("Microsoft YaHei");
  const [voice, setVoice] = useState("zh-CN-XiaoxiaoNeural");
  const [voiceRate, setVoiceRate] = useState("+0%");
  const [backgroundSource, setBackgroundSource] = useState("pexels");
  const [loading, setLoading] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [testingVoice, setTestingVoice] = useState(false);
  const [videoResolution, setVideoResolution] = useState({
    width: 1080,
    height: 1920,
  });

  useEffect(() => {
    if (open) {
      loadTTSSettings();
      loadGeneralSettings();
      loadMusicFiles();
      loadSavedPrompts();
    }
  }, [open]);

  const loadTTSSettings = async () => {
    setSettingsLoading(true);
    try {
      const response = await ttsSettingsApi.get();
      if (response.success && response.data) {
        setVoice(response.data.voice || "zh-CN-XiaoxiaoNeural");
        setVoiceRate(response.data.rate || "+0%");
      }
    } catch (error) {
      console.error("Failed to load TTS settings:", error);
    } finally {
      setSettingsLoading(false);
    }
  };

  const loadGeneralSettings = async () => {
    try {
      const response = await generalSettingsApi.get();
      if (response.success && response.data) {
        setVideoResolution({
          width: response.data.video_resolution_width || 1080,
          height: response.data.video_resolution_height || 1920,
        });
        if (response.data.default_background_music) {
          setBackgroundMusic(response.data.default_background_music);
        }
      }
    } catch (error) {
      console.error("Failed to load general settings:", error);
    }
  };

  const loadMusicFiles = async () => {
    try {
      const response = await fetch("/api/music");
      const data = await response.json();
      if (data.success && data.data) {
        setMusicFiles(data.data);
      }
    } catch (error) {
      console.error("Failed to load music files:", error);
    }
  };

  const loadSavedPrompts = async () => {
    try {
      const response = await systemPromptsApi.list();
      if (response.success && response.data) {
        setSavedPrompts(response.data);
        const defaultPrompt = response.data.find((p) => p.is_default);
        if (defaultPrompt && !systemPrompt) {
          setSystemPrompt(defaultPrompt.content);
        }
      }
    } catch (error) {
      console.error("Failed to load prompts:", error);
    }
  };

  const selectPrompt = (prompt: SystemPromptType) => {
    setSystemPrompt(prompt.content);
  };

  const handleTestVoice = async () => {
    if (!textContent.trim()) {
      alert("Please enter text content first");
      return;
    }
    setTestingVoice(true);
    try {
      const result = await ttsSettingsApi.test({
        voice,
        rate: voiceRate,
        test_text: textContent.substring(0, 200),
      });
      if (result.success && result.blob) {
        const audioUrl = URL.createObjectURL(result.blob);
        const audio = new Audio(audioUrl);
        audio.onended = () => URL.revokeObjectURL(audioUrl);
        await audio.play();
      } else {
        alert(`Voice test failed: ${result.error || "Unknown error"}`);
      }
    } catch (error) {
      alert(
        `Voice test failed: ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    } finally {
      setTestingVoice(false);
    }
  };

  const handleGenerate = async () => {
    if (!title.trim()) {
      alert("Please enter a title");
      return;
    }
    if (!textContent.trim()) {
      alert("Please enter text content");
      return;
    }
    setLoading(true);
    try {
      const response = await fetch("/api/videos/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          systemPrompt,
          textContent,
          backgroundMusic,
          generateSubtitle,
          subtitleColor,
          subtitleFont,
          voice,
          voiceRate,
          backgroundSource,
          videoResolution,
        }),
      });
      const result = await response.json();
      console.log("Video generation result:", result);
      onOpenChange(false);
      setTitle("");
      setSystemPrompt("");
      setTextContent("");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl">Generate Video</DialogTitle>
        </DialogHeader>

        <div className="space-y-6 py-4">
          <div className="space-y-2">
            <Label htmlFor="title" className="text-base font-medium">
              Title
            </Label>
            <Input
              id="title"
              placeholder="Enter video title..."
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="systemPrompt" className="text-base font-medium">
              System Prompt
            </Label>
            <Select
              value={
                savedPrompts.find((p) => p.content === systemPrompt)?.id || ""
              }
              onValueChange={(value) => {
                const prompt = savedPrompts.find((p) => p.id === value);
                if (prompt) selectPrompt(prompt);
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a prompt..." />
              </SelectTrigger>
              <SelectContent>
                {savedPrompts.length === 0 ? (
                  <div className="px-2 py-1 text-sm text-muted-foreground">
                    No prompts saved. Add prompts in Assets page.
                  </div>
                ) : (
                  savedPrompts.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      <div className="flex items-center gap-2">
                        {p.is_default && (
                          <Star className="h-3 w-3 text-yellow-500" />
                        )}
                        {p.name}
                      </div>
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            <Textarea
              id="systemPrompt"
              placeholder="Enter system prompt for AI content generation..."
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={4}
              className="resize-none"
            />
            <p className="text-xs text-muted-foreground">
              Optional: Select a saved prompt or enter custom instructions.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="textContent" className="text-base font-medium">
              Text Content
            </Label>
            <Textarea
              id="textContent"
              placeholder="Enter the text content for your video..."
              value={textContent}
              onChange={(e) => setTextContent(e.target.value)}
              rows={6}
              className="resize-none"
            />
            <p className="text-xs text-muted-foreground">
              This text will be converted to speech and used as subtitles.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-6">
            <div className="space-y-4">
              <div className="space-y-2">
                <Label className="text-base font-medium">Voice Settings</Label>
                <div className="space-y-3 p-4 border rounded-lg">
                  <div className="space-y-2">
                    <Label>Voice</Label>
                    <Select
                      value={voice}
                      onValueChange={setVoice}
                      disabled={settingsLoading}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {VOICE_OPTIONS.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value}>
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Speech Rate</Label>
                    <Select
                      value={voiceRate}
                      onValueChange={setVoiceRate}
                      disabled={settingsLoading}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {RATE_OPTIONS.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value}>
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleTestVoice}
                    disabled={testingVoice || !textContent.trim()}
                    className="w-full"
                  >
                    {testingVoice ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Volume2 className="h-4 w-4 mr-2" />
                    )}
                    Test Voice
                  </Button>
                </div>
              </div>
            </div>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label className="text-base font-medium">
                  Background Music
                </Label>
                <Select
                  value={backgroundMusic}
                  onValueChange={setBackgroundMusic}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select music..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">No Music</SelectItem>
                    {musicFiles.map((music) => (
                      <SelectItem key={music.id} value={music.filename}>
                        {music.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Select from assets/background-music folder
                </p>
              </div>

              <div className="space-y-2">
                <Label className="text-base font-medium">
                  Background Video Source
                </Label>
                <Select
                  value={backgroundSource}
                  onValueChange={setBackgroundSource}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {BACKGROUND_SOURCES.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label className="text-base font-medium">
                  Video Resolution
                </Label>
                <Select
                  value={`${videoResolution.width}x${videoResolution.height}`}
                  onValueChange={(value) => {
                    const [w, h] = value.split("x").map(Number);
                    setVideoResolution({ width: w, height: h });
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {VIDEO_RESOLUTIONS.map((res) => (
                      <SelectItem
                        key={`${res.width}x${res.height}`}
                        value={`${res.width}x${res.height}`}
                      >
                        {res.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          <div className="space-y-4 p-4 border rounded-lg">
            <div className="flex items-center justify-between">
              <div>
                <Label className="text-base font-medium">
                  Generate Subtitles
                </Label>
                <p className="text-sm text-muted-foreground">
                  Add subtitles to the video based on text content
                </p>
              </div>
              <Switch
                checked={generateSubtitle}
                onCheckedChange={setGenerateSubtitle}
              />
            </div>

            {generateSubtitle && (
              <div className="grid grid-cols-2 gap-4 pt-2">
                <div className="space-y-2">
                  <Label>Subtitle Color</Label>
                  <Select
                    value={subtitleColor}
                    onValueChange={setSubtitleColor}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SUBTITLE_COLORS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          <div className="flex items-center gap-2">
                            <div
                              className="w-4 h-4 rounded border"
                              style={{ backgroundColor: opt.value }}
                            />
                            {opt.label}
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Subtitle Font</Label>
                  <Select value={subtitleFont} onValueChange={setSubtitleFont}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SUBTITLE_FONTS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-4 border-t">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleGenerate}
            disabled={loading || !title.trim() || !textContent.trim()}
          >
            {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Generate Video
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
