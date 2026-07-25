/**
 * SlashCommandPanel — the inline configuration panel that opens above
 * the message input when the user selects a /add_* or /list_* command.
 */
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AddModelForm } from "./forms/AddModelForm";
import { AddMCPForm } from "./forms/AddMCPForm";
import { AddAgentForm } from "./forms/AddAgentForm";
import { AddPersonaForm } from "./forms/AddPersonaForm";
import { ListCards } from "./forms/ListCards";

export type SlashCommandName =
  | "/add_model"
  | "/add_mcp"
  | "/add_agent"
  | "/add_persona"
  | "/list_models"
  | "/list_mcp"
  | "/list_agents"
  | "/list_personas";

export const CONFIG_COMMANDS: SlashCommandName[] = [
  "/add_model",
  "/add_mcp",
  "/add_agent",
  "/add_persona",
  "/list_models",
  "/list_mcp",
  "/list_agents",
  "/list_personas",
];

interface Props {
  command: SlashCommandName;
  onClose: () => void;
}

export function SlashCommandPanel({ command, onClose }: Props) {
  const title: Record<SlashCommandName, string> = {
    "/add_model": "Add AI Model",
    "/add_mcp": "Add MCP Server",
    "/add_agent": "Add Agent",
    "/add_persona": "Add Persona",
    "/list_models": "AI Models",
    "/list_mcp": "MCP Servers",
    "/list_agents": "Agents",
    "/list_personas": "Personas",
  };

  return (
    <div className="absolute bottom-full left-0 right-0 mb-1 rounded-lg border border-border bg-popover shadow-xl z-50">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <span className="text-xs font-mono text-muted-foreground">{command}</span>
          <h3 className="text-sm font-semibold text-foreground">{title[command]}</h3>
        </div>
        <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Body */}
      <div className="max-h-[420px] overflow-y-auto p-4">
        {command === "/add_model"     && <AddModelForm   onDone={onClose} />}
        {command === "/add_mcp"       && <AddMCPForm     onDone={onClose} />}
        {command === "/add_agent"     && <AddAgentForm   onDone={onClose} />}
        {command === "/add_persona"   && <AddPersonaForm onDone={onClose} />}
        {command === "/list_models"   && <ListCards type="models"   onClose={onClose} />}
        {command === "/list_mcp"      && <ListCards type="mcp"      onClose={onClose} />}
        {command === "/list_agents"   && <ListCards type="agents"   onClose={onClose} />}
        {command === "/list_personas" && <ListCards type="personas" onClose={onClose} />}
      </div>
    </div>
  );
}
