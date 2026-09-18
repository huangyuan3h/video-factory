"use client";

import { useState, useEffect, useCallback } from "react";
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
  publishersApi,
  seriesApi,
  SystemPrompt as SystemPromptType,
  PublisherAccount,
  Series,
} from "@/lib/api-client";

interface GenerateVideoModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialSeriesId?: string;
}

const BACKGROUND_SOURCES = [
  { value: "both", label: "自动 (在线 + 本地 + AI 兜底)" },
  { value: "pexels", label: "Pexels" },
  { value: "pixabay", label: "Pixabay" },
  { value: "local", label: "Local Library" },
  { value: "synthetic", label: "AI 合成图 (ComfyUI, 实验性)" },
  { value: "synthetic_video", label: "AI 动画 (ComfyUI 视频, 很慢/高显存)" },
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
  initialSeriesId,
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
  const [backgroundSource, setBackgroundSource] = useState("both");
  const [loading, setLoading] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [testingVoice, setTestingVoice] = useState(false);
  const [videoResolution, setVideoResolution] = useState({
    width: 1920,
    height: 1080,
  });
  const [rewriteContent, setRewriteContent] = useState(false);
  const [publishTo, setPublishTo] = useState<string[]>([]);
  const [publishFolderId, setPublishFolderId] = useState("");
  const [publishers, setPublishers] = useState<PublisherAccount[]>([]);
  const [seriesList, setSeriesList] = useState<Series[]>([]);
  const [seriesId, setSeriesId] = useState("none");
  const [newSeriesName, setNewSeriesName] = useState("");
  const [creatingSeries, setCreatingSeries] = useState(false);

  useEffect(() => {
    if (open) {
      loadTTSSettings();
      loadGeneralSettings();
      loadMusicFiles();
      loadSavedPrompts();
      loadPublishers();
      loadSeries().then((list) => {
        if (initialSeriesId) {
          setSeriesId(initialSeriesId);
          const s = list.find((x) => x.id === initialSeriesId);
          if (s) applySeriesDefaults(s);
        }
      });
    }
  }, [open, initialSeriesId]);

  const loadSeries = async () => {
    try {
      const res = await seriesApi.list();
      if (res.success && res.data) {
        const list = res.data as unknown as Series[];
        setSeriesList(list);
        return list;
      }
    } catch {}
    return [] as Series[];
  };

  const applySeriesDefaults = useCallback((s: Series) => {
    if (s.default_voice) setVoice(s.default_voice);
    if (s.default_voice_rate) setVoiceRate(s.default_voice_rate);
    if (s.system_prompt) setSystemPrompt(s.system_prompt);
    if (s.default_resolution_width && s.default_resolution_height) {
      setVideoResolution({ width: s.default_resolution_width, height: s.default_resolution_height });
    }
    if (s.default_background_source) setBackgroundSource(s.default_background_source);
    if (s.default_background_music) setBackgroundMusic(s.default_background_music);
  }, []);

  const handleSeriesChange = (value: string) => {
    setSeriesId(value);
    const s = seriesList.find((x) => x.id === value);
    if (s) applySeriesDefaults(s);
  };

  const handleCreateSeries = async () => {
    const name = newSeriesName.trim();
    if (!name) return;
    setCreatingSeries(true);
    try {
      const res = await seriesApi.create({ name });
      if (res.success && res.data) {
        setSeriesList((prev) => [...prev, res.data as Series]);
        setSeriesId((res.data as Series).id);
        setNewSeriesName("");
      }
    } finally {
      setCreatingSeries(false);
    }
  };

  const loadPublishers = async () => {
    try {
      const res = await publishersApi.list();
      if (res.success && res.data) setPublishers(res.data as unknown as PublisherAccount[]);
    } catch {}
  };

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
          series_id: seriesId !== "none" ? seriesId : undefined,
          videoResolution,
          rewrite_content: rewriteContent,
          publish_to: publishTo.length ? publishTo : undefined,
          folder_id: publishFolderId || undefined,
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
          <div className="space-y-2 p-4 border rounded-lg bg-muted/30">
            <Label className="text-base font-medium">系列 / Series</Label>
            <p className="text-xs text-muted-foreground">
              视频会归入该系列的文件夹，便于成组管理和发布。
            </p>
            <div className="flex gap-2">
              <Select value={seriesId} onValueChange={handleSeriesChange}>
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder="选择系列..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">无系列 (_unsorted)</SelectItem>
                  {seriesList.map((s) => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Input
                placeholder="新建系列名称"
                value={newSeriesName}
                onChange={(e) => setNewSeriesName(e.target.value)}
                className="w-48"
              />
              <Button
                variant="outline"
                onClick={handleCreateSeries}
                disabled={creatingSeries || !newSeriesName.trim()}
              >
                {creatingSeries ? <Loader2 className="h-4 w-4 animate-spin" /> : "新建"}
              </Button>
            </div>
          </div>

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
                <Label className="text-base font-medium">LLM 重写内容</Label>
                <p className="text-sm text-muted-foreground">
                  开启后先用 LLM 口播化重写（可用 deepseek/vercel gateway），再生成脚本
                </p>
              </div>
              <Switch checked={rewriteContent} onCheckedChange={setRewriteContent} />
            </div>
          </div>

          <div className="space-y-4 p-4 border rounded-lg">
            <div className="space-y-3">
              <Label className="text-base font-medium">自动发布</Label>
              <p className="text-sm text-muted-foreground">生成完成后自动分发到选中平台（可设文件夹/合集）</p>
              <div className="flex flex-wrap gap-2">
                {publishers.length === 0 ? (
                  <p className="text-xs text-muted-foreground">暂无发布账号，请先到 Publishers 页面添加</p>
                ) : (
                  publishers.map((p) => (
                    <label key={p.id} className="flex items-center gap-2 border rounded-lg px-3 py-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={publishTo.includes(p.platform)}
                        onChange={(e) => {
                          setPublishTo((prev) =>
                            e.target.checked ? [...prev, p.platform] : prev.filter((x) => x !== p.platform),
                          );
                        }}
                      />
                      <span className="text-sm">{p.name} ({p.platform})</span>
                    </label>
                  ))
                )}
              </div>
              {publishTo.length > 0 && (
                <div className="space-y-2">
                  <Label>文件夹 / Playlist ID（可选）</Label>
                  <Input
                    placeholder="如 YouTube playlistId 或 Douyin 合集ID，留空用账号默认"
                    value={publishFolderId}
                    onChange={(e) => setPublishFolderId(e.target.value)}
                  />
                </div>
              )}
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
