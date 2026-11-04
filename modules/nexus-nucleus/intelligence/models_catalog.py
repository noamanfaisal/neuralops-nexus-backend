"""
The model catalog (owner, 2026-11-04): which model ids each provider takes,
for the model dialog's suggestions.

Found live 2026-11-04: the app suggested DeepSeek ids from OpenRouter's list,
and DeepSeek's own API refused every one of them. The owner's design:

  * the list is a FILE (models.json) -- a copy is built into the image, so a
    new or offline server always has one;
  * the server keeps a working copy on its own volume (MODELS_CATALOG_DIR)
    and, at worker start-up and once a day, downloads the latest from
    MODELS_CATALOG_URL -- but only when it is NEWER, READS CORRECTLY, and its
    SHA-256 matches the published checksum (MODELS_CATALOG_URL + ".sha256");
  * the app asks the server (GET /model-catalog/?provider=...) and nothing
    else.

The checksum proves the download arrived whole and unchanged in transit. It
does NOT prove who wrote it -- someone able to change the hosted file could
change the checksum too; a signature would cover that (not built).

The file is made by `manage.py build_models_catalog` from each provider's own
models list plus a small curated overrides file (recommended / hidden /
labels), and published to the installer repo next to install.sh.

Format (schema 1):
    {"schema": 1, "version": "2026-11-04.1", "generated_at": "...",
     "providers": {"deepseek": [{"id": "deepseek-flash", "label": "...",
                                 "recommended": true, "preview": false,
                                 "context_window": 1000000,
                                 "max_output_tokens": 393216}, ...], ...}}
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
BUNDLED = DATA_DIR / "models_catalog.json"
OVERRIDES = DATA_DIR / "models_catalog_overrides.json"
CACHE_NAME = "models.json"

PROVIDERS = ("anthropic", "openai", "google", "deepseek")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_VERSION_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.(\d{1,4})$")
_MAX_PER_PROVIDER = 500
_MAX_BYTES = 2 * 1024 * 1024

_memo: dict = {"at": 0.0, "data": None}
_MEMO_SECONDS = 60


class CatalogError(ValueError):
    """A catalog that must not be used: malformed, wrong schema, bad checksum."""


# ── reading and checking ─────────────────────────────────────────────────

def version_key(version: str) -> tuple:
    m = _VERSION_RE.match(version or "")
    if not m:
        raise CatalogError(f"bad catalog version {version!r}")
    return tuple(int(x) for x in m.groups())


def validate(data) -> dict:
    """The catalog as stored, or CatalogError. Unknown providers are dropped,
    never fatal -- a newer catalog may know providers this server doesn't."""
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise CatalogError("not a schema-1 model catalog")
    version_key(str(data.get("version", "")))
    providers = data.get("providers")
    if not isinstance(providers, dict):
        raise CatalogError("providers missing")
    clean: dict = {}
    for provider in PROVIDERS:
        rows = providers.get(provider, [])
        if not isinstance(rows, list) or len(rows) > _MAX_PER_PROVIDER:
            raise CatalogError(f"{provider}: not a list (or too long)")
        seen = set()
        out = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not _ID_RE.match(row["id"]):
                raise CatalogError(f"{provider}: a model without a valid id")
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            entry = {
                "id": row["id"],
                "label": str(row.get("label") or row["id"])[:200],
                "recommended": bool(row.get("recommended", False)),
                "preview": bool(row.get("preview", False)),
                "context_window": _count(row.get("context_window")),
                "max_output_tokens": _count(row.get("max_output_tokens")),
            }
            out.append(entry)
        clean[provider] = out
    return {"schema": 1, "version": data["version"],
            "generated_at": str(data.get("generated_at", "")), "providers": clean}


def _count(value) -> int | None:
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def parse(raw: bytes, expected_sha256: str | None = None) -> dict:
    if len(raw) > _MAX_BYTES:
        raise CatalogError("catalog too large")
    if expected_sha256 is not None:
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected_sha256.strip().lower():
            raise CatalogError("checksum does not match")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogError(f"not JSON: {exc}") from exc
    return validate(data)


def _cache_dir() -> Path | None:
    d = getattr(settings, "MODELS_CATALOG_DIR", "")
    return Path(d) if d else None


def _read_cache() -> dict | None:
    """The downloaded copy, re-checked against its own stored checksum (a
    half-written or hand-edited file is ignored, never trusted)."""
    d = _cache_dir()
    if not d:
        return None
    path, sha = d / CACHE_NAME, d / (CACHE_NAME + ".sha256")
    try:
        return parse(path.read_bytes(), sha.read_text())
    except FileNotFoundError:
        return None
    except (OSError, CatalogError) as exc:
        logger.warning("[models-catalog] cached copy ignored: %s", exc)
        return None


def bundled() -> dict:
    return parse(BUNDLED.read_bytes())


def current(use_memo: bool = True) -> dict:
    """The catalog to serve: the downloaded copy when it is newer than the one
    built into the image, otherwise the built-in one."""
    now = time.monotonic()
    if use_memo and _memo["data"] is not None and now - _memo["at"] < _MEMO_SECONDS:
        return _memo["data"]
    base = bundled()
    cached = _read_cache()
    chosen = cached if cached and version_key(cached["version"]) > version_key(base["version"]) else base
    _memo.update(at=now, data=chosen)
    return chosen


def models_for(provider: str) -> dict:
    cat = current()
    return {"version": cat["version"], "models": cat["providers"].get(provider, [])}


# ── refreshing from the hosted copy ─────────────────────────────────────

def refresh(http_get=None) -> str:
    """Download the hosted catalog and keep it if it is newer, whole and
    valid. Never raises: offline or a bad file leaves what we have."""
    url = getattr(settings, "MODELS_CATALOG_URL", "")
    d = _cache_dir()
    if not url or not d:
        return "skipped: MODELS_CATALOG_URL or MODELS_CATALOG_DIR not set"
    if http_get is None:
        import httpx

        def http_get(u):
            r = httpx.get(u, timeout=30.0, follow_redirects=True)
            r.raise_for_status()
            return r.content
    try:
        raw = http_get(url)
        sha = http_get(url + ".sha256").decode("ascii", "replace").split()[0]
    except Exception as exc:  # noqa: BLE001 -- offline installs stay silent
        logger.info("[models-catalog] refresh skipped (offline or source down): %s", exc)
        return f"skipped: {type(exc).__name__}"
    try:
        new = parse(raw, sha)
    except CatalogError as exc:
        logger.warning("[models-catalog] downloaded catalog refused: %s", exc)
        return f"refused: {exc}"
    have = current(use_memo=False)
    if version_key(new["version"]) <= version_key(have["version"]):
        return f"unchanged: have {have['version']}, hosted {new['version']}"
    try:
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write(d / CACHE_NAME, raw)
        _atomic_write(d / (CACHE_NAME + ".sha256"), (sha + "\n").encode())
    except OSError as exc:
        logger.warning("[models-catalog] could not save the new catalog: %s", exc)
        return f"failed to save: {exc}"
    _memo.update(at=0.0, data=None)
    logger.info("[models-catalog] updated %s -> %s", have["version"], new["version"])
    return f"updated: {have['version']} -> {new['version']}"


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ── building a new catalog (release tooling) ─────────────────────────────

# What a provider's own /models answer holds that is NOT a chat model the
# dialog should offer (embeddings, speech, images, dated snapshots...).
_NOT_CHAT = {
    "openai": re.compile(
        r"(embedding|audio|realtime|tts|transcribe|whisper|dall-e|image|moderation|search|"
        r"instruct|babbage|davinci|computer-use|deep-research|codex-mini|sora|-\d{4}-\d{2}-\d{2}$)"),
    "google": re.compile(r"(embedding|tts|image|live|aqa|robotics|computer-use|veo|imagen|lyria|"
                         r"deep-research|native-audio|learnlm|gemma)"),
    "anthropic": re.compile(r"^$"),
    "deepseek": re.compile(r"^$"),
}
_CHAT_PREFIX = {
    "openai": re.compile(r"^(gpt-|o\d|chatgpt-)"),
    "google": re.compile(r"^gemini-"),
    "anthropic": re.compile(r"^claude-"),
    "deepseek": re.compile(r"^deepseek-"),
}


def provider_ids(provider: str, api_key: str, http_get_json) -> list[tuple[str, str]]:
    """(id, label) pairs from the provider's own models list."""
    if provider == "openai":
        body = http_get_json("https://api.openai.com/v1/models", {"Authorization": f"Bearer {api_key}"})
        rows = [(m["id"], m["id"]) for m in body.get("data", [])]
    elif provider == "anthropic":
        body = http_get_json("https://api.anthropic.com/v1/models?limit=1000",
                             {"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        rows = [(m["id"], m.get("display_name") or m["id"]) for m in body.get("data", [])]
    elif provider == "google":
        body = http_get_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
                             {"x-goog-api-key": api_key})
        rows = [(m["name"].split("/", 1)[-1], m.get("displayName") or m["name"])
                for m in body.get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    elif provider == "deepseek":
        body = http_get_json("https://api.deepseek.com/models", {"Authorization": f"Bearer {api_key}"})
        rows = [(m["id"], m["id"]) for m in body.get("data", [])]
    else:
        return []
    keep = _CHAT_PREFIX[provider]
    drop = _NOT_CHAT[provider]
    rows = [(i, label) for i, label in rows if keep.search(i) and not drop.search(i)]
    if provider in ("openai", "deepseek"):
        # Their lists come in no useful order: newest-looking first
        # (anthropic and google already answer newest first).
        rows.sort(key=lambda r: _natural(r[0]), reverse=True)
    return rows


def _natural(model_id: str) -> list:
    return [(1, int(t)) if t.isdigit() else (0, t) for t in re.split(r"(\d+)", model_id)]


def probe(provider: str, api_key: str, model_id: str, http_post) -> bool:
    """Does this id answer a one-word chat the way NeuralOps calls it?
    Found 2026-11-04: OpenAI's /v1/models still lists retired ids (gpt-4,
    gpt-5-codex...) and Responses-only ones (gpt-5-pro) that the chat
    endpoint the engine uses refuses -- a listed id is not a working id.
    `http_post(url, headers, json) -> status code`. Costs a few tokens."""
    msg = [{"role": "user", "content": "Reply with: ok"}]
    if provider == "openai":
        return http_post("https://api.openai.com/v1/chat/completions",
                         {"Authorization": f"Bearer {api_key}"},
                         {"model": model_id, "messages": msg, "max_completion_tokens": 64}) == 200
    if provider == "deepseek":
        return http_post("https://api.deepseek.com/chat/completions",
                         {"Authorization": f"Bearer {api_key}"},
                         {"model": model_id, "messages": msg, "max_tokens": 64}) == 200
    if provider == "anthropic":
        return http_post("https://api.anthropic.com/v1/messages",
                         {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                         {"model": model_id, "messages": msg, "max_tokens": 16}) == 200
    if provider == "google":
        return http_post(f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent",
                         {"x-goog-api-key": api_key},
                         {"contents": [{"parts": [{"text": "Reply with: ok"}]}]}) == 200
    return False


def build(*, previous: dict, overrides: dict, live: dict[str, list[tuple[str, str]]],
          sizes, today: str) -> dict:
    """A new catalog. `live` holds the providers whose own list we could read
    (provider -> [(id, label)]); a provider without one keeps the previous
    file's list. `sizes(provider, id)` -> (context_window, max_output) from the
    price table. Overrides: hidden ids are dropped, recommended ones go first,
    labels replace the provider's names, `preview` marks previews."""
    providers: dict = {}
    for provider in PROVIDERS:
        o = overrides.get(provider, {})
        hidden = set(o.get("hidden", []))
        recommended = list(o.get("recommended", []))
        labels = o.get("labels", {})
        preview = set(o.get("preview", []))
        if provider in live:
            pairs = live[provider]
        else:
            pairs = [(r["id"], r["label"]) for r in previous.get("providers", {}).get(provider, [])]
            pairs += [(i, i) for i in o.get("fallback", []) if i not in {p for p, _ in pairs}]
        rows = []
        for model_id, label in pairs:
            if model_id in hidden:
                continue
            ctx, out = sizes(provider, model_id)
            rows.append({"id": model_id, "label": labels.get(model_id, label),
                         "recommended": model_id in recommended,
                         "preview": model_id in preview or "preview" in model_id,
                         "context_window": ctx, "max_output_tokens": out})
        order = {mid: n for n, mid in enumerate(recommended)}
        rows.sort(key=lambda r: (0, order[r["id"]]) if r["id"] in order else (1 if not r["preview"] else 2, ""))
        providers[provider] = rows
    prev_version = str(previous.get("version", ""))
    n = 1
    m = _VERSION_RE.match(prev_version)
    if m and prev_version.startswith(today + "."):
        n = int(m.group(4)) + 1
    from django.utils import timezone

    return validate({"schema": 1, "version": f"{today}.{n}",
                     "generated_at": timezone.now().isoformat(timespec="seconds"),
                     "providers": providers})


def dump(catalog: dict) -> tuple[bytes, str]:
    raw = (json.dumps(catalog, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest()
