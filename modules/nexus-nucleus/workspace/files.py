"""
Step 5 — the project file viewer (docs/NUCLEUS-REVAMP.md §3).

Browse, download and view-as-HTML over the project's folder on the server —
the same /nexus/projects/<slug>-<id8> folder the personas' filesystem tools
write into (workspace/services.get_project_folder_name; both containers
bind-mount ./projects there, verified in Step 0).

Safety, in plain words:
- Every path is resolved (symlinks followed) and must land INSIDE the
  project's folder — `..`, absolute paths and symlinks pointing out are all
  refused with a 400. The project folder is the wall.
- Rendered views have a size cap (big files are download-only).
- Rendered HTML is served with `Content-Security-Policy: sandbox`, which
  makes the browser run NO scripts from it — a file a persona (or anyone)
  wrote can't act in the viewer's browser.
- Who may look: the endpoints in workspace/api.py resolve the project the
  same way every other read does (project.view, with the topic-reach
  fallback).

Markdown rendering and code highlighting use the `markdown` and `Pygments`
packages WHEN the image has them (added to docker/dev/requirements.txt in
this step — an image built before that shows the same content as escaped,
readable plain text instead; nothing breaks).
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import secrets
from datetime import datetime, timezone as dt_timezone
from html import escape
from pathlib import Path

from asgiref.sync import async_to_sync
from django.conf import settings

logger = logging.getLogger(__name__)

# Render caps — a view is for READING; anything bigger is download-only.
RENDER_MAX_BYTES = 2 * 1024 * 1024          # text/markdown/code shown as HTML
IMAGE_RENDER_MAX_BYTES = 8 * 1024 * 1024    # images are embedded as data URIs
LIST_MAX_ENTRIES = 500
# Part 2: one-use download tickets — short-lived, so a leaked link dies fast.
TICKET_TTL_SECONDS = 60
_TICKET_KEY = "nx:filetkt:{token}"
# Part 2: how many files one reply chips at most — a loop that wrote hundreds
# still shows the first few rather than flooding the bubble.
CHIP_FILES_MAX = 20

MARKDOWN_EXTS = {".md", ".markdown", ".mdown"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"}

# Optional renderers — present once the image is rebuilt with this step's
# requirements.txt; everything degrades to escaped plain text without them.
try:  # pragma: no cover - depends on the installed image
    import markdown as _markdown
except ImportError:  # pragma: no cover
    _markdown = None
try:  # pragma: no cover
    from pygments import highlight as _pyg_highlight
    from pygments.formatters import HtmlFormatter as _PygFormatter
    from pygments.lexers import get_lexer_for_filename as _pyg_lexer_for
    from pygments.util import ClassNotFound as _PygClassNotFound
except ImportError:  # pragma: no cover
    _pyg_highlight = None


class FileViewerError(Exception):
    """A refused file request; `status` is the HTTP answer."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ── The wall ──────────────────────────────────────────────────────────────────

def project_root(project) -> Path:
    from .services import get_project_folder_name

    return (Path(settings.PROJECTS_ROOT) / get_project_folder_name(project)).resolve()


def resolve_path(project, rel: str | None) -> tuple[Path, Path]:
    """
    (root, target) with the target resolved (symlinks followed) and proven to
    be the root itself or inside it. Everything else is a 400 — `..`, an
    absolute path, a symlink pointing out, a null byte.
    """
    root = project_root(project)
    if not root.is_dir():
        raise FileViewerError(409, "This project has no folder on the server yet.")

    rel = (rel or "").strip()
    if "\x00" in rel:
        raise FileViewerError(400, "That path isn't valid.")
    rel = rel.lstrip("/")

    try:
        target = (root / rel).resolve() if rel else root
    except OSError:
        raise FileViewerError(400, "That path isn't valid.")

    if target != root and root not in target.parents:
        raise FileViewerError(400, "That path points outside the project's folder.")
    return root, target


# ── Browse ────────────────────────────────────────────────────────────────────

def list_folder(project, rel: str | None) -> dict:
    """The folder's entries, folders first then by name, capped and flagged."""
    root, target = resolve_path(project, rel)
    if not target.exists():
        raise FileViewerError(404, "No such folder in this project.")
    if not target.is_dir():
        raise FileViewerError(400, "That's a file — fetch it from files/content/ instead.")

    entries = []
    try:
        children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        raise FileViewerError(400, f"That folder can't be read: {exc.__class__.__name__}.")

    truncated = False
    for child in children:
        if len(entries) >= LIST_MAX_ENTRIES:
            truncated = True
            break
        try:
            stat = child.stat()
            is_dir = child.is_dir()
        except OSError:
            continue  # a broken symlink or a vanished file is just skipped
        entries.append({
            "name": child.name,
            "type": "dir" if is_dir else "file",
            "size": None if is_dir else stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc).isoformat(),
        })

    return {
        "path": str(target.relative_to(root)) if target != root else "",
        "entries": entries,
        "truncated": truncated,
    }


# ── Download ──────────────────────────────────────────────────────────────────

def open_for_download(project, rel: str | None) -> tuple[Path, str]:
    """(path, content_type) for a plain download — no size cap, streamed."""
    root, target = resolve_path(project, rel)
    if not target.exists():
        raise FileViewerError(404, "No such file in this project.")
    if target.is_dir():
        raise FileViewerError(400, "That's a folder — list it from files/ instead.")
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return target, content_type


# ── Download tickets (part 2) ───────────────────────────────────────────
# A ticket is proof enough on its own: 32 random url-safe bytes, valid
# TICKET_TTL_SECONDS, ONE use, tied to one file of one project. It lives in
# the shared signal store (Redis in production), so any nucleus worker can
# honour a ticket another one minted. push/pop_all give the one-use take:
# the first GET pops the payload, the second finds nothing.

def make_download_ticket(project, rel: str | None) -> dict:
    """{url, expires_in} for one existing file — same wall and the caller's
    same read check as every other file route."""
    from chat.stop_signals import signal_store

    root, target = resolve_path(project, rel)
    if not target.exists():
        raise FileViewerError(404, "No such file in this project.")
    if target.is_dir():
        raise FileViewerError(400, "That's a folder — tickets are for files.")
    token = secrets.token_urlsafe(32)
    payload = json.dumps({
        "project_id": str(project.id),
        "path": str(target.relative_to(root)),
    })
    async_to_sync(signal_store().push)(_TICKET_KEY.format(token=token), payload, TICKET_TTL_SECONDS)
    return {"url": f"/api/v1/files/download/{token}", "expires_in": TICKET_TTL_SECONDS}


def take_download_ticket(token: str) -> dict | None:
    """The ticket's {project_id, path} — exactly once. None when it never
    existed, expired, or was already used (indistinguishable on purpose)."""
    from chat.stop_signals import signal_store

    token = (token or "").strip()
    if not token or len(token) > 128:
        return None
    values = async_to_sync(signal_store().pop_all)(_TICKET_KEY.format(token=token))
    if not values:
        return None
    try:
        payload = json.loads(values[0])
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def stat_files(project, paths: list[str]) -> list[dict]:
    """Part 2's file chips: {path, name, size} for each written path that still
    resolves INSIDE the project folder and exists — everything else is silently
    skipped (a file deleted again mid-run is not a chip). Never raises."""
    out: list[dict] = []
    seen: set[str] = set()
    for rel in paths or []:
        if len(out) >= CHIP_FILES_MAX:
            break
        try:
            root, target = resolve_path(project, rel)
            if not target.is_file():
                continue
            rel_path = str(target.relative_to(root))
            if rel_path in seen:
                continue
            seen.add(rel_path)
            out.append({"path": rel_path, "name": target.name, "size": target.stat().st_size})
        except (FileViewerError, OSError):
            continue
    return out


# ── Upload (part 3) ──────────────────────────────────────────────────────
# One file into one folder, by whoever holds project.files_write (the route
# checks). Same wall as every other path; the NAME is a bare file name — a
# separator, a `..` or a null byte is refused before anything touches disk.

_BAD_NAME_CHARS = ("/", "\\", "\x00")
UPLOAD_NAME_MAX = 255


def upload_limit() -> int:
    """Read at call time so tests (and app.env) can change it."""
    return int(getattr(settings, "FILES_UPLOAD_MAX_BYTES", 50 * 1024 * 1024))


def save_upload(project, folder_rel: str | None, name: str, uploaded, overwrite: bool = False) -> dict:
    """
    Save ONE uploaded file into the project folder.
    - the folder must exist inside the wall (the root counts);
    - the name is a BARE file name (≤255, no / \\ .. or null byte);
    - the size cap is FILES_UPLOAD_MAX_BYTES (default 50 MB), enforced on the
      declared size AND again while writing (a lying Content-Length still stops);
    - an existing file is only replaced with overwrite=true (else 409); a
      folder or a symlink under that name is never written over.
    Returns the chip shape {path, name, size}.
    """
    root, folder = resolve_path(project, folder_rel)
    if not folder.exists():
        raise FileViewerError(404, "No such folder in this project.")
    if not folder.is_dir():
        raise FileViewerError(400, "That's a file — pick a folder to upload into.")

    name = (name or "").strip()
    if (not name or name in (".", "..") or len(name) > UPLOAD_NAME_MAX
            or any(c in name for c in _BAD_NAME_CHARS)):
        raise FileViewerError(400, "That file name isn't valid.")

    limit = upload_limit()
    declared = getattr(uploaded, "size", None)
    if declared is not None and declared > limit:
        raise FileViewerError(413, f"That file is too big — the limit is {limit // (1024 * 1024)} MB.")

    target = folder / name
    if target.is_symlink():
        # Writing through a link writes WHEREVER it points — never.
        raise FileViewerError(400, "That name is taken by a link — pick another name.")
    if target.is_dir():
        raise FileViewerError(400, "A folder with that name exists — pick another name.")
    if target.exists() and not overwrite:
        raise FileViewerError(409, "A file with that name exists — send overwrite=true to replace it.")

    written = 0
    try:
        with open(target, "wb") as out:
            for chunk in uploaded.chunks():
                written += len(chunk)
                if written > limit:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise FileViewerError(413, f"That file is too big — the limit is {limit // (1024 * 1024)} MB.")
                out.write(chunk)
    except FileViewerError:
        raise
    except OSError as exc:
        raise FileViewerError(400, f"The file couldn't be saved: {exc.__class__.__name__}.")
    return {"path": str(target.relative_to(root)), "name": name, "size": target.stat().st_size}


# ── View as HTML ──────────────────────────────────────────────────────────────

def render_html(project, rel: str | None) -> str:
    """
    One self-contained HTML page for the file: markdown rendered, code
    highlighted, text and images shown directly — all inside the size caps.
    Served with CSP `sandbox` by the endpoint, so nothing in it can run.
    """
    root, target = resolve_path(project, rel)
    if not target.exists():
        raise FileViewerError(404, "No such file in this project.")
    if target.is_dir():
        raise FileViewerError(400, "That's a folder — list it from files/ instead.")

    ext = target.suffix.lower()
    size = target.stat().st_size

    if ext in IMAGE_EXTS:
        if size > IMAGE_RENDER_MAX_BYTES:
            raise FileViewerError(413, "This image is too big to view — download it instead.")
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = base64.b64encode(target.read_bytes()).decode()
        body = f'<img src="data:{content_type};base64,{data}" alt="{escape(target.name)}">'
        return _page(target.name, body)

    if size > RENDER_MAX_BYTES:
        raise FileViewerError(413, "This file is too big to view — download it instead.")

    raw = target.read_bytes()
    if b"\x00" in raw[:8192]:
        raise FileViewerError(415, "This file isn't text — download it instead.")
    text = raw.decode("utf-8", errors="replace")

    if ext in MARKDOWN_EXTS and _markdown is not None:
        body = _markdown.markdown(text, extensions=["fenced_code", "tables"])
    elif _pyg_highlight is not None and ext not in MARKDOWN_EXTS and ext not in (".txt", ""):
        try:
            lexer = _pyg_lexer_for(target.name)
            body = _pyg_highlight(text, lexer, _PygFormatter(noclasses=True))
        except _PygClassNotFound:
            body = f"<pre>{escape(text)}</pre>"
    else:
        # No renderer installed (or plain text): readable, escaped, safe.
        body = f"<pre>{escape(text)}</pre>"

    return _page(target.name, body)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
  body {{ margin: 0; padding: 24px; font: 15px/1.6 -apple-system, system-ui, sans-serif;
         color: #1a1a1a; background: #ffffff; max-width: 920px; }}
  pre {{ padding: 12px; background: #f6f6f6; border-radius: 6px; overflow-x: auto;
        font: 13px/1.5 ui-monospace, monospace; white-space: pre-wrap; word-break: break-word; }}
  img {{ max-width: 100%; height: auto; }}
  table {{ border-collapse: collapse; }} td, th {{ border: 1px solid #ccc; padding: 4px 8px; }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #e8e8e8; background: #141414; }}
    pre {{ background: #1f1f1f; }} td, th {{ border-color: #444; }}
  }}
</style>
</head>
<body>
{body}
</body>
</html>
"""
