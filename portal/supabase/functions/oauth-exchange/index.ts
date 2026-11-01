// oauth-exchange — the middle server's EXCHANGE half (WP4, Step 6 road 2b).
//
// WHY: the vendor "Connect with NeuralOps" apps (Google Drive, Atlassian,
// GitHub) all DEMAND the app's client SECRET at the token exchange, even with
// PKCE — and the secret must never ship in the open image or reach any
// install. Every install lives at its own address, so the providers know only
// the portal: the consent bounces through the static relay page
// (portal/oauth-relay/index.html) back to the install, and the install then
// sends the CODE here; this function alone holds the secrets (Edge Function
// secrets) and performs the exchange. It stores NOTHING and answers the
// provider's token JSON verbatim — the tokens live only on the install.
//
// Also the REFRESH road: these providers want the secret when refreshing
// too, so grant_type "refresh_token" rides the same door.
//
// Deploy with "Verify JWT" ON (like device-request): installs send the anon
// key (nucleus authn/portal.py _headers). Secrets to set on this function:
//   GOOGLE_DRIVE_CLIENT_ID / GOOGLE_DRIVE_CLIENT_SECRET
//   ATLASSIAN_CLIENT_ID    / ATLASSIAN_CLIENT_SECRET
//   GITHUB_CLIENT_ID       / GITHUB_CLIENT_SECRET
//   PORTAL_RELAY_URL       (optional; defaults below — must EXACTLY match
//                           the redirect_uri the vendor apps are registered
//                           with and the one the install's authorize used)
//
// ABUSE SURFACE, considered: anyone may call this with a stolen code — but a
// code is single-use, expires in minutes, and redeems only with the matching
// PKCE verifier (which never left the install's signed state) and only
// against OUR fixed redirect_uri. The function never accepts a token
// endpoint or redirect_uri from the caller.

const DEFAULT_RELAY = "https://auth.neuralopsnexus.ai/oauth/relay";

const PROVIDERS: Record<string, { token: string; idEnv: string; secretEnv: string; json: boolean }> = {
  // json: Atlassian's token endpoint takes a JSON body; the others take form.
  "google-drive": { token: "https://oauth2.googleapis.com/token", idEnv: "GOOGLE_DRIVE_CLIENT_ID", secretEnv: "GOOGLE_DRIVE_CLIENT_SECRET", json: false },
  "atlassian": { token: "https://auth.atlassian.com/oauth/token", idEnv: "ATLASSIAN_CLIENT_ID", secretEnv: "ATLASSIAN_CLIENT_SECRET", json: true },
  "github": { token: "https://github.com/login/oauth/access_token", idEnv: "GITHUB_CLIENT_ID", secretEnv: "GITHUB_CLIENT_SECRET", json: false },
};

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") {
    return Response.json({ error: "POST only" }, { status: 405, headers: CORS });
  }

  let body: Record<string, unknown> = {};
  try {
    body = await req.json();
  } catch (_) { /* handled below */ }

  const provider = PROVIDERS[String(body.provider ?? "")];
  if (!provider) {
    return Response.json({ error: "Unknown provider." }, { status: 400, headers: CORS });
  }
  const clientId = Deno.env.get(provider.idEnv) ?? "";
  const clientSecret = Deno.env.get(provider.secretEnv) ?? "";
  if (!clientId || !clientSecret) {
    return Response.json(
      { error: `This provider's vendor app is not configured on the portal (set ${provider.idEnv} / ${provider.secretEnv}).` },
      { status: 503, headers: CORS });
  }

  const grantType = String(body.grant_type ?? "authorization_code");
  const fields: Record<string, string> = {
    grant_type: grantType,
    client_id: clientId,
    client_secret: clientSecret,
  };
  if (grantType === "authorization_code") {
    const code = String(body.code ?? "");
    if (!code) return Response.json({ error: "No code." }, { status: 400, headers: CORS });
    fields.code = code;
    // The one redirect the vendor apps know — never caller-supplied.
    fields.redirect_uri = Deno.env.get("PORTAL_RELAY_URL") ?? DEFAULT_RELAY;
    const verifier = String(body.code_verifier ?? "");
    if (verifier) fields.code_verifier = verifier;
  } else if (grantType === "refresh_token") {
    const refreshToken = String(body.refresh_token ?? "");
    if (!refreshToken) return Response.json({ error: "No refresh_token." }, { status: 400, headers: CORS });
    fields.refresh_token = refreshToken;
  } else {
    return Response.json({ error: "Unknown grant_type." }, { status: 400, headers: CORS });
  }

  let upstream: Response;
  try {
    upstream = await fetch(provider.token, {
      method: "POST",
      headers: provider.json
        ? { "Content-Type": "application/json", Accept: "application/json" }
        : { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: provider.json ? JSON.stringify(fields) : new URLSearchParams(fields).toString(),
    });
  } catch (e) {
    console.error("oauth-exchange: provider unreachable:", String(e));
    return Response.json({ error: "The provider could not be reached." }, { status: 502, headers: CORS });
  }

  let token: Record<string, unknown> = {};
  try {
    token = await upstream.json();
  } catch (_) { /* a non-JSON answer is a refusal below */ }

  // GitHub answers 200 even on failure, with an `error` field — normalize.
  if (!upstream.ok || token.error || !token.access_token) {
    const detail = String(token.error_description ?? token.error ?? `status ${upstream.status}`);
    console.warn("oauth-exchange refused:", String(body.provider), detail);
    return Response.json({ error: detail }, { status: 502, headers: CORS });
  }
  // Verbatim to the install; nothing is kept here.
  return Response.json(token, { headers: CORS });
});
