import { describe, it, expect } from "vitest";
import type {
  AISettings,
  SourceConfig,
  Task,
  Run,
  PublisherAccount,
  VideoOptions,
  ApiResponse,
  PaginatedResponse,
} from "./types";
import {
  isValidSourceType,
  isValidPlatform,
  isValidRunStatus,
  isValidAssetType,
} from "./types";

describe("types", () => {
  describe("validation functions", () => {
    it("should validate source type correctly", () => {
      expect(isValidSourceType("rss")).toBe(true);
      expect(isValidSourceType("news_api")).toBe(true);
      expect(isValidSourceType("hot_topics")).toBe(true);
      expect(isValidSourceType("custom")).toBe(true);
      expect(isValidSourceType("invalid")).toBe(false);
    });

    it("should validate platform correctly", () => {
      expect(isValidPlatform("douyin")).toBe(true);
      expect(isValidPlatform("xiaohongshu")).toBe(true);
      expect(isValidPlatform("wechat_video")).toBe(true);
      expect(isValidPlatform("bilibili")).toBe(true);
      expect(isValidPlatform("invalid")).toBe(false);
    });

    it("should validate run status correctly", () => {
      expect(isValidRunStatus("pending")).toBe(true);
      expect(isValidRunStatus("processing")).toBe(true);
      expect(isValidRunStatus("completed")).toBe(true);
      expect(isValidRunStatus("failed")).toBe(true);
      expect(isValidRunStatus("invalid")).toBe(false);
    });

    it("should validate asset type correctly", () => {
      expect(isValidAssetType("music")).toBe(true);
      expect(isValidAssetType("video")).toBe(true);
      expect(isValidAssetType("invalid")).toBe(false);
    });
  });
  it("should define AISettings type correctly", () => {
    const aiSettings: AISettings = {
      id: "1",
      name: "Test AI",
      baseUrl: "https://api.test.com",
      apiKey: "test-key",
      modelId: "test-model",
      temperature: 0.7,
      maxTokens: 1000,
      isActive: true,
    };
    expect(aiSettings.id).toBe("1");
    expect(aiSettings.name).toBe("Test AI");
  });

  it("should define SourceConfig type correctly", () => {
    const source: SourceConfig = {
      id: "1",
      type: "rss",
      name: "Test RSS",
      url: "https://test.com/rss",
      enabled: true,
      createdAt: "2024-01-01",
      updatedAt: "2024-01-01",
    };
    expect(source.type).toBe("rss");
    expect(source.enabled).toBe(true);
  });

  it("should define Task type correctly", () => {
    const task: Task = {
      id: "1",
      name: "Test Task",
      sourceId: "1",
      schedule: "0 * * * *",
      enabled: true,
      createdAt: "2024-01-01",
      updatedAt: "2024-01-01",
    };
    expect(task.name).toBe("Test Task");
    expect(task.schedule).toBe("0 * * * *");
  });

  it("should define Run type correctly", () => {
    const run: Run = {
      id: "1",
      taskId: "1",
      status: "completed",
      createdAt: "2024-01-01",
    };
    expect(run.status).toBe("completed");
  });

  it("should define PublisherAccount type correctly", () => {
    const account: PublisherAccount = {
      id: "1",
      platform: "douyin",
      name: "Test Account",
      enabled: true,
      createdAt: "2024-01-01",
    };
    expect(account.platform).toBe("douyin");
  });

  it("should define VideoOptions type correctly", () => {
    const options: VideoOptions = {
      voice: "zh-CN-XiaoxiaoNeural",
      resolution: "1080p",
      fps: 30,
    };
    expect(options.resolution).toBe("1080p");
    expect(options.fps).toBe(30);
  });

  it("should define ApiResponse type correctly", () => {
    const response: ApiResponse<string> = {
      success: true,
      data: "test",
    };
    expect(response.success).toBe(true);
    expect(response.data).toBe("test");
  });

  it("should define PaginatedResponse type correctly", () => {
    const response: PaginatedResponse<string> = {
      items: ["a", "b", "c"],
      total: 3,
      page: 1,
      pageSize: 10,
    };
    expect(response.items.length).toBe(3);
    expect(response.total).toBe(3);
  });
});
