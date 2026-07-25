import { apiJson } from "./api-client";
import type { Agent, TestResult } from "@/types";

export async function listAgents(): Promise<Agent[]> {
  return apiJson<Agent[]>("/api/v1/agents/");
}

export async function getAgent(id: string): Promise<Agent> {
  return apiJson<Agent>(`/api/v1/agents/${id}/`);
}

export async function createAgent(input: Partial<Agent>): Promise<Agent> {
  return apiJson<Agent>("/api/v1/agents/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function deleteAgent(id: string): Promise<void> {
  await apiJson<void>(`/api/v1/agents/${id}/`, { method: "DELETE" });
}

export async function testAgent(id: string): Promise<TestResult> {
  return apiJson<TestResult>(`/api/v1/agents/${id}/test/`, { method: "POST" });
}
