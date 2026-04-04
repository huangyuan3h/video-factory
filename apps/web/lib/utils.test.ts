import { describe, it, expect } from "vitest";
import { cn, formatDate, formatDuration } from "./utils";

describe("utils", () => {
  it("should merge class names with cn", () => {
    const result = cn("text-red-500", "bg-blue-500");
    expect(result).toContain("text-red-500");
    expect(result).toContain("bg-blue-500");
  });

  it("should handle conditional class names", () => {
    const result = cn("base-class", false && "hidden", true && "visible");
    expect(result).toContain("base-class");
    expect(result).toContain("visible");
    expect(result).not.toContain("hidden");
  });

  it("should format date correctly", () => {
    const date = "2024-01-01T12:00:00Z";
    const result = formatDate(date);
    expect(result).toContain("2024");
    expect(result).toContain("01");
  });

  it("should format Date object correctly", () => {
    const date = new Date("2024-01-01T12:00:00Z");
    const result = formatDate(date);
    expect(result).toContain("2024");
  });

  it("should format duration correctly", () => {
    const result = formatDuration(125);
    expect(result).toBe("2:05");
  });

  it("should format duration with zero minutes", () => {
    const result = formatDuration(45);
    expect(result).toBe("0:45");
  });

  it("should format duration with zero seconds", () => {
    const result = formatDuration(120);
    expect(result).toBe("2:00");
  });
});
