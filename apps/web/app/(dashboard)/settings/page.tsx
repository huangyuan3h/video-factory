'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Save, Plus, Trash2, TestTube } from 'lucide-react';

interface AIConfig {
  id: string;
  name: string;
  baseUrl: string;
  modelId: string;
  isActive: boolean;
}

const mockAIConfigs: AIConfig[] = [
  {
    id: '1',
    name: 'OpenAI GPT-4o',
    baseUrl: 'https://api.openai.com/v1',
    modelId: 'gpt-4o',
    isActive: true,
  },
  {
    id: '2',
    name: 'DeepSeek',
    baseUrl: 'https://api.deepseek.com/v1',
    modelId: 'deepseek-chat',
    isActive: false,
  },
];

export default function SettingsPage() {
  const [aiConfigs, setAIConfigs] = useState<AIConfig[]>(mockAIConfigs);
  const [showAIForm, setShowAIForm] = useState(false);

  const setActive = (id: string) => {
    setAIConfigs(
      aiConfigs.map((config) => ({
        ...config,
        isActive: config.id === id,
      }))
    );
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
                    Configure OpenAI-compatible API providers for content generation
                  </CardDescription>
                </div>
                <Button onClick={() => setShowAIForm(true)}>
                  <Plus className="h-4 w-4 mr-2" />
                  Add Provider
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {aiConfigs.map((config) => (
                <div
                  key={config.id}
                  className="flex items-center justify-between p-4 border rounded-lg"
                >
                  <div className="flex items-center gap-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{config.name}</span>
                        {config.isActive && (
                          <Badge variant="success">Active</Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground">
                        {config.baseUrl} / {config.modelId}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {!config.isActive && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setActive(config.id)}
                      >
                        Set Active
                      </Button>
                    )}
                    <Button variant="ghost" size="sm">
                      <TestTube className="h-4 w-4 mr-1" />
                      Test
                    </Button>
                    <Button variant="ghost" size="sm">
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </div>
                </div>
              ))}

              {showAIForm && (
                <>
                  <Separator />
                  <div className="space-y-4 p-4 border rounded-lg bg-muted/50">
                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label>Provider Name</Label>
                        <Input placeholder="e.g., OpenAI, DeepSeek" />
                      </div>
                      <div className="space-y-2">
                        <Label>Model ID</Label>
                        <Input placeholder="e.g., gpt-4o, deepseek-chat" />
                      </div>
                      <div className="col-span-2 space-y-2">
                        <Label>Base URL</Label>
                        <Input placeholder="https://api.openai.com/v1" />
                      </div>
                      <div className="col-span-2 space-y-2">
                        <Label>API Key</Label>
                        <Input type="password" placeholder="sk-..." />
                      </div>
                      <div className="space-y-2">
                        <Label>Temperature</Label>
                        <Input type="number" step="0.1" defaultValue="0.7" />
                      </div>
                      <div className="space-y-2">
                        <Label>Max Tokens</Label>
                        <Input type="number" defaultValue="4096" />
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <Button onClick={() => setShowAIForm(false)}>
                        <Save className="h-4 w-4 mr-2" />
                        Save Provider
                      </Button>
                      <Button variant="outline" onClick={() => setShowAIForm(false)}>
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
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Voice</Label>
                  <Select defaultValue="zh-CN-XiaoxiaoNeural">
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
                  <Select defaultValue="1.0">
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="0.8">Slow (0.8x)</SelectItem>
                      <SelectItem value="1.0">Normal (1.0x)</SelectItem>
                      <SelectItem value="1.2">Fast (1.2x)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <Button>
                <TestTube className="h-4 w-4 mr-2" />
                Test Voice
              </Button>
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
                    <p className="text-sm text-muted-foreground">Not connected</p>
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
                    <p className="text-sm text-muted-foreground">Not connected</p>
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
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Output Directory</Label>
                  <Input defaultValue="./data/output" />
                </div>
                <div className="space-y-2">
                  <Label>Video Resolution</Label>
                  <Select defaultValue="1080p">
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="720p">720p (1280x720)</SelectItem>
                      <SelectItem value="1080p">1080p (1920x1080)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Material Source</Label>
                  <Select defaultValue="both">
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="online">Online (Pexels/Pixabay)</SelectItem>
                      <SelectItem value="local">Local Library</SelectItem>
                      <SelectItem value="both">Both</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Pexels API Key</Label>
                  <Input type="password" placeholder="Enter API key" />
                </div>
              </div>
              <Button>
                <Save className="h-4 w-4 mr-2" />
                Save Settings
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}