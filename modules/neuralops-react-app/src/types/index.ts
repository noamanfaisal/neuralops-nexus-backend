// Shared types used across services. Refine as the Django API solidifies.

export interface Company {
  id: string;
  name: string;
  slug?: string;
}

export interface User {
  id: string;
  email: string;
  display_name?: string;
  avatar_url?: string;
}

export interface Project {
  id: string;
  company_id: string;
  name: string;
  description?: string;
}

export interface Channel {
  id: string;
  project_id: string;
  name: string;
}

export interface Topic {
  id: string;
  channel_id: string;
  title: string;
  updated_at?: string;
}

export interface Message {
  id: string;
  topic_id: string;
  role: "user" | "assistant" | "agent" | "system";
  content: string;
  author_id?: string;
  created_at?: string;
}

// ── Intelligence types ────────────────────────────────────────────────────────

export interface AIModel {
  id: string;
  name: string;
  provider: string;
  model_id: string;
  api_base?: string;
  api_key?: string;           // write-only (never returned)
  secret_ref?: string;
  description?: string;
  licence_accepted: boolean;
  temperature: number;
  max_tokens: number;
  context_window: number;
  supports_tools: boolean;
  supports_streaming: boolean;
  supports_vision: boolean;
  supports_audio: boolean;
  config: Record<string, unknown>;
  is_active: boolean;
  has_api_key: boolean;
}

export interface MCPServer {
  id: string;
  name: string;
  description?: string;
  server_type: string;
  transport: string;
  url?: string;
  command?: string;
  docker_image?: string;
  config: Record<string, unknown>;
  timeout_seconds: number;
  max_retries: number;
  is_active: boolean;
}

export interface Agent {
  id: string;
  name: string;
  description?: string;
  agent_type: "internal" | "external";
  model_id?: string;
  mcp_server_id?: string;
  external_url?: string;
  api_key?: string;           // write-only
  system_prompt?: string;
  safety_mode: boolean;
  max_steps: number;
  allow_parallel_tools: boolean;
  has_api_key: boolean;
  is_active: boolean;
}

export interface Persona {
  id: string;
  name: string;
  description?: string;
  source_type: "model" | "agent";
  model_id?: string;
  agent_id?: string;
  prompt?: {
    id: string;
    system_prompt: string;
    output_type: string;
    context_scope?: string[];
    template_id?: string;
  };
  is_active: boolean;
}

export interface TestResult {
  ok: boolean;
  response?: string;
  tools?: string[];
  latency_ms: number;
  error?: string;
}

// ── Other types ───────────────────────────────────────────────────────────────

export interface KnowledgeItem {
  id: string;
  title: string;
  content?: string;
}

export interface Notification {
  id: string;
  title: string;
  body?: string;
  read: boolean;
  created_at?: string;
}

export interface ServerEntry {
  id: string;
  name: string;
  url: string;
  lastConnected?: number;
}
