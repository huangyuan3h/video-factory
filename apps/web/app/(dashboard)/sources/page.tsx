'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Plus, Trash2, Edit, Rss, Newspaper, TrendingUp, Globe } from 'lucide-react';

interface Source {
  id: string;
  name: string;
  type: 'rss' | 'news_api' | 'hot_topics' | 'custom';
  url: string;
  keywords: string[];
  enabled: boolean;
  lastFetch: string;
}

const mockSources: Source[] = [
  {
    id: '1',
    name: 'TechCrunch',
    type: 'rss',
    url: 'https://techcrunch.com/feed/',
    keywords: ['AI', 'startup', 'tech'],
    enabled: true,
    lastFetch: '2024-03-20 09:00',
  },
  {
    id: '2',
    name: 'OpenAI Blog',
    type: 'rss',
    url: 'https://openai.com/blog/rss.xml',
    keywords: ['GPT', 'AI'],
    enabled: true,
    lastFetch: '2024-03-20 08:30',
  },
  {
    id: '3',
    name: 'Weibo Hot Topics',
    type: 'hot_topics',
    url: 'https://weibo.com/hot',
    keywords: [],
    enabled: false,
    lastFetch: '2024-03-19 10:00',
  },
];

const typeIcons = {
  rss: Rss,
  news_api: Newspaper,
  hot_topics: TrendingUp,
  custom: Globe,
};

export default function SourcesPage() {
  const [sources, setSources] = useState<Source[]>(mockSources);
  const [showCreateForm, setShowCreateForm] = useState(false);

  const toggleSource = (id: string) => {
    setSources(
      sources.map((source) =>
        source.id === id ? { ...source, enabled: !source.enabled } : source
      )
    );
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">Content Sources</h1>
          <p className="text-muted-foreground">
            Configure RSS feeds, news APIs, and hot topics sources
          </p>
        </div>
        <Button onClick={() => setShowCreateForm(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Add Source
        </Button>
      </div>

      {showCreateForm && (
        <Card className="mb-8">
          <CardHeader>
            <CardTitle>Add New Source</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="name">Source Name</Label>
                <Input id="name" placeholder="Enter source name" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="type">Source Type</Label>
                <Select>
                  <SelectTrigger>
                    <SelectValue placeholder="Select type" />
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
                <Label htmlFor="url">URL / Endpoint</Label>
                <Input id="url" placeholder="https://example.com/feed/" />
              </div>
              <div className="col-span-2 space-y-2">
                <Label htmlFor="keywords">Keywords (comma separated)</Label>
                <Input id="keywords" placeholder="AI, startup, tech" />
              </div>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => setShowCreateForm(false)}>Add Source</Button>
              <Button variant="outline" onClick={() => setShowCreateForm(false)}>
                Cancel
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="p-0">
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
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon">
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
    </div>
  );
}