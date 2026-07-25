"""
Schemas for AI Model, Persona, Prompt, and PromptTemplate APIs.
"""
from typing import Optional
from ninja import Schema


# ── AIModel ───────────────────────────────────────────────────────────────────

class AIModelIn(Schema):
    name: str
    provider: str
    model_id: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    secret_ref: Optional[str] = None
    description: Optional[str] = None
    licence_accepted: bool = False
    temperature: float = 0.7
    max_tokens: int = 4096
    context_window: int = 8192
    supports_tools: bool = False
    supports_streaming: bool = True
    supports_vision: bool = False
    supports_audio: bool = False
    config: dict = {}


class AIModelPatchIn(Schema):
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    model_id: Optional[str] = None
    description: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    context_window: Optional[int] = None
    supports_tools: Optional[bool] = None
    supports_vision: Optional[bool] = None
    config: Optional[dict] = None


class AIModelOut(Schema):
    id: str
    name: str
    provider: str
    model_id: str
    api_base: Optional[str] = None
    secret_ref: Optional[str] = None
    description: Optional[str] = None
    licence_accepted: bool
    temperature: float
    max_tokens: int
    context_window: int
    supports_tools: bool
    supports_streaming: bool
    supports_vision: bool
    supports_audio: bool
    config: dict
    is_active: bool
    has_api_key: bool


# ── MCPServer ─────────────────────────────────────────────────────────────────

class MCPServerIn(Schema):
    name: str
    description: Optional[str] = None
    server_type: str = "remote"
    transport: str = "http"
    url: Optional[str] = None
    command: Optional[str] = None
    docker_image: Optional[str] = None
    docker_command: Optional[str] = None
    kubernetes_service: Optional[str] = None
    config: dict = {}
    secret_ref: Optional[str] = None
    timeout_seconds: int = 60
    max_retries: int = 3


class MCPServerOut(Schema):
    id: str
    name: str
    description: Optional[str] = None
    server_type: str
    transport: str
    url: Optional[str] = None
    command: Optional[str] = None
    docker_image: Optional[str] = None
    config: dict
    timeout_seconds: int
    max_retries: int
    is_active: bool


# ── Prompt ────────────────────────────────────────────────────────────────────

class PromptIn(Schema):
    system_prompt: str
    output_type: str = "text"
    context_scope: Optional[list] = None
    template_id: Optional[str] = None


class PromptOut(Schema):
    id: str
    system_prompt: str
    output_type: str
    context_scope: Optional[list] = None
    template_id: Optional[str] = None


# ── Persona ───────────────────────────────────────────────────────────────────

class PersonaIn(Schema):
    name: str
    description: Optional[str] = None
    source_type: str
    model_id: Optional[str] = None
    agent_id: Optional[str] = None
    prompt: PromptIn


class PersonaPatchIn(Schema):
    name: Optional[str] = None
    description: Optional[str] = None
    prompt: Optional[PromptIn] = None


class PersonaOut(Schema):
    id: str
    name: str
    description: Optional[str] = None
    source_type: str
    model_id: Optional[str] = None
    agent_id: Optional[str] = None
    prompt: Optional[PromptOut] = None
    is_active: bool


# ── PromptTemplate ────────────────────────────────────────────────────────────

class PromptTemplateOut(Schema):
    id: str
    title: str
    description: str
    system_prompt: str
    output_type: str
    tags: list
    is_featured: bool


# ── CompanyAIConfig ───────────────────────────────────────────────────────────

# ── AIRequestLog ─────────────────────────────────────────────────────────────

class AIRequestLogOut(Schema):
    id: str
    job_id: str
    msg_id: str
    persona_id: Optional[str] = None
    model_id: str
    provider: str
    prompt: list
    response: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    status: str
    error: Optional[str] = None
    created_at: str


# ── AIAgent ──────────────────────────────────────────────────────────────────

class AgentIn(Schema):
    name: str
    description: Optional[str] = None
    agent_type: str = "internal"          # "internal" | "external"
    model_id: Optional[str] = None        # required for internal
    mcp_server_id: Optional[str] = None   # optional for internal
    external_url: Optional[str] = None    # required for external
    api_key: Optional[str] = None         # optional external auth key
    system_prompt: Optional[str] = None
    safety_mode: bool = True
    max_steps: int = 5
    allow_parallel_tools: bool = False


class AgentOut(Schema):
    id: str
    name: str
    description: Optional[str] = None
    agent_type: str
    model_id: Optional[str] = None
    mcp_server_id: Optional[str] = None
    external_url: Optional[str] = None
    system_prompt: Optional[str] = None
    safety_mode: bool
    max_steps: int
    allow_parallel_tools: bool
    has_api_key: bool
    is_active: bool


# ── Test results ──────────────────────────────────────────────────────────────

class TestResultOut(Schema):
    ok: bool
    response: Optional[str] = None
    tools: list[str] = []
    latency_ms: int = 0
    error: Optional[str] = None


class CompanyAIConfigIn(Schema):
    embedding_provider: str
    embedding_model: str
    embedding_base_url: str = ""
    default_llm_model: str


class CompanyAIConfigOut(Schema):
    embedding_provider: str
    embedding_model: str
    embedding_base_url: str
    default_llm_model: str
