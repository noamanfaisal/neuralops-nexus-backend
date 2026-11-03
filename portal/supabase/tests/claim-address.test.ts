// Tests for functions/claim-address against a FAKE Hostinger and a loopback
// "server" that answers the port-80 proof. Nothing real is touched.
//
//   docker run --rm -v "$PWD/portal/supabase:/s:ro" denoland/deno:2.1.4 \
//     test --allow-net --allow-env /s/tests/claim-address.test.ts
//
// The function reads its settings at import, so the env is set first and the
// module is imported dynamically.

Deno.env.set("ADDRESS_TEST_MODE", "1");
Deno.env.set("ADDRESS_TEST_PROOF_PORT", "8702");
Deno.env.set("HOSTINGER_API_BASE", "http://127.0.0.1:8701");
Deno.env.set("HOSTINGER_API_TOKEN", "test-token");
Deno.env.set("ADDRESS_ZONE", "neuralopsnexus.ai");

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(msg);
}

// ── fake Hostinger ──────────────────────────────────────────────────────────
type RS = { name: string; type: string; ttl: number; records: { content: string }[] };
const zone: RS[] = [
  { name: "@", type: "A", ttl: 300, records: [{ content: "216.198.79.1" }] },
  { name: "www", type: "CNAME", ttl: 300, records: [{ content: "cname.vercel-dns.com." }] },
  { name: "auth", type: "CNAME", ttl: 300, records: [{ content: "cname.vercel-dns.com." }] },
  { name: "@", type: "MX", ttl: 300, records: [{ content: "mx1.titan.email" }] },
];
const calls: { method: string; body: Record<string, unknown> | null }[] = [];
let hostingerDown = false;

Deno.serve({ port: 8701, onListen() {} }, async (req) => {
  if (req.headers.get("authorization") !== "Bearer test-token") return new Response("no", { status: 401 });
  if (!new URL(req.url).pathname.endsWith("/api/dns/v1/zones/neuralopsnexus.ai")) return new Response("?", { status: 404 });
  if (hostingerDown && req.method !== "GET") return new Response("{}", { status: 500 });
  const body = req.method === "GET" ? null : await req.json();
  calls.push({ method: req.method, body });
  if (req.method === "GET") return Response.json(zone);
  if (req.method === "PUT") {
    for (const item of body.zone as RS[]) {
      if (body.overwrite) {
        for (let i = zone.length - 1; i >= 0; i--) {
          if (zone[i].name === item.name && zone[i].type === item.type) zone.splice(i, 1);
        }
        zone.push(item);
      } else {
        const existing = zone.find((z) => z.name === item.name && z.type === item.type);
        if (existing) existing.records.push(...item.records);
        else zone.push(item);
      }
    }
    return Response.json({ message: "ok" });
  }
  if (req.method === "DELETE") {
    for (const f of body.filters as { name: string; type: string }[]) {
      for (let i = zone.length - 1; i >= 0; i--) {
        if (zone[i].name === f.name && zone[i].type === f.type) zone.splice(i, 1);
      }
    }
    return Response.json({ message: "ok" });
  }
  return new Response("?", { status: 405 });
});

// ── the install's temporary port-80 answer ───────────────────────────────────
let served = "";
Deno.serve({ port: 8702, onListen() {} }, (req) => {
  const token = new URL(req.url).pathname.split("/").pop() ?? "";
  return token && token === served ? new Response(token) : new Response("nope", { status: 404 });
});

const { handle } = await import("../functions/claim-address/index.ts");

async function call(body: Record<string, unknown>, from = "127.0.0.1") {
  const r = await handle(new Request("http://fn/claim-address", {
    method: "POST",
    headers: { "content-type": "application/json", "x-forwarded-for": `${from}, 10.0.0.1` },
    body: JSON.stringify({ format: "env", ...body }),
  }));
  const text = await r.text();
  const kv: Record<string, string> = {};
  for (const line of text.trim().split("\n")) {
    const i = line.indexOf("=");
    if (i > 0) kv[line.slice(0, i)] = line.slice(i + 1);
  }
  return { status: r.status, kv, text };
}

const token = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
const opts = { sanitizeOps: false, sanitizeResources: false };
const OWN = /^[a-hj-km-np-z2-9]{6}\.on$/;
let first = { hostname: "", code: "" };

Deno.test({ name: "whoami answers the caller's address", ...opts, async fn() {
  const r = await call({ action: "whoami" }, "203.0.114.9");
  assert(r.status === 200 && r.kv.IP === "203.0.114.9", r.text);
}});

Deno.test({ name: "claim: a proven server gets a random .on name, written without overwrite", ...opts, async fn() {
  const t = token();
  served = t;
  const before = calls.length;
  const r = await call({ action: "claim", token: t });
  assert(r.status === 200, r.text);
  assert(/^[a-hj-km-np-z2-9]{6}\.on\.neuralopsnexus\.ai$/.test(r.kv.NEURALOPS_DOMAIN), r.text);
  assert(r.kv.NEURALOPS_PUBLIC_IP === "127.0.0.1", r.text);
  assert(/^[0-9a-f]{64}$/.test(r.kv.NEURALOPS_ADDRESS_CODE), "claim code is 32 random bytes");
  const put = calls.slice(before).find((c) => c.method === "PUT");
  assert(put && put.body!.overwrite === false, "a new name is written with overwrite:false");
  const record = r.kv.NEURALOPS_DOMAIN.replace(".neuralopsnexus.ai", "");
  assert(zone.some((z) => z.name === record && z.type === "A" && z.records[0].content === "127.0.0.1"), "A record exists");
  assert(calls.slice(before)[0].method === "GET", "the zone is read (and backed up) before the write");
  first = { hostname: r.kv.NEURALOPS_DOMAIN, code: r.kv.NEURALOPS_ADDRESS_CODE };
}});

Deno.test({ name: "claim: two installs never get the same name", ...opts, async fn() {
  const t = token();
  served = t;
  const r = await call({ action: "claim", token: t }, "127.0.0.3");
  assert(r.status === 200 && r.kv.NEURALOPS_DOMAIN !== first.hostname, r.text);
}});

Deno.test({ name: "claim: closed port 80 is refused with the firewall advice, nothing written", ...opts, async fn() {
  served = "";
  const before = calls.length;
  const r = await call({ action: "claim", token: token() }, "127.0.0.4");
  assert(r.status === 422 && r.kv.ERROR.includes("ports 80 and 443"), r.text);
  assert(!calls.slice(before).some((c) => c.method !== "GET"), "no DNS write");
}});

Deno.test({ name: "claim: private and odd IPs are refused before any fetch", ...opts, async fn() {
  for (const ip of ["10.0.0.5", "192.168.1.2", "172.20.0.1", "169.254.169.254", "100.100.1.1", "0.0.0.0", "1.2.3", "300.1.1.1"]) {
    const r = await call({ action: "claim", token: token(), ip });
    assert(r.status === 400, `${ip}: ${r.text}`);
  }
  const t = token();
  served = t;
  const r = await call({ action: "claim", token: t }, "10.1.2.3");  // caller behind private IP
  assert(r.status === 400 && r.kv.ERROR.includes("NEURALOPS_PUBLIC_IP"), r.text);
}});

Deno.test({ name: "claim: a bad token is refused", ...opts, async fn() {
  const r = await call({ action: "claim", token: "short" });
  assert(r.status === 400, r.text);
}});

Deno.test({ name: "update: same IP changes nothing in DNS", ...opts, async fn() {
  const before = calls.length;
  const r = await call({ action: "update", hostname: first.hostname, claim_code: first.code });
  assert(r.status === 200 && r.kv.CHANGED === "no", r.text);
  assert(calls.length === before, "no Hostinger call at all");
}});

Deno.test({ name: "update: a new IP replaces exactly this name's A record", ...opts, async fn() {
  const others = JSON.stringify(zone.filter((z) => !z.name.endsWith(".on")));
  const before = calls.length;
  const r = await call({ action: "update", hostname: first.hostname, claim_code: first.code, ip: "127.0.0.9" });
  assert(r.status === 200 && r.kv.CHANGED === "yes" && r.kv.NEURALOPS_PUBLIC_IP === "127.0.0.9", r.text);
  const put = calls.slice(before).find((c) => c.method === "PUT")!;
  const items = put.body!.zone as RS[];
  assert(put.body!.overwrite === true && items.length === 1 && items[0].type === "A", "scoped replace");
  const record = first.hostname.replace(".neuralopsnexus.ai", "");
  assert(items[0].name === record, "only this name");
  const now = zone.filter((z) => z.name === record);
  assert(now.length === 1 && now[0].records.length === 1 && now[0].records[0].content === "127.0.0.9", "one A record, new IP");
  assert(JSON.stringify(zone.filter((z) => !z.name.endsWith(".on"))) === others, "nothing else in the zone changed");
}});

Deno.test({ name: "update/release: a wrong code or foreign hostname is refused", ...opts, async fn() {
  const wrong = await call({ action: "update", hostname: first.hostname, claim_code: "a".repeat(64) });
  assert(wrong.status === 403, wrong.text);
  for (const hostname of ["www.neuralopsnexus.ai", "auth.neuralopsnexus.ai", "abcdef.demo.neuralopsnexus.ai", "abcdef.on.example.com", "@"]) {
    const r = await call({ action: "release", hostname, claim_code: first.code });
    assert(r.status === 400, `${hostname}: ${r.text}`);
  }
}});

Deno.test({ name: "release: deletes exactly its record; the name is never reusable", ...opts, async fn() {
  const record = first.hostname.replace(".neuralopsnexus.ai", "");
  const before = calls.length;
  const r = await call({ action: "release", hostname: first.hostname, claim_code: first.code });
  assert(r.status === 200, r.text);
  const del = calls.slice(before).find((c) => c.method === "DELETE")!;
  const filters = del.body!.filters as { name: string; type: string }[];
  assert(filters.length === 1 && filters[0].name === record && filters[0].type === "A", "scoped delete");
  assert(!zone.some((z) => z.name === record), "record gone");
  const again = await call({ action: "update", hostname: first.hostname, claim_code: first.code });
  assert(again.status === 403, "a released address cannot be updated");
}});

Deno.test({ name: "a failed DNS write leaves no claim behind", ...opts, async fn() {
  hostingerDown = true;
  const t = token();
  served = t;
  const r = await call({ action: "claim", token: t }, "127.0.0.5");
  hostingerDown = false;
  assert(r.status === 500, r.text);
}});

Deno.test({ name: "brake: a sixth claim for the same IP in a day is refused", ...opts, async fn() {
  let last = { status: 0, text: "" };
  for (let i = 0; i < 6; i++) {
    const t = token();
    served = t;
    last = await call({ action: "claim", token: t }, "127.0.0.6");
  }
  assert(last.status === 429, last.text);
}});

Deno.test({ name: "every DNS write ever made touched only <6>.on names", ...opts, fn() {
  for (const c of calls) {
    if (c.method === "PUT") for (const z of c.body!.zone as RS[]) assert(OWN.test(z.name), `PUT ${z.name}`);
    if (c.method === "DELETE") for (const f of c.body!.filters as RS[]) assert(OWN.test(f.name), `DELETE ${f.name}`);
  }
  for (const keep of ["www", "auth"]) assert(zone.some((z) => z.name === keep), `${keep} untouched`);
  assert(zone.filter((z) => z.name === "@").length === 2, "apex A + MX untouched");
}});

Deno.test({ name: "JSON answers when format is not env", ...opts, async fn() {
  const r = await handle(new Request("http://fn", { method: "POST", body: JSON.stringify({ action: "whoami" }), headers: { "x-forwarded-for": "8.8.8.8" } }));
  const j = await r.json();
  assert(j.IP === "8.8.8.8", JSON.stringify(j));
}});
