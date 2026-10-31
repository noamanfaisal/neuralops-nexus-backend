"""
"Free to start" model presets (free-LLM onboarding WP1, owner's work order
2026-10-23: "install NeuralOps, talk to a model in 2 minutes, for $0").

Content, not prompt text and not a shared key: one preset per provider whose
FREE TIER a person can sign up for themselves — provider type, API base,
recommended model ids, the provider's own key page, a rate-limit note and a
data-usage note. Picking a tile in /add-model pre-fills everything except the
key; the person brings their own. A dead free tier is fixed by editing THIS
row, never a prompt on every deployment.

HARD RULES (the work order's, none bend): no shared or baked-in key, ever; no
automated signups — the human clicks every consent; a raw key never travels
through a chat message; honest notes on rate limits and training use; Ollama
is flagged as the private, local option.

Like mcp_catalog.py this is hand-kept content and a maintenance job
(docs/OPEN-ITEMS.md). Each entry is to be VERIFIED against the real provider
before release — endpoints and free tiers move.
"""

MODEL_PRESETS = [
    {
        "id": "github-models",
        "title": "GitHub Models",
        "provider": "openai_compatible",
        "api_base": "https://models.github.ai/inference",
        # publisher/name ids, as the GitHub Models endpoint spells them
        "model_ids": ["openai/gpt-4o-mini", "meta/llama-3.3-70b-instruct"],
        "key_page": "https://github.com/settings/personal-access-tokens",
        "key_hint": "A fine-grained personal access token with the models:read permission.",
        "rate_note": "Free for evaluation with per-model rate and token caps — fine for trying, not a team's production day.",
        "data_note": "Requests run through GitHub/Azure infrastructure; check GitHub's Models terms for your account tier.",
        "needs_key": True,
        "private": False,
    },
    {
        "id": "gemini",
        "title": "Google Gemini",
        "provider": "google",
        "api_base": None,
        "model_ids": ["gemini-2.0-flash"],
        "key_page": "https://aistudio.google.com/apikey",
        "key_hint": "An AI Studio API key — one click once you're signed in to Google.",
        "rate_note": "The free tier allows a handful of requests per minute and a daily cap.",
        "data_note": "Google may use free-tier prompts and replies to improve its products — don't send anything private.",
        "needs_key": True,
        "private": False,
    },
    {
        "id": "groq",
        "title": "Groq",
        "provider": "openai_compatible",
        "api_base": "https://api.groq.com/openai/v1",
        # Groq decommissioned the llama-3.x ids in Aug 2026 (found live
        # 2026-10-30: the provider 404s them); gpt-oss are the production
        # replacements — and strong tool-callers, right for agentic personas.
        "model_ids": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
        "key_page": "https://console.groq.com/keys",
        "key_hint": "A free Groq Cloud account; keys are minted on the console's Keys page.",
        "rate_note": "Very fast inference; the free tier has per-minute and per-day request caps.",
        "data_note": "Check Groq's data policy for the free tier before sending anything sensitive.",
        "needs_key": True,
        "private": False,
    },
    {
        "id": "openrouter-free",
        "title": "OpenRouter (:free models)",
        "provider": "openai_compatible",
        "api_base": "https://openrouter.ai/api/v1",
        "model_ids": ["meta-llama/llama-3.3-70b-instruct:free"],
        "key_page": "https://openrouter.ai/settings/keys",
        "key_hint": "A free OpenRouter account; use models whose id ends in :free.",
        "rate_note": ":free models are shared capacity — rate-limited and sometimes queued.",
        "data_note": "Many :free models log prompts for provider training — OpenRouter labels which; don't send anything private.",
        "needs_key": True,
        "private": False,
    },
    {
        "id": "mistral",
        "title": "Mistral",
        "provider": "openai_compatible",
        "api_base": "https://api.mistral.ai/v1",
        "model_ids": ["mistral-small-latest"],
        "key_page": "https://console.mistral.ai/api-keys",
        "key_hint": "La Plateforme's free experiment tier; keys live under API Keys.",
        "rate_note": "The free tier is rate-limited per second and per month.",
        "data_note": "Mistral's free experiment tier may use your data to improve its models — the paid tier does not.",
        "needs_key": True,
        "private": False,
    },
    {
        "id": "cerebras",
        "title": "Cerebras",
        "provider": "openai_compatible",
        "api_base": "https://api.cerebras.ai/v1",
        "model_ids": ["llama-3.3-70b"],
        "key_page": "https://cloud.cerebras.ai",
        "key_hint": "A free Cerebras Cloud account; keys are on the dashboard.",
        "rate_note": "Extremely fast; the free tier has daily token caps.",
        "data_note": "Check Cerebras' free-tier data policy before sending anything sensitive.",
        "needs_key": True,
        "private": False,
    },
    {
        "id": "ollama",
        "title": "Ollama (local — private)",
        "provider": "ollama",
        # From inside the deployment's containers, "localhost" is the
        # container itself — the machine running Ollama must be reachable
        # from the server. The tile says so instead of pretending.
        "api_base": "http://host.docker.internal:11434",
        "model_ids": ["llama3.2", "qwen2.5"],
        "key_page": "https://ollama.com/download",
        "key_hint": "No key at all — install Ollama and `ollama pull` a model first.",
        "rate_note": "As fast as the machine it runs on; no quotas, no account.",
        "data_note": "The private option: everything stays on your own hardware, nothing leaves it.",
        "needs_key": False,
        "private": True,
    },
]


def catalog() -> list[dict]:
    """The presets as the app reads them. A copy, so a caller cannot edit the module."""
    return [dict(entry) for entry in MODEL_PRESETS]


def entry(entry_id: str) -> dict | None:
    return next((dict(e) for e in MODEL_PRESETS if e["id"] == entry_id), None)


def helper_prompt() -> str:
    """
    WP2: the configure-channel helper persona's system prompt, RENDERED from
    the presets above so the provider list is never hardcoded in prompt text —
    the work order's rule (b). Changing a preset changes what newly created
    helpers know; nothing else to edit.
    """
    lines = []
    for preset in MODEL_PRESETS:
        bits = [f"{preset['title']}: {preset['key_hint']}", f"Key page: {preset['key_page']}" if preset["needs_key"] else f"Install: {preset['key_page']}"]
        bits.append(preset["rate_note"])
        bits.append(preset["data_note"])
        lines.append("- " + " ".join(bits))
    providers = "\n".join(lines)
    return (
        "You are this server's setup guide. Your one job: get this deployment from zero to a "
        "working model and persona, for free, honestly.\n\n"
        "Start with two questions: (1) cloud or fully local — should anything leave this machine? "
        "(2) which accounts do they already have — GitHub? Google? Then recommend ONE provider and "
        "walk them to a key.\n\n"
        "The free options you know (from the server's catalog — trust these over memory):\n"
        + providers + "\n\n"
        "Be honest, always: free tiers are rate-limited — fine for evaluating, not for a team's "
        "production day — and some free tiers use prompts for training (say which, from the notes "
        "above). The private path is Ollama: local, no account, nothing leaves the machine.\n\n"
        "The hand-off: send them to Intelligence → Models → Register a model, where the "
        "\"Free to start\" tiles pre-fill everything except the key. They paste the key there, "
        "press Check to verify it with the provider, then Register. NEVER ask for an API key in "
        "chat and refuse one if it is pasted — chat is stored; keys belong only in the Register "
        "dialog's key field, where they are encrypted. If a key is pasted in chat, tell them to "
        "revoke it on the provider's page and mint a fresh one.\n\n"
        "You cannot create models or personas yourself yet — guide, verify, and celebrate when "
        "their first persona answers."
    )
