// claim-address — a free https address for an install on a server with a
// public IP (owner, 2026-11-01: "in case of live ip, will provide some ip from
// hostinger api ... address will be random ... pay if you want, otherwise use
// your own or tailscale; on next install it might be different").
//
// The installer (install.sh) and the `neuralops` command call this; nothing
// else does. Four actions, all POST JSON:
//
//   claim   {token, ip?}                 → a NEW random name <xxxxxx>.on.<zone>
//           The install first serves `token` at
//           http://<ip>/.well-known/neuralops-claim/<token>; this function
//           fetches it. That proves the IP really is that server AND that
//           port 80 is open (Caddy needs 80 + 443 for the certificate).
//   update  {hostname, claim_code, ip?}  → re-point the name when the
//           server's IP changes (AWS gives a new IP after every stop/start).
//           Also the heartbeat: last_seen_at is what a later cleanup uses.
//   release {hostname, claim_code}       → `neuralops uninstall` gives it back.
//   whoami  {}                           → the IP this function sees.
//
// ip: optional. Without it the caller's own address is used. A server whose
// outbound traffic leaves through a different IP (NAT gateway) passes its
// public IP explicitly — the port-80 proof still has to succeed AT that IP.
//
// "format": "env" answers plain KEY=value lines (errors: ERROR=...), so a bash
// installer needs no JSON parser. Otherwise JSON.
//
// SAFETY of the Hostinger token (it can usually manage the whole account):
//   - every write goes through assertOwnRecord(): ONLY names matching
//     <6 chars>.on can ever be written or deleted — never @, www, auth,
//     mail records or anything else;
//   - a new name is written with overwrite:false after checking the zone has
//     no record of that name at all; an IP change replaces exactly that one
//     name's A record (Hostinger's overwrite:true only touches RRs matching
//     the request's name AND type);
//   - the zone is backed up to address_zone_backups before every write;
//   - the caller never supplies a record name, type or zone.
//   - private, loopback and other non-public IPs are refused, so the proof
//     fetch can never be pointed inside anyone's network.
//
// "Verify JWT" may be ON or OFF: the installer and CLI send Supabase's public
// anon key either way (it adds no protection — it is public). The claim code
// (32 random bytes, only its SHA-256 is stored) is what guards
// update/release. Secrets to set on this function:
//   HOSTINGER_API_TOKEN   (required — set by the owner in the dashboard)
//   ADDRESS_ZONE          (optional, default neuralopsnexus.ai)
// Tables: schema.sql § claim-address (address_claims, address_events,
// address_zone_backups), RLS on, no policies — service role only.
import { createClient, type SupabaseClient } from "npm:@supabase/supabase-js@2";

const ZONE = (Deno.env.get("ADDRESS_ZONE") ?? "neuralopsnexus.ai").toLowerCase();
const SUFFIX = "on";                       // names are <random>.on.<zone>
const HOSTINGER_BASE = Deno.env.get("HOSTINGER_API_BASE") ?? "https://developers.hostinger.com";
const TTL = 300;                           // short, so an IP change spreads fast
const NAME_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"; // no 0/o, 1/l/i
const NAME_LENGTH = 6;
const PROOF_TIMEOUT_MS = 8000;

// Brakes (per 24 hours). Attempts count, not just successes: each claim makes
// this function fetch from an IP, so probing is braked too.
const CLAIMS_PER_SOURCE = 10;
const CLAIMS_PER_TARGET_IP = 5;
const CLAIMS_TOTAL = 200;
const UPDATES_PER_NAME = 48;

// Test harness only (portal/supabase/tests/claim-address.test.ts): an
// in-memory store, a fake Hostinger and a proof server on loopback. Never set
// on the deployed function.
const TEST_MODE = Deno.env.get("ADDRESS_TEST_MODE") === "1";
const PROOF_PORT = TEST_MODE ? Number(Deno.env.get("ADDRESS_TEST_PROOF_PORT") ?? "80") : 80;

const NAME_RE = new RegExp(`^[${NAME_ALPHABET}]{${NAME_LENGTH}}$`);
const RECORD_RE = new RegExp(`^[${NAME_ALPHABET}]{${NAME_LENGTH}}\\.${SUFFIX}$`);

class Refusal extends Error {
  constructor(public status: number, message: string) { super(message); }
}

// ── addresses ────────────────────────────────────────────────────────────────

function publicIPv4(raw: unknown): string | null {
  const m = String(raw ?? "").trim().match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!m) return null;
  const o = m.slice(1).map(Number);
  if (o.some((n) => n > 255)) return null;
  const [a, b, c] = o;
  if (TEST_MODE && a === 127) return o.join(".");
  const blocked =
    a === 0 || a === 10 || a === 127 || a >= 224 ||
    (a === 100 && b >= 64 && b <= 127) ||          // carrier NAT, Tailscale
    (a === 169 && b === 254) ||                     // link-local, cloud metadata
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 192 && b === 0 && (c === 0 || c === 2)) ||
    (a === 198 && (b === 18 || b === 19)) ||
    (a === 198 && b === 51 && c === 100) ||
    (a === 203 && b === 0 && c === 113);
  return blocked ? null : o.join(".");
}

function callerIP(req: Request): string {
  const forwarded = (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim();
  return forwarded || req.headers.get("cf-connecting-ip") || req.headers.get("x-real-ip") || "";
}

function nameFromHostname(hostname: unknown): string {
  const h = String(hostname ?? "").trim().toLowerCase().replace(/\.$/, "");
  const tail = `.${SUFFIX}.${ZONE}`;
  const name = h.endsWith(tail) ? h.slice(0, -tail.length) : "";
  if (!NAME_RE.test(name)) throw new Refusal(400, "That is not an address this service gave out.");
  return name;
}

function assertOwnRecord(record: string): void {
  // The one gate every Hostinger write passes through.
  if (!RECORD_RE.test(record)) throw new Error(`refusing to touch DNS record "${record}"`);
}

function randomName(): string {
  let out = "";
  const limit = 256 - (256 % NAME_ALPHABET.length); // no modulo bias
  while (out.length < NAME_LENGTH) {
    for (const byte of crypto.getRandomValues(new Uint8Array(16))) {
      if (byte < limit && out.length < NAME_LENGTH) out += NAME_ALPHABET[byte % NAME_ALPHABET.length];
    }
  }
  return out;
}

function randomHex(bytes: number): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

// ── the port-80 proof ────────────────────────────────────────────────────────

async function proofError(ip: string, token: string): Promise<string | null> {
  const port = PROOF_PORT === 80 ? "" : `:${PROOF_PORT}`;
  try {
    const r = await fetch(`http://${ip}${port}/.well-known/neuralops-claim/${token}`, {
      redirect: "manual",
      signal: AbortSignal.timeout(PROOF_TIMEOUT_MS),
    });
    const text = (await r.text()).slice(0, 200).trim();
    if (r.status !== 200) return `it answered on port 80 with status ${r.status}`;
    return text === token ? null : "something else answered on port 80";
  } catch (_) {
    return "nothing answered on port 80";
  }
}

// ── Hostinger DNS ────────────────────────────────────────────────────────────

type RecordSet = { name: string; type: string; ttl?: number; records?: { content: string }[] };

async function hostinger(method: "GET" | "PUT" | "DELETE", body?: unknown): Promise<unknown> {
  const token = Deno.env.get("HOSTINGER_API_TOKEN") ?? "";
  if (!token) throw new Refusal(503, "The address service is not configured yet (HOSTINGER_API_TOKEN).");
  const r = await fetch(`${HOSTINGER_BASE}/api/dns/v1/zones/${ZONE}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(20000),
  });
  const text = await r.text();
  if (!r.ok) throw new Error(`Hostinger ${method} answered ${r.status}: ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : null;
}

async function readZone(store: Store): Promise<RecordSet[]> {
  const zone = await hostinger("GET");
  if (!Array.isArray(zone)) throw new Error("Hostinger returned an unreadable zone");
  await store.saveZoneBackup(zone);
  return zone as RecordSet[];
}

async function writeA(record: string, ip: string, replace: boolean): Promise<void> {
  assertOwnRecord(record);
  await hostinger("PUT", {
    overwrite: replace,  // ALWAYS explicit: Hostinger's default is true
    zone: [{ name: record, type: "A", ttl: TTL, records: [{ content: ip }] }],
  });
}

async function deleteA(record: string): Promise<void> {
  assertOwnRecord(record);
  await hostinger("DELETE", { filters: [{ name: record, type: "A" }] });
}

// ── storage ──────────────────────────────────────────────────────────────────

type Claim = { name: string; ip: string; code_hash: string; status: string };

interface Store {
  nameTaken(name: string): Promise<boolean>;
  insertClaim(c: Claim): Promise<boolean>;          // false = name already taken
  getClaim(name: string): Promise<Claim | null>;
  updateClaim(name: string, fields: Partial<Claim> & { last_seen_at?: string }): Promise<void>;
  deleteClaim(name: string): Promise<void>;
  recentEvents(kind: string, key: string | null, sinceIso: string): Promise<number>;
  logEvent(kind: string, key: string): Promise<void>;
  saveZoneBackup(zone: unknown): Promise<void>;
}

class SupabaseStore implements Store {
  constructor(private db: SupabaseClient) {}
  private check(error: { message: string } | null, what: string) {
    if (error) throw new Error(`${what}: ${error.message}`);
  }
  async nameTaken(name: string) {
    const { data, error } = await this.db.from("address_claims").select("name").eq("name", name).maybeSingle();
    this.check(error, "address_claims read");
    return !!data;
  }
  async insertClaim(c: Claim) {
    const { error } = await this.db.from("address_claims").insert(c);
    if (error && (error as { code?: string }).code === "23505") return false;
    this.check(error, "address_claims insert");
    return true;
  }
  async getClaim(name: string) {
    const { data, error } = await this.db.from("address_claims")
      .select("name,ip,code_hash,status").eq("name", name).maybeSingle();
    this.check(error, "address_claims read");
    return (data as Claim | null) ?? null;
  }
  async updateClaim(name: string, fields: Record<string, unknown>) {
    const { error } = await this.db.from("address_claims")
      .update({ ...fields, updated_at: new Date().toISOString() }).eq("name", name);
    this.check(error, "address_claims update");
  }
  async deleteClaim(name: string) {
    const { error } = await this.db.from("address_claims").delete().eq("name", name);
    this.check(error, "address_claims delete");
  }
  async recentEvents(kind: string, key: string | null, sinceIso: string) {
    let q = this.db.from("address_events").select("id", { count: "exact", head: true })
      .eq("kind", kind).gte("at", sinceIso);
    if (key !== null) q = q.eq("key", key);
    const { count, error } = await q;
    this.check(error, "address_events read");
    return count ?? 0;
  }
  async logEvent(kind: string, key: string) {
    const { error } = await this.db.from("address_events").insert({ kind, key });
    this.check(error, "address_events insert");
  }
  async saveZoneBackup(zone: unknown) {
    const { error } = await this.db.from("address_zone_backups").insert({ zone });
    this.check(error, "address_zone_backups insert");
  }
}

class MemoryStore implements Store {
  claims = new Map<string, Claim & { last_seen_at?: string }>();
  events: { kind: string; key: string; at: string }[] = [];
  backups: unknown[] = [];
  nameTaken(name: string) { return Promise.resolve(this.claims.has(name)); }
  insertClaim(c: Claim) {
    if (this.claims.has(c.name)) return Promise.resolve(false);
    this.claims.set(c.name, { ...c });
    return Promise.resolve(true);
  }
  getClaim(name: string) { return Promise.resolve(this.claims.get(name) ?? null); }
  updateClaim(name: string, fields: Record<string, unknown>) {
    const c = this.claims.get(name);
    if (c) Object.assign(c, fields);
    return Promise.resolve();
  }
  deleteClaim(name: string) { this.claims.delete(name); return Promise.resolve(); }
  recentEvents(kind: string, key: string | null, sinceIso: string) {
    return Promise.resolve(this.events.filter((e) => e.kind === kind && (key === null || e.key === key) && e.at >= sinceIso).length);
  }
  logEvent(kind: string, key: string) {
    this.events.push({ kind, key, at: new Date().toISOString() });
    return Promise.resolve();
  }
  saveZoneBackup(zone: unknown) { this.backups.push(zone); return Promise.resolve(); }
}

let storeInstance: Store | null = null;
function store(): Store {
  if (!storeInstance) {
    storeInstance = TEST_MODE
      ? new MemoryStore()
      : new SupabaseStore(createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!));
  }
  return storeInstance;
}

// ── actions ──────────────────────────────────────────────────────────────────

const dayAgo = () => new Date(Date.now() - 24 * 3600_000).toISOString();
const hostnameOf = (name: string) => `${name}.${SUFFIX}.${ZONE}`;

function targetIP(body: Record<string, unknown>, req: Request): string {
  const given = body.ip !== undefined && body.ip !== null && String(body.ip).trim() !== "";
  const raw = given ? body.ip : callerIP(req);
  const ip = publicIPv4(raw);
  if (!ip) {
    throw new Refusal(400, given
      ? `${String(raw)} is not a public IPv4 address.`
      : `This server reached the internet from ${String(raw) || "an unknown address"}, which is not a public IPv4 address. ` +
        "If it has a public IP, run the installer again with NEURALOPS_PUBLIC_IP=<that IP>; otherwise choose Tailscale.");
  }
  return ip;
}

async function claim(body: Record<string, unknown>, req: Request) {
  const token = String(body.token ?? "");
  if (!/^[0-9a-f]{32}$/.test(token)) throw new Refusal(400, "A 32-character check token is required.");
  const ip = targetIP(body, req);
  const source = callerIP(req) || "unknown";
  const db = store();
  const since = dayAgo();

  if (await db.recentEvents("claim", null, since) >= CLAIMS_TOTAL) {
    throw new Refusal(429, "The free address service is busy today. Try again tomorrow, or choose Tailscale.");
  }
  if (await db.recentEvents("claim-source", source, since) >= CLAIMS_PER_SOURCE ||
      await db.recentEvents("claim-ip", ip, since) >= CLAIMS_PER_TARGET_IP) {
    throw new Refusal(429, "Too many address requests from this server today. Try again tomorrow.");
  }
  await db.logEvent("claim", source);
  await db.logEvent("claim-source", source);
  await db.logEvent("claim-ip", ip);

  const why = await proofError(ip, token);
  if (why) {
    throw new Refusal(422,
      `Could not reach this server at http://${ip} — ${why}. ` +
      "Open ports 80 and 443 to the internet (the cloud provider's firewall / security group, and ufw if it is on), then run the installer again.");
  }

  const zone = await readZone(db);
  const inZone = new Set(zone.map((r) => String(r.name ?? "").toLowerCase()));
  let name = "";
  for (let i = 0; i < 20 && !name; i++) {
    const candidate = randomName();
    if (inZone.has(`${candidate}.${SUFFIX}`) || await db.nameTaken(candidate)) continue;
    const code = randomHex(32);
    if (!await db.insertClaim({ name: candidate, ip, code_hash: await sha256(code), status: "active" })) continue;
    try {
      await writeA(`${candidate}.${SUFFIX}`, ip, false);
    } catch (e) {
      await db.deleteClaim(candidate);  // never leave a row without its record
      throw e;
    }
    name = candidate;
    return { NEURALOPS_DOMAIN: hostnameOf(name), NEURALOPS_PUBLIC_IP: ip, NEURALOPS_ADDRESS_CODE: code };
  }
  throw new Error("could not find a free name in 20 tries");
}

async function verifiedClaim(body: Record<string, unknown>): Promise<Claim> {
  const name = nameFromHostname(body.hostname);
  const code = String(body.claim_code ?? "");
  const row = await store().getClaim(name);
  // One answer for "unknown", "released" and "wrong code": nothing to enumerate.
  if (!row || row.status !== "active" || !/^[0-9a-f]{64}$/.test(code) || row.code_hash !== await sha256(code)) {
    throw new Refusal(403, "This server's address code does not match. A fresh install gets a new address.");
  }
  return row;
}

async function update(body: Record<string, unknown>, req: Request) {
  const row = await verifiedClaim(body);
  const ip = targetIP(body, req);
  const db = store();
  if (await db.recentEvents("update", row.name, dayAgo()) >= UPDATES_PER_NAME) {
    throw new Refusal(429, "Too many address updates today for this server.");
  }
  await db.logEvent("update", row.name);
  const now = new Date().toISOString();
  if (ip === row.ip) {
    await db.updateClaim(row.name, { last_seen_at: now });
    return { NEURALOPS_DOMAIN: hostnameOf(row.name), NEURALOPS_PUBLIC_IP: ip, CHANGED: "no" };
  }
  await readZone(db);                                  // backup before the write
  await writeA(`${row.name}.${SUFFIX}`, ip, true);    // replaces exactly this name's A record
  await db.updateClaim(row.name, { ip, last_seen_at: now });
  return { NEURALOPS_DOMAIN: hostnameOf(row.name), NEURALOPS_PUBLIC_IP: ip, CHANGED: "yes" };
}

async function release(body: Record<string, unknown>) {
  const row = await verifiedClaim(body);
  const db = store();
  await readZone(db);
  await deleteA(`${row.name}.${SUFFIX}`);
  // The row stays (released) so the name is never handed out again.
  await db.updateClaim(row.name, { status: "released" });
  return { RELEASED: hostnameOf(row.name) };
}

// ── HTTP ─────────────────────────────────────────────────────────────────────

function answer(result: Record<string, string>, status: number, asEnv: boolean): Response {
  if (asEnv) {
    const text = Object.entries(result).map(([k, v]) => `${k}=${v}`).join("\n") + "\n";
    return new Response(text, { status, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }
  return Response.json(result, { status });
}

export async function handle(req: Request): Promise<Response> {
  let body: Record<string, unknown> = {};
  try {
    body = await req.json();
  } catch (_) { /* empty body → unknown action below */ }
  const asEnv = body.format === "env";
  if (req.method !== "POST") return answer({ ERROR: "POST only." }, 405, asEnv);
  try {
    switch (body.action) {
      case "claim": return answer(await claim(body, req), 200, asEnv);
      case "update": return answer(await update(body, req), 200, asEnv);
      case "release": return answer(await release(body), 200, asEnv);
      case "whoami": return answer({ IP: callerIP(req) }, 200, asEnv);
      default: return answer({ ERROR: "Unknown action." }, 400, asEnv);
    }
  } catch (e) {
    if (e instanceof Refusal) return answer({ ERROR: e.message }, e.status, asEnv);
    console.error("claim-address failed:", String(e));
    return answer({ ERROR: "The address service hit an error. Try again in a few minutes, or choose Tailscale." }, 500, asEnv);
  }
}

Deno.serve(handle);
