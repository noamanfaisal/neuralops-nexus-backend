# The OAuth middle server (WP4 — "Connect with NeuralOps")

Every NeuralOps install lives at its own address, but Google/Atlassian/GitHub
accept only a FIXED redirect URI per OAuth app — and all three demand the
app's client SECRET at the token exchange, which must never ship in the image
or reach an install. So the middle server has TWO halves, both already built:

1. **The relay page** (`index.html`, static, this folder) — the one redirect
   URI the vendor apps know. It reads the install's address out of the OAuth
   state (signed, not encrypted) and bounces the browser home. Stores
   nothing, holds no secret.
2. **The exchange function** (`portal/supabase/functions/oauth-exchange/`) —
   the install sends the code there; only this function holds the vendor
   secrets and performs the exchange; the token JSON goes back to the install
   and is kept nowhere else. Also handles refreshes (same secret rule).

The nucleus side is live: the famous-three catalog presets carry
`redirect_mode: portal_relay` + `exchange_mode: portal`, and
`intelligence/oauth_client.py` routes the exchange + refresh through the
portal for them. **Only the client_ids are missing** — they ship empty until
the vendor apps below exist.

## Owner's steps (one-time)

### 0. Host the relay page

Serve `index.html` at exactly:

    https://neuralopsnexus.ai/oauth/relay

(owner, 2026-10-31 — the `NEURALOPS_OAUTH_RELAY_URL` default; its own setting,
so the claim page can stay on the portal host; e.g. copy to
`<webroot>/oauth/relay/index.html`). It must answer a
plain anonymous GET. Quick check: open
`…/oauth/relay?state=x` in a browser → "This connection could not be
completed" in words, not a 404.

### 1. Deploy the exchange function

Supabase → Edge Functions → Deploy new function → name EXACTLY
`oauth-exchange` → paste `functions/oauth-exchange/index.ts` → Deploy
("Verify JWT" stays ON, like device-request). No table needed.

### 2. Register the three vendor apps

Use the ONE redirect URI everywhere: `https://neuralopsnexus.ai/oauth/relay`
(the function's `DEFAULT_RELAY`; if you ever move it, set `PORTAL_RELAY_URL` on
the function AND `NEURALOPS_OAUTH_RELAY_URL` on every install to the same value).

| Provider | Where | Settings |
|---|---|---|
| **Google Drive** | console.cloud.google.com → APIs & Services → Credentials → Create OAuth client ID → type **Web application** (enable the Drive API on the project; configure the consent screen, publish it past "Testing" or tokens expire in 7 days) | Authorized redirect URI = the relay URI. Scope used: `https://www.googleapis.com/auth/drive.readonly` |
| **Atlassian** | developer.atlassian.com → Console → Create app → **OAuth 2.0 integration** | Callback URL = the relay URI. Permissions: Jira (`read:jira-work`, `write:jira-work`), Confluence (`read:confluence-content.all`); "offline access" rides the scope list automatically |
| **GitHub** | github.com → Settings → Developer settings → **OAuth Apps** → New OAuth App | Authorization callback URL = the relay URI |

### 3. Put the secrets ON THE FUNCTION (never anywhere else)

Supabase → Edge Functions → `oauth-exchange` → Secrets:

    GOOGLE_DRIVE_CLIENT_ID / GOOGLE_DRIVE_CLIENT_SECRET
    ATLASSIAN_CLIENT_ID    / ATLASSIAN_CLIENT_SECRET
    GITHUB_CLIENT_ID       / GITHUB_CLIENT_SECRET

### 4. Hand over the client_ids (PUBLIC ids only — never a secret)

Give the three client_ids to the developer → they go into
`intelligence/mcp_catalog.py`'s `oauth_preset.client_id` fields and ship with
the code. A non-empty client_id is what turns the "Connect with NeuralOps"
road on in the app; empty keeps paste-your-own only.

## Security model, in one breath

The relay forwards the provider's query verbatim to a FIXED path on whatever
host the signed state names — the code inside is redeemable only with the
PKCE verifier that never left the install's signed state, and only through
our fixed redirect URI. The exchange function accepts no token endpoint and
no redirect URI from callers, answers only its three hardcoded providers,
and stores nothing. Tokens live encrypted on the install; secrets live only
in the function's env.
