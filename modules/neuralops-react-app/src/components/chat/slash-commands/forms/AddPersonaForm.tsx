/**
 * AddPersonaForm — /add_persona
 *
 * Persona wraps either a Model or an Agent and exposes it as a chat participant.
 *
 * source_type = "model"  → pick a model
 * source_type = "agent"  → pick an agent
 *
 * Required: system prompt (creates a Prompt record linked to the persona)
 */
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { listAIModels } from "@/services/ai-models.service";
import { listAgents } from "@/services/agents.service";
import { createPersona, testPersona } from "@/services/personas.service";
import type { AIModel, Agent, TestResult } from "@/types";
import { Field, Input, Select, Textarea, Row, TestBadge } from "./shared";

const SOURCE_TYPES = [
  { value: "model", label: "Plain Model" },
  { value: "agent", label: "Agent (with tools)" },
];

const OUTPUT_TYPES = [
  { value: "auto",     label: "Auto (AI decides)" },
  { value: "text",     label: "Text" },
  { value: "code",     label: "Code" },
  { value: "html",     label: "HTML Page" },
  { value: "form",     label: "Interactive Form" },
  { value: "chart",    label: "Chart" },
  { value: "table",    label: "Table" },
  { value: "diagram",  label: "Diagram" },
  { value: "terminal", label: "Terminal" },
];

export function AddPersonaForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [sourceType, setSourceType] = useState<"model" | "agent">("model");
  const [modelId, setModelId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [outputType, setOutputType] = useState("auto");
  const [models, setModels] = useState<AIModel[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);

  useEffect(() => {
    listAIModels().then(setModels).catch(() => {});
    listAgents().then(setAgents).catch(() => {});
  }, []);

  async function handleSave() {
    if (!name) {
      toast.error("Name is required.");
      return;
    }
    if (!systemPrompt) {
      toast.error("System prompt is required.");
      return;
    }
    if (sourceType === "model" && !modelId) {
      toast.error("Select a model.");
      return;
    }
    if (sourceType === "agent" && !agentId) {
      toast.error("Select an agent.");
      return;
    }
    setSaving(true);
    try {
      const persona = await createPersona({
        name,
        description: description || undefined,
        source_type: sourceType,
        model_id: sourceType === "model" ? modelId : undefined,
        agent_id: sourceType === "agent" ? agentId : undefined,
        prompt: {
          id: "",
          system_prompt: systemPrompt,
          output_type: outputType,
        },
      });
      setSavedId(persona.id);
      toast.success(`Persona "${persona.name}" created. Use @${persona.name} in chat.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create persona.");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    if (!savedId) {
      toast.info("Save the persona first, then test it.");
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testPersona(savedId);
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
        <Field label="Persona Name" required>
          <Input
            placeholder="Aria (use in chat as @Aria)"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="Source Type" required>
          <Select
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value as "model" | "agent")}
          >
            {SOURCE_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </Select>
        </Field>
      </Row>

      <Row>
        {sourceType === "model" ? (
          <Field label="Model" required>
            <Select value={modelId} onChange={(e) => setModelId(e.target.value)}>
              <option value="">— select model —</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </Select>
          </Field>
        ) : (
          <Field label="Agent" required>
            <Select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
              <option value="">— select agent —</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </Select>
          </Field>
        )}
        <Field label="Default Output Type">
          <Select value={outputType} onChange={(e) => setOutputType(e.target.value)}>
            {OUTPUT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </Select>
        </Field>
      </Row>

      <Field label="System Prompt" required>
        <Textarea
          placeholder="You are Aria, a friendly AI assistant..."
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          rows={4}
        />
      </Field>

      <Field label="Description (optional)">
        <Input
          placeholder="What does this persona do?"
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
            {saving ? "Saving…" : "Save Persona"}
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
