# NeuralOps — Master Strategy

> Single source of truth for all architectural and build decisions.
> Last updated: 2025

---

## 1. What NeuralOps Is

A multi-tenant AI platform where teams can:
- Chat in topics with human members, AI personas, and agents
- Get AI responses in 6 structured output formats
- Connect knowledge bases and MCP servers to agents
- Run agents as background tasks with real-time streaming output

---

## 2. Tech Stack — Final Decisions

### Backend
| Layer | Technology |
|---|---|
| API framework | Django 5.2 + Django Ninja |
| Database | PostgreSQL (UUID PKs, soft delete) |
| Auth | Supabase (JWT) — backend validates, frontend never touches Supabase directly |
| Real-time | Centrifuge via nexus-transport (Go) — frontend never connects to Centrifuge directly |
| Background tasks | Celery + Redis |
| Vector DB | ChromaDB |
| LLM abstraction | LiteLLM (OpenAI, Anthropic, Ollama, Azure, local) |
| Multi-tenancy | All queries scoped to `request.auth.current_company` |
| Soft delete | `is_active=False` + `deleted_at` — never hard delete user content |

### Frontend
| Layer | Technology |
|---|---|
| Framework | Next.js 15 (App Router) |
| Styling | Tailwind CSS + shadcn/ui |
| Server state | TanStack Query |
| Client state | Zustand |
| Auth | Custom fetch to Django Ninja — no Supabase JS client |
| Streaming | Native EventSource (SSE) — no WebSocket library |
| Text/Markdown | react-markdown |
| Code output | shiki |
| Graph output | Chart.js (react-chartjs-2) |
| Terminal output | xterm.js |
| Form output | Custom form renderer |
| Web output | Sandboxed iframe |

### Architecture Rule
> **Frontend talks to one server only: Django Ninja (nexus-nucleus).**
> Django Ninja handles everything internally — Supabase auth, Centrifuge publishing, Celery dispatch.
> Frontend never touches Supabase, Centrifuge, Celery, ChromaDB, or any external service directly.

---

## 3. The 6 Output Types

AI responses are not plain text. Every message has a `message_type` that tells the frontend which renderer to use.

| Type | message_type | Renderer | Streams? | Description |
|---|---|---|---|---|
| Text | `text` | react-markdown | Yes | Standard markdown AI response |
| Code | `code` | shiki | Yes — highlights on complete | Syntax-highlighted code block with copy button |
| Graph | `graph` | Chart.js | No — renders on complete JSON | Bar, line, pie, radar charts from structured data |
| Terminal | `terminal` | xterm.js | Yes — line by line | Command output, logs, shell responses |
| Form | `form` | Custom renderer | No | Interactive form user fills and submits back |
| Web | `web` | Sandboxed iframe | No | Generated HTML or URL rendered in sandbox |

### How the format is selected

The user requests a format explicitly ("show as chart", "give me a form") OR the agent decides based on tool output. The backend appends a format instruction to the model prompt:

```python
FORMAT_PROMPTS = {
    "text":     "Respond in plain markdown.",
    "code":     "Return code only in a fenced block with the language specified.",
    "graph":    "Return JSON only: { chart_type, labels, datasets[] }",
    "terminal": "Return the command output only, plain text, no explanation.",
    "form":     "Return JSON only: { fields: [{ name, type, label, options? }] }",
    "web":      "Return valid HTML only. No markdown. No explanation.",
}
```

The structured output is saved in `ChatMessage.content_json`. The `message_type` field tells the frontend which renderer to use.

---

## 4. Model Strategy — Handling Changes During Development

### Locked models (do not restructure)
These are migrated and stable. Add fields, don't rename or remove.

```
User, Company, CompanyAccess
Project, Channel, ChatTopic
ChatMessage, ChatReaction, ChatAttachment
KnowledgeBase, KnowledgeFile, KnowledgeChunk
AIAgent, AIModel, MCPServer, Persona
AgentRun, EmbeddingJob, VectorDocument
AuditEvent, Notification, SearchLog
```

### Proposed models (not yet migrated — expect changes)
These are documented but not in migrations. Shape may change before migration.

```
MessageBlock       — content blocks for form/graph/code in messages
AgentRunStep       — individual steps within an agent run
AgentRunLog        — logs from agent execution
Role               — RBAC role definition
Permission         — RBAC permission definition
RolePermission     — M2M through table
TopicParticipant   — already migrated in latest code (check migrations)
```

### Rule for model changes during development

1. **Before migration exists**: change freely, document the change in the relevant api .md file
2. **After migration exists**: never rename a field or table — add new fields, deprecate old ones
3. **When in doubt**: add a field with `null=True, blank=True` first — you can make it required later
4. **Never delete a migration file** — squash only, never delete

### Adding a field during development

```python
# Safe — nullable first
new_field = models.CharField(max_length=100, null=True, blank=True)

# Then once code is using it consistently, make it required in a second migration
new_field = models.CharField(max_length=100)
```

---

## 5. Build Order — Backend First

### Phase 1 — Foundation (nothing else works without this)
```
Auth endpoints (login, signup, invite, refresh, logout)
Companies (create, switch, members)
Users (profile, current user)
```
Done condition: Supabase JWT validates, `current_company` scopes queries correctly.

### Phase 2 — Workspace structure
```
Projects (CRUD)
Channels (CRUD)
Topics (CRUD)
```
Done condition: left sidebar can be populated from real API data.

### Phase 3 — Core demo (the "wow" moment)
```
Messages (list, create, delete)
AI Models (CRUD — connect LiteLLM)
Agents (CRUD, run, cancel)
Streaming (SSE — chunks flow from agent → Django → frontend)
```
Done condition: user sends a message, agent responds, response streams in real time.

### Phase 4 — Rich output
```
Output format system (text, code, graph, terminal, form, web)
Personas (CRUD, clone)
Participants (add human, persona, agent to topic)
```
Done condition: agent can return a chart, a form, a terminal command.

### Phase 5 — Knowledge & Search
```
Knowledge Bases (CRUD, attach to project)
Knowledge Files (upload, embed, chunk)
Search (semantic, keyword, federated)
```
Done condition: agent can answer questions from uploaded documents.

### Phase 6 — Everything else
```
Uploads, MCP Servers, RBAC, Audit, Notifications, Admin
```

---

## 6. Frontend Build Order — Lovable + Claude

### What Lovable builds (~70% of UI)
- Auth screens (login, signup, invite)
- App shell (sidebar layout, top bar, navigation)
- Settings pages (company, profile, team)
- CRUD forms (create project, channel, agent, model, persona, KB)
- Notifications panel
- Admin pages
- Knowledge base management pages

### What Claude writes (~30% of UI — the hard parts)
- Auth service layer (fetch to Django Ninja, token management)
- SSE streaming hook (`useStream`)
- Chat message list with virtual scrolling
- 6 output renderers (Text, Code, Graph, Terminal, Form, Web)
- Zustand store (active topic, streaming state, unread counts)
- All `/services` files (API call functions)

### Lovable handoff instructions (give this to Lovable before generating anything)

```
Build a Next.js 15 App Router project with Tailwind CSS and shadcn/ui.

Theme: dark, professional, sidebar-based. Similar feel to Linear or Slack.
No light mode needed initially.

Project structure rules — non-negotiable:
- All API calls go in /src/services/ folder
- One file per domain: auth.service.ts, messages.service.ts, topics.service.ts, etc.
- No fetch() calls inside components or hooks
- Components call service functions only
- Use TanStack Query for all server data fetching
- Auth token stored in Zustand authStore, auto-attached to every request
- Base API URL from environment variable: NEXT_PUBLIC_API_URL

Pages to generate:
1. /login — email + password form
2. /signup — name, email, password
3. /invite/[token] — accept invitation screen
4. /app — main layout with left sidebar + right content area
5. /app/settings/company — company settings
6. /app/settings/profile — user profile
7. /app/settings/team — team members list
8. /app/settings/ai-models — AI model configurations
9. /app/settings/agents — agent list and config
10. /app/settings/personas — persona list
11. /app/settings/mcp-servers — MCP server list
12. /app/settings/knowledge — knowledge base management
13. /app/admin — admin dashboard (staff only)

Left sidebar structure:
- Company name + switcher at top
- Project list (expandable)
  - Each project shows channels
  - Each channel shows topics
  - + button to add topic
- Bottom: settings, profile, notifications

Main content area:
- Shows chat topic when topic selected
- Shows settings pages when settings selected
- Chat area has: message list (top), message input (bottom)
- Message input has: text area, send button, attach button, format selector

Leave the following as empty placeholder components — do not implement:
- ChatMessageList — I will implement this
- ChatMessageItem — I will implement this
- StreamingIndicator — I will implement this
- All output renderers (TextRenderer, CodeRenderer, GraphRenderer, etc.)
- All /services/*.ts files — generate empty shells with function signatures only

Generate TypeScript throughout. No JavaScript files.
```

---

## 7. What to Give Lovable for Each Window

### Auth screens
Give Lovable this:
```
POST /api/v1/auth/login     { email, password } → { token, user }
POST /api/v1/auth/signup    { name, email, password } → { token, user }
GET  /api/v1/auth/invite/[token] → { company_name, inviter_name, email }
POST /api/v1/auth/invite/[token]/accept { password } → { token, user }
```

### Left sidebar
Give Lovable this:
```
GET /api/v1/projects → [{ id, name, slug }]
GET /api/v1/projects/{id}/channels → [{ id, name, slug }]
GET /api/v1/channels/{id}/topics → [{ id, title, slug, unread_count }]
```

### Settings pages
Give Lovable the relevant endpoint request/response shapes from the api docs.

### What NOT to give Lovable
- Streaming endpoints
- Message rendering logic
- Output format structures
- Anything involving SSE or WebSocket

---

## 8. SSE Streaming — How It Works

Frontend never connects to Centrifuge. All streaming goes through Django Ninja.

```
User sends message
      ↓
POST /api/v1/topics/{id}/messages  { content, trigger_agent: true }
      ↓
Django creates ChatMessage(status=pending)
Django creates AgentRun → dispatches to Celery
      ↓
Frontend opens SSE connection:
GET /api/v1/stream/messages/{message_id}
      ↓
Django Ninja yields chunks as agent produces them:
  data: {"type": "chunk", "content": "Based on"}
  data: {"type": "chunk", "content": " your knowledge base..."}
  data: {"type": "done", "message_type": "text"}
      ↓
Frontend appends chunks to message content
On "done" event: close SSE, set message status=completed, render final output
```

Frontend SSE hook (Claude writes this, not Lovable):
```typescript
function useMessageStream(messageId: string) {
  const [content, setContent] = useState('')
  const [status, setStatus] = useState('pending')

  useEffect(() => {
    const source = new EventSource(`${API_URL}/stream/messages/${messageId}`)
    source.onmessage = (e) => {
      const data = JSON.parse(e.data)
      if (data.type === 'chunk') setContent(prev => prev + data.content)
      if (data.type === 'done') { setStatus('completed'); source.close() }
      if (data.type === 'error') { setStatus('failed'); source.close() }
    }
    return () => source.close()
  }, [messageId])

  return { content, status }
}
```

---

## 9. The Single Rule That Covers Everything

> **One thing working end to end is worth more than ten things half done.**

Every phase ends with a live demo of that phase working against the real backend.
Never move to the next phase until the current one is fully connected and working.

```
Auth works → Shell loads → Sidebar populates → Messages load →
Message sends → Agent responds → Response streams → Output renders
```

That sequence is the product. Everything else is settings pages.
