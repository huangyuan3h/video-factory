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
      'Content-Type': 'application/json',
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

  async request<T>(path: string, options: RequestOptions = {}): Promise<ApiResponse<T>> {
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
        error: error instanceof Error ? error.message : 'Network error',
      };
    }
  }

  async get<T>(path: string, params?: Record<string, string>): Promise<ApiResponse<T>> {
    return this.request<T>(path, { method: 'GET', params });
  }

  async post<T>(path: string, body?: unknown): Promise<ApiResponse<T>> {
    return this.request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  async put<T>(path: string, body?: unknown): Promise<ApiResponse<T>> {
    return this.request<T>(path, {
      method: 'PUT',
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  async delete<T>(path: string): Promise<ApiResponse<T>> {
    return this.request<T>(path, { method: 'DELETE' });
  }
}

export const apiClient = new ApiClient();

// AI Settings API
export const aiSettingsApi = {
  list: () => apiClient.get<AISetting[]>('/api/ai-settings'),
  getActive: () => apiClient.get<AISetting>('/api/ai-settings/active'),
  create: (data: AISettingCreate) => apiClient.post<AISetting>('/api/ai-settings', data),
  update: (id: string, data: AISettingUpdate) => apiClient.put<AISetting>(`/api/ai-settings/${id}`, data),
  activate: (id: string) => apiClient.post<AISetting>(`/api/ai-settings/${id}/activate`),
  delete: (id: string) => apiClient.delete<void>(`/api/ai-settings/${id}`),
  test: (id: string) => apiClient.post<TestResult>(`/api/ai-settings/${id}/test`),
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