import { apiJson } from "./api-client";
import type { AIModel, TestResult } from "@/types";

export async function listAIModels(): Promise<AIModel[]> {
  return apiJson<AIModel[]>("/api/v1/ai-models/");
}

export async function createAIModel(input: Partial<AIModel>): Promise<AIModel> {
  return apiJson<AIModel>("/api/v1/ai-models/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function deleteAIModel(id: string): Promise<void> {
  await apiJson<void>(`/api/v1/ai-models/${id}/`, { method: "DELETE" });
}

export async function testAIModel(id: string): Promise<TestResult> {
  return apiJson<TestResult>(`/api/v1/ai-models/${id}/test/`, { method: "POST" });
}
