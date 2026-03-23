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
    apiClient.get<Record<string, string>>("/api/tts-settings/voices"),
};

export const generalSettingsApi = {
  get: () => apiClient.get<GeneralSettings>("/api/settings"),
  update: (data: GeneralSettingsUpdate) =>
    apiClient.put<GeneralSettings>("/api/settings", data),
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
  status: "pending" | "processing" | "completed" | "failed";
  progress: number;
  current_step: number;
  step_name?: string;
  message: string;
  created_at: string;
  completed_at?: string;
  video_path?: string;
  error?: string;
  request: {
    title: string;
    has_background_music: boolean;
    voice: string;
  };
  files?: Record<string, string>;
}

export interface VideoGenerateRequest {
  title: string;
  systemPrompt?: string;
  textContent: string;
  backgroundMusic?: string;
  generateSubtitle?: boolean;
  subtitleColor?: string;
  subtitleFont?: string;
  voice?: string;
  voiceRate?: string;
  backgroundSource?: string;
  resolutionWidth?: number;
  resolutionHeight?: number;
}

export const videosApi = {
  generate: (data: VideoGenerateRequest) =>
    apiClient.post<{ id: string; task_uuid: string; status: string }>(
      "/api/videos/generate",
      data,
    ),
  list: () => apiClient.get<VideoTask[]>("/api/videos/generate"),
  get: (taskId: string) =>
    apiClient.get<VideoTask>(`/api/videos/generate?taskId=${taskId}`),
  getLog: (taskId: string) =>
    apiClient.get<{ log: string }>(
      `/api/videos/generate?taskId=${taskId}&action=log`,
    ),
  delete: (taskId: string) =>
    apiClient.delete<void>(`/api/videos/generate?taskId=${taskId}`),
};
