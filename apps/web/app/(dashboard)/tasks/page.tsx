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
import { Plus, Play, Pause, Trash2, Edit } from 'lucide-react';

interface Task {
  id: string;
  name: string;
  source: string;
  schedule: string;
  enabled: boolean;
  lastRun: string;
  status: 'idle' | 'running' | 'error';
}

const mockTasks: Task[] = [
  {
    id: '1',
    name: 'Tech News Daily',
    source: 'TechCrunch RSS',
    schedule: '0 9 * * *',
    enabled: true,
    lastRun: '2024-03-20 09:00',
    status: 'idle',
  },
  {
    id: '2',
    name: 'AI Weekly Summary',
    source: 'OpenAI Blog',
    schedule: '0 10 * * 1',
    enabled: true,
    lastRun: '2024-03-18 10:00',
    status: 'running',
  },
  {
    id: '3',
    name: 'Hot Topics Morning',
    source: 'Weibo Hot',
    schedule: '0 8 * * *',
    enabled: false,
    lastRun: '2024-03-19 08:00',
    status: 'error',
  },
];

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>(mockTasks);
  const [showCreateForm, setShowCreateForm] = useState(false);

  const toggleTask = (id: string) => {
    setTasks(
      tasks.map((task) =>
        task.id === id ? { ...task, enabled: !task.enabled } : task
      )
    );
  };

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold">Tasks</h1>
          <p className="text-muted-foreground">
            Manage your automated video generation tasks
          </p>
        </div>
        <Button onClick={() => setShowCreateForm(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Create Task
        </Button>
      </div>

      {showCreateForm && (
        <Card className="mb-8">
          <CardHeader>
            <CardTitle>Create New Task</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="name">Task Name</Label>
                <Input id="name" placeholder="Enter task name" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="source">Content Source</Label>
                <Select>
                  <SelectTrigger>
                    <SelectValue placeholder="Select source" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="techcrunch">TechCrunch RSS</SelectItem>
                    <SelectItem value="openai">OpenAI Blog</SelectItem>
                    <SelectItem value="weibo">Weibo Hot Topics</SelectItem>
                    <SelectItem value="custom">Custom RSS</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="schedule">Schedule (Cron)</Label>
                <Input id="schedule" placeholder="0 9 * * *" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="platform">Publish Platform</Label>
                <Select>
                  <SelectTrigger>
                    <SelectValue placeholder="Select platform" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="douyin">Douyin</SelectItem>
                    <SelectItem value="xiaohongshu">Xiaohongshu</SelectItem>
                    <SelectItem value="both">Both</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => setShowCreateForm(false)}>Create</Button>
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
                <TableHead>Source</TableHead>
                <TableHead>Schedule</TableHead>
                <TableHead>Last Run</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Enabled</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tasks.map((task) => (
                <TableRow key={task.id}>
                  <TableCell className="font-medium">{task.name}</TableCell>
                  <TableCell>{task.source}</TableCell>
                  <TableCell>
                    <code className="text-sm bg-muted px-2 py-1 rounded">
                      {task.schedule}
                    </code>
                  </TableCell>
                  <TableCell>{task.lastRun}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        task.status === 'running'
                          ? 'warning'
                          : task.status === 'error'
                          ? 'destructive'
                          : 'secondary'
                      }
                    >
                      {task.status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={task.enabled}
                      onCheckedChange={() => toggleTask(task.id)}
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button variant="ghost" size="icon">
                        {task.enabled ? (
                          <Pause className="h-4 w-4" />
                        ) : (
                          <Play className="h-4 w-4" />
                        )}
                      </Button>
                      <Button variant="ghost" size="icon">
                        <Edit className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon">
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}