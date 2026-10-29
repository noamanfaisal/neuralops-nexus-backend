# File viewer pane: developer spec

**For the developer.** Written 2026-10-28. Goal: people can see, open and
download the files in a project's folder (what personas write with their file
tools, plus anything the team puts there), and later upload files and preview a
web page they built.

Background: `docs/MISSING.md` §3 and the Stage 4 "File viewer pane" entry.

---

## 1. What already exists (backend: built and tested, nothing to change for part 1)

The project folder on the server is `/nexus/projects/<slug>-<id8>`, the same
folder the personas' filesystem tools read and write.

`modules/nexus-nucleus/workspace/files.py` + routes in `workspace/api.py`,
tests in `workspace/tests_files.py`:

| Call | Does |
|---|---|
| `GET /api/v1/projects/{project_id}/files/?path=<folder>` | Lists a folder: `{path, entries:[{name, type: dir\|file, size, modified}], truncated}`. Folders first, max 500 entries |
| `GET /api/v1/projects/{project_id}/files/content/?path=<file>` | **Download**: the file itself, streamed, any size, `Content-Disposition: attachment` |
| `GET /api/v1/projects/{project_id}/files/content/?path=<file>&as=html` | **View**: one HTML page. Markdown rendered, code highlighted, text and images shown. Caps: 2 MB for text, 8 MB for images; bigger → 413 "download it instead". Binary → 415. Served with `Content-Security-Policy: sandbox`, so no script in the file can run |

Safety that's already there:
- Every path is resolved and must stay inside the project folder. `..`, absolute paths and symlinks pointing out all get a 400.
- Who can read: anyone who can see the project (the same `project.view` rule as every other read); otherwise 404.

Errors to word in the UI: 400 (bad path), 404 (missing), 409 (the project has no folder yet), 413 (too big to view), 415 (not text).

## 2. Part 1: the pane (frontend only)

### Where
A **Files** pane in the pane rail, next to the other project panes, for anyone who can see the project.

### What it shows
- A breadcrumb (`Project files / reports / 2026`) and a list: folder/file icon, name, size (human-readable), modified (relative time). Folders first. A "showing the first 500" note when `truncated`.
- A **Refresh** button. Personas write files while you watch, so the list must be re-fetchable.
- Click a folder → open it. Click a file → **view** it (below).
- Each file row has a **Download** button.
- Empty folder → "No files yet. Files your personas create appear here."
- 409 → "This project has no folder on the server yet."

### Viewing a file
- Fetch `…/files/content/?path=…&as=html` **with the normal Authorization header** (the API uses a bearer token, so a plain link or `<iframe src>` would arrive without it and get 401).
- Show the returned HTML in an `<iframe srcdoc=… sandbox>`, with **no** `allow-scripts` and **no** `allow-same-origin`. The server's CSP header doesn't come along with `srcdoc`, so the iframe's `sandbox` attribute is what keeps file content from running. Required, with a test.
- 413/415 → show the message and a **Download** button instead.
- Viewer header: file name, size, Download, Close.

### Downloading a file
- Fetch `…/files/content/?path=…` with the Authorization header → `blob` → object URL → click a temporary `<a download>` → revoke the URL.
- Show progress / "Downloading…" for big files. Files over about 200 MB → see part 2 (ticket link), so the browser doesn't hold the whole file in memory.

### Tests (frontend)
List renders folders first; breadcrumb navigation; refresh re-fetches; view uses `srcdoc` + `sandbox` without `allow-scripts`; download sends the Authorization header; 404/409/413/415 messages; empty state.

## 3. Part 2: download links for big files and for chat (backend + frontend)

**Problem:** a blob download keeps the whole file in browser memory, and a link in a chat message can't carry the bearer token.

**Build:** a short-lived, single-use download ticket (the same pattern as the terminal/browser session tickets):
- `POST /api/v1/projects/{id}/files/ticket/` `{path}` → `{url, expires_in: 60}`. Same path rules and the same read check.
- `GET /api/v1/files/download/{ticket}` → streams the file. No login needed, because the ticket is the proof. Valid 60 seconds, **one use**, tied to that one file. Expired, reused or unknown → 410/404.
- The pane uses tickets for files over ~200 MB (the browser's own download manager then streams to disk).

**Chat integration (nice next step):** when a persona writes a file, its reply shows a small **file chip** (name + size). Clicking it opens the file in the Files pane, or downloads it with a fresh ticket. Never put a long-lived link in a message.

Tests (nucleus): ticket works once; second use refused; expires after 60 s; a ticket for project A can't fetch project B's file; path rules still apply.

## 4. Part 3: upload (backend + frontend)

- `POST /api/v1/projects/{id}/files/upload/?path=<folder>`, multipart. Needs **a write right** (proposal: a new `project.files_write`, given to project admins and members; viewers can't upload).
- Limits: a max size per file (setting, default 50 MB); refuse names with `/`, `\`, `..` or a null byte; same "stay inside the folder" check; refuse to overwrite unless `overwrite=true` is sent.
- The nucleus **64 KB request limit** (see the approval-pause bug in MISSING.md) must not apply to this route; give it its own limit.
- UI: an Upload button and drag-and-drop on the pane, a progress bar, and "a file with that name exists, replace it?".
- Tests: upload works; too big → 413; bad names → 400; no right → 403; overwrite needs the flag.

Optional, same part: **New folder**, **Rename**, **Delete** (delete asks to confirm, and needs the write right).

## 5. Part 4: "Run as web page": live preview of HTML the personas build (needs your security ruling first)

**What:** a persona builds `site/index.html` + CSS + JS; the person clicks **Preview** and sees it working, scripts included.

**Why it needs a ruling:** this runs JavaScript that a persona (or anyone with write access) wrote. If it ran on the app's own address, that script could act as the signed-in person: read their token, call the API, delete things.

**Safe design (recommended):**
- Serve previews **from a different address than the app**, e.g. `https://<id>.preview.<server address>` or a separate port, so browsers keep it isolated from the app and its sign-in.
- Static files only (no server-side code); read-only; a short-lived ticket in the address (part 2's mechanism, but valid e.g. 30 minutes and for one folder).
- Headers: no cookies, `Referrer-Policy: no-referrer`; the app embeds it in an iframe with `sandbox="allow-scripts"` (never `allow-same-origin`), or opens it in a new tab.
- Who may start a preview: decide (proposal: project admins and members).

**Your decisions before building:** (1) who may run previews; (2) a separate preview address per install (needs DNS/Caddy for domain installs; with Tailscale a separate port is simpler); (3) whether previews may make network requests out.

## 6. Order

1. **Part 1**, frontend only: gets most of the value. People can browse, view and download today's files.
2. **Part 2:** big files + file chips in chat.
3. **Part 3:** upload.
4. **Part 4:** after your security ruling.
