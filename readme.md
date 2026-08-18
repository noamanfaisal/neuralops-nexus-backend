# NeuralOps Nexus

A self-hosted team workspace where every conversation can pull in an AI persona — backed by a plain LLM or an agent with tool access (MCP servers) — right in the chat. Projects → Channels → Topics, human members and AI personas side by side, `@mention` to trigger a persona, `@directive` to shape its output (chart, table, diagram, form...).

Everything is private. You run it on your own server, on your own data, with your own model provider keys. Nothing leaves your server unless you configure it to.

## Architecture at a glance

| Service | What it does | Stack |
|---|---|---|
| `nucleus` | Orchestrator — auth, workspace, chat, REST API | Django + Django Ninja |
| `nexus-ai` | AI worker — runs the LLM/agent, embeddings, MCP tool calls | FastAPI + LiteLLM + pydantic-ai |
| `realtime` | Real-time transport — message delivery to the browser | Centrifugo |
| `nginx` | Reverse proxy — single entry point (`/api/`, `/admin/`, websocket) | nginx |
| `postgres` | Relational data | PostgreSQL 17 |
| `chromadb` | Vector store for embeddings / semantic context search | ChromaDB |
| `redis` | Celery broker + Centrifugo engine | Redis 7 |
| `mcps/` | Optional first-party MCP tool servers (SerpAPI, Odoo ERP, filesystem) | FastMCP |

Curious how these fit together and why each tool was chosen? See [`ARCHITECTURE.md`](./ARCHITECTURE.md).

---

## 1. Self-hosting NeuralOps

This is the fast path: one pre-built Docker image, no source code, no local builds. You connect the official NeuralOps web app to your self-hosted server afterward — there's no separate frontend to install.

Estimated time: 10–15 minutes.

### What you need first or Prerequisite

- A computer or server with **Docker** installed and running.
- That machine reachable from the internet (or at least from wherever you'll use NeuralOps from) on **one port**. Any of the following works:
  - A domain name pointed at the machine, with a reverse proxy / TLS in front.
  - [Tailscale Funnel](https://tailscale.com/kb/1223/funnel) — the simplest option if you already use Tailscale.
  - A cloud provider's load balancer / public IP.
- An existing NeuralOps account — sign up at the hosted app first — to run `create_owner` in step 6.

You'll end up with one URL, e.g. `https://neuralops.example.com`. Keep it handy — you'll need it in step 2.

### Step 1 — Pull the image

```bash
docker pull noamanfaisal/neuralops-fat:latest
```

### Step 2 — Run the container

```bash
docker run -d --name neuralops -p 8080:8080 \
  -e NEURALOPS_SERVER_URL=https://neuralops.example.com \
  -v neuralops-postgres-data:/var/lib/postgresql/data \
  -v neuralops-secrets:/nexus/secrets \
  -v neuralops-logs:/nexus/logs \
  -v neuralops-projects:/nexus/projects \
  noamanfaisal/neuralops-fat:latest
```

Replace `https://neuralops.example.com` with your own public URL from the prerequisites above, and point whatever's serving that URL (reverse proxy, Tailscale Funnel, load balancer) at port `8080` on this machine.

The named volumes (`neuralops-postgres-data`, etc.) keep your data safe across restarts and upgrades — don't delete them unless you intend to wipe everything.

### Step 3 — Set up your database and credentials

```bash
docker exec neuralops python3 /nexus/bootstrap.py generate-env
docker exec neuralops python3 /nexus/bootstrap.py init-db
```

This generates a unique database and set of secrets for your server (nothing shared with anyone else's install) and gets the database ready. Safe to run more than once — it won't overwrite anything already set up.

### Step 4 — Apply database migrations

```bash
docker exec -u nexus neuralops bash -c '
  cd /nexus/nucleus
  set -a; . /nexus/secrets/app.env; set +a
  python3 manage.py migrate
'
```

### Step 5 — Start the server

Run each of these once. They start the backend, AI engine, real-time chat, caching, and background task processing.

```bash
# Cache / background task queue
docker exec -u redis -d neuralops bash -c '
  redis-server --bind 127.0.0.1 --port 6379 --logfile /nexus/logs/redis/redis.log
'

# Backend
docker exec -u nexus -d neuralops bash -c '
  cd /nexus/nucleus
  set -a; . /nexus/secrets/app.env; set +a
  export LOG_DIR=/nexus/logs/nucleus
  uvicorn core.asgi:application --host 0.0.0.0 --port 8000 --workers 2 > /nexus/logs/nucleus/stdout.log 2>&1
'

# AI engine
docker exec -u nexus -d neuralops bash -c '
  cd /nexus/ai
  set -a; . /nexus/secrets/app.env; set +a
  export LOG_DIR=/nexus/logs/ai
  export PYTHONPATH=/nexus/ai
  python3 -m uvicorn apps.main:app --host 0.0.0.0 --port 8002 > /nexus/logs/ai/stdout.log 2>&1
'

# Real-time chat
docker exec -u nexus -d neuralops bash -c '
  set -a; . /nexus/secrets/app.env; set +a
  nexus-transport --admin.enabled --admin.insecure --client.insecure --http_api.insecure --http_server.port=8001 > /nexus/logs/transport.log 2>&1
'

# Background tasks
docker exec -u nexus -d neuralops bash -c '
  cd /nexus/nucleus
  set -a; . /nexus/secrets/app.env; set +a
  export LOG_DIR=/nexus/logs/nucleus
  celery -A core worker -l info > /nexus/logs/nucleus/celery-worker.log 2>&1
'

# Scheduled tasks
docker exec -u nexus -d neuralops bash -c '
  cd /nexus/nucleus
  set -a; . /nexus/secrets/app.env; set +a
  export LOG_DIR=/nexus/logs/nucleus
  celery -A core beat -l info > /nexus/logs/nucleus/celery-beat.log 2>&1
'
```

### Step 6 — Create your owner account

This links your NeuralOps account to your new server as its owner.

```bash
docker exec -u nexus -it neuralops bash -c '
  cd /nexus/nucleus
  set -a; . /nexus/secrets/app.env; set +a
  python3 manage.py create_owner
'
```

Enter the email and password of your NeuralOps account when prompted.

### Step 7 — Connect

Open the NeuralOps web app, choose "Connect to your own server," and enter your server's URL from step 2. Sign in with the account you just made the owner of.

### Checking everything's running

```bash
docker exec neuralops ps aux
```

You should see six processes: nginx, uvicorn (backend), uvicorn (AI engine), nexus-transport, and two celery processes.

### Upgrading to a new version

```bash
docker pull noamanfaisal/neuralops-fat:latest
docker stop neuralops
docker rm neuralops
```

Then repeat step 2 onward with the same volume names — your data and credentials carry over automatically. `generate-env` and `init-db` in step 3 are safe to re-run; they won't touch anything already set up.

### Troubleshooting

- **Can't sign in / "Update required" message** — make sure the URL you connected to in step 7 exactly matches `NEURALOPS_SERVER_URL` from step 2.
- **Avatar or media images not loading** — double check `NEURALOPS_SERVER_URL` was set correctly in step 2; this is what the server uses to build image links.
- **A process isn't running** — check its log under the `neuralops-logs` volume, e.g. `docker exec neuralops cat /nexus/logs/nucleus/stdout.log`.

---

## 2. Using NeuralOps

Everything below is driven from inside the chat itself — type `/` in the message box to see all available commands, or `@` to mention a persona or attach context.

### Add your first AI model

Type **`/add-model`** in any chat. You'll need:

| Field | Notes |
|---|---|
| Name | Display name, e.g. "GPT-4o" |
| Model ID | LiteLLM format, e.g. `gpt-4o`, `anthropic/claude-haiku-4-5-20251001` |
| API Base URL | Optional — only for custom/self-hosted endpoints |
| API Key | Stored encrypted |
| Terms of service checkbox | Required before saving |

`/list-models` shows everything you've registered.

### Add an MCP server

*No MCP servers are configured on a fresh server by default.* Type **`/add-mcp`** and provide:

| Field | Notes |
|---|---|
| Name | e.g. "Odoo ERP" |
| URL | The server's `/mcp` endpoint |
| Transport | `streamable-http` (default), `sse`, or `stdio` |
| Server Type | Remote or Local |

The `mcps/` folder ships three ready-to-run example servers (SerpAPI shopping, Odoo ERP, filesystem) you can spin up with `cd mcps && docker compose up -d` and then register here. **Important:** when a persona actually calls a tool, the request comes from inside the `nexus-ai` container — register the MCP server's URL using your host's real IP, not `localhost`, or tool calls will fail with connection refused. `/list-mcps` shows everything registered.

### Add an agent

An agent pairs a model with an MCP server so a persona built on it can call tools. Type **`/add-agent`**:

| Field | Notes |
|---|---|
| Name | e.g. "ERP Agent" |
| AI Model | Required — pick from your registered models |
| MCP Server | Optional — pick one, or None for a plain-LLM agent |
| System Prompt | Optional instructions |

`/list-agents` to review.

### Add a persona

Personas are what you `@mention` in chat. Type **`/add-persona`**:

| Field | Notes |
|---|---|
| Name | Used as the `@mention`, e.g. "Layla" → `@Layla` |
| Backed by | **Agent** (model + tools) or **Model directly** (plain LLM, no tools) |
| System Prompt | Defaults to "You are {name}, a helpful AI assistant." |

`/list-personas` to review or manage existing ones.

### Invite a user

Type **`/invite`** followed by either an `@PersonaName` or an email address:

```
/invite @Layla                        → adds the persona to this project
/invite someone@example.com           → invites them to this topic
/invite someone@example.com project   → invites them to the whole project
```

New users get an emailed invite link; existing workspace users are added directly.

### Create a project, channel, and topic

- **Project:** click **+** next to Projects in the sidebar → name + optional description.
- **Channel:** inside a project, **+** next to Channels → name + optional description.
- **Topic:** inside a channel, **+** next to Topics → title. This is the actual conversation thread.

### Talk to a persona

`@mention` any persona in a message to trigger it:

```
@Layla summarize the last quarter's numbers
```

You can mention multiple personas at once, and add an output directive to shape the reply — `@chart`, `@table`, `@diagram`, `@form`, `@code`, `@terminal`, `@html`, or `@text`:

```
@Layla show me the sales trend @chart
```

### `@session` — keep talking without re-mentioning

Add `@session` to open a running session with whichever personas you just mentioned — every plain message after that (no `@mention` needed) goes to them automatically, until the session times out (default 30 min, configurable per company) or you close it:

```
@Layla @session let's dig into this together
...then just type normally, no @mention needed...
@session close        (or "@session end")
```

---

## 3. Developing & contributing

Want to run from source, dig into how the system is put together, or send a pull request? Start here:

| Doc | What's in it |
|---|---|
| [`how-to-contribute.md`](./how-to-contribute.md) | Fork/branch/PR workflow, commit conventions, running a local dev build from source |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | System design and *why* each tool/framework was chosen |
| [`DECISIONS.md`](./DECISIONS.md) | Product decisions, implementation rules, and constraints — read before changing behavior |
| [`STORY.md`](./STORY.md) | The narrative version — how the architecture evolved, what was tried and abandoned, and why |
| [`story/`](./story) | Deep-dive narratives on specific subsystems (auth architecture, permissions model, owner setup) |
| [`TASKS.md`](./TASKS.md) | Full development task history + known gotchas |
| [`neuralops-backend-api-catalog.md`](./neuralops-backend-api-catalog.md) | Full REST + internal API reference |
| [`CONCEPTS-AND-ROLES.md`](./CONCEPTS-AND-ROLES.md) | Every core object (Company, Project, Channel, Topic, User, AI Model, Agent, MCP Server, Context, Knowledge Base) — philosophy + Django model — plus the full permissions/role hierarchy |

> **Branch notice:** `dev` is the active development branch — clone and build from it. `master`/`main` may lag behind.

---

## License

The NeuralOps Nexus **Community/Freemium core** — everything in this repository — is licensed under the **[GNU Affero General Public License v3.0](./LICENSE)** (AGPL-3.0).

In short: you're free to self-host, use, study, modify, and redistribute this code, including for commercial purposes — but if you modify it and run it as a network service for others, the AGPL requires you to make your modified source available to those users under the same license. This keeps the project's improvements open for everyone, including improvements made by companies offering it as a hosted service.

NeuralOps' own **SaaS** and **Enterprise** offerings include additional proprietary features and are licensed separately — that code is not published in this repository and is not covered by the AGPL-3.0 license above.

See the [`LICENSE`](./LICENSE) file for the full legal text.
