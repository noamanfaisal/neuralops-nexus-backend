# neuralops-console

The NeuralOps **project console** — a terminal data bus over your project's
MCP servers. You call the tools directly; no model is involved, no tokens are
spent, and every line is audited on the server.

```
uvx neuralops-console https://your-neuralops-server.example
```

Sign in with your NeuralOps email and password (or set
`NEURALOPS_CONSOLE_TOKEN`), pick a project, then type lines:

```
github.search({"query": "payment bug"})
github.search({"query": "payment bug"}) > /issues/payments.json
graph.ingest(@/issues/payments.json)
graph.ingest(_)                                 # _ = the previous result
graph.ingest(github.search({"query": "x"}))     # one nesting level
```

`> /path` saves the full result into the **project folder** on the server —
the same folder your personas' Filesystem capability reads — and `@/path`
loads args back out of it. That is the point: one MCP's output becomes
another MCP's input, through the folder everything already shares.

Built-in commands: `servers`, `projects`, `use <name>`, `help`, `exit`.

## Server requirements

- NeuralOps server **1.1.8+**
- The console switched **on** in project settings (off by default)
- Your role holds the **mcp.playground** right (Owner/Admin by default)

## Grammar

| Line | Meaning |
|---|---|
| `server.tool({"k": "v"})` | call a tool with JSON args |
| `server.tool()` | no args |
| `server.tool(other.tool({...}))` | one nesting level: inner result → outer args |
| `server.tool(@/path.json)` | args loaded from the project folder |
| `server.tool(_)` | args = the previous result |
| `… > /path.json` | save the result into the project folder |

Paths are project-folder-relative; `..` never escapes it. Results over the
inline cap must be piped with `>`; args files are capped at 2 MB, saves at
20 MB.
