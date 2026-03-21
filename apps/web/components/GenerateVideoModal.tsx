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
import { Loader2, Volume2 } from "lucide-react";
import { ttsSettingsApi, TTSSetting } from "@/lib/api-client";

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

const MUSIC_OPTIONS = [
  { value: "none", label: "No Music" },
  { value: "upbeat", label: "Upbeat" },
  { value: "calm", label: "Calm" },
  { value: "dramatic", label: "Dramatic" },
  { value: "corporate", label: "Corporate" },
];

export function GenerateVideoModal({
  open,
  onOpenChange,
}: GenerateVideoModalProps) {
  const [textContent, setTextContent] = useState("");
  const [backgroundMusic, setBackgroundMusic] = useState("none");
  const [generateSubtitle, setGenerateSubtitle] = useState(true);
  const [subtitleColor, setSubtitleColor] = useState("#FFFFFF");
  const [subtitleFont, setSubtitleFont] = useState("Microsoft YaHei");
  const [voice, setVoice] = useState("zh-CN-XiaoxiaoNeural");
  const [voiceRate, setVoiceRate] = useState("+0%");
  const [backgroundSource, setBackgroundSource] = useState("pexels");
  const [loading, setLoading] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [testingVoice, setTestingVoice] = useState(false);

  useEffect(() => {
    if (open) {
      loadTTSSettings();
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
    if (!textContent.trim()) {
      alert("Please enter text content");
      return;
    }
    setLoading(true);
    try {
      // TODO: Implement video generation API call
      console.log({
        textContent,
        backgroundMusic,
        generateSubtitle,
        subtitleColor,
        subtitleFont,
        voice,
        voiceRate,
        backgroundSource,
      });
      await new Promise((resolve) => setTimeout(resolve, 1000));
      onOpenChange(false);
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
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MUSIC_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
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
            disabled={loading || !textContent.trim()}
          >
            {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Generate Video
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
