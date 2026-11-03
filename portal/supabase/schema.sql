-- NeuralOps portal — the claim-code table (device flow, Step 4's contract).
-- Paste into Supabase: Dashboard → SQL Editor → New query → Run.
--
-- SECURITY (owner's ruling 2026-10-18, "installer-only"): this table is
-- reachable ONLY by the edge functions (service role). RLS is enabled with
-- NO policies, so the anon key and signed-in users can never read or write
-- it directly — a signed-in user can only act through device-claim, which
-- demands the code from the install's own screen.

create table if not exists public.device_requests (
  id          uuid primary key default gen_random_uuid(),  -- the request_id: only the install knows it
  code        text not null,                               -- what the installer sees, e.g. 483-291
  server_url  text not null default '',                    -- which install asked (informational)
  status      text not null default 'pending',             -- pending | claimed | consumed | expired
  access_token text,                                       -- set at claim, handed to the install ONCE
  claimed_email text,                                      -- who claimed (informational)
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null default now() + interval '15 minutes'
);

-- Two different pending requests must never share a code.
create unique index if not exists device_requests_pending_code
  on public.device_requests (code) where (status = 'pending');

alter table public.device_requests enable row level security;
-- No policies on purpose: service-role-only access.

-- ---------------------------------------------------------------------------
-- phone-home (added 2026-10-18) — Step 6 ruling 5's collector table.
-- ONE value ever leaves a customer's server: its total token count, sent on
-- app open and app close. Each report is one row here; nothing else arrives.
-- Same security stance: RLS on, NO policies — only the phone-home edge
-- function (service role) can write, and nobody can read via the anon key.

create table if not exists public.phone_home_events (
  id            bigint generated always as identity primary key,
  install_token text not null,                       -- which install reported
  event         text not null check (event in ('open', 'close')),
  total_tokens  bigint not null check (total_tokens >= 0),
  received_at   timestamptz not null default now()
);

-- Fast "latest reports per install" lookups for the future portal dashboard.
create index if not exists phone_home_events_by_install
  on public.phone_home_events (install_token, received_at desc);

alter table public.phone_home_events enable row level security;
-- No policies on purpose: service-role-only access.

-- ---------------------------------------------------------------------------
-- claim guess-brake (added 2026-10-30) — the recorded TODO: a signed-in
-- account gets ~5 WRONG codes per 10 minutes, then waits. device-claim logs
-- each wrong, well-formed code here and refuses (429) once the window is
-- full; rows simply age out of the window (nothing to clean). Same security
-- stance: RLS on, NO policies — service-role (the edge function) only.

create table if not exists public.claim_attempts (
  id           bigint generated always as identity primary key,
  user_id      uuid not null,
  attempted_at timestamptz not null default now()
);

create index if not exists claim_attempts_by_user
  on public.claim_attempts (user_id, attempted_at desc);

alter table public.claim_attempts enable row level security;
-- No policies on purpose: service-role-only access.

-- ---------------------------------------------------------------------------
-- claim-address (added 2026-11-01) — free random addresses
-- <xxxxxx>.on.neuralopsnexus.ai for installs on a server with a public IP
-- (functions/claim-address). Same security stance: RLS on, NO policies —
-- only the edge function (service role) reads or writes.

create table if not exists public.address_claims (
  name         text primary key,                 -- the random part, e.g. k7x2m9
  ip           text not null,                    -- where its A record points now
  code_hash    text not null,                    -- SHA-256 of the server's claim code (the code itself is never stored)
  status       text not null default 'active' check (status in ('active', 'released')),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  last_seen_at timestamptz not null default now() -- refreshed by the server's address check (boot + every 6 hours)
);
-- Released names keep their row, so a name is never handed out twice.

alter table public.address_claims enable row level security;
-- No policies on purpose: service-role-only access.

-- The brakes' ledger: claim attempts per source and per target IP, updates
-- per name, all counted over the last 24 hours.
create table if not exists public.address_events (
  id   bigint generated always as identity primary key,
  kind text not null,                            -- claim | claim-source | claim-ip | update
  key  text not null,
  at   timestamptz not null default now()
);

create index if not exists address_events_by_kind_key
  on public.address_events (kind, key, at desc);

alter table public.address_events enable row level security;
-- No policies on purpose: service-role-only access.

-- The whole Hostinger zone, saved before every DNS write the function makes.
create table if not exists public.address_zone_backups (
  id       bigint generated always as identity primary key,
  taken_at timestamptz not null default now(),
  zone     jsonb not null
);

alter table public.address_zone_backups enable row level security;
-- No policies on purpose: service-role-only access.
