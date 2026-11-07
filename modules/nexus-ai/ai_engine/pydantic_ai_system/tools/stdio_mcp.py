"""
Spawn-side plumbing for stdio MCP servers — the SSH road and the catalog's
npx/uvx tiles (docs/MISSING.md "stdio waits for the runner" — this is the
runner, 2026-11-08).

A stdio MCP server row carries a COMMAND string (nucleus model field) and a
decrypted SECRETS dict (MCPServerInternal.secrets — nucleus already documents
it as "subprocess env vars when spawning a stdio MCP server"). This module
turns the pair into a pydantic-ai StdioTransport:

  - the command is shlex-split; it is NEVER handed to a shell, so secrets
    cannot be injected into it and it cannot chain further commands;
  - argv[0] must be on the executable allowlist (MCP_STDIO_ALLOWED_COMMANDS,
    default "ssh,npx,uvx") — defence in depth: an MCP row is data from the
    database, and the engine refuses to exec arbitrary binaries over it;
  - the secret named SSH_PRIVATE_KEY is special: it never becomes child env.
    It is written to a 0600 file under MCP_KEY_DIR and substituted for the
    literal {SSH_KEY_FILE} placeholder in the argv — so a stored command like
        ssh -i {SSH_KEY_FILE} -o StrictHostKeyChecking=accept-new user@host …
    works without the key ever touching the row, the logs or the command
    string in the database;
  - every other secret becomes an env var of the CHILD process only.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shlex
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SSH_KEY_SECRET = "SSH_PRIVATE_KEY"
KEY_FILE_PLACEHOLDER = "{SSH_KEY_FILE}"

_DEFAULT_ALLOWED = "ssh,npx,uvx"


def _allowed_commands() -> set[str]:
    raw = os.environ.get("MCP_STDIO_ALLOWED_COMMANDS", _DEFAULT_ALLOWED)
    return {c.strip() for c in raw.split(",") if c.strip()}


def _key_dir() -> Path:
    return Path(os.environ.get("MCP_KEY_DIR", "/tmp/nexus-mcp-keys"))


@dataclass(frozen=True)
class StdioSpec:
    command: str
    args: list[str]
    env: dict[str, str] | None


def build_spec(server_id: str, command: str, secrets: dict | None) -> StdioSpec:
    """The validated spawn spec, or ValueError with a human-worded reason
    (shown verbatim next to the Refresh button / in the engine log)."""
    argv = shlex.split(command or "")
    if not argv:
        raise ValueError("the server has no command to run")

    executable = Path(argv[0]).name
    if executable not in _allowed_commands():
        raise ValueError(
            f"command {executable!r} is not on this engine's stdio allowlist "
            f"({', '.join(sorted(_allowed_commands()))}) — set "
            "MCP_STDIO_ALLOWED_COMMANDS to extend it"
        )

    secrets = dict(secrets or {})
    key = secrets.pop(SSH_KEY_SECRET, None)
    env = {k: str(v) for k, v in secrets.items() if v is not None}

    needs_key = any(KEY_FILE_PLACEHOLDER in a for a in argv)
    if needs_key and not key:
        raise ValueError(
            "the command references {SSH_KEY_FILE} but no SSH_PRIVATE_KEY "
            "secret is stored on this server"
        )
    if key:
        path = _write_key(server_id, key)
        argv = [a.replace(KEY_FILE_PLACEHOLDER, str(path)) for a in argv]

    return StdioSpec(command=argv[0], args=argv[1:], env=env or None)


def _write_key(server_id: str, key: str) -> Path:
    """The key file ssh demands: 0600, owner-only directory, stable per
    server so repeated dials reuse it. Content is rewritten every time —
    a rotated key takes effect on the next spawn."""
    directory = _key_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)  # pre-existing dir keeps the right mode too
    name = hashlib.sha256(str(server_id).encode()).hexdigest()[:24]
    path = directory / name
    body = key if key.endswith("\n") else key + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, body.encode())
    finally:
        os.close(fd)
    os.chmod(path, 0o600)  # pre-existing file keeps 0600 even with a umask surprise
    return path


def transport_for(server_id: str, command: str, secrets: dict | None):
    """The pydantic-ai StdioTransport for this server row. Imported lazily so
    a framework layout shift surfaces where it is handled (the callers wrap
    ValueError/ImportError into their own worded skip/502)."""
    from pydantic_ai.mcp import StdioTransport  # noqa: PLC0415

    spec = build_spec(server_id, command, secrets)
    return StdioTransport(command=spec.command, args=spec.args, env=spec.env)
