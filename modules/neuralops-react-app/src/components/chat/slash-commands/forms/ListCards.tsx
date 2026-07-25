/**
 * ListCards — renders a list of configured resources for /list_* commands.
 *
 * Supports: models, mcp, agents, personas
 * Shows name, type, status indicators.
 * Has a delete button per item.
 */
import { useEffect, useState } from "react";
import { Trash2, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { listAIModels, deleteAIModel, testAIModel } from "@/services/ai-models.service";
import { listMCPServers, deleteMCPServer, testMCPServer } from "@/services/mcp-servers.service";
import { listAgents, deleteAgent, testAgent } from "@/services/agents.service";
import { listPersonas, deletePersona, testPersona } from "@/services/personas.service";
import type { AIModel, MCPServer, Agent, Persona, TestResult } from "@/types";

type ListType = "models" | "mcp" | "agents" | "personas";

interface Props {
  type: ListType;
  onClose: () => void;
}

type Item = { id: string; name: string; subtitle?: string; badge?: string };

function toBadge(item: AIModel | MCPServer | Agent | Persona): string {
  if ("provider" in item) return (item as AIModel).provider;
  if ("transport" in item) return (item as MCPServer).transport;
  if ("agent_type" in item) return (item as Agent).agent_type;
  if ("source_type" in item) return (item as Persona).source_type;
  return "";
}

function toSubtitle(item: AIModel | MCPServer | Agent | Persona): string {
  if ("model_id" in item && "provider" in item) return (item as AIModel).model_id;
  if ("url" in item && "transport" in item) return (item as MCPServer).url ?? (item as MCPServer).command ?? "";
  if ("external_url" in item && "agent_type" in item) {
    const a = item as Agent;
    return a.agent_type === "external" ? (a.external_url ?? "") : `model + ${a.mcp_server_id ? "MCP" : "no MCP"}`;
  }
  if ("source_type" in item) {
    const p = item as Persona;
    return p.source_type === "model" ? "model persona" : "agent persona";
  }
  return "";
}

export function ListCards({ type, onClose }: Props) {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        let raw: (AIModel | MCPServer | Agent | Persona)[] = [];
        if (type === "models")   raw = await listAIModels();
        if (type === "mcp")      raw = await listMCPServers();
        if (type === "agents")   raw = await listAgents();
        if (type === "personas") raw = await listPersonas();

        setItems(raw.map((r) => ({
          id: r.id,
          name: r.name,
          subtitle: toSubtitle(r),
          badge: toBadge(r),
        })));
      } catch {
        toast.error("Failed to load list.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [type]);

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete "${name}"?`)) return;
    try {
      if (type === "models")   await deleteAIModel(id);
      if (type === "mcp")      await deleteMCPServer(id);
      if (type === "agents")   await deleteAgent(id);
      if (type === "personas") await deletePersona(id);
      setItems((prev) => prev.filter((i) => i.id !== id));
      toast.success(`Deleted "${name}".`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed.");
    }
  }

  async function handleTest(id: string) {
    setTestingId(id);
    try {
      let result: TestResult = { ok: false, latency_ms: 0 };
      if (type === "models")   result = await testAIModel(id);
      if (type === "mcp")      result = await testMCPServer(id);
      if (type === "agents")   result = await testAgent(id);
      if (type === "personas") result = await testPersona(id);
      setTestResults((prev) => ({ ...prev, [id]: result }));
    } catch (err) {
      setTestResults((prev) => ({ ...prev, [id]: { ok: false, latency_ms: 0, error: String(err) } }));
    } finally {
      setTestingId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Loading…
      </div>
    );
  }

  if (items.length === 0) {
    const labels: Record<ListType, string> = {
      models: "models",
      mcp: "MCP servers",
      agents: "agents",
      personas: "personas",
    };
    return (
      <div className="py-8 text-center text-sm text-muted-foreground">
        No {labels[type]} yet. Use{" "}
        <code className="rounded bg-muted px-1 py-0.5 text-xs">
          /add_{type === "mcp" ? "mcp" : type.slice(0, -1)}
        </code>{" "}
        to add one.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {items.map((item) => {
        const result = testResults[item.id];
        const isTesting = testingId === item.id;
        return (
          <div
            key={item.id}
            className="rounded-md border border-border bg-card p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground truncate">
                    {item.name}
                  </span>
                  {item.badge && (
                    <span className="shrink-0 rounded-full border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {item.badge}
                    </span>
                  )}
                </div>
                {item.subtitle && (
                  <p className="mt-0.5 text-xs text-muted-foreground truncate">
                    {item.subtitle}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {result && (
                  result.ok
                    ? <CheckCircle2 className="h-4 w-4 text-green-500" />
                    : <XCircle className="h-4 w-4 text-destructive" />
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2 text-xs"
                  onClick={() => handleTest(item.id)}
                  disabled={isTesting}
                >
                  {isTesting
                    ? <Loader2 className="h-3 w-3 animate-spin" />
                    : "Test"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                  onClick={() => handleDelete(item.id, item.name)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
            {result && !result.ok && result.error && (
              <p className="mt-1.5 text-[11px] font-mono text-destructive line-clamp-2">
                {result.error}
              </p>
            )}
            {result && result.ok && result.response && (
              <p className="mt-1.5 text-[11px] text-muted-foreground line-clamp-1">
                "{result.response}"
              </p>
            )}
            {result && result.ok && result.tools && result.tools.length > 0 && (
              <p className="mt-1.5 text-[11px] text-muted-foreground">
                Tools: {result.tools.join(", ")}
              </p>
            )}
          </div>
        );
      })}
      <div className="pt-1 flex justify-end">
        <Button size="sm" variant="ghost" onClick={onClose}>Close</Button>
      </div>
    </div>
  );
}
