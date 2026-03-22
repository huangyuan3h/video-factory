"use client";

import { useState, useEffect, useCallback, useRef } from "react";
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
  Save,
  Plus,
  Trash2,
  TestTube,
  Loader2,
  Pencil,
  X,
  Volume2,
} from "lucide-react";
import {
  aiSettingsApi,
  ttsSettingsApi,
  generalSettingsApi,
  AISetting,
  AISettingCreate,
  AISettingUpdate,
  TTSSetting,
  GeneralSettings,
} from "@/lib/api-client";

interface AIConfigForm {
  name: string;
  baseUrl: string;
  modelId: string;
  apiKey: string;
  temperature: number;
  maxTokens: number;
}

const emptyForm: AIConfigForm = {
  name: "",
  baseUrl: "https://api.openai.com/v1",
  modelId: "gpt-4o",
  apiKey: "",
  temperature: 0.7,
  maxTokens: 4096,
};

export default function SettingsPage() {
  const [aiConfigs, setAIConfigs] = useState<AISetting[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAIForm, setShowAIForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formData, setFormData] = useState<AIConfigForm>(emptyForm);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<
    Record<string, { success: boolean; latency?: number; error?: string }>
  >({});

  // TTS Settings state
  const [ttsSetting, setTtsSetting] = useState<TTSSetting | null>(null);
  const [ttsLoading, setTtsLoading] = useState(true);
  const [ttsSaving, setTtsSaving] = useState(false);
  const [ttsTesting, setTtsTesting] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Local state for test text input (allows editing before save)
  const [localTestText, setLocalTestText] =
    useState("你好，这是一个语音测试。");

  const [generalSettings, setGeneralSettings] = useState<GeneralSettings>({
    id: "",
    output_dir: "./data/output",
    video_resolution_width: 1080,
    video_resolution_height: 1920,
    pexels_api_key: null,
    pixabay_api_key: null,
    created_at: "",
    updated_at: "",
  });
  const [generalLoading, setGeneralLoading] = useState(true);
  const [generalSaving, setGeneralSaving] = useState(false);

  const fetchAIConfigs = useCallback(async () => {
    setLoading(true);
    const response = await aiSettingsApi.list();
    if (response.success && response.data) {
      setAIConfigs(response.data);
    }
    setLoading(false);
  }, []);

  const fetchTTSSetting = useCallback(async () => {
    setTtsLoading(true);
    const response = await ttsSettingsApi.get();
    if (response.success && response.data) {
      setTtsSetting(response.data);
      setLocalTestText(response.data.test_text || "你好，这是一个语音测试。");
    }
    setTtsLoading(false);
  }, []);

  const fetchGeneralSettings = useCallback(async () => {
    setGeneralLoading(true);
    const response = await generalSettingsApi.get();
    if (response.success && response.data) {
      setGeneralSettings(response.data);
    }
    setGeneralLoading(false);
  }, []);

  useEffect(() => {
    fetchAIConfigs();
    fetchTTSSetting();
    fetchGeneralSettings();
  }, [fetchAIConfigs, fetchTTSSetting, fetchGeneralSettings]);

  const handleCreate = () => {
    setEditingId(null);
    setFormData(emptyForm);
    setShowAIForm(true);
  };

  const handleEdit = (config: AISetting) => {
    setEditingId(config.id);
    setFormData({
      name: config.name,
      baseUrl: config.base_url,
      modelId: config.model_id,
      apiKey: "", // Don't show existing API key for security
      temperature: config.temperature,
      maxTokens: config.max_tokens,
    });
    setShowAIForm(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (editingId) {
        const updateData: AISettingUpdate = {
          name: formData.name,
          base_url: formData.baseUrl,
          model_id: formData.modelId,
          temperature: formData.temperature,
          max_tokens: formData.maxTokens,
        };
        if (formData.apiKey) {
          updateData.api_key = formData.apiKey;
        }
        await aiSettingsApi.update(editingId, updateData);
      } else {
        const createData: AISettingCreate = {
          name: formData.name,
          base_url: formData.baseUrl,
          model_id: formData.modelId,
          api_key: formData.apiKey,
          temperature: formData.temperature,
          max_tokens: formData.maxTokens,
        };
        await aiSettingsApi.create(createData);
      }
      setShowAIForm(false);
      setFormData(emptyForm);
      setEditingId(null);
      fetchAIConfigs();
    } finally {
      setSaving(false);
    }
  };

  const handleActivate = async (id: string) => {
    await aiSettingsApi.activate(id);
    fetchAIConfigs();
  };

  const handleDelete = async (id: string) => {
    if (confirm("Are you sure you want to delete this AI provider?")) {
      await aiSettingsApi.delete(id);
      fetchAIConfigs();
    }
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    setTestResults((prev) => ({ ...prev, [id]: { success: false } }));
    try {
      const response = await aiSettingsApi.test(id);
      if (response.success && response.data) {
        setTestResults((prev) => ({
          ...prev,
          [id]: {
            success: response.data!.success,
            latency: response.data!.latency_ms,
            error: response.data!.error,
          },
        }));
      }
    } catch (error) {
      setTestResults((prev) => ({
        ...prev,
        [id]: { success: false, error: "Test failed" },
      }));
    } finally {
      setTesting(null);
    }
  };

  // TTS handlers
  const handleTTSSave = async () => {
    if (!ttsSetting) return;
    setTtsSaving(true);
    try {
      const response = await ttsSettingsApi.update({
        voice: ttsSetting.voice,
        rate: ttsSetting.rate,
        test_text: localTestText,
      });
      if (response.success && response.data) {
        setTtsSetting(response.data);
        setLocalTestText(response.data.test_text || localTestText);
      }
    } finally {
      setTtsSaving(false);
    }
  };

  const handleTTSTest = async () => {
    setTtsTesting(true);
    try {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }

      const voice = ttsSetting?.voice || "zh-CN-XiaoxiaoNeural";
      const rate = ttsSetting?.rate || "+0%";
      const testText = localTestText || "你好，这是一个语音测试。";

      console.log("Testing TTS with:", { voice, rate, testText });

      const result = await ttsSettingsApi.test({
        voice,
        rate,
        test_text: testText,
      });

      console.log("TTS test result:", result);

      if (result.success && result.blob) {
        const audioUrl = URL.createObjectURL(result.blob);
        const audio = new Audio(audioUrl);
        audioRef.current = audio;
        audio.onended = () => {
          URL.revokeObjectURL(audioUrl);
        };
        audio.onerror = (e) => {
          console.error("Audio playback error:", e);
          URL.revokeObjectURL(audioUrl);
        };
        await audio.play();
      } else if (result.error) {
        console.error("TTS test error:", result.error);
        alert(`TTS test failed: ${result.error}`);
      } else {
        alert("TTS test failed: Unknown error");
      }
    } catch (error) {
      console.error("TTS test failed:", error);
      alert(
        `TTS test failed: ${error instanceof Error ? error.message : "Unknown error"}`,
      );
    } finally {
      setTtsTesting(false);
    }
  };

  const handleGeneralSave = async () => {
    setGeneralSaving(true);
    try {
      const response = await generalSettingsApi.update({
        output_dir: generalSettings.output_dir,
        video_resolution_width: generalSettings.video_resolution_width,
        video_resolution_height: generalSettings.video_resolution_height,
        pexels_api_key: generalSettings.pexels_api_key || undefined,
        pixabay_api_key: generalSettings.pixabay_api_key || undefined,
      });
      if (response.success && response.data) {
        setGeneralSettings(response.data);
      }
    } finally {
      setGeneralSaving(false);
    }
  };

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground">
          Configure AI providers, TTS, and publishing accounts
        </p>
      </div>

      <Tabs defaultValue="ai" className="space-y-6">
        <TabsList>
          <TabsTrigger value="ai">AI Provider</TabsTrigger>
          <TabsTrigger value="tts">TTS Voice</TabsTrigger>
          <TabsTrigger value="publishing">Publishing</TabsTrigger>
          <TabsTrigger value="general">General</TabsTrigger>
        </TabsList>

        <TabsContent value="ai" className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>AI Providers</CardTitle>
                  <CardDescription>
                    Configure OpenAI-compatible API providers for content
                    generation
                  </CardDescription>
                </div>
                <Button onClick={handleCreate} disabled={showAIForm}>
                  <Plus className="h-4 w-4 mr-2" />
                  Add Provider
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {loading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : aiConfigs.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  No AI providers configured. Click &quot;Add Provider&quot; to
                  get started.
                </div>
              ) : (
                aiConfigs.map((config) => (
                  <div
                    key={config.id}
                    className="flex items-center justify-between p-4 border rounded-lg"
                  >
                    <div className="flex items-center gap-4">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{config.name}</span>
                          {config.is_active && (
                            <Badge variant="default" className="bg-green-600">
                              Active
                            </Badge>
                          )}
                        </div>
                        <p className="text-sm text-muted-foreground">
                          {config.base_url} / {config.model_id}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Temperature: {config.temperature} | Max Tokens:{" "}
                          {config.max_tokens}
                        </p>
                        {testResults[config.id] && (
                          <p
                            className={`text-xs mt-1 ${testResults[config.id].success ? "text-green-600" : "text-red-600"}`}
                          >
                            {testResults[config.id].success
                              ? `Connection OK (${testResults[config.id].latency}ms)`
                              : `Error: ${testResults[config.id].error}`}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {!config.is_active && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleActivate(config.id)}
                        >
                          Set Active
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleTest(config.id)}
                        disabled={testing === config.id}
                      >
                        {testing === config.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <TestTube className="h-4 w-4" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleEdit(config)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(config.id)}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </div>
                ))
              )}

              {showAIForm && (
                <>
                  <Separator />
                  <div className="space-y-4 p-4 border rounded-lg bg-muted/50">
                    <div className="flex items-center justify-between">
                      <h3 className="font-medium">
                        {editingId ? "Edit Provider" : "Add New Provider"}
                      </h3>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setShowAIForm(false);
                          setEditingId(null);
                          setFormData(emptyForm);
                        }}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label>Provider Name</Label>
                        <Input
                          placeholder="e.g., OpenAI, DeepSeek"
                          value={formData.name}
                          onChange={(e) =>
                            setFormData({ ...formData, name: e.target.value })
                          }
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Model ID</Label>
                        <Input
                          placeholder="e.g., gpt-4o, deepseek-chat"
                          value={formData.modelId}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              modelId: e.target.value,
                            })
                          }
                        />
                      </div>
                      <div className="col-span-2 space-y-2">
                        <Label>Base URL</Label>
                        <Input
                          placeholder="https://api.openai.com/v1"
                          value={formData.baseUrl}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              baseUrl: e.target.value,
                            })
                          }
                        />
                      </div>
                      <div className="col-span-2 space-y-2">
                        <Label>API Key</Label>
                        <Input
                          type="password"
                          placeholder={
                            editingId
                              ? "Leave empty to keep existing key"
                              : "sk-..."
                          }
                          value={formData.apiKey}
                          onChange={(e) =>
                            setFormData({ ...formData, apiKey: e.target.value })
                          }
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Temperature</Label>
                        <Input
                          type="number"
                          step="0.1"
                          min="0"
                          max="2"
                          value={formData.temperature}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              temperature: parseFloat(e.target.value),
                            })
                          }
                        />
                      </div>
                      <div className="space-y-2">
                        <Label>Max Tokens</Label>
                        <Input
                          type="number"
                          value={formData.maxTokens}
                          onChange={(e) =>
                            setFormData({
                              ...formData,
                              maxTokens: parseInt(e.target.value),
                            })
                          }
                        />
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        onClick={handleSave}
                        disabled={
                          saving ||
                          !formData.name ||
                          !formData.modelId ||
                          (!editingId && !formData.apiKey)
                        }
                      >
                        {saving ? (
                          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                        ) : (
                          <Save className="h-4 w-4 mr-2" />
                        )}
                        {editingId ? "Update Provider" : "Save Provider"}
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => {
                          setShowAIForm(false);
                          setEditingId(null);
                          setFormData(emptyForm);
                        }}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="tts" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>TTS Voice Settings</CardTitle>
              <CardDescription>
                Configure text-to-speech voice for video narration
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {ttsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>Voice</Label>
                      <Select
                        value={ttsSetting?.voice || "zh-CN-XiaoxiaoNeural"}
                        onValueChange={(value) => {
                          setTtsSetting((prev) =>
                            prev ? { ...prev, voice: value } : null,
                          );
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="zh-CN-XiaoxiaoNeural">
                            Xiaoxiao (Female, Natural)
                          </SelectItem>
                          <SelectItem value="zh-CN-YunxiNeural">
                            Yunxi (Male, Sunny)
                          </SelectItem>
                          <SelectItem value="zh-CN-YunjianNeural">
                            Yunjian (Male, News)
                          </SelectItem>
                          <SelectItem value="zh-CN-XiaoyiNeural">
                            Xiaoyi (Female, Gentle)
                          </SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>Speech Rate</Label>
                      <Select
                        value={ttsSetting?.rate || "+0%"}
                        onValueChange={(value) => {
                          setTtsSetting((prev) =>
                            prev ? { ...prev, rate: value } : null,
                          );
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="-20%">Slow (0.8x)</SelectItem>
                          <SelectItem value="+0%">Normal (1.0x)</SelectItem>
                          <SelectItem value="+20%">Fast (1.2x)</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label>Test Text</Label>
                    <Textarea
                      placeholder="Enter text to test voice..."
                      value={localTestText}
                      onChange={(e) => setLocalTestText(e.target.value)}
                      rows={3}
                    />
                    <p className="text-xs text-muted-foreground">
                      This text will be used when testing the voice.
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button onClick={handleTTSSave} disabled={ttsSaving}>
                      {ttsSaving ? (
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      ) : (
                        <Save className="h-4 w-4 mr-2" />
                      )}
                      Save Settings
                    </Button>
                    <Button
                      variant="outline"
                      onClick={handleTTSTest}
                      disabled={ttsTesting}
                    >
                      {ttsTesting ? (
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      ) : (
                        <Volume2 className="h-4 w-4 mr-2" />
                      )}
                      Test Voice
                    </Button>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="publishing" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Publishing Accounts</CardTitle>
              <CardDescription>
                Connect your social media accounts for auto-publishing
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between p-4 border rounded-lg">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 bg-black rounded-lg flex items-center justify-center text-white font-bold">
                    D
                  </div>
                  <div>
                    <p className="font-medium">Douyin</p>
                    <p className="text-sm text-muted-foreground">
                      Not connected
                    </p>
                  </div>
                </div>
                <Button variant="outline">Connect</Button>
              </div>

              <div className="flex items-center justify-between p-4 border rounded-lg">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 bg-red-500 rounded-lg flex items-center justify-center text-white font-bold">
                    X
                  </div>
                  <div>
                    <p className="font-medium">Xiaohongshu</p>
                    <p className="text-sm text-muted-foreground">
                      Not connected
                    </p>
                  </div>
                </div>
                <Button variant="outline">Connect</Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="general" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>General Settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {generalLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>Output Directory</Label>
                      <Input
                        value={generalSettings.output_dir}
                        onChange={(e) =>
                          setGeneralSettings({
                            ...generalSettings,
                            output_dir: e.target.value,
                          })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Video Resolution</Label>
                      <Select
                        value={`${generalSettings.video_resolution_width}x${generalSettings.video_resolution_height}`}
                        onValueChange={(value) => {
                          const [w, h] = value.split("x").map(Number);
                          setGeneralSettings({
                            ...generalSettings,
                            video_resolution_width: w,
                            video_resolution_height: h,
                          });
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="1080x1920">
                            竖屏 1080x1920 (手机)
                          </SelectItem>
                          <SelectItem value="720x1280">
                            竖屏 720x1280
                          </SelectItem>
                          <SelectItem value="1920x1080">
                            横屏 1920x1080 (电脑)
                          </SelectItem>
                          <SelectItem value="1280x720">
                            横屏 1280x720
                          </SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>Pexels API Key</Label>
                      <Input
                        placeholder="Enter Pexels API key"
                        value={generalSettings.pexels_api_key || ""}
                        onChange={(e) =>
                          setGeneralSettings({
                            ...generalSettings,
                            pexels_api_key: e.target.value || null,
                          })
                        }
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Pixabay API Key</Label>
                      <Input
                        placeholder="Enter Pixabay API key"
                        value={generalSettings.pixabay_api_key || ""}
                        onChange={(e) =>
                          setGeneralSettings({
                            ...generalSettings,
                            pixabay_api_key: e.target.value || null,
                          })
                        }
                      />
                    </div>
                  </div>
                  <Button onClick={handleGeneralSave} disabled={generalSaving}>
                    {generalSaving ? (
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4 mr-2" />
                    )}
                    Save Settings
                  </Button>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
