/**
 * API Client for Video Factory
 * Uses Next.js API routes as proxy with custom user-agent header
 */

interface RequestOptions extends RequestInit {
  params?: Record<string, string>;
}

interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

class ApiClient {
  private headers: HeadersInit;

  constructor() {
    this.headers = {
      "Content-Type": "application/json",
    };
  }

  private buildUrl(path: string, params?: Record<string, string>): string {
    const url = new URL(path, window.location.origin);
    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        url.searchParams.append(key, value);
      });
    }
    return url.toString();
  }

  async request<T>(
    path: string,
    options: RequestOptions = {},
  ): Promise<ApiResponse<T>> {
    const { params, ...fetchOptions } = options;
    const url = this.buildUrl(path, params);

    try {
      const response = await fetch(url, {
        ...fetchOptions,
        headers: {
          ...this.headers,
          ...fetchOptions.headers,
        },
      });

      const data = await response.json();
      return data as ApiResponse<T>;
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Network error",
      };
    }
  }

  async get<T>(
    path: string,
    params?: Record<string, string>,
  ): Promise<ApiResponse<T>> {
    return this.request<T>(path, { method: "GET", params });
  }

  async post<T>(path: string, body?: unknown): Promise<ApiResponse<T>> {
    return this.request<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  async put<T>(path: string, body?: unknown): Promise<ApiResponse<T>> {
    return this.request<T>(path, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  async delete<T>(path: string): Promise<ApiResponse<T>> {
    return this.request<T>(path, { method: "DELETE" });
  }
}

export const apiClient = new ApiClient();

// AI Settings API
export const aiSettingsApi = {
  list: () => apiClient.get<AISetting[]>("/api/ai-settings"),
  getActive: () => apiClient.get<AISetting>("/api/ai-settings/active"),
  create: (data: AISettingCreate) =>
    apiClient.post<AISetting>("/api/ai-settings", data),
  update: (id: string, data: AISettingUpdate) =>
    apiClient.put<AISetting>(`/api/ai-settings/${id}`, data),
  activate: (id: string) =>
    apiClient.post<AISetting>(`/api/ai-settings/${id}/activate`),
  delete: (id: string) => apiClient.delete<void>(`/api/ai-settings/${id}`),
  test: (id: string) =>
    apiClient.post<TestResult>(`/api/ai-settings/${id}/test`),
};

// Types
export interface AISetting {
  id: string;
  name: string;
  base_url: string;
  api_key: string;
  model_id: string;
  temperature: number;
  max_tokens: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AISettingCreate {
  name: string;
  base_url: string;
  api_key: string;
  model_id: string;
  temperature?: number;
  max_tokens?: number;
}

export interface AISettingUpdate {
  name?: string;
  base_url?: string;
  api_key?: string;
  model_id?: string;
  temperature?: number;
  max_tokens?: number;
  is_active?: boolean;
}

export interface TestResult {
  success: boolean;
  latency_ms?: number;
  error?: string;
  model?: string;
}

// TTS Settings Types
export interface TTSSetting {
  id: string;
  voice: string;
  rate: string;
  test_text: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface TTSSettingUpdate {
  voice?: string;
  rate?: string;
  test_text?: string;
}

export interface TTSSettingTestRequest {
  voice?: string;
  rate?: string;
  test_text?: string;
}

export interface GeneralSettings {
  id: string;
  output_dir: string;
  video_resolution_width: number;
  video_resolution_height: number;
  pexels_api_key: string | null;
  pixabay_api_key: string | null;
  default_background_music: string | null;
  created_at: string;
  updated_at: string;
}

export interface GeneralSettingsUpdate {
  output_dir?: string;
  video_resolution_width?: number;
  video_resolution_height?: number;
  pexels_api_key?: string;
  pixabay_api_key?: string;
  default_background_music?: string;
}

// TTS Settings API
export const ttsSettingsApi = {
  get: () => apiClient.get<TTSSetting>("/api/tts-settings"),
  update: (data: TTSSettingUpdate) =>
    apiClient.put<TTSSetting>("/api/tts-settings", data),
  test: async (
    data: TTSSettingTestRequest,
  ): Promise<{ success: boolean; blob?: Blob; error?: string }> => {
    try {
      const response = await fetch("/api/tts-settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (response.ok) {
        const blob = await response.blob();
        if (blob.size === 0) {
          return { success: false, error: "Received empty audio file" };
        }
        return { success: true, blob };
      }
      const errorData = await response.json().catch(() => ({}));
      return {
        success: false,
        error:
          errorData.error || `Failed to generate audio (${response.status})`,
      };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      };
    }
  },
  listVoices: () =>
    apiClient.get<Record<string, string> | { voices: unknown; languages: unknown; source: string }>("/api/tts-settings/voices"),
  status: () => apiClient.get<{
    backend: string;
    configured: boolean;
    url: string | null;
    hint: string;
    upstream_engine?: string;
  }>("/api/tts-settings/status"),
  speak: async (data: { text: string; voice?: string; speed?: number; language?: string }) => {
    const r = await fetch("/api/tts-settings/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!r.ok) return { success: false as const, error: await r.text() };
    return { success: true as const, blob: await r.blob() };
  },
  speakStream: async (data: { text: string; voice?: string; speed?: number; language?: string }) => {
    const r = await fetch("/api/tts-settings/speak-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!r.ok || !r.body) return null;
    return r.body;
  },
  registerVoice: async (voiceId: string, transcript: string, file: File) => {
    const fd = new FormData();
    fd.append("voice_id", voiceId);
    fd.append("transcript", transcript);
    fd.append("file", file);
    const r = await fetch("/api/tts-settings/voices/register", { method: "POST", body: fd });
    return r.json();
  },
};

export const capabilitiesApi = {
  get: () => apiClient.get<Record<string, unknown>>("/api/capabilities"),
};

export const generalSettingsApi = {
  get: () => apiClient.get<GeneralSettings>("/api/settings"),
  update: (data: GeneralSettingsUpdate) =>
    apiClient.put<GeneralSettings>("/api/settings", data),
};

export interface SystemPrompt {
  id: string;
  name: string;
  content: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface SystemPromptCreate {
  name: string;
  content: string;
  is_default?: boolean;
}

export interface SystemPromptUpdate {
  name?: string;
  content?: string;
  is_default?: boolean;
}

export const systemPromptsApi = {
  list: () => apiClient.get<SystemPrompt[]>("/api/system-prompts"),
  create: (data: SystemPromptCreate) =>
    apiClient.post<SystemPrompt>("/api/system-prompts", data),
  update: (id: string, data: SystemPromptUpdate) =>
    apiClient.put<SystemPrompt>(`/api/system-prompts/${id}`, data),
  delete: (id: string) => apiClient.delete<void>(`/api/system-prompts/${id}`),
  setDefault: (id: string) =>
    apiClient.post<SystemPrompt>(`/api/system-prompts/${id}/default`),
};

export interface Source {
  id: string;
  type: string;
  name: string;
  url: string | null;
  api_key: string | null;
  keywords: string[] | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface SourceCreate {
  type: string;
  name: string;
  url?: string;
  api_key?: string;
  keywords?: string[];
  enabled?: boolean;
}

export const sourcesApi = {
  list: () => apiClient.get<Source[]>("/api/sources"),
  create: (data: SourceCreate) => apiClient.post<Source>("/api/sources", data),
};

export interface Task {
  id: string;
  name: string;
  source_id: string;
  schedule: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  source?: Source;
}

export interface TaskCreate {
  name: string;
  source_id: string;
  schedule: string;
  enabled?: boolean;
}

export interface TaskUpdate {
  name?: string;
  schedule?: string;
  enabled?: boolean;
}

export const tasksApi = {
  list: (enabled?: boolean) => {
    const params: Record<string, string> = {};
    if (enabled !== undefined) params.enabled = String(enabled);
    return apiClient.get<Task[]>("/api/tasks", params);
  },
  get: (id: string) => apiClient.get<Task>(`/api/tasks/${id}`),
  create: (data: TaskCreate) => apiClient.post<Task>("/api/tasks", data),
  update: (id: string, data: TaskUpdate) =>
    apiClient.put<Task>(`/api/tasks/${id}`, data),
  delete: (id: string) => apiClient.delete<void>(`/api/tasks/${id}`),
  run: (id: string) =>
    apiClient.post<{ run_id: string }>(`/api/tasks/${id}/run`),
};

export interface Run {
  id: string;
  task_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  input_content: string | null;
  script: string | null;
  video_path: string | null;
  published_to: string[] | null;
  error: string | null;
  started_at: string | null;
  ended_at: string | null;
  created_at: string;
  task?: Task;
}

export interface PaginatedRuns {
  items: Run[];
  total: number;
  page: number;
  page_size: number;
}

export const runsApi = {
  list: (params?: {
    task_id?: string;
    status?: string;
    page?: number;
    page_size?: number;
  }) => {
    const searchParams: Record<string, string> = {};
    if (params?.task_id) searchParams.taskId = params.task_id;
    if (params?.status) searchParams.status = params.status;
    if (params?.page) searchParams.page = String(params.page);
    if (params?.page_size) searchParams.pageSize = String(params.page_size);
    return apiClient.get<PaginatedRuns>("/api/runs", searchParams);
  },
  get: (id: string) => apiClient.get<Run>(`/api/runs/${id}`),
};

export interface VideoTask {
  id: string;
  task_uuid: string;
  task_dir: string;
  status: "pending" | "processing" | "completed" | "failed" | "cancelled";
  progress: number;
  current_step: number;
  step_name?: string;
  message: string;
  created_at: string;
  completed_at?: string;
  video_path?: string;
  error?: string;
  series_id?: string | null;
  series_name?: string | null;
  series_slug?: string | null;
  review_status?: "draft" | "approved" | "rejected";
  review_note?: string | null;
  request: {
    title: string;
    has_background_music: boolean;
    voice: string;
  };
  files?: Record<string, string>;
}

export interface VideoGenerateRequest {
  title: string;
  content?: string;
  textContent?: string;
  text_content?: string;
  systemPrompt?: string;
  rewrite_content?: boolean;
  rewriteContent?: boolean;
  optimize?: boolean;
  rewrite_prompt?: string;
  rewritePrompt?: string;
  backgroundMusic?: string;
  generateSubtitle?: boolean;
  subtitleColor?: string;
  subtitleFont?: string;
  voice?: string;
  voiceRate?: string;
  backgroundSource?: string;
  series_id?: string;
  seriesId?: string;
  resolution?: string;
  orientation?: "landscape" | "portrait" | "square" | string;
  aspectRatio?: string;
  resolutionWidth?: number;
  resolutionHeight?: number;
  width?: number;
  height?: number;
  fps?: number;
  generateCover?: boolean;
  publish_to?: string[];
  publishTo?: string[];
  folder_id?: string;
  folderId?: string;
  publish_privacy?: string;
  [key: string]: unknown;
}

export interface PublisherAccount {
  id: string;
  platform: string;
  name: string;
  enabled: boolean;
  folder_id?: string | null;
  folder_name?: string | null;
  cookies?: string | null;
  credentials?: string | null;
}

export const videosApi = {
  generate: (data: VideoGenerateRequest) => {
    const payload: Record<string, unknown> = { ...data };
    if (!payload.content && !payload.textContent && !(payload as Record<string, unknown>).text_content) {
      // keep as is; worker will 422
    }
    if ((payload as Record<string, unknown>).textContent && !payload.content) {
      payload.content = payload.textContent;
    }
    // Normalize publish_to alias
    if ((payload as Record<string, unknown>).publishTo && !payload.publish_to) {
      payload.publish_to = (payload as Record<string, unknown>).publishTo;
    }
    return apiClient.post<{ id: string; task_uuid: string; status: string; resolution: { width: number; height: number } }>(
      "/api/videos/generate",
      payload,
    );
  },
  // Alias for agent convenience
  generateSimple: (title: string, content: string, opts: Partial<VideoGenerateRequest> = {}) =>
    apiClient.post<{ id: string; task_uuid: string; status: string }>(
      "/api/videos/generate",
      { title, content, ...opts },
    ),
  list: (seriesId?: string) =>
    apiClient.get<VideoTask[]>(
      seriesId ? `/api/videos/generate?series_id=${encodeURIComponent(seriesId)}` : "/api/videos/generate",
    ),
  get: (taskId: string) =>
    apiClient.get<VideoTask>(`/api/videos/generate?taskId=${taskId}`),
  getLog: (taskId: string) =>
    apiClient.get<{ log: string }>(
      `/api/videos/generate?taskId=${taskId}&action=log`,
    ),
  delete: (taskId: string) =>
    apiClient.delete<void>(`/api/videos/generate?taskId=${taskId}`),
  cancel: (taskId: string) =>
    apiClient.post<{ id: string; status: string }>(`/api/videos/tasks/${taskId}/cancel`),
  retry: (taskId: string) =>
    apiClient.post<{ id: string; task_uuid: string }>(`/api/videos/tasks/${taskId}/retry`),
  review: (taskId: string, decision: "approve" | "reject", note?: string) =>
    apiClient.post<{ id: string; review_status: string }>(`/api/videos/tasks/${taskId}/review`, {
      decision,
      note,
    }),
  publish: (
    taskId: string,
    data: {
      platforms?: string[];
      account_ids?: string[];
      folder_id?: string;
      title?: string;
      description?: string;
      tags?: string[];
      privacy?: string;
    },
  ) => apiClient.post<{ queued: number; jobs: string[] }>(`/api/videos/tasks/${taskId}/publish`, data),
  listPublishJobs: (taskId: string) =>
    apiClient.get<PublishJob[]>(`/api/videos/tasks/${taskId}/publish`),
  eventsUrl: () => "/api/videos/events",
  downloadUrl: (taskId: string, kind: "video" | "cover" | "subtitle" | "script" = "video") =>
    `/api/videos/tasks/${taskId}/download?kind=${kind}`,
};

export const publishersApi = {
  list: () => apiClient.get<PublisherAccount[]>("/api/publishers"),
  create: (data: { platform: string; name: string; cookies?: string; credentials?: string; folder_id?: string }) =>
    apiClient.post<PublisherAccount>("/api/publishers", data),
  listPlatforms: () => apiClient.get<string[]>("/api/publishers/platforms/list"),
  listFolders: (id: string) => apiClient.get<{ id: string; name: string }[]>(`/api/publishers/${id}/folders`),
  createFolder: (id: string, name: string) =>
    apiClient.post<{ id: string; name: string }>(`/api/publishers/${id}/folders`, { name }),
  login: (id: string, headless = false, timeout = 180) =>
    apiClient.post<{ platform: string; cookies_saved: boolean }>(`/api/publishers/${id}/login`, {
      headless,
      timeout,
    }),
  publish: (id: string, data: { task_id?: string; video_path?: string; title?: string; folder_id?: string }) =>
    apiClient.post<{ post_url?: string; post_id?: string }>(`/api/publishers/${id}/publish`, data),
};

export interface Series {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  cover_path?: string | null;
  system_prompt?: string | null;
  default_voice?: string | null;
  default_voice_rate?: string | null;
  default_resolution_width?: number | null;
  default_resolution_height?: number | null;
  default_background_source?: string | null;
  default_background_music?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface SeriesCreate {
  name: string;
  slug?: string;
  description?: string;
  system_prompt?: string;
  default_voice?: string;
  default_voice_rate?: string;
  default_resolution_width?: number;
  default_resolution_height?: number;
  default_background_source?: string;
  default_background_music?: string;
}

export interface SeriesTarget {
  id: string;
  series_id: string;
  platform: string;
  account_id?: string | null;
  folder_id?: string | null;
  folder_name?: string | null;
  enabled: boolean;
}

export interface PublishJob {
  id: string;
  task_id: string;
  platform: string;
  account_id?: string | null;
  status: "pending" | "processing" | "completed" | "failed";
  post_url?: string | null;
  post_id?: string | null;
  error?: string | null;
  attempts?: number;
  created_at?: string | null;
}

export const seriesApi = {
  list: () => apiClient.get<Series[]>("/api/series"),
  get: (id: string) => apiClient.get<Series>(`/api/series/${id}`),
  create: (data: SeriesCreate) => apiClient.post<Series>("/api/series", data),
  update: (id: string, data: Partial<SeriesCreate>) => apiClient.put<Series>(`/api/series/${id}`, data),
  delete: (id: string) => apiClient.delete<void>(`/api/series/${id}`),
  listTargets: (id: string) => apiClient.get<SeriesTarget[]>(`/api/series/${id}/targets`),
  createTarget: (id: string, data: Omit<SeriesTarget, "id" | "series_id">) =>
    apiClient.post<SeriesTarget>(`/api/series/${id}/targets`, data),
  deleteTarget: (id: string, targetId: string) =>
    apiClient.delete<void>(`/api/series/${id}/targets/${targetId}`),
  publishApproved: (id: string) =>
    apiClient.post<{ videos: number; queued: number }>(`/api/series/${id}/publish-approved`),
};

export const publishingApi = {
  list: (status?: string) =>
    apiClient.get<PublishJob[]>(`/api/publish/jobs${status ? `?status=${status}` : ""}`),
  retry: (id: string) => apiClient.post<{ id: string; status: string }>(`/api/publish/jobs/${id}/retry`),
};
