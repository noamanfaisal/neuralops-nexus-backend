"""
The NeuralOps project console (v1) — a terminal data bus over your project's
MCP servers. No model is involved: you are the caller.

    uvx neuralops-console https://your-server.example

Sign in with your NeuralOps email and password (or set
NEURALOPS_CONSOLE_TOKEN to skip the prompt), pick a project, then type lines:

    github.search({"query": "payment bug"})
    github.search({"query": "payment bug"}) > /issues/payments.json
    graph.ingest(@/issues/payments.json)
    graph.ingest(_)                      # _ = the previous result
    graph.ingest(github.search({"query": "x"}))   # one nesting level

`> /path` saves the full result into the PROJECT FOLDER on the server (the
same folder personas' Filesystem capability sees); `@/path` loads args from
it. Built-ins: servers, projects, use <n>, help, exit.

Server side: the console must be switched on in project settings, and your
role must hold the mcp.playground right. Every line is audited.
"""
from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path

import httpx

from . import __version__

try:  # history + line editing when the platform has it
    import readline  # noqa: F401
except ImportError:  # pragma: no cover - windows
    readline = None

STATE_DIR = Path(os.environ.get("NEURALOPS_CONSOLE_HOME",
                                Path.home() / ".config" / "neuralops-console"))

HELP = """\
commands
  servers            the project's MCP servers and their tools
  projects           your projects (* = console switched on)
  use <n|name>       switch project
  help               this text
  exit / quit        leave

lines
  server.tool({"key": "value"})         call a tool (JSON args)
  server.tool()                         no args
  server.tool(other.tool({...}))        one nesting level: inner result -> outer args
  server.tool(@/path.json)              args from a project-folder file
  server.tool(_)                        args = the previous result
  ... > /path.json                      save the result into the project folder
"""


class ConsoleError(Exception):
    pass


class Client:
    def __init__(self, base_url: str, token: str):
        self.http = httpx.Client(
            base_url=base_url.rstrip("/") + "/api/v1",
            headers={"Authorization": f"Bearer {token}"},
            timeout=190,
        )

    def _unwrap(self, resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text[:300])
            except Exception:  # noqa: BLE001
                detail = resp.text[:300] or f"status {resp.status_code}"
            raise ConsoleError(str(detail))
        return resp.json()

    def projects(self) -> list[dict]:
        return self._unwrap(self.http.get("/projects/"))

    def servers(self, project_id: str) -> list[dict]:
        return self._unwrap(self.http.get(f"/projects/{project_id}/console/servers/"))["servers"]

    def run(self, project_id: str, line: str, last_result=None) -> dict:
        return self._unwrap(self.http.post(
            f"/projects/{project_id}/console/run/",
            json={"line": line, "last_result": last_result}))


def sign_in(base_url: str) -> str:
    token = os.environ.get("NEURALOPS_CONSOLE_TOKEN", "").strip()
    if token:
        return token
    print(f"neuralops-console {__version__} — {base_url}")
    email = input("email: ").strip()
    password = getpass.getpass("password: ")
    resp = httpx.post(base_url.rstrip("/") + "/api/v1/auth/local/signin/",
                      json={"email": email, "password": password}, timeout=30)
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail", resp.text[:200])
        except Exception:  # noqa: BLE001
            detail = resp.text[:200]
        print(f"sign-in failed: {detail}", file=sys.stderr)
        sys.exit(1)
    body = resp.json()
    print(f"signed in as {body['user']['email']} "
          f"(token good for {body.get('expires_hours', '?')}h)")
    return body["access_token"]


def pick_project(client: Client) -> dict:
    projects = client.projects()
    if not projects:
        print("no projects visible to you.", file=sys.stderr)
        sys.exit(1)
    enabled = [p for p in projects if p.get("console_enabled")]
    if len(enabled) == 1:
        print(f"project: {enabled[0]['name']}")
        return enabled[0]
    _print_projects(projects)
    while True:
        choice = input("project> ").strip()
        found = _match_project(projects, choice)
        if found:
            return found
        print("pick a number or a name from the list.")


def _print_projects(projects: list[dict]) -> None:
    for i, p in enumerate(projects, 1):
        mark = "*" if p.get("console_enabled") else " "
        print(f"  {i:2} {mark} {p['name']}")
    print("     (* = console switched on)")


def _match_project(projects: list[dict], choice: str):
    if choice.isdigit() and 1 <= int(choice) <= len(projects):
        return projects[int(choice) - 1]
    for p in projects:
        if p["name"].lower() == choice.lower() or p.get("slug", "").lower() == choice.lower():
            return p
    return None


def _print_servers(servers: list[dict]) -> None:
    if not servers:
        print("no dialable MCP servers in this project.")
        return
    for s in servers:
        print(f"  {s['name']}  ({s['transport']}, {s.get('title', '')})")
        for t in s.get("tools", []):
            ro = " [read]" if t.get("read_only") else ""
            desc = (t.get("description") or "")[:70]
            print(f"      .{t['name']}{ro}  {desc}")
        if not s.get("tools"):
            print("      (no stored tool list — use the app's Refresh tools button)")


def _print_result(body: dict) -> None:
    if not body.get("ok"):
        print(f"error: {body.get('error', 'unknown')}")
        return
    if body.get("saved_to"):
        print(f"saved {body.get('saved_bytes', '?')} bytes -> {body['saved_to']}")
    result = body.get("result")
    if result is not None:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif body.get("text"):
        print(body["text"])
    if body.get("truncated"):
        print("(truncated — pipe it with > /path.json for the full result)")
    ms = body.get("duration_ms")
    if ms is not None:
        print(f"({ms} ms)")


def _save_last(body: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / "last.json").write_text(
            json.dumps(body, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _history_file() -> Path:
    return STATE_DIR / "history"


def repl(client: Client, project: dict) -> None:
    if readline is not None:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            readline.read_history_file(_history_file())
        except OSError:
            pass
    last_result = None
    prompt = f"{project['slug']}> "
    print("type `help` for the grammar, `servers` for what you can call.")
    while True:
        try:
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if readline is not None:
            try:
                readline.write_history_file(_history_file())
            except OSError:
                pass
        if line in ("exit", "quit"):
            break
        if line == "help":
            print(HELP)
            continue
        try:
            if line == "servers":
                _print_servers(client.servers(project["id"]))
                continue
            if line == "projects" or line.startswith("use "):
                projects = client.projects()
                if line == "projects":
                    _print_projects(projects)
                    continue
                found = _match_project(projects, line[4:].strip())
                if not found:
                    print("no such project.")
                    continue
                project = found
                prompt = f"{project['slug']}> "
                last_result = None
                print(f"project: {project['name']}")
                continue
            body = client.run(project["id"], line, last_result)
        except ConsoleError as exc:
            print(f"error: {exc}")
            continue
        except httpx.HTTPError as exc:
            print(f"connection error: {type(exc).__name__}: {exc}")
            continue
        _print_result(body)
        if body.get("ok"):
            # `_` = the next line's args: the structured result when there is
            # one, else the text — mirrored to <state>/last.json for scripts.
            last_result = body.get("result") if body.get("result") is not None \
                else ({"text": body["text"]} if body.get("text") else last_result)
            _save_last(body)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--version" in sys.argv:
        print(__version__)
        return
    if not args or "--help" in sys.argv or "-h" in sys.argv:
        print("usage: neuralops-console <server-url>\n")
        print(HELP)
        return
    base_url = args[0]
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url
    token = sign_in(base_url)
    client = Client(base_url, token)
    try:
        project = pick_project(client)
    except ConsoleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    repl(client, project)


if __name__ == "__main__":
    main()
