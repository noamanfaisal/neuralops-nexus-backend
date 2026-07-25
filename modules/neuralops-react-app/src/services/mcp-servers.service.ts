import { apiJson } from "./api-client";
import type { MCPServer, TestResult } from "@/types";

export async function listMCPServers(): Promise<MCPServer[]> {
  return apiJson<MCPServer[]>("/api/v1/mcp-servers/");
}

export async function createMCPServer(input: Partial<MCPServer>): Promise<MCPServer> {
  return apiJson<MCPServer>("/api/v1/mcp-servers/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function deleteMCPServer(id: string): Promise<void> {
  await apiJson<void>(`/api/v1/mcp-servers/${id}/`, { method: "DELETE" });
}

export async function testMCPServer(id: string): Promise<TestResult> {
  return apiJson<TestResult>(`/api/v1/mcp-servers/${id}/test/`, { method: "POST" });
}
