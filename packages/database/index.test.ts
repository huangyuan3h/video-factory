import { describe, it, expect, vi } from "vitest";

vi.mock("@prisma/client", () => ({
  PrismaClient: vi.fn().mockImplementation(() => ({
    $connect: vi.fn(),
    $disconnect: vi.fn(),
  })),
}));

describe("database", () => {
  it("should export prisma client", async () => {
    const { default: prisma } = await import("./index");
    expect(prisma).toBeDefined();
    expect(typeof prisma.$connect).toBe("function");
    expect(typeof prisma.$disconnect).toBe("function");
  });

  it("should export PrismaClient class", async () => {
    const { PrismaClient } = await import("./index");
    expect(PrismaClient).toBeDefined();
  });
});
