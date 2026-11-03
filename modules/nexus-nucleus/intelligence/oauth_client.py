"""
OAuth2 authorization-code flow for MCPServer.auth_type = OAUTH2.

Uses Authlib's plain httpx-based OAuth2Client (not the Django integration --
this backend is stateless/bearer-auth throughout, no Django session reliance
anywhere else, so state rides on django.core.signing instead of the session).

Step 6 (docs/NUCLEUS-REVAMP.md, ruling 8) added the three roads:

1. DYNAMIC CLIENT REGISTRATION (the MCP standard) -- ensure_client(): when an
   oauth2 server row has no client_id, nucleus discovers the server's OAuth
   metadata (/.well-known/oauth-protected-resource, then
   /.well-known/oauth-authorization-server or openid-configuration) and
   REGISTERS ITSELF, callback = this install's own address. No pre-registered
   list anywhere; every install introduces itself. Registered as a PUBLIC
   client (token_endpoint_auth_method "none") secured by PKCE.

2. THE PORTAL RELAY (the famous three -- GitHub, Google Drive, Atlassian):
   oauth_config.redirect_mode = "portal_relay" sends the provider's bounce to
   NEURALOPS_OAUTH_RELAY_URL (auth.neuralopsnexus.ai/oauth/relay) instead of this
   install. The signed
   state carries server_url; django signing is SIGNED, NOT ENCRYPTED, so the
   relay can base64-read server_url WITHOUT the key and bounce the browser
   on to {server_url}/api/v1/mcp-servers/oauth/callback/?code&state -- where
   the signature IS verified and the exchange happens. The relay stores
   nothing. (Providers that force a client secret need the relay-exchange
   variant -- portal-side, specced in the doc, designed when one demands it.)

3. PASTE-YOUR-OWN (unchanged, the universal/air-gapped fallback): the admin's
   own OAuth app; client_id in oauth_config, client_secret in secrets.

PKCE rides EVERY road now (the code_verifier travels inside the signed,
short-lived state) -- mandatory for the public clients road 1 creates,
harmless everywhere else.
"""
from datetime import timedelta

import httpx
from authlib.common.security import generate_token
from authlib.integrations.httpx_client import OAuth2Client
from django.conf import settings
from django.core import signing
from django.utils import timezone

_SIGNING_SALT = "mcp-oauth-state"
_STATE_MAX_AGE = 600  # 10 min to complete the provider's consent screen
DISCOVERY_TIMEOUT = 15


def _redirect_uri(cfg: dict | None = None) -> str:
    cfg = cfg or {}
    if cfg.get("redirect_mode") == "portal_relay":
        # Road 2: the provider only ever knows the relay's ONE address
        # (NEURALOPS_OAUTH_RELAY_URL, https://auth.neuralopsnexus.ai/oauth/relay).
        return getattr(settings, "NEURALOPS_OAUTH_RELAY_URL", "").rstrip("/")
    base = getattr(settings, "NEURALOPS_SERVER_URL", "").rstrip("/")
    # intelligence_router is mounted at "/" (see core/urls.py) -- the actual
    # path is /api/v1/mcp-servers/oauth/callback/. Must match the authorize
    # request AND the token exchange, or the provider rejects the exchange.
    return f"{base}/api/v1/mcp-servers/oauth/callback/"


def _is_github(authorize_endpoint: str | None) -> bool:
    from urllib.parse import urlsplit
    host = (urlsplit(authorize_endpoint or "").hostname or "").lower()
    return host == "github.com" or host.endswith(".github.com")


def build_authorize_url(server, frontend_origin: str) -> str:
    """
    frontend_origin: window.location.origin of the tab that asked for this --
    signed into state so the callback knows which origin's postMessage() to
    use (self-hosted deployments don't have one fixed frontend URL).

    The state also carries the PKCE code_verifier (one-time, 10-minute TTL,
    signed) and this install's server_url (for the portal relay's bounce).
    """
    cfg = server.oauth_config or {}
    code_verifier = generate_token(48)
    state = signing.dumps(
        {
            "server_id": str(server.id),
            "frontend_origin": frontend_origin,
            "code_verifier": code_verifier,
            "server_url": getattr(settings, "NEURALOPS_SERVER_URL", "").rstrip("/"),
        },
        salt=_SIGNING_SALT,
    )
    client = OAuth2Client(
        client_id=cfg["client_id"],
        scope=" ".join(cfg.get("scopes", [])),
        redirect_uri=_redirect_uri(cfg),
        code_challenge_method="S256",
    )
    # Extra provider-specific authorize params (Atlassian needs audience +
    # prompt=consent, Google needs access_type=offline + prompt=consent) so
    # the provider actually returns a refresh_token. Generic -- any auth-code
    # provider works by supplying its own endpoints/scopes/params.
    extra = {str(k): str(v) for k, v in (cfg.get("authorize_params") or {}).items()}
    # GitHub skips its screens entirely for an app the browser's account has
    # already authorized, so a second GitHub server silently got the SAME
    # account (found live 2026-11-02). prompt=select_account makes GitHub show
    # its account picker on every Connect -- pick a signed-in account or "use a
    # different account". Applies to rows created before this too, and to
    # paste-your-own GitHub OAuth apps; an explicit prompt param still wins.
    if _is_github(cfg.get("authorize_endpoint")) and "prompt" not in extra:
        extra["prompt"] = "select_account"
    url, _ = client.create_authorization_url(
        cfg["authorize_endpoint"], state=state, code_verifier=code_verifier, **extra,
    )
    return url


def _portal_exchange(cfg: dict, fields: dict) -> dict:
    """Road 2b (WP4): providers whose token exchange DEMANDS the vendor app's
    client secret (Google, Atlassian, GitHub). The secret never ships in the
    image and never reaches an install — the portal's oauth-exchange function
    alone holds it, so the code (+ PKCE verifier) goes THERE and the token
    JSON comes back. The portal stores nothing; the token lives only here."""
    from authn.portal import _headers

    url = getattr(settings, "SUPABASE_OAUTH_EXCHANGE_URL", "")
    if not url:
        raise ValueError("This preset exchanges through the portal, and no "
                         "portal exchange is configured (SUPABASE_OAUTH_EXCHANGE_URL).")
    body = {"provider": cfg.get("exchange_provider") or "", **fields}
    response = httpx.post(url, json=body, headers=_headers(), timeout=30)
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code != 200 or not isinstance(data, dict) or not data.get("access_token"):
        detail = (data.get("error") if isinstance(data, dict) else None) or f"status {response.status_code}"
        raise ValueError(f"The portal exchange was refused: {detail}")
    return data


def complete_callback(code: str, state: str) -> dict:
    """Exchange code→tokens, store them. Returns {"server_id", "frontend_origin"}."""
    from nucleus.models import MCPServer

    data = signing.loads(state, salt=_SIGNING_SALT, max_age=_STATE_MAX_AGE)
    server = MCPServer.objects.filter(
        id=data["server_id"], auth_type=MCPServer.AuthType.OAUTH2, is_active=True,
    ).first()
    if not server:
        raise ValueError("MCP server not found or no longer OAuth2.")

    cfg = server.oauth_config or {}
    if cfg.get("exchange_mode") == "portal":
        # Road 2b: the portal holds the vendor secret and does the exchange.
        fields = {"grant_type": "authorization_code", "code": code}
        if data.get("code_verifier"):
            fields["code_verifier"] = data["code_verifier"]
        token = _portal_exchange(cfg, fields)
    else:
        secrets = server.get_secrets()
        client = OAuth2Client(
            client_id=cfg["client_id"],
            client_secret=secrets.get("client_secret"),
            redirect_uri=_redirect_uri(cfg),
            headers={"Accept": "application/json"},
        )
        fetch_kwargs = {"code": code}
        if data.get("code_verifier"):
            fetch_kwargs["code_verifier"] = data["code_verifier"]
        token = client.fetch_token(cfg["token_endpoint"], **fetch_kwargs)
    _store_token(server, token)
    return {"server_id": data["server_id"], "frontend_origin": data["frontend_origin"]}


def ensure_client(server) -> tuple[bool, str]:
    """
    Road 1 (the MCP standard): make sure this server row has a usable OAuth
    client -- discovering the metadata and REGISTERING this install when the
    admin pasted nothing. (True, "") when ready; (False, a plain-words reason)
    when the admin must act. Never raises.
    """
    cfg = dict(server.oauth_config or {})
    if cfg.get("client_id") and cfg.get("authorize_endpoint") and cfg.get("token_endpoint"):
        return True, ""
    if not server.url:
        return False, "This server has no URL to discover OAuth settings from."

    from urllib.parse import urlsplit
    parts = urlsplit(server.url)
    origin = f"{parts.scheme}://{parts.netloc}"

    def _get_json(url: str) -> dict | None:
        try:
            response = httpx.get(url, timeout=DISCOVERY_TIMEOUT,
                                 headers={"Accept": "application/json"})
            if response.status_code == 200:
                data = response.json()
                return data if isinstance(data, dict) else None
        except Exception:  # noqa: BLE001 -- discovery failures are one answer below
            return None
        return None

    # Who is the authorization server? The resource says so; absent metadata
    # means the server IS its own auth server (both shapes are in the wild).
    auth_server = origin
    resource = _get_json(f"{origin}/.well-known/oauth-protected-resource")
    if resource and resource.get("authorization_servers"):
        auth_server = str(resource["authorization_servers"][0]).rstrip("/")

    meta = (_get_json(f"{auth_server}/.well-known/oauth-authorization-server")
            or _get_json(f"{auth_server}/.well-known/openid-configuration"))
    if not meta:
        return False, ("Could not discover this server's OAuth settings (no "
                       "/.well-known metadata answered). Create an OAuth app with the "
                       "provider and paste its client_id and endpoints instead.")
    authorize_endpoint = meta.get("authorization_endpoint")
    token_endpoint = meta.get("token_endpoint")
    if not authorize_endpoint or not token_endpoint:
        return False, "The server's OAuth metadata is missing its endpoints."

    if not cfg.get("client_id"):
        registration_endpoint = meta.get("registration_endpoint")
        if not registration_endpoint:
            return False, ("This provider doesn't offer dynamic client registration — "
                           "create an OAuth app with it and paste the client_id here.")
        try:
            response = httpx.post(registration_endpoint, json={
                "client_name": "NeuralOps",
                "redirect_uris": [_redirect_uri(cfg)],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                # A public client: the secret-free road, secured by PKCE.
                "token_endpoint_auth_method": "none",
            }, timeout=DISCOVERY_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            return False, f"Registration failed: {type(exc).__name__}: {exc}"
        if response.status_code not in (200, 201):
            return False, f"Registration refused ({response.status_code}): {response.text[:200]}"
        registered = response.json()
        if not registered.get("client_id"):
            return False, "Registration answered without a client_id."
        cfg["client_id"] = registered["client_id"]
        if registered.get("client_secret"):
            secrets = server.get_secrets()
            secrets["client_secret"] = registered["client_secret"]
            server.set_secrets(secrets)

    cfg["authorize_endpoint"] = cfg.get("authorize_endpoint") or authorize_endpoint
    cfg["token_endpoint"] = cfg.get("token_endpoint") or token_endpoint
    server.oauth_config = cfg
    server.save(update_fields=["oauth_config", "secrets_encrypted"])
    return True, ""


def has_usable_token(server) -> bool:
    """Is this OAuth2 server signed in? Either a refresh token is stored (the
    usual case), OR an access token is stored that never expires -- GitHub
    OAuth Apps issue exactly that: a non-expiring token and NO refresh token
    (found 2026-10-31 wiring "Connect with NeuralOps" for GitHub; requiring a
    refresh token would show a working connection as "not connected")."""
    cfg = server.oauth_config or {}
    secrets = server.get_secrets()
    if secrets.get("refresh_token"):
        return True
    access = secrets.get(cfg.get("token_env_var", "OAUTH_ACCESS_TOKEN"))
    return bool(access) and not cfg.get("expires_at")


def refresh_if_needed(server) -> bool:
    """
    Called from internal/api.py right before a server's secrets go to
    nexus-ai. Returns True if the server has (or now has, after a silent
    refresh) a valid token. Returns False if it genuinely needs the user
    to reconnect. No-op / True for non-OAuth2 servers.
    """
    from nucleus.models import MCPServer

    if server.auth_type != MCPServer.AuthType.OAUTH2:
        return True

    cfg = server.oauth_config or {}
    secrets = server.get_secrets()
    refresh_token = secrets.get("refresh_token")
    if not refresh_token:
        # No refresh token: usable only while the access token itself is --
        # a non-expiring one (GitHub OAuth Apps) always, an expiring one
        # until it runs out. Never connected = no access token at all.
        if not secrets.get(cfg.get("token_env_var", "OAUTH_ACCESS_TOKEN")):
            return False
        expires_at = cfg.get("expires_at")
        return (not expires_at or timezone.datetime.fromisoformat(expires_at)
                > timezone.now() + timedelta(seconds=60))

    expires_at = cfg.get("expires_at")
    if expires_at and timezone.datetime.fromisoformat(expires_at) > timezone.now() + timedelta(seconds=60):
        return True  # still valid, nothing to do
    if cfg.get("exchange_mode") == "portal":
        # Road 2b: these providers demand the vendor secret on REFRESH too.
        try:
            token = _portal_exchange(cfg, {"grant_type": "refresh_token",
                                           "refresh_token": refresh_token})
        except Exception:
            return False  # refused/unreachable -- needs a real re-auth
        _store_token(server, token)
        return True
    client = OAuth2Client(
        client_id=cfg["client_id"],
        client_secret=secrets.get("client_secret"),
        headers={"Accept": "application/json"},
    )
    try:
        token = client.refresh_token(cfg["token_endpoint"], refresh_token=refresh_token)
    except Exception:
        return False  # revoked/expired refresh_token -- needs a real re-auth

    _store_token(server, token)
    return True


def _store_token(server, token: dict) -> None:
    cfg = server.oauth_config or {}
    token_env_var = cfg.get("token_env_var", "OAUTH_ACCESS_TOKEN")

    secrets = server.get_secrets()
    secrets[token_env_var] = token["access_token"]
    if token.get("refresh_token"):  # some providers omit this on refresh
        secrets["refresh_token"] = token["refresh_token"]
    server.set_secrets(secrets)

    if token.get("expires_in"):
        cfg["expires_at"] = (timezone.now() + timedelta(seconds=int(token["expires_in"]))).isoformat()
    else:
        # A non-expiring token (GitHub OAuth Apps): an expiry left over from an
        # earlier connection would wrongly mark the new token stale.
        cfg.pop("expires_at", None)
    server.oauth_config = cfg

    server.save()
