// AI Settings Types
export interface AISettings {
  id: string;
  name: string;
  baseUrl: string;
  apiKey: string;
  modelId: string;
  temperature?: number;
  maxTokens?: number;
  isActive?: boolean;
}

export interface AISettingsCreateInput {
  name: string;
  baseUrl: string;
  apiKey: string;
  modelId: string;
  temperature?: number;
  maxTokens?: number;
}

// Source Types
export type SourceType = 'rss' | 'news_api' | 'hot_topics' | 'custom';

export interface SourceConfig {
  id: string;
  type: SourceType;
  name: string;
  url?: string;
  apiKey?: string;
  keywords?: string[];
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface SourceCreateInput {
  type: SourceType;
  name: string;
  url?: string;
  apiKey?: string;
  keywords?: string[];
  enabled?: boolean;
}

// Task Types
export interface Task {
  id: string;
  name: string;
  sourceId: string;
  schedule: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface TaskCreateInput {
  name: string;
  sourceId: string;
  schedule: string;
  enabled?: boolean;
}

// Run Types
export type RunStatus = 'pending' | 'processing' | 'completed' | 'failed';

export interface Run {
  id: string;
  taskId: string;
  status: RunStatus;
  inputContent?: string;
  script?: string;
  videoPath?: string;
  publishedTo?: string[];
  error?: string;
  startedAt?: string;
  endedAt?: string;
  createdAt: string;
}

// Publisher Types
export type Platform = 'douyin' | 'xiaohongshu' | 'wechat_video' | 'bilibili';

export interface PublisherAccount {
  id: string;
  platform: Platform;
  name: string;
  cookies?: string;
  enabled: boolean;
  createdAt: string;
}

export interface PublisherAccountCreateInput {
  platform: Platform;
  name: string;
  enabled?: boolean;
}

// Video Generation Types
export interface VideoOptions {
  voice?: string;
  resolution?: '720p' | '1080p';
  fps?: number;
  subtitleStyle?: SubtitleStyle;
  materialSource?: 'online' | 'local' | 'both';
}

export interface SubtitleStyle {
  fontSize: number;
  fontFamily: string;
  color: string;
  backgroundColor?: string;
  position: 'bottom' | 'top' | 'center';
}

// API Response Types
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}