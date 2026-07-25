/**
 * AddMCPForm — /add_mcp
 *
 * Fields:
 *   Name, Transport, URL (http/sse), Command (stdio), Description
 *   [Test] → /mcp-servers/{id}/test/ — shows list of tools found
 *   [Save]
 */
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { createMCPServer, testMCPServer } from "@/services/mcp-servers.service";
import type { TestResult } from "@/types";
import { Field, Input, Select, Textarea, Row, TestBadge } from "./shared";

const TRANSPORTS = [
  { value: "http",  label: "HTTP (Streamable)" },
  { value: "sse",   label: "SSE" },
  { value: "stdio", label: "STDIO (local command)" },
];

const SERVER_TYPES = [
  { value: "remote",     label: "Remote" },
  { value: "local",      label: "Local" },
  { value: "docker",     label: "Docker" },
  { value: "kubernetes", label: "Kubernetes" },
  { value: "hosted",     label: "Hosted / Online" },
];

export function AddMCPForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [transport, setTransport] = useState("http");
  const [serverType, setServerType] = useState("remote");
  const [url, setUrl] = useState("");
  const [command, setCommand] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);

  const isStdio = transport === "stdio";

  async function handleSave() {
    if (!name) {
      toast.error("Name is required.");
      return;
    }
    if (isStdio && !command) {
      toast.error("Command is required for STDIO transport.");
      return;
    }
    if (!isStdio && !url) {
      toast.error("URL is required for HTTP/SSE transport.");
      return;
    }
    setSaving(true);
    try {
      const server = await createMCPServer({
        name,
        description: description || undefined,
        transport,
        server_type: serverType,
        url: !isStdio ? url : undefined,
        command: isStdio ? command : undefined,
        timeout_seconds: 60,
        max_retries: 3,
        config: {},
      });
      setSavedId(server.id);
      toast.success(`MCP server "${server.name}" added.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save MCP server.");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    if (!savedId) {
      toast.info("Save the MCP server first, then test it.");
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testMCPServer(savedId);
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
            placeholder="GitHub MCP"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field label="Transport" required>
          <Select
            value={transport}
            onChange={(e) => setTransport(e.target.value)}
          >
            {TRANSPORTS.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </Select>
        </Field>
      </Row>

      <Row>
        <Field label="Server Type">
          <Select
            value={serverType}
            onChange={(e) => setServerType(e.target.value)}
          >
            {SERVER_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </Select>
        </Field>
        {isStdio ? (
          <Field label="Command" required>
            <Input
              placeholder="npx -y @github/mcp"
              value={command}
              onChange={(e) => setCommand(e.target.value)}
            />
          </Field>
        ) : (
          <Field label="URL" required>
            <Input
              placeholder="https://mcp.example.com/sse"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </Field>
        )}
      </Row>

      <Field label="Description">
        <Textarea
          placeholder="What does this MCP server do?"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
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
            {saving ? "Saving…" : "Save MCP Server"}
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
