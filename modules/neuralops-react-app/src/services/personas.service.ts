import { apiJson } from "./api-client";
import type { Persona, TestResult } from "@/types";

export async function listPersonas(): Promise<Persona[]> {
  return apiJson<Persona[]>("/api/v1/personas/");
}

export async function createPersona(input: Partial<Persona> & { prompt: Persona["prompt"] }): Promise<Persona> {
  return apiJson<Persona>("/api/v1/personas/", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function deletePersona(id: string): Promise<void> {
  await apiJson<void>(`/api/v1/personas/${id}/`, { method: "DELETE" });
}

export async function testPersona(id: string): Promise<TestResult> {
  return apiJson<TestResult>(`/api/v1/personas/${id}/test/`, { method: "POST" });
}
