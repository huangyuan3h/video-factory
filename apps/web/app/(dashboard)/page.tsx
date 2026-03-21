import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Video, Clock, CheckCircle, XCircle, TrendingUp } from 'lucide-react';

const stats = [
  {
    title: 'Total Videos',
    value: '128',
    change: '+12%',
    icon: Video,
  },
  {
    title: 'Pending Tasks',
    value: '5',
    change: '-2',
    icon: Clock,
  },
  {
    title: 'Completed Today',
    value: '24',
    change: '+8',
    icon: CheckCircle,
  },
  {
    title: 'Failed',
    value: '2',
    change: '-1',
    icon: XCircle,
  },
];

const recentRuns = [
  {
    id: '1',
    taskName: 'Tech News Daily',
    status: 'completed',
    platform: 'Douyin',
    time: '2 hours ago',
  },
  {
    id: '2',
    taskName: 'AI Weekly Summary',
    status: 'processing',
    platform: 'Xiaohongshu',
    time: '1 hour ago',
  },
  {
    id: '3',
    taskName: 'Hot Topics Morning',
    status: 'failed',
    platform: 'Douyin',
    time: '3 hours ago',
  },
  {
    id: '4',
    taskName: 'RSS Feed Update',
    status: 'completed',
    platform: 'Bilibili',
    time: '5 hours ago',
  },
];

export default function DashboardPage() {
  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold">Dashboard</h1>
        <p className="text-muted-foreground">
          Overview of your video factory
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => (
          <Card key={stat.title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">{stat.title}</CardTitle>
              <stat.icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <p className="text-xs text-muted-foreground flex items-center gap-1">
                <TrendingUp className="h-3 w-3 text-green-500" />
                {stat.change} from last week
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="mt-8">
        <h2 className="text-xl font-semibold mb-4">Recent Runs</h2>
        <Card>
          <CardContent className="p-0">
            <div className="divide-y">
              {recentRuns.map((run) => (
                <div
                  key={run.id}
                  className="flex items-center justify-between p-4"
                >
                  <div className="flex items-center gap-4">
                    <Video className="h-5 w-5 text-muted-foreground" />
                    <div>
                      <p className="font-medium">{run.taskName}</p>
                      <p className="text-sm text-muted-foreground">
                        {run.platform}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <Badge
                      variant={
                        run.status === 'completed'
                          ? 'success'
                          : run.status === 'processing'
                          ? 'warning'
                          : 'destructive'
                      }
                    >
                      {run.status}
                    </Badge>
                    <span className="text-sm text-muted-foreground">
                      {run.time}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}