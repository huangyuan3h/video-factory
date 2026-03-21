'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Video,
  Settings,
  ListTodo,
  Rss,
  FileText,
  LayoutDashboard,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';

const navigation = [
  {
    name: 'Dashboard',
    href: '/',
    icon: LayoutDashboard,
  },
  {
    name: 'Tasks',
    href: '/tasks',
    icon: ListTodo,
  },
  {
    name: 'Sources',
    href: '/sources',
    icon: Rss,
  },
  {
    name: 'Videos',
    href: '/videos',
    icon: Video,
  },
  {
    name: 'Logs',
    href: '/logs',
    icon: FileText,
  },
  {
    name: 'Settings',
    href: '/settings',
    icon: Settings,
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <div className="flex h-full w-64 flex-col border-r bg-card">
      <div className="flex h-16 items-center gap-2 px-6">
        <Video className="h-6 w-6 text-primary" />
        <span className="text-lg font-semibold">Video Factory</span>
      </div>
      <Separator />
      <nav className="flex-1 space-y-1 p-4">
        {navigation.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link key={item.name} href={item.href}>
              <Button
                variant={isActive ? 'secondary' : 'ghost'}
                className={cn(
                  'w-full justify-start gap-3',
                  isActive && 'bg-secondary'
                )}
              >
                <item.icon className="h-4 w-4" />
                {item.name}
              </Button>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}