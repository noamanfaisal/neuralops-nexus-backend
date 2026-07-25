/**
 * AddAgentForm — /add_agent
 *
 * Agent types:
 *   internal: model + optional MCP server → pydantic-ai + tools
 *   external: external_url + optional API key → HTTP proxy
 *
 * Fields depend on agent_type selection.
 */
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { listAIModels } from "@/services/ai-models.service";
import { listMCPServers } from "@/services/mcp-servers.service";
import { createAgent, testAgent } from "@/services/agents.service";
import type { AIModel, MCPServer, TestResult } from "@/types";
import { Field, Input, Select, Textarea, Row, TestBadge } from "./shared";

const AGENT_TYPES = [
  { value: "internal", label: "Internal (model + MCP tools)" },
  { value: "external", label: "External (HTTP proxy)" },
];

export function AddAgentForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [agentType, setAgentType] = useState<"internal" | "external">("internal");
  const [modelId, setModelId] = useState("");
  const [mcpServerId, setMcpServerId] = useState("");
  const [externalUrl, setExternalUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [models, setModels] = useState<AIModel[]>([]);
  const [mcpServers, setMcpServers] = useState<MCPServer[]>([]);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);

  useEffect(() => {
    listAIModels().then(setModels).catch(() => {});
    listMCPServers().then(setMcpServers).catch(() => {});
  }, []);

  async function handleSave() {
    if (!name) {
      toast.error("Name is required.");
      return;
    }
    if (agentType === "internal" && !modelId) {
      toast.error("Select a model for an internal agent.");
      return;
    }
    if (agentType === "external" && !externalUrl) {
      toast.error("External URL is required for an external agent.");
      return;
    }
    setSaving(true);
    try {
      const agent = await createAgent({
        name,
        description: description || undefined,
        agent_type: agentType,
        model_id: agentType === "internal" ? (modelId || undefined) : undefined,
        mcp_server_id: agentType === "internal" && mcpServerId ? mcpServerId : undefined,
        external_url: agentType === "external" ? externalUrl : undefined,
        api_key: apiKey || undefined,
        system_prompt: systemPrompt || undefined,
        safety_mode: true,
        max_steps: 5,
        allow_parallel_tools: false,
      });
      setSavedId(agent.id);
      toast.success(`Agent "${agent.name}" added.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save agent.");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    if (!savedId) {
      toast.info("Save the agent first, then test it.");
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testAgent(savedId);
      setTestResult(result);
    } catch (err) {
      setTestResult({ ok: false, latency_ms: 0, error: String(err) });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Row>
        <Field label="Name" required>
          <Input
            placeholder="Code Assistant"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="Agent Type" required>
          <Select
            value={agentType}
            onChange={(e) => setAgentType(e.target.value as "internal" | "external")}
          >
            {AGENT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </Select>
        </Field>
      </Row>

      {agentType === "internal" && (
        <Row>
          <Field label="Model" required>
            <Select value={modelId} onChange={(e) => setModelId(e.target.value)}>
              <option value="">— select model —</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </Select>
          </Field>
          <Field label="MCP Server (optional)">
            <Select value={mcpServerId} onChange={(e) => setMcpServerId(e.target.value)}>
              <option value="">— none —</option>
              {mcpServers.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </Select>
          </Field>
        </Row>
      )}

      {agentType === "external" && (
        <Row>
          <Field label="External URL" required>
            <Input
              placeholder="https://api.example.com/agent"
              value={externalUrl}
              onChange={(e) => setExternalUrl(e.target.value)}
            />
          </Field>
          <Field label="API Key (optional)">
            <Input
              type="password"
              placeholder="Bearer token or API key"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </Field>
        </Row>
      )}

      <Field label="System Prompt (optional)">
        <Textarea
          placeholder="You are a helpful coding assistant..."
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
        />
      </Field>

      <Field label="Description (optional)">
        <Input
          placeholder="Brief description of what this agent does"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>

      <TestBadge result={testResult} loading={testing} />

      <div className="flex items-center gap-2 pt-1">
        {savedId ? (
          <Button
            size="sm"
            variant="outline"
            onClick={handleTest}
            disabled={testing}
          >
            {testing ? "Testing…" : "Test"}
          </Button>
        ) : (
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save Agent"}
          </Button>
        )}
        {savedId && (
          <Button size="sm" onClick={onDone}>
            Done
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onDone} className="ml-auto">
          Cancel
        </Button>
      </div>
    </div>
  );
}
