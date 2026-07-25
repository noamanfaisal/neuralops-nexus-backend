/**
 * AddModelForm — /add_model
 *
 * Fields:
 *   Name, Provider, Model ID, API Key, API Base (optional), Temperature, Max Tokens
 *   Licence checkbox
 *   [Test] → hits /ai-models/{id}/test/ after save
 *   [Save]
 */
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { createAIModel, testAIModel } from "@/services/ai-models.service";
import type { AIModel, TestResult } from "@/types";
import { Field, Input, Select, Row, TestBadge } from "./shared";

const PROVIDERS = [
  { value: "litellm", label: "LiteLLM (cloud / hosted)" },
  { value: "local",   label: "Local (Ollama / ONNX)" },
];

// Common model shortcuts
const MODEL_PRESETS: Record<string, string[]> = {
  litellm: [
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-haiku-4-5-20251001",
    "gemini/gemini-1.5-pro",
  ],
  local: [
    "ollama/llama3.2:3b",
    "ollama/llama3.1:8b",
    "ollama/mistral",
    "ollama/phi3",
  ],
};

export function AddModelForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("litellm");
  const [modelId, setModelId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [temperature, setTemperature] = useState("0.7");
  const [maxTokens, setMaxTokens] = useState("4096");
  const [licenceAccepted, setLicenceAccepted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);

  async function handleSave() {
    if (!name || !modelId) {
      toast.error("Name and Model ID are required.");
      return;
    }
    if (!licenceAccepted) {
      toast.error("You must accept the provider's terms of service.");
      return;
    }
    setSaving(true);
    try {
      const model = await createAIModel({
        name,
        provider,
        model_id: modelId,
        api_key: apiKey || undefined,
        api_base: apiBase || undefined,
        temperature: parseFloat(temperature),
        max_tokens: parseInt(maxTokens),
        licence_accepted: licenceAccepted,
        supports_streaming: true,
      } as Partial<AIModel>);
      setSavedId(model.id);
      toast.success(`Model "${model.name}" added.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save model.");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    if (!savedId) {
      toast.info("Save the model first, then test it.");
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testAIModel(savedId);
      setTestResult(result);
    } catch (err) {
      setTestResult({ ok: false, latency_ms: 0, error: String(err) });
    } finally {
      setTesting(false);
    }
  }

  const presets = MODEL_PRESETS[provider] ?? [];

  return (
    <div className="flex flex-col gap-4">
      <Row>
        <Field label="Name" required>
          <Input
            placeholder="GPT-4o Mini"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="Provider" required>
          <Select
            value={provider}
            onChange={(e) => { setProvider(e.target.value); setModelId(""); }}
          >
            {PROVIDERS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </Select>
        </Field>
      </Row>

      <Field label="Model ID" required>
        <Input
          placeholder={provider === "local" ? "ollama/llama3.2:3b" : "openai/gpt-4o-mini"}
          value={modelId}
          onChange={(e) => setModelId(e.target.value)}
        />
        {presets.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {presets.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setModelId(p)}
                className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                {p}
              </button>
            ))}
          </div>
        )}
      </Field>

      <Row>
        <Field label="API Key">
          <Input
            type="password"
            placeholder={provider === "local" ? "(not needed for local)" : "sk-..."}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
        </Field>
        <Field label="API Base URL">
          <Input
            placeholder={provider === "local" ? "http://ollama:11434/v1" : "(optional)"}
            value={apiBase}
            onChange={(e) => setApiBase(e.target.value)}
          />
        </Field>
      </Row>

      <Row>
        <Field label="Temperature">
          <Input
            type="number"
            min="0"
            max="2"
            step="0.1"
            value={temperature}
            onChange={(e) => setTemperature(e.target.value)}
          />
        </Field>
        <Field label="Max Tokens">
          <Input
            type="number"
            min="256"
            max="131072"
            step="256"
            value={maxTokens}
            onChange={(e) => setMaxTokens(e.target.value)}
          />
        </Field>
      </Row>

      <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
        <input
          type="checkbox"
          checked={licenceAccepted}
          onChange={(e) => setLicenceAccepted(e.target.checked)}
          className="rounded border-input"
        />
        I accept this provider's terms of service
      </label>

      <TestBadge result={testResult} loading={testing} />

      <div className="flex items-center gap-2 pt-1">
        {savedId ? (
          <Button
            size="sm"
            variant="outline"
            onClick={handleTest}
            disabled={testing}
            className="gap-1.5"
          >
            {testing ? "Testing…" : "Test"}
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={handleSave}
            disabled={saving}
            className="gap-1.5"
          >
            {saving ? "Saving…" : "Save Model"}
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
