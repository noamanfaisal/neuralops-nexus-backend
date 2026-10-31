# NeuralOps — what is still missing

**Started 2026-10-19 (owner's ask: "add a document what is missing, we will
run it later").** Plain language. Each item says WHAT is missing, WHERE the
gap is, and roughly HOW BIG the job is. When an item is built, move its line
to the matching BUILT block in FRONTEND-REVAMP.md / NUCLEUS-REVAMP.md and
strike it here with the date.

---

## ROADMAP TO RELEASE (consolidated 2026-10-22, owner + Claude)

**Stage 1 — finish the acceptance pass (now).** The live list is in
TEST-CASES.md §Progress: suites (engine 117 / frontend 1143), seed push +
TC-09a, default-router @Plain test, fallback (broken key) or defer, fresh
web_search + web_fetch + Web approval knob, TC-12 shell guard, external MCP
tiles TC-13/14, chains, team/invites, recall-pane inspection, gateway, UI
sweep, TC-38 embedder check. Plus the two pending git commits.

**Stage 2 — fix round. ~~REMOVALS~~ BUILT + VERIFIED 2026-10-22 21:49
(suites green at the new targets; three test-only stragglers fixed in the
first run — record in FRONTEND-REVAMP §2k).**
The removals the owner ruled 2026-10-22 15:50 are DONE in both repos:
DELIVERABLES (model, routes, schemas, Keep button, keep-dialog, pane, API
lib, hooks, 6 nucleus + 11 frontend tests) and RECALL (RecallEntry model,
recall API + internal route, Persona.recall_enabled everywhere, the engine's
recall kind + embed endpoints, the pane, the "Remembered N things" chip and
the whole `recalled` wire field, 5 nucleus + 1 engine + 10 frontend tests).
Migrations: nucleus **0042_remove_recall_and_deliverables** (drops both
tables + the persona flag, ROWS INCLUDED) and authn
**0007_recall_deliverable_rights_cleanup** (drops recall.manage +
deliverable.manage rights; registry 49 → 47). Removed code is parked in
nucleus `.step0-removed/` and web `_attic/removed-panes/`. Also ridden in
this round (both ruled): viewers may POST (the composer shows for everyone;
only persona calls are refused — the server already behaved this way) and
the supervisor verdict prompt got the pass-unless-broken bias (style is
never a defect; REDO needs a named, fixable problem). New suite targets:
nucleus **464**, engine **117 passed / 5 skipped**, frontend **121 files /
1122 tests**. This also VOIDS the recall-writer half of the memory-pass
hardening entry (parts 2/5 — no pane, no writer needed); parts 1 and 3
(don't store tool transcripts; retrieval text never poses as this turn's
output) still stand. Remaining Stage 2: the owner's comments file keyed by
TC id, if any comments come.

**Stage 3 — release chores.** ~~Rotate the exposed OpenAI/Anthropic keys~~
(DONE 2026-10-28, owner terminated the old keys); Supabase cleanups (owner
does these LAST, right before release) (legacy
device-verify function, test-install-1 phone_home_events row); regenerate
engine requirements.lock at next image build (7c); `seed_catalog
--regenerate` + commit as the release's catalog snapshot.

**EASY INSTALL + FREE TRIAL — RULED (owner, 2026-10-24 19:48: "lets do it
phase by phase, a single click installer on linux terminal (whether using
dpkg, docker whatever) / a click to host it for server for 1 hour … this
thing we need to do immediately"). TOP OF STAGE 4, ahead of chains v2** —
the owner's reason: "this is the biggest blocker, that normal people wont
even try it". Full design + open rulings: the owner's private project doc
easy-install-and-free-trial-plan.
- **Phase 1 — one-command Linux installer: BUILT 2026-10-24, reworked &
  verified 2026-10-25** (upstream rework, merged 2026-10-30: multi-arch
  images, `linux/amd64` + `linux/arm64` on Docker Hub; the ONE question is
  now Tailscale Funnel [default] or a domain via Caddy; interrupted installs
  cleanly RESUME — secrets kept, previous choices re-used; complete installs
  stop safely; shellcheck clean, 0 warnings on both scripts; verified LIVE on
  Ubuntu 24.04 aarch64: fresh install, resume after interrupt, re-run
  "already installed" exit 0, backup and status). Original build record kept
  below. Mechanism (owner left it to Claude): a
  bash installer over the SAME production compose stack that smoke-passed
  2026-10-22 — no new image, nothing to push. `install.sh` (repo root):
  checks Linux/x86_64/memory/disk, installs Docker if missing (asks), asks
  ONE question (domain → Caddy automatic HTTPS, or no domain → Cloudflare
  quick tunnel, no account), fetches the compose file + nginx config,
  writes infra/app env, generates secrets ONCE (never regenerated — the
  2026-10-24 stale-password lesson), chowns projects to 1000, starts the
  stack, creates nexus_vectors + the vector extension, runs migrate /
  seed_permissions / seed_catalog, restarts the workers, waits for the API,
  prints the address + the claim steps. Installs `neuralops`
  (neuralops/neuralops-cli.sh): status / address / update [ver] (backs up
  first, re-fetches compose + nginx + itself, migrates) / backup (pg_dumpall
  + secrets + projects tarball; RESTORE stays the Stage 4 backup item) /
  logs / restart / stop / start / uninstall (data kept unless the person
  types DELETE; volumes removed by NAME, never `down -v`). Tunnel installs
  get a boot-time systemd unit that re-syncs the changed address. Re-running
  the installer over an install stops and points at `neuralops update`.
  Lint: shellcheck clean (all severities). COMPOSE fixes found on the way
  (production profile, affect every install, not just the installer):
  nucleus / nexus-ai / centrifugo had NO restart policy (app stayed down
  after a reboot) → `unless-stopped`; postgres + redis (no password) were
  published on all interfaces (internet-reachable on a VPS, past the host
  firewall) → bound to 127.0.0.1 by default (POSTGRES_BIND / REDIS_BIND to
  override); nginx bind made configurable (NGINX_BIND, installer sets
  127.0.0.1); new `caddy` (profile https) and `cloudflared` (profile
  tunnel) services. The all-in-one single-container image (plan Phase A)
  is DEFERRED as an optimization the installer can switch to later — the
  compose-based installer reaches "one command" today with no new image.
  Fetch source: defaults to mapax-io/neuralops-nexus main (works once the
  release is merged there); NEURALOPS_RAW=file:///<clone> tests from a
  local checkout.
- **RULINGS 2026-10-25:** the installer's no-domain path is **Tailscale
  Funnel** (anyone with the link; `serve` as a setting) — the Cloudflare
  quick tunnel is dropped; a half-finished install must RESUME (`.installed`
  marker) — **BUILT & VERIFIED** in the upstream rework. Step 2 is NOT a
  self-serve trial but **one-click demo servers for
  people who request a demo**: we create a cloud server (AWS / Google /
  Azure, on free startup credits), the installer runs unattended, and
  `create_owner --email <requester>` reserves ownership for that verified
  email; each server deletes itself at the end. The demo tool is **Python in
  a separate PRIVATE repo** (`neuralops-demo`); the installer stays bash.
  **Tasks 1.1, 1.2, 1.4 and 2.1 BUILT by the developer** from
  docs/EASY-INSTALL-TASKS.md (tasks 1.1–1.5, 2.1–2.8, each with exact
  behaviour + proof); design in docs/EASY-INSTALL.md. Task 2.1
  (`create_owner --email`) landed in public nucleus: model `OwnerReservation`
  + authn migration **0008**, non-interactive `--email` reservation storage,
  auto-claim on verified email sign-in/connect via `auth_verify`, 7-test
  suite `authn.tests_step4` (upstream's full nucleus suite green at 471 OK;
  re-verify at our higher count when the dev stack next runs — migration
  0008 must be applied then).
- **RULINGS 2026-10-28:** (1) demo DNS = **Hostinger's DNS API**; the domain
  stays at Hostinger; demo addresses are `<id>.demo.neuralopsnexus.ai`
  (EASY-INSTALL-TASKS task 2.3, with safety rules: overwrite always false,
  only `*.demo` names, never /reset, zone backup before each write).
  (2) Step 2 becomes an AUTOMATIC web service: the website's "Request a
  demo" calls our FastAPI service, which (after email confirmation + bot
  check + rate limits) creates the server on whichever provider still has
  free credits, switching provider when one runs out, then DNS, install,
  `create_owner --email`, emails the link. No human approval. Spec lives in
  the private repo (DEMO-SERVICE.md + DEMO-DNS-HOSTINGER.md), not here.
  Notes: always-free tiers are ~1 GB (too small); OCI's free ARM servers
  need ARM images first; RunPod pods can't run Docker.
- **Sign-up emails — DONE 2026-10-28 (owner):** Supabase's built-in mailer
  only sends to team members, ~2/hour, on every plan, so Supabase now uses
  custom SMTP through Resend (domain neuralopsnexus.ai verified, DKIM at
  Hostinger; smtp.resend.com:587, sender no-reply@neuralopsnexus.ai).
  Confirmation emails now reach any address.

**EASY INSTALL + DEMO SERVICE — HANDED TO THE DEVELOPER (owner,
2026-10-28):** the developer owns the whole track, including the open
decisions, and is finishing it for a merge. Not tracked in this file any
more; his reference specs are docs/EASY-INSTALL-TASKS.md and (private repo)
DEMO-SERVICE.md + DEMO-DNS-HOSTINGER.md.

**FILE VIEWER — OPEN WORK (spec: docs/FILE-VIEWER-PANE.md; the nucleus
browse/download/view endpoints are BUILT and tested, see §3):**
- [x] Part 1 — **Files pane**: BUILT 2026-10-29 (G1). Fifth pane in the rail
  (minServer 1.0.0 — an older server gets no pane): breadcrumb + list
  (folders first, human sizes, relative age, truncated note), Refresh, view
  in `iframe srcdoc` + `sandbox=""` (no allow-scripts — pinned by test; the
  server's CSP header doesn't ride into srcdoc), authorised blob download,
  worded 409 ("no folder yet") / 413 / 415 (sentence + Download button) and
  empty states. Files: `lib/api/files.ts`, `components/shell/files-pane.tsx`
  (+ its test file), `pane-ids.ts`, `pane-defs.tsx` (+ test updated to five
  panes); TESTER-GUIDE T-04/T-44 updated.
- [ ] Part 2 — one-time **download tickets** (60 s, single use) for big
  files + **file chips** in chat when a persona writes a file.
- [ ] Part 3 — **upload** (new `project.files_write` right, own size limit,
  no overwrite without the flag; optional new folder / rename / delete).
- [ ] Part 4 — **live HTML preview** on a SEPARATE origin (scripts can't
  reach the app's sign-in). Owner rules first: who may preview, which
  address, network access.

**FOUND 2026-10-27 (connecting the aaf-analytics MCP to an Analyst persona):**
- **BUG — MCP tokens are sent WITHOUT "Bearer " (affects EVERY authenticated
  MCP server: static secrets AND OAuth).** pydantic-ai 2.55's `MCP` capability
  (the engine always uses its local path — `native` defaults to False) copies
  `authorization_token` VERBATIM into the `Authorization` header
  (pydantic_ai/capabilities/mcp.py `_build_local`). The engine passes the raw
  secret (toolset_builder.py `_bearer_token`), so servers receive
  `Authorization: <token>` and refuse it ("missing or invalid bearer token").
  Verified live: same token, both sides matching by hash, refused until the
  secret was saved as `Bearer <token>` by hand — then it worked. Servers
  without auth (Shop-Demo) were never affected, which is why it went unseen.
  **FIX (task for the owner's developer):** in
  `modules/nexus-ai/ai_engine/pydantic_ai_system/tools/toolset_builder.py`,
  `_bearer_token` returns `"Bearer " + token` (token stripped) unless the value
  already starts with `bearer ` (any letter case); empty/missing → None. Same
  for the oauth2 branch. Existing secrets saved with a manual `Bearer ` keep
  working (no double prefix). Tests (engine, tests/test_mcp_dial.py): raw →
  `Bearer raw` · `Bearer raw` unchanged · `bearer raw` unchanged · padded
  `  raw  ` → `Bearer raw` · empty/None → None · oauth2 token → prefixed; plus
  one dial test where the fake MCP server asserts the header it received is
  `Bearer <token>`. Optional UI hint under the Secret field: "Paste the token
  only — NeuralOps adds 'Bearer' itself." Proof: engine suite green at +N;
  re-save the aaf-analytics secret WITHOUT `Bearer ` → a new topic → the
  Analyst's tool calls succeed. (Follow-up worth noting: servers that want a
  different header, e.g. `X-API-Key`, are not supported yet.)
- **HONESTY SLIP — a reply claimed a tool attempt that never happened.** After
  three real auth failures in one topic, the Analyst (answered by DeepSeek)
  twice wrote "Attempted now: aaf_analytics__get_schema → missing or invalid
  bearer token" with NO tool call behind it (no tool row in the chat; the
  analytics server log shows no call). A fresh topic fixed it. The engine's
  honesty rule covers invented tool RESULTS but not invented tool ATTEMPTS.
  To design: (1) prompt rule — never say a tool was called/attempted in this
  reply unless it was; (2) a check — a reply that names a tool as run with no
  matching tool call in the run gets flagged (or the claim stripped). Ties to
  the memory-pass hardening family.
- **BUG — approval pauses fail once a run has read large tool output
  ("Nothing is waiting on this message").** Found live 2026-10-27 with the
  Dashboard persona (aaf-analytics tools on Ask): the first pauses saved
  (201), then a pause after two or three query results was refused by
  nucleus — `RequestDataTooBig: Request body exceeded
  settings.DATA_UPLOAD_MAX_MEMORY_SIZE` → 500 on
  `/api/v1/internal/messages/<id>/pause/` → the engine job failed
  (ai_system.respond → save_pause raise_for_status) while the approval card
  stayed on screen → every Allow/Deny answered 409 Conflict. CAUSE:
  `core/settings.py` sets `DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024`
  GLOBALLY — its comment says it is for the public hook endpoint
  (scheduling/hooks_api.py), but it also caps every internal engine→nucleus
  POST, and a pause carries the whole run so far (history + tool results).
  Usage / AI-request-log posts can hit the same wall. **FIX (task for the
  owner's developer):** raise the global limit (e.g. 16 MB — the internal
  routes are already behind the internal key and blocked at nginx), and keep
  the hook's protection where it belongs: in the hook view, refuse a body over
  64 KB from the Content-Length header BEFORE the body is read (413 with a
  worded message). Tests (nucleus): a pause POST with a ~1 MB state → 201 and
  stored intact; the public hook with a 100 KB body → 413, with a normal body
  → still fires; an internal usage batch of ~200 KB → 201. Also worth it in
  the same change: when the pause save fails, the engine should end the reply
  with a clear error event so the card is withdrawn instead of left dangling.
  Proof: Dashboard with analytics tools on Ask, several queries + approvals in
  one reply → no 500, Allow resumes the run. WORKAROUND until then: analytics
  tools on Auto (no pause, no problem) — recommended anyway, they are
  read-only.
- ~~The aaf-analytics `neuralops` token was shown in a chat on 2026-10-27 —
  rotate it~~ **DONE 2026-10-28 (owner terminated the old tokens).**
- **CHECK — prompt caching on Claude models.** The Usage page (project mktv,
  2026-10-27) showed claude-sonnet-5-5 with 660K input tokens and **0
  cached** (DeepSeek: 48% cached), so every Claude call paid full price for
  the whole history. Check whether the engine enables Anthropic prompt
  caching (cache breakpoints on the system prompt + history); if not, turn
  it on and confirm cached tokens appear on the Usage page.

**FIX ROUND — CODED 2026-10-28 night, in the COPY `/data/code/neuralops-fixwork`
(+ `-frontend`), NOT in this folder — demo freeze. Pending: commit on a
`fixround` branch, merge after the demo, run all three suites, restart.**
What is in the copy, each with tests:
1. 64 KB pause bug: global cap → 16 MB (`core/settings.py`); the public hook
   enforces its own 64 KB from Content-Length before parsing
   (`scheduling/hooks_api.py`); tests: 1 MB pause → 201 intact, 200 KB usage
   batch → 201 (`internal/tests.py`), 70 KB hook body → 413 at the door,
   non-JSON → 422 (`scheduling/tests.py`).
2. Pause-save failure: the engine ends the reply with a worded error
   (`ai_system.PauseSaveFailed`) instead of a dangling card; `chat/reasons.py`
   maps it ABOVE the 5xx rule, so it is never blamed on the model provider;
   tests in `tests/test_approvals.py` (fake nucleus gained `pause_status`)
   and `chat/tests_reasons.py` (new).
3. Bearer prefix: `toolset_builder._bearer_token` adds `Bearer ` (both auth
   kinds, no double prefix, empty → None); tests incl. an on-the-wire header
   assertion (`tests/test_mcp_dial.py`). After merge: re-save the
   aaf-analytics secret WITHOUT the hand-typed `Bearer `.
4. Stray text / glued markers: the event mapper puts a line break between a
   run's text parts (`event_mapper.py`); `markers.py` accepts an opener glued
   after sentence punctuation (every type, the pre-marker prose is dropped —
   it is router/filler junk); the frontend clears the bubble on
   `deep_escalation` (message-store) and `stripLeakedMarkers` strips glued
   markers + renders any surviving marker token as a code span, never an
   autolink. Tests: `test_output_types.py` ot10/ot11, directives + message-
   store tests.
5. Persona "Default answer format" respected: resolver order is directive →
   persona default (not auto) → classifier → text (`resolver.py`,
   `ai_system.py`); the persona dialogs gained **Auto — decide per question**
   and NEW personas default to Auto. Tests ot12/ot13.
   NOTE FOR THE OWNER after merge: existing personas all STORE "text" (the
   old dialog default), so they will answer in text until set to Auto — set
   @Dashboard (and any chart-ish persona) to Auto or Chart deliberately.
6. Change password now verifies the CURRENT password first (Supabase
   sign-in check before updateUser) with a third field in the dialog;
   wrong current → refused, nothing changed (`profile-dialog.tsx` + tests).
7. Rename + unarchive topic (B9, tester finding 3): nucleus gained
   `POST …/topics/{t}/unarchive/` (right `topic.archive`; restores the
   soft-deleted row, idempotent) and topic listings accept
   `?include_archived=true`, each row carrying `archived`
   (`workspace/services.py` get_topic_any/unarchive_topic, `api.py`,
   `schema.py`; `TopicUnarchiveTests` in `workspace/tests.py`). Frontend:
   a rename pencil per row (gated `topic.update`, never on the configure
   topic — its provisioned title is the one signal that marks it) opening
   a dialog seeded with the current name, and a collapsed “Archived
   chats” section (fetched only when opened) with a Restore button per
   row (gated `topic.archive`; the restored chat opens; a 404 from an
   older server gets the worded “needs a newer NeuralOps” toast) —
   `chat-list-panel.tsx`, `lib/api/workspace.ts` (listTopics
   include_archived + unarchiveTopic), `use-workspace.ts`
   (useArchivedTopics / useUnarchiveTopic / useRenameTopic), new
   `chat-list-panel.test.tsx`.
8. Model Edit dialog Save-lock (B14, ruled 2026-10-28): nucleus
   ModelConfig gained `last_check_ok_at` (migration 0043), SET only by the
   check endpoint when the values just checked are exactly the stored ones
   (a pre-save check of edited values never stamps), CLEARED by any PATCH
   that changes the reach (provider, model id, api_base, key — re-saving
   the same key keeps it); `ModelConfigOut.last_check_ok_at` ships it
   (`intelligence/services.py` _stamp_check_pass + update_model_config,
   `schema.py`, `api.py`; `SaveLockTests` in `intelligence/tests.py`).
   Frontend Edit dialog: never-passed opens with Save locked + a hint;
   Check (current form values) unlocks; a reach change re-locks; after a
   reach-changing save the dialog fires one check of the newly stored
   values so the server stamps them (no wasted double-check — pinned by
   test); a server without the field NEVER locks (`models-tab.tsx` +
   "Save-lock" describe in `models-tab.test.tsx`).
9. Detach-model wording (B10): VERIFIED, no code needed — the backend 409
   already names the personas ("still used by: …"), and the frontend's
   useSetModelConfigProject surfaces e.message as the toast verbatim.
10. Claude prompt caching (B8): the engine never asked Anthropic to cache —
    `agent_builder.py` now sets `anthropic_cache: True` (pydantic-ai 2.55's
    automatic, forward-moving cache breakpoint) on Anthropic specs only;
    UsageReader already reads cache_read/cache_write, so cached tokens will
    show on the Usage page from the first long topic after the merge. Tests
    test_b8_* in `tests/test_7b_generation.py`.
11. Honesty slip (B7): two defences. (a) The tool-catalog prompt section now
    bans invented ATTEMPTS like invented results ("never say a tool was
    called, attempted or failed in this reply unless that call really
    happened in this reply") — `prompts/layout.py`. (b) A narrow detector
    (`core/honesty.py` + hook in `ai_system.py`): a reply that names one of
    the persona's EXACT tool names on a completed-claim line (attempted/ran/
    called/… or a → arrow) for a tool with no matching call in the run gets
    a visible "Correction (added automatically)" appended (text replies;
    always logged) — memory ("earlier we ran …"), intent ("I will run …")
    and honest inability ("couldn't call …") are all spared, pinned by
    `tests/test_honesty.py` (unit + two e2e through the harness).
12. TESTER-GUIDE "nudge" (B11): T-13 now says what a nudge IS (an ordinary
    message typed while the persona is still replying), docs only. The
    composer hint while a reply streams stays a nice-to-have.
Still open from the fix round: ONLY T16 (retest the long-topic table after
B3+B4 — needs the tester's persona + topic, owner's A7).

**TESTER ROUND 2026-10-28 (owner's tester, TESTER-GUIDE):** passed T15–T20,
T32–T34, and the walkthrough items photo, about/version, pane rail,
project/channel, chat + realtime, register + check, bad-key check, attach,
persona, first reply, stop, session. Findings:
1. **BUG (T16):** in a long existing topic, "draw a table" came back as a
   raw preflight plan (JSON summary/steps/risks) shown as code; the same
   prompt in a NEW topic renders a table. Investigate why the turn took the
   preflight shape (history imitation? a gate firing?) and why it rendered
   as text (no markers; `recover_unmarked` only covers chart/choice). Same
   family as the 2026-10-27 marker/format bugs. Need from tester: persona +
   topic.
2. **SECURITY (Change password):** no current-password check, and slow.
   Require the current password and verify it (Supabase re-auth) before
   `updateUser`; show a saving state. Test: wrong current password →
   refused, nothing changed.
3. **MISSING:** rename a topic; unarchive an archived topic (archived
   topics cannot be brought back today). CHECKED 2026-10-28: rename is
   **frontend-only** — the backend already has it (`PATCH
   /projects/{p}/channels/{c}/topics/{t}/` with `title`, right
   `topic.update`). Unarchive needs **both**: a new
   `POST …/topics/{t}/unarchive/` (right `topic.archive`) + UI (list
   archived topics with `include_archived=true`, a Restore action).
4. **UX (detach model):** refusing to detach a model a project persona uses
   is right, but the message must name those personas and say "change their
   model first".
5. **DOCS (TESTER-GUIDE "Stop and nudge"):** say that a nudge is a message
   sent WHILE the persona is still replying, to steer it; consider a hint
   in the composer while a reply streams.
6. **OPEN:** the tester's "minor error message issue" in T15–T20 — get the
   test number, the exact text and a screenshot.

**Stage 4 — post-release build queue (details in "Post-test build queue"
below). SCHEDULE AGREED 2026-10-23 evening (owner: "i need these things to
be done asap"; each item ships as its own point release when done, the
owner verifying daily):**
1. **Week of Oct 26–30 → 1.1.0:** Chains rework v2, all remaining 5 parts
   (rename, query input, @ChainName invocation, model-only steps, role
   labels — supervisor bias already shipped in 1.0.0).
2. **Week of Nov 2–6 → 1.2.0:** Connector tiles with icons (owner's 8-
   service list; OAuth2 flow exists) + MCP suggest-attach option 2 +
   FREE-LLM ONBOARDING parts 1–2 (catalog presets + configure-channel
   helper — full entry below).
3. **Week of Nov 9–13 → 1.3.0:** AI audit log (full reply anatomy +
   "investigate with a model") + backup & restore (one-command dump, DB +
   media, secrets.env excluded; restore onto a fresh install).
4. **Week of Nov 16–20 → 1.4.0:** Setup copilot admin tools (the owner's
   11-tool gateway list) + the secure key card + free-LLM one-click
   connects + file viewer pane (security ruling first).
   UPDATE 2026-10-28: file viewer parts 1–3 (pane, download tickets,
   upload) don't need the ruling and can ship earlier; only part 4 (live
   preview) waits for it.

Still parked (unchanged): local login UI, gateway mint-for-others,
delegation/tool_access/approval_scope toggles, portal guess-brake,
cached-tokens column on the usage rollups, usage by-kind split UI.

---

## 1. Persona seats the UI cannot set (found 2026-10-19, walkthrough)

**BUILT (2026-10-19, same night, straight after the ruling):** PersonaIn/
PatchIn/Out carry router_model_config_id + deep_model_config_id (+
clear_router/clear_deep; refs on Out); services resolve/validate/set both
seats (seat ≠ standard enforced, attach-to-project enforced); both persona
dialogs show Router + Deep pickers in the ruled order (Model → Router →
Deep → Fallbacks → Advisor) with attach-&-use, inline register per seat,
and primary-takeover clearing; cards chip "router · X" / "deep · X".
Tests: nucleus PersonaSeatTests (7) + 4 new frontend tests. NO migration
(the FKs existed).

**DEFAULT ROUTER — RULED PROJECT-WIDE (owner, 2026-10-19 23:43), BUILT
2026-10-21 (owner said "make all missing changes"; UI home picked by Claude:
the PROJECT OVERVIEW PANE — owner may move it to the configure topic).**
What was built:
- `Project.default_router_model` FK + migration **0039_project_default_router**;
- project API: ProjectOut ships `default_router_model {id, name}` (a retired
  model reads as none); PATCH project takes `default_router_model_id` /
  `clear_default_router` under project.update — the model must be active,
  this company's and ATTACHED to the project (update_project validates);
- `internal/api.py`: an EMPTY persona router seat fills from the PROJECT
  default; the persona's own seat wins; a default equal to the persona's
  STANDARD model is skipped (screening with itself saves nothing); the
  dormant CompanyAIConfig.default_router_model is no longer read at all
  (tests_step3 pins all four rules);
- UI: "Default router" section on the project overview pane — one select of
  the project's attached models, saved on change, [clear] = "No default
  router"; read-only sentence without project.update; too-old-server note;
- tests: nucleus ProjectDefaultRouterTests (workspace) + the reworked
  tests_step3 case; frontend +3 pane tests.
Still parked: delegation / tool_access / approval_scope.

**SMART ROUTER — RULED (owner, 2026-10-20 17:40: "no round robin, the
router will select … based on pros and cons of every model"), BUILT
2026-10-21 (all three repos; suites pending owner verify).** The deep seat
is a BENCH (0..N models, ordered) and the ROUTER picks the hand-over target
by each model's routing_notes. What was built:
- NUCLEUS: `PersonaDeepModel` bench table (like PersonaFallbackModel,
  ordered, first = default pick) + migration **0038_deep_bench** (creates
  the table AND seeds it from any single deep seat already set, so nothing
  configured is lost). `Persona.deep_model` FK stays as a LEGACY MIRROR of
  the bench's first entry (services keep it synced) so an older engine
  image keeps escalating. PersonaIn/PatchIn: `deep_model_config_ids` (list,
  [] clears on patch); the old `deep_model_config_id` + `clear_deep` still
  work (a one-item bench / an empty one) so old callers don't 400.
  PersonaOut + PersonaInternal ship `deep_models` (bench, in order) AND
  `deep_model` (= first). Wiring rules per bench member (≠ standard, same
  company, attached to project); delete/detach guards now also cover the
  ROUTER seat and the bench (they only covered model/advisor/fallbacks).
  PersonaSeatTests 7 → 10.
- ENGINE: bench models ride PersonaSpec.models as multiple DEEP entries
  (first = default — every existing road untouched); `models_for(role)` on
  PersonaSpec; `Escalate.target_model`; `router_instructions(bench)` lists
  a 2+ bench with each model's notes (1 or 0 → the plain text);
  `pick_deep_model()` matches name or model_id case-insensitively, falls
  back to the bench's first; ai_system runs the deep turn ON THE PICK
  (generator `primary=` override; budget + context_window follow the pick);
  an older nucleus's single deep_model maps to a one-item bench
  (nucleus_client). Tests r7/r8/r9 (113 → 116 passed).
- FRONTEND: DeepBenchPicker (ordered list like fallbacks, no cap, first
  row chips "default pick"); both persona dialogs swap the single Deep
  picker for it (order stays Model → Router → Deep → Fallbacks → Advisor);
  payloads send `deep_model_config_ids` (never the legacy single field);
  edit diffs positionally, [] clears; attach-&-use covers every bench
  model; cards chip `deep · X` for one, `deep bench · N` for more; the
  model dialogs' strengths field landed with 7b. Tests: 4 reworked + 3 new
  (1128 → 1131).
- Standard stays SINGLE and required, as assumed (owner did not veto).
- Considered and DECLINED (same exchange): round-robin / random multi-seat.
- VERIFY (owner): see FRONTEND-REVAMP §2g.


The database and the engine are READY for all of these (Step 3 built them,
the engine tests prove them) — but the public persona API (PersonaIn/Out)
and the builder dialogs never expose them, so nothing can set them:

- **Router seat** (`Persona.router_model`) — a cheap model that screens each
  message: answers trivial ones itself, passes the rest on. Falls back to
  `CompanyAIConfig.default_router_model` — which ALSO has no public API
  field (CompanyAIConfigIn lacks it), so the company default is equally
  unreachable.
- **Deep seat** (`Persona.deep_model`) — the heavyweight the router (or the
  standard model) hands a hard question to. Without a settable deep seat the
  whole escalation road (deep_escalation event, "Handed to <model>" note,
  already rendered by the chat since chunk 2) stays dormant.
- **Delegation** (`Persona.delegation_enabled`) — the supervisor checkbox:
  gives the persona `call_persona` (one-shot, depth 1). Engine: built,
  billed, tested (test_delegation). No API field, no checkbox.
- **Tool mounting + approval scope** (`Persona.tool_access` all|selected,
  `Persona.approval_scope` topic|requester_only) — stored, shipped on the
  internal API, enforced; never settable from outside.

**RULED (owner, 2026-10-19 23:33): road A — build the per-persona seats**
("actually squence is to have router, standard, deep, cheaper, fallback,
advisor etc … why dont we first add it" — his "cheaper" IS the router).
This supersedes the earlier "i dont know". Scope of the build: expose
router_model_config_id + deep_model_config_id on PersonaIn/PatchIn/Out (the
Django FKs already exist — NO migration) + Router/Deep pickers in both
persona dialogs with the seat rules below + CompanyAIConfigIn gains
default_router_model (fills an EMPTY router seat server-wide). Engine:
already built and tested — nothing to change. Delegation / tool_access /
approval_scope stay parked (not part of this ruling). NEXT BUILD SESSION,
first in line, ahead of 7b. The two roads, for the record:

- **A. Per-persona seats** — the table below; full control, heavier builder.
- **B. Server-side simplicity** — personas keep only Model/Advisor/Fallbacks
  as today; router and deep live ONLY as company-wide defaults (one setting,
  every persona benefits), or are dropped entirely. The engine supports both
  roads already — this is purely a product decision.

If road A is picked, the sketch:
One "Model seats" picture, in plain words:

| Seat | Required? | What it does |
|---|---|---|
| **Standard** | ALWAYS (it is today's "Model") | answers every normal message |
| **Router** | optional | a cheap screener: answers trivial messages itself, passes the rest to Standard, may escalate |
| **Deep** | optional | the heavyweight a hard question is handed to ("Handed to <model>" in chat) |
| Advisor | optional (already in the UI) | a second opinion Standard consults mid-reply — never takes over |
| Fallbacks 0..3 | optional (already in the UI) | answer only when Standard FAILS |

Seat rules to enforce in the builder (matching what the engine already does):
- Standard is always required — the other seats hang off it.
- Router alone is fine (screen + pass to Standard, no escalation target — hard
  questions just stay on Standard).
- Deep alone is fine too: with no Router, the STANDARD model itself decides to
  hand over (engine test r5) — but the owner's expectation reads naturally as
  "a deep seat usually comes with a router + standard", so the builder should
  HINT that pairing (not block the lone-deep case the engine supports).
- A seat must differ from Standard (same rule the advisor already has).

**The job:** one backend change (PersonaIn/PatchIn/Out gains
router/deep model ids + clear flags, services validation with the same
project-attachment rules as the advisor; CompanyAIConfigIn gains
default_router_model; + nucleus tests) and one frontend change (Router and
Deep ModelPicker slots in a "Model seats" section + the delegation /
tool-access / approval-scope toggles; + tests). Medium.

## 2. MCP server screen — stored tool list + Refresh (FRONTEND-REVAMP §2.7)

**BUILT (2026-10-21, frontend half — nucleus was already built).**
MCPServer type gained `tools` + `refreshMcpTools()`; the card of every
external HTTP/SSE server sums its stored list in the meta line ("3 tools ·
1 read / 2 write", or "no stored tools") with a **Refresh tools** button
(mcp_server.update) whose failed dial shows the 502 reason VERBATIM beside
it; the edit dialog gained a read-only **Tools** section listing each stored
tool with its read / write / write-(unlabeled) badge. Internal rows and
stdio stay untouched (no stored lists yet). +4 frontend tests.

## 3. File viewer (FRONTEND-REVAMP §2.4)

Nucleus half BUILT (browse/download/view endpoints with the sandbox rules).
Frontend DEFERRED by the owner ("if not now, later"). **The job:** one new
pane/screen + error wording for 404/400/409/413/415; medium.
**SPEC WRITTEN 2026-10-28: docs/FILE-VIEWER-PANE.md** — part 1 the pane
(frontend only; view via `iframe srcdoc` + `sandbox` without allow-scripts,
download via an authorised fetch → blob), part 2 one-time download tickets
(big files + file chips in chat), part 3 upload (new write right, own size
limit), part 4 live HTML preview on a SEPARATE origin (owner's security
ruling first).

## 4. Embedder setting + rebuild banner (FRONTEND-REVAMP §2.11) — **BUILT 2026-10-30**

**LIVE TEST 2026-10-31 (owner, T-44f) — three bugs found and FIXED (commit
509e72a + the 403 wording):** a hosted embedder saved with no key locked the
project 'building' for 15 h (engine never reported failure; nucleus driver
killed by the worker's soft limit before its own "mark failed"; save accepted
a keyless hosted endpoint). Now: engine abandons + reports 'failed' with a
key-free reason; driver stops on 'failed', limits above its budget, unlocks
on SoftTimeLimitExceeded; keyless hosted save refused. 401 vs 403 now worded
differently (403 = valid key without embeddings permission — the owner's
actual case: a Restricted OpenAI key). ALSO FIXED: the engine test harness
wiped the LIVE vector DB when run inside the dev container — tests now use
<db>_test with a hard name guard.
**FOLLOW-UPS (queued, not built):**
- The panel shows only "failed"; the engine's worded reason never reaches
  it (nucleus stores reindex_status only). Carry the reason through (a
  reindex_error field + the pane's failed note) — small, one migration.
- SECURITY: vx_indexes.embedder (vector DB registry) stores the full spec
  INCLUDING the embedder api_key in plaintext JSON — model keys are
  encrypted at rest everywhere else. Strip the key from the registry row and
  have the engine receive it per call (or encrypt with the shared field key).
  Do before release.

Nucleus half built (GET/PUT /projects/{id}/embedder/, reindex_status).
Verified 2026-10-30: the frontend half did NOT exist — built the same night.
**BUILT:** an **EmbedderSection** on the project overview pane (under the
spend limit): System default (local FastEmbed) / FastEmbed with a chosen
model / OpenAI-compatible endpoint (model id + API base + key), Save &
rebuild memory, a polled (5 s) "memory is being rebuilt" banner while
reindex_status=building with every control disabled, a "last rebuild
failed — saving retries" note, a read-only description without
project.embedder, and "needs a newer server" on a 404. Hooks
useProjectEmbedder/useSetProjectEmbedder; api workspace.ts
getProjectEmbedder/setProjectEmbedder. **HOLE CLOSED riding along:** the
embedder GET/PUT echoed the stored api_key to ANY project member — now
masked server-side (_embedder_out: has_api_key only, the key never leaves),
and the key is WRITE-ONLY with kept-on-omit, same rule as model configs.
TESTS: nucleus workspace/tests_embedder.py +1 (write-only + kept-on-omit +
never echoed) + the read pin updated; frontend project-overview-pane +4
(no-right description, save + PUT body + banner + disabled controls,
failed note + stored-key placeholder + key stays out of the body, older
server); test ALL_RIGHTS + project.embedder. The chat side already worded
the refusal (code "reindexing") — nothing to add there.

## 5. Local (offline) login UI — PARKED (owner, 2026-10-18)

Backend endpoints exist and wait (/auth/local/signin, set-password,
reset-password). Supabase stays the only login road in the UI until the
owner unparks this.

## 6. Gateway: mint a token FOR someone else — **BUILT 2026-10-30**

The server supports POST /gateway/tokens/ with user_id (company-level
holders only). **BUILT:** the Mint dialog gains an "Acts as" member picker
(default: Myself) — shown ONLY to a company-level gateway.token holder (a
project-level holder keeps the self-only dialog); the mint POST carries
user_id, and the one-time token showing names who it acts as with a "hand
it to them over a safe channel, never through a chat" note. TESTS: frontend
gateway-tab +2 (company holder picks a member → user_id in the body + the
hand-over note; project-level holder sees no picker and mints for themself).

## 7. Portal / distribution track

- **device-claim guess-brake — CODE BUILT 2026-10-30, owner deploy pending.**
  device-claim/index.ts now refuses (429, worded) after 5 well-formed WRONG
  codes per account per 10 minutes, logged in a new `claim_attempts` table
  (schema.sql; RLS locked, service-role only; rows age out, nothing to
  clean). A malformed code never counts; a missing table degrades to no
  brake with a console warning, so claiming keeps working until the table
  exists. OWNER: SQL Editor → run schema.sql's claim_attempts block, then
  redeploy the `device-claim` function.
- **OAuth relay + vendor "NeuralOps" app registrations — THE MIDDLE SERVER
  IS BUILT 2026-10-30 (owner's 00:05 ask: "we will have to have a middle
  server, because our server can be anywhere"); only the vendor app
  registrations remain (owner-only).** Two halves, both coded + tested:
  · **The relay page** `portal/oauth-relay/index.html` — static, hosted at
  {NEURALOPS_PORTAL_URL}/oauth/relay (the ONE redirect URI every vendor app
  knows); reads server_url out of the signed-not-encrypted state (split on
  ":" — django signing's separator, pinned by the relay-mode test) and
  bounces the browser to the install's FIXED callback path with the
  provider's query verbatim. Stores nothing, holds no secret.
  · **The exchange function** `portal/supabase/functions/oauth-exchange/` —
  Google, Atlassian AND GitHub all demand the vendor secret at the token
  exchange (and on refresh), so installs POST {provider, code,
  code_verifier} there (anon-key headers, like device-request); only the
  function holds the secrets (its env); providers + token endpoints are
  hardcoded server-side, redirect_uri never caller-supplied; the token JSON
  returns verbatim and is stored only on the install.
  · **Nucleus**: presets gain exchange_mode="portal" + exchange_provider;
  oauth_client.complete_callback and refresh_if_needed route through
  SUPABASE_OAUTH_EXCHANGE_URL (new setting) for such configs; the direct
  road is untouched for everything else. TESTS: tests_oauth_dyn +2 (the
  code+verifier go to the portal and the provider is never dialed; a
  refusal is worded and stores nothing; the refresh rides the portal) and
  the preset pin now demands exchange_mode/exchange_provider on all three.
  OWNER (portal/oauth-relay/README.md has the exact steps): host the relay
  page · deploy oauth-exchange · register the three vendor apps with the one
  relay URI · set the six function secrets · hand the three PUBLIC
  client_ids to the developer to fill mcp_catalog. STILL FRONTEND-SIDE
  (after the client_ids land): the "Connect with NeuralOps" tile pre-fill —
  today's create dialog copies no oauth fields from a preset, so the button
  stays rightly hidden until then.
- **Step 8 distribution half** — rebuild the PRODUCTION profile around the
  unified image's new engine (nexus-ai-new semantics, chromadb retirement),
  publish the image. Large; its own step.

## 7b. Max tokens AND temperature move to the MODEL — **BUILT 2026-10-20**
(owner, 2026-10-19: "i think the road B" … "i think max tokens, and
temperature should be in model"; release plan #2)

**BUILT:** `ModelConfig.max_output_tokens` (16000) + `.temperature` (0.7) +
`.routing_notes` (the smart router's strengths line, carried in the same
migration) — **migration 0037_model_generation**, no backfill on purpose
(several personas can share a config, so any copy would be a guess).
ModelConfigIn/PatchIn/Out carry all three; `_model_config_out` returns them;
PersonaIn/PatchIn still ACCEPT temperature/max_tokens so old callers don't
400, and services pop them unread. Internal API: ModelInternal carries them,
so the engine budgets and generates PER CANDIDATE. Engine: ModelSpec gained
the fields (defaults keep an older nucleus working — the persona's legacy
numbers stand in, see nucleus_client.model_spec_from); agent_builder reads
`spec.temperature` / `spec.max_output_tokens`; reply_generator and ai_system
budget from the candidate's own cap. Frontend: both MODEL dialogs gained a
Generation section (Max reply tokens / Temperature / Strengths note), the
model card shows "reply Nk", and BOTH persona dialogs LOST temperature and
max tokens (Generation keeps Max steps + Proposes first + Recall). Tests: 1
engine file (2 cases incl. the older-nucleus fallback) + 2 frontend cases +
updated persona cases. Persona.temperature/max_tokens COLUMNS stay for now
(dropping them is a later cleanup; nothing reads them).

Today both sit on the persona (max_tokens default just raised to 16000).
The ruling: they are properties of the MODEL — each model has its own
output ceiling and its own sensible temperature. The final split:
**the model card owns HOW it generates (max output tokens, temperature);
the persona owns WHAT it is and does (prompt, tools, max steps,
propose-first, recall).** Known trade, accepted: two personas sharing one
registered model share its temperature — wanting two temperatures means
registering the model twice (same key, two cards).

The build, when we run it:
- **nucleus:** `ModelConfig.max_output_tokens` (int, default 16000) and
  `ModelConfig.temperature` (float, default 0.7) + ONE migration; expose in
  ModelConfigIn/Out and both model dialogs (near context window);
  PersonaInternal's ModelSpec entries carry each model's own numbers;
  PersonaIn.max_tokens/temperature become optional/ignored (kept so old
  callers don't 400); persona create/edit dialogs lose both fields
  (Generation keeps Max steps + Proposes before acting + Recall).
- **engine:** budget math + run settings read the ANSWERING model's
  max_output_tokens and temperature (today: persona-level) — per candidate,
  so a fallback with a smaller ceiling gets its own right numbers.
- **tests:** nucleus persona/model API suites, engine budget tests, frontend
  personas-tab + models-tab suites.
- Size: a solid evening. Not started — tonight's walkthrough runs on the
  current shape (persona fields, max_tokens default 16000), which works fine.

## 7c. Engine image: regenerate requirements.lock with the web-fetch extra
(found 2026-10-19, owner's first live persona)

A persona with the web_fetch capability crashed at toolset build ("No module
named 'bs4'") — the image's pydantic-ai-slim install lacked the `web-fetch`
extra (bs4 + markdownify). FIXED for tonight by pip-installing it into the
RUNNING nexus-ai-new container (lost if the container is ever recreated),
and requirements.txt now carries the extra. STILL TO DO: regenerate
requirements.lock from the updated requirements.txt (never hand-edit —
lesson 14) and rebuild the image — fold into the next image build.

## 8. Owner's own list (no code)

- Supabase dashboard: delete the legacy `device-verify` function; delete the
  `test-install-1` row in phone_home_events.
- If the nexus-ai-new container is ever RECREATED before the image rebuild
  (7c): re-run `docker exec neuralops-nexus-ai-new
  /opt/venv/nexus-ai-env/bin/pip install "pydantic-ai-slim[web-fetch]"`.
- ~~Rotate the OpenAI/Anthropic keys that appeared in earlier terminal pastes.~~
  DONE 2026-10-28.
- Git commits in BOTH repos — **DONE 2026-10-21 17:11**: backend 581d21b
  (step8-switchover), frontend 79bcef4 (noamanfaisal) — the whole revamp
  through the spend limit, suites 469/116/1140 all green at commit time.

## 9. Later / nice-to-have

- **Cached tokens on the Usage page — BUILT 2026-10-20** (release plan #1):
  `cached_tokens` on _money + every breakdown row; by_kind split on the
  project/company rollups (usage_api.py); Usage page shows a "From cache"
  stat with its share, a Cached column, and a "By kind of work" table in
  plain words (Chat replies / Router screening / Memory passes /
  Embeddings); older servers without the fields render clean. Tests: one
  nucleus (rides UsageReadApiTests) + one frontend. Original note kept
  below for history.
  (owner noticed 2026-10-19; scope CORRECTED after reading the code): the backend already has it ALL — the
  engine captures cache read/write per call, nucleus stores the columns
  (cache_read_tokens, cache_write_5m/1h, uncached_input_tokens,
  reasoning_tokens) AND prices cache reads at the cached rate (pricing.py).
  Only the LAST MILE is missing: the usage rollup endpoints (topic/project/
  company) sum just input/output, so the frontend has nothing to show.
  Build: add cache sums to the three rollups' _money shape + a Cached column
  (or "N% from cache" note) on the Usage page. Small; no migration.
  ALSO (owner's usage question, 2026-10-20): a by-KIND split on the Usage
  page — the rows already store kind (chat_reply/router/memory) and seat
  (role), the rollups just don't group by it. Interesting once routers are
  live ("what does the screener cost vs save?"). Small; same endpoints.
- **Default project capabilities — RULED (owner, 2026-10-21 16:25): KEEP ALL
  FOUR** (filesystem, shell, web_search, web_fetch). Today's behavior stands
  — nothing to build; per-persona unticking and the MCP screen's capability
  editing stay the control points. CLOSED.
- **Spend limits — RULED (owner, 2026-10-21 16:25: per-PROJECT monthly cap,
  BLOCK at the cap), BUILT the same hour.** `Project.spend_limit_monthly`
  (Decimal USD, null = no limit) + migration **0040_spend_limit**; the sum is
  the project's UsageRecord.cost for the CURRENT CALENDAR month — ESTIMATED
  by design, unpriced rows count 0 (workspace/services.py spend_this_month /
  spend_limit_reached). Enforced in chat/api.py _trigger_personas, the same
  road as the reindex lock: the human message still posts, the AI reply is
  refused with code "spend_limit" and a worded message naming ≈spent/cap.
  API: ProjectOut ships spend_limit_monthly + spent_this_month (detail
  route only; decimal STRINGS, money is never a float); PATCH project takes
  spend_limit_monthly / clear_spend_limit under project.update (validated:
  >0, ≤1,000,000). UI: "Monthly spend limit" section on the project
  overview pane — ≈spent aside, a dollar input, Save/Remove, estimates
  caveat spelled out. Tests: nucleus SpendLimitTests (+1 → 469), frontend
  +2 pane tests (→ 1140).
- **gpt-4o-mini showed "no price known"** (2026-10-19, first live run): the
  daily refresh_model_prices task should fill it from the litellm catalog.
  If it still shows after a day, investigate the catalog fetch/key matching.
- **Register-dialog defaults from the catalog DB — RULED (owner, 2026-10-21,
  during the from-zero test pass: "these default values must be fetched from
  db"), BUILT the same hour.** ModelPrice gained context_window +
  max_output_tokens (migration **0041_catalog_windows**), filled by the same
  daily litellm refresh that fills prices (rows with sizes but no prices are
  now kept too); GET /model-configs/defaults/ serves them to the register
  dialog, which prefills on id blur / provider change and never overwrites a
  hand-typed value; the frontend's hardcoded table (src/lib/model-context.ts)
  is now only the offline fallback. PLUS the owner's follow-up ruling the
  same evening: setup pushes DEFAULT DATA into the DB — `manage.py
  seed_catalog` loads the bundled snapshot (fills missing rows only, never
  downgrades the online refresh), `seed_catalog --regenerate` re-downloads
  the latest catalog from GitHub and rewrites the bundled file at release
  time (the file is committed, so it is versioned on GitHub with the code).
  Persona prompts / catalogues / templates already ship in code — no seed
  needed. Full detail + VERIFY block: FRONTEND-REVAMP §2j. Targets after
  this: nucleus 475 · frontend 1141 · migrations through 0041 (engine
  unchanged).

## Post-test build queue (owner, 2026-10-22 morning — build AFTER the
## acceptance pass; design details to be ruled when each starts)

- **MEMORY-PASS HARDENING — ~~REQUIRED BEFORE RELEASE~~ PARTS 1+3 BUILT
  2026-10-22 23:45 (the only parts that survived the Recall removal; 2/5
  voided, 4 fixed earlier).** Part 1: the memory pass never stores a
  shell/terminal transcript verbatim — prompt hard rules PLUS a code guard
  (_NEVER_RAW_TOOLS: a `raw` ruling on shell/run_command/terminal/
  execute_command downgrades to its summary or to nothing); trivia and
  anything that looks simulated is ruled skip. Part 3: the RETRIEVED prompt
  section now ends with a provenance rule — remembered text is never
  presentable as this turn's tool output and is named as memory when used.
  Tests: engine +m3 (transcript never raw; summary survives; non-shell raw
  untouched) and tr1 extended (provenance line reaches the model). Engine
  target moves 117 → **118** — VERIFIED by owner 2026-10-22 23:01: "118
  passed, 5 skipped". Original entry kept below for history:
  (promoted 2026-10-22 after the fabricated-terminal finding).** Three parts: (1) the pass must
  stop recording trivia and must NEVER store tool/terminal transcripts as
  facts — a fabricated transcript got stored and was replayed verbatim in
  its topic; (2) VISIBILITY: "Remembered N things" rows live only in the
  vector store with NO UI — the owner found the Recall pane empty while the
  chip counted away; either show memory-pass rows somewhere curatable or
  stop the chip implying they're inspectable; (3) retrieval-echo: text served
  from memory must not be presentable as THIS turn's tool output. Mitigating
  facts: memory rows are same-topic-scoped, so poison is contained to its
  topic (archiving the topic buries it). FOUND 2026-10-22 15:15 while the
  owner chased the empty pane, TWO MORE PARTS: (4) the "Remembered N things"
  chip was a MISWIRE — chat/relay.py published len(retrieved_sources) as the
  recall count, so every memory SEARCH claimed a memory WRITE (fixed same
  hour: relay publishes no count until real recording exists; nucleus suite
  must re-run — if a chat test asserted the old count, that test asserted the
  bug and gets fixed too); (5) RECALL HAS NO WRITER — storage, internal route
  (/internal/recall/), pane, editing all exist and are tested, but no persona
  tool or engine path ever records an entry; "remember this decision: we
  deploy on Fridays only" was acknowledged in words and stored nowhere. The
  hardening build adds the writer: a record_recall tool (or the memory pass
  writing decision/fact/preference entries) through the existing route, and
  the chip counts THOSE writes only.

- **AI audit log ("log for all chats").** Project owner/admin can open any AI
  reply and see the whole anatomy: the user's query, what retrieval fetched
  (vector DB hits — and graph DB once that exists), the exact prompt and
  history sent, the model's raw response, model/seat/lane, tokens and cost.
  Plus "investigate with a model": ask a model questions ABOUT the log from
  inside it. Foundations already exist: AIRequestLog rows, UsageRecord,
  retrieved_sources on message_done — the build is capturing the full prompt
  /retrieval payload per reply, a permission-gated API (owner/admin only —
  this is reading people's chats, needs its own right), and the viewer UI.
  **BUILT 2026-10-29 (1.3.0, the owner's 19:14 ask: "i want to know in log…
  how every prompt is building, vector db + system prompt + context +
  file"). ~~"Investigate with a model" is EXPLICITLY DEFERRED~~ — **BUILT
  2026-10-30**, see the INVESTIGATE record at the end of this entry.**
  · CAPTURE (engine): ReplyGenerator records one audit dict per model RUN
  (reply_generator.py — a fallback or router→deep hand-over writes two): the
  plan's sections POST-FIT with kind + chars + FULL text (capped 20k/field —
  system prompt, project brief, output contract, tool catalog, other
  servers, retrieved, approved plan, step context), the extra instructions
  (router bench / hand-over note, now split from the base so the log names
  them), history count, the user message, seat/provider/model, resume flag,
  fallback attempt, per-run token sums and latency, and the ending as it
  really was: done / escalated / paused / failed / cancelled. ai_system
  `_record_audit` posts them at the SAME three endings as usage (success,
  error, shielded cancel), attaching the retrieval refs (label+score+kind);
  a failed write is logged, never breaks a reply.
  NucleusClient.record_request_log → the EXISTING internal
  POST /ai-request-logs/ (the legacy endpoint the new engine never used).
  · STORE (nucleus): AIRequestLog gains topic_id (indexed), project FK,
  role, model_name, breakdown JSON — migration **0045_audit_anatomy**; the
  internal route saves them (an older engine's plain write still lands).
  · READ (nucleus): NEW right **project.audit** (Admin bundle only — this is
  reading everyone's prompts and raw model output); `GET
  /projects/{id}/audit/` (topic_id / msg_id filters, cap 200, light summary
  rows) + `GET /projects/{id}/audit/{log_id}/` (full breakdown + raw
  response). HOLE CLOSED riding along: the legacy company-wide
  `GET /ai-request-logs/` was auth-only — ANY signed-in member could read
  every raw prompt/response; now gated on project.audit at company reach.
  · UI: a hover action on every persona reply ("How this reply was built",
  only with the right — canAudit rides TopicView→MessageList like canDecide)
  and a Context-pane action ("How replies here are built") for the TOPIC
  view — both open audit-dialog.tsx: one card per run (seat, model, status,
  @persona, tokens in/out, latency, time), unfolding to the anatomy — each
  ingredient a named collapsible with char count and full text, the vector-DB
  retrieval list with scores, history count / resume / fallback line, the
  message answered and the raw response. Detail fetched per run on first
  unfold.
  TESTS: engine tests/test_audit.py (plain reply anatomy incl. tool_catalog
  + persona prompt text; escalation = ROUTER escalated + DEEP done rows with
  the hand-over note in extra_instructions; a dead-endpoint run still lands
  as failed with the anatomy intact); nucleus intelligence/tests.py
  AuditLogTests (internal write incl. the older-engine shape, owner reads /
  Member 403 on list+detail, topic/msg filters, cross-project invisibility,
  the legacy listing now 403s a Member); frontend context-panel.test
  (no right = no action; the topic view's run unfolds to prompt text,
  retrieval scores, message, response), message-list.test (hover action only
  with canAudit and only on persona replies), test/permissions ALL_RIGHTS +
  project.audit.
  OWNER: `manage.py migrate` (0045) + `manage.py seed_permissions`
  (project.audit → Admin/Owner) ride the next round; restart BOTH
  containers (engine now writes the log).
- **Connector tiles with icons.** The add-MCP screen shows ready-made tiles
  (icon + one click to configure) for: GitHub, Bitbucket, a graph-DB context
  MCP, Atlassian, AWS, Google, Vercel, draw.io/charts (owner's list, extended
  2026-10-22 19:45) — OAuth2 flow already built, the
  mcp_catalog already pre-fills dialogs; the build is catalog entries with
  icons + tile UI + per-service oauth_config defaults, each entry TESTED
  against the real service.
  **BUILT 2026-10-29 (code side; LIVE VERIFICATION IS THE OWNER'S HALF).**
  The tile UI + brand marks existed (W11 Catalogue + brand-icons); this round
  added the five missing entries to intelligence/mcp_catalog.py —
  **bitbucket** (community `@aashari/mcp-server-atlassian-bitbucket`, stdio,
  workspace + Atlassian API token), **neo4j** (official
  `uvx mcp-neo4j-cypher`, the graph-context option), **aws** (AWS Labs
  `uvx awslabs.aws-api-mcp-server@latest`, credentials-scoped; NEW
  "Infrastructure" category), **vercel** (hosted https://mcp.vercel.com,
  oauth2 via the dynamic-registration road — no preset needed) and
  **mermaid** (`npx -y mcp-mermaid` — the draw.io/charts ask; the chat
  renders Mermaid natively). Frontend: brand marks for
  bitbucket/neo4j/vercel/mermaid (simple-icons 16); AWS has NO mark there
  (brand takedown, like Slack — but its geometry isn't reproducible) so it
  wears a house Cloud glyph; brand-icons test pins the new list + the AWS
  rule. OWNER before release: add each tile's server against the REAL
  service once (the ruling demands it — package names rot); GitHub/Google
  Drive/Atlassian oauth_presets still await the vendor app client_ids
  (portal-side, unchanged).
- **Backup & restore.**
  **BUILT 2026-10-29 night (CLI side; the owner's live proof run is the
  other half).** `neuralops backup` already existed (database.sql.gz via
  pg_dumpall · secrets.env · projects.tar.gz — secrets are IN the backup on
  purpose: without FIELD_ENCRYPTION_KEY the restored model keys are
  unreadable). NEW: **`neuralops restore <backup folder>`**
  (neuralops-cli.sh cmd_restore): validates the folder, then — append-only
  secrets rule — a fresh install takes the backup's secrets, matching
  secrets pass silently, DIFFERENT secrets refuse loudly (the DB would be
  undecryptable) unless `--use-backup-secrets`, which keeps the old file
  aside as secrets.env.replaced-<ts>; asks the person to type RESTORE;
  stops the app services (postgres stays up), drops both databases
  (pg_dumpall carries CREATE DATABASE), pipes the dump back in, swaps the
  projects folder (old one kept as projects.replaced-<ts>, chown 1000),
  then compose up + the standard setup_database (migrate/seed) so the
  restored data is brought to the running version. Never `down -v`.
  ALSO FIXED riding along: someone had pasted the developer-brief MESSAGE
  ("WHAT WE'RE BUILDING … Thanks!") into the END of neuralops-cli.sh after
  the esac — not shell, so EVERY `neuralops` command errored at exit;
  removed. OWNER'S PROOF (no automated test can cover a live stack):
  on a server with data → `neuralops backup` → fresh install →
  `neuralops restore backups/neuralops-<ts>` → sign in: chats, models
  (keys decrypt), project files all back; `bash -n` + shellcheck clean.
- **File viewer pane (un-parked).** Browse project files with: download,
  upload, and "run as HTML server" (serve a folder/file as a live preview —
  security ruling needed: who may run it, same-origin isolation).
  **Parts 1+2 BUILT 2026-10-29 (spec: docs/FILE-VIEWER-PANE.md §2–3).**
  PART 1 (the pane): a **Files** pane in the rail — breadcrumb, folders
  first, sizes/ages, Refresh, sandboxed viewer (`srcdoc` + `sandbox=""`,
  never allow-scripts), blob downloads with the bearer, worded 400/404/409/
  413/415. PART 2 (tickets + chat chips):
  · **One-use download tickets** — `POST /projects/{id}/files/ticket/`
  (same project read as every file route) answers `{url, expires_in: 60}`;
  `GET /api/v1/files/download/{token}` is PUBLIC ON PURPOSE (the token is
  the credential; `files_public_router` in workspace/api.py, mounted in
  core/urls.py). One use = push at mint, pop at take, on the shared signal
  store (Redis in prod, memory in tests); 60 s TTL; unknown/expired/reused
  all answer the SAME 410 so a guesser learns nothing; the file having
  vanished since the mint is the one honest 404. The pane downloads files
  ≥200 MB by ticket (the browser streams to disk — no blob in memory);
  smaller files keep the blob road.
  · **File chips in chat** — the engine stamps `path` on every ok write
  tool's tool_result (event_mapper `written_path_of`; contracts
  ToolResultData.path); the relay collects the written paths and, at
  message_done (stopped included), CONFIRMS them against the project
  folder (workspace/files.stat_files — inside the wall, real sizes, dedup,
  cap 20) and ships `files: [{path, name, size}]` on the done event and in
  metadata (chat/messages.py serialise). The app shows one chip per file
  under the bubble — name, size, **View** (opens the Files pane at the
  file's folder, a one-shot ui.store target like jumpToMessage) and
  **Download** (a FRESH ticket per click, absolutized against the server).
  Never a long-lived link in a message.
  TESTS: nucleus workspace/tests_files.py **DownloadTicketTests** (once-and
  -only-once, expiry, uniform 410, minting walls: outsider 404 / `..` 400 /
  sneaky symlink 400 / folder 400, subfolder bytes, deleted-after-mint 404)
  + **FileChipTests** (an e2e streamed reply: write_file×2 dedup + a ghost
  path dropped + ../ dropped, read_file never a chip; metadata + serialise +
  the published done all carry the chips; a toolless reply ships none);
  frontend: files-pane (big file by ticket, small file never, View-target
  consumption), message-list (chips + View + ticket mint), message-store
  (wire parse both roads).
  **Part 3 (upload) BUILT 2026-10-29, same day.**
  · `POST /projects/{id}/files/upload/` — multipart field `file`, `?path=`
  folder + `?overwrite=true`; gated on a NEW right **project.files_write**
  (rights.py registry — Admin + Member by default, never Viewer; reading
  stays on project.view). workspace/files.save_upload: bare-name rules
  (≤255, no `/ \\ ..` or null byte), the same folder wall, never writes
  over a folder or THROUGH a symlink, 409 without the overwrite flag,
  size cap `FILES_UPLOAD_MAX_BYTES` (settings/env, default 50 MB)
  enforced on the declared size AND while writing (a lying Content-Length
  still stops, the partial file is removed). The 64 KB pause-wall does
  not bite: Django's DATA_UPLOAD cap never counts multipart FILE parts,
  and nginx's client_max_body_size is already 50m.
  · UI: an Upload button + hidden picker (multi-file, sequential) and
  drag-and-drop onto the pane, a progress bar (XHR — fetch has no upload
  progress), "Replace this file?" confirm on 409, list refresh on success;
  all of it absent without the right.
  TESTS: nucleus workspace/tests_files.py **UploadTests** (member uploads /
  bytes land, subfolder, viewer 403 + outsider 404, overwrite flag, 413 +
  nothing lands, name rules incl. the lying-size mid-write stop, wall);
  frontend files-pane (no right = no control, picked file rides ?path= of
  the OPEN folder + refresh, 409 → dialog → overwrite retry, drag-drop).
  STILL OPEN here: part 4 run-as-web-page (blocked on the owner's security
  ruling) and the optional New folder / Rename / Delete controls.
  OWNER: run `manage.py seed_permissions` (the new right + role links —
  no migration), nucleus suite now includes `workspace.tests_files`;
  restart nucleus + engine after pulling.
- **CHAINS REWORK — RULED (owner, 2026-10-22 18:39, after testing runbooks
  live).** Six parts:
  (1) RENAME: "chain" everywhere — UI, banners, docs (code may keep runbook
  internals).
  (2) STEP ACTOR — BOTH KINDS: a step is a PERSONA (full power: tools,
  approvals, identity — unchanged) OR a bare MODEL + prompt (text-only
  transform: no tools, no approvals; cheap). Design points to settle at
  build: who a model step posts as (proposal: the chain itself as sender,
  model named in metadata) and how its usage bills (no persona_id —
  proposal: kind=chat_reply with the chain/run id).
  (3) QUERY INPUT (the owner's best ask): a chain takes a QUERY at run time;
  it rides into step 1 as the task and every step can see it — chains become
  reusable workflows, not frozen scripts.
  (4) INVOCATION: @ChainName <query> in chat, allowed for project admin/
  owner; whether the Run button stays as a second door — owner no
  preference, decide at build (Claude leans keep).
  (5) ROLE LABEL per step, so banners read "step 2 of 4 — Reviewer".
  (6) SUPERVISOR BIAS: verdict prompt gets a pass-unless-broken rule — live
  test showed a self-reviewing supervisor REDO-ing materially fine work
  until the cap failed the run (same fix family as the router's keep-it
  bias). Also warn in the UI when the supervisor is also a step persona.
  Inline ad-hoc chains (@chain "@A @B" "query") SKIPPED for v1 — fragile;
  a saved chain + query gives the same power.
  **BUILT 2026-10-29 (Chains v2, 1.1.0 — all six parts, in the real folders).**
  (1) RENAME: every banner/announce line is "Chain: …" (runbooks.py _announce
  lines, api.py error wording, tasks.py, schedules wording); frontend: the
  Intelligence tab is "Chains", every button/dialog/toast says chain,
  /add-chain + /list-chains added (old /add-runbook names still work); code
  keeps runbook internals as the ruling allows.
  (2) MODEL STEPS: step kind "model" = {model_config_id, prompt, role} — the
  model must be ATTACHED to the project; execution goes through a NEW engine
  road POST /api/v1/models/transform/ (ai_engine/pydantic_ai_system/
  model_transform.py — built by the same ModelFactory as model_check, streamed,
  usage counted with UsageReader's semantics) via NexusAIClient.transform();
  the reply posts AS THE CHAIN (ChatMessage sender=None, persona_name=chain
  title, chain_step+model_name in metadata — chat serialise lets a senderless
  persona_name through; the app shows a "chain" pill) and BILLS
  kind=chat_reply, persona_id empty, job_id="chain-run:<id>",
  source=chain_model_step (UsageRecord written in runbooks.py, priced by
  intelligence/pricing.price_record). No tools, no approvals; retry/redo/
  review/on_failure rules apply unchanged (_run_step dispatches).
  (3) QUERY: RunbookRun.query (migration **0044_chain_query** — RUN ON THE
  SERVER), RunbookStartIn.query (≤4,000, 400 over), start_run(..., query);
  _with_query() prepends "The chain's task for this run:" to EVERY step's
  prompt (redos included) and the supervisor's review question; the start
  announce line carries "Task: …" (clipped 200); serialise_run ships query +
  current_role; a SCHEDULE's query_text now rides the run as the chain's task
  (tasks.py), and the schedules UI offers it for chain schedules; the gateway's
  run_chain tool takes query too. Run dialog has a "What is this run about?"
  box.
  (4) @ChainName <query>: chat/api.py step 5c2 — mention tokens no persona
  answered to are matched against chain titles (case/separators ignored:
  @WeeklyOpsUpdate = "Weekly ops update"; personas always win their own name);
  the rest of the message rides as the query. Door per the ruling: project
  admin/owner — runbook.manage + persona.mention; a member keeps the ▶ Run
  button (kept, as leaned). Refusals ride the normal mention_refused shape; a
  chain mention suppresses the session auto-trigger like a persona mention.
  (5) ROLE LABELS: optional per persona/model step (≤60 chars); serialised,
  in step_results, in the reply's runbook_run metadata and in serialise_run's
  current_role — the chat banner and the message chip read "step 2 of 4 —
  Reviewer"; editor has a Role label field; history rows show it.
  (6) SUPERVISOR WARNING: the editor warns (never blocks) when the supervisor
  is also a step persona (the bias fix's prompt half shipped in 1.0.0).
  TESTS: nucleus scheduling/tests_chains.py **ChainsV2Tests** (5 tests:
  query ride incl. redo+review+start line, role labels end to end, model step
  end to end incl. billing + failure road, @ChainName mention incl. the admin
  door and separator forgiveness, schedule query_text ride) + gateway
  run_chain-takes-a-query + all pinned "Runbook:" lines in scheduling/tests.py
  now "Chain:"; engine tests/test_model_transform.py (tr1–tr3); frontend:
  runbooks-tab/runbook-banner/message-list/message-store/schedules-panel/slash
  tests updated + new (model step editor, supervisor warning, query in run
  dialog + schedule dialog, role in banner/chip). OWNER: run the three suites,
  `manage.py migrate` (0044), restart nucleus+engine containers, commit both
  repos.
- **FREE-LLM ONBOARDING — RULED (owner, 2026-10-23 evening; full work
  order with hard rules lives in the owner's private project doc
  free-llm-onboarding-prompt — business/credits tracks stay OUT of this
  public repo).** Goal: "install NeuralOps, talk to a model in 2 minutes,
  for $0" — each user brings their own FREE-TIER key; NeuralOps never
  ships, shares or pays for a key. Four build parts:
  (1) **"Free to start" presets in the CATALOG** (seed_catalog data, not
  prompt text): one row per provider — GitHub Models (OpenAI-compatible,
  GitHub token), Google Gemini free tier, Groq, OpenRouter :free, Mistral,
  Cerebras, Ollama (local; no key — flagged as the private option) — each
  with provider type, API base, recommended model ids, the provider's
  key-page URL, a rate-limit note and a data-usage note. UI: tiles in
  /add-model with everything prefilled except the key. A dead free tier is
  fixed by a catalog refresh, never a prompt edit.
  (2) **Configure-channel HELPER persona**: walks a new user from zero to
  a working model — triage (cloud or local? which accounts exist?), exact
  per-provider key steps, honesty notes (rate limits; some free tiers may
  train on data; Ollama is the private path), then hands off to the
  prefilled /add-model dialog (and to part 3's tool once it exists). Its
  provider knowledge comes from the catalog presets, never hardcoded.
  (3) **register_model via the setup-copilot gateway tools + a SECURE KEY
  CARD** (first slice of the setup-copilot entry below): the tool
  PROPOSES; an approval card carries a write-only secret field — the key
  is typed ON THE CARD, verified with the provider (the Check path),
  stored encrypted, never echoed; message history records only "model X
  registered". A raw key must never travel through a chat message (chat
  lands in DB/history/memory). Rights: approver needs model management;
  card expiry follows the 24h rule.
  (4) **One-click connects**: "Connect OpenRouter" via OpenRouter's
  official OAuth PKCE (app obtains a user-scoped key on consent — reuses
  the MCP OAuth plumbing); GitHub Models via a GitHub OAuth app IF a
  non-PAT token proves out at build time, else the guided-PAT path stays.
  HARD RULES (none bend): no shared/baked key ever; no automated account
  registration or consent-clicking — the human clicks every consent and
  approves every card; keys never in chat; honest rate-limit/data-usage
  wording. Parts 1–2 build in the Nov 2–6 week; parts 3–4 ride the setup-
  copilot week.
  **Parts 1+2 BUILT 2026-10-29 (early — the owner wanted the list done).**
  · WP1: `intelligence/model_presets.py` — the owner's seven (GitHub Models,
  Gemini, Groq, OpenRouter :free, Mistral, Cerebras, Ollama flagged private/
  keyless), each with provider type, API base, recommended ids, the
  provider's key page, a rate note and a data-usage note; served at
  `GET /model-presets/` (model_config.list); the Register dialog shows them
  as **"Free to start" tiles** — a click pre-fills name/provider/id/base,
  never a key, and shows the key page + BOTH honesty notes verbatim.
  · NEEDED FIX riding along: the bare-model-id guard now EXEMPTS
  `openai_compatible` (server `_reject_prefixed_model_id` + the dialog rule)
  — OpenRouter's `meta-llama/…:free` and GitHub Models' `openai/gpt-4o-mini`
  are real ids with separators, reached by api_base + the id verbatim; every
  native provider keeps the wall.
  · WP2: the persona catalogue gains **"Guide" (setup-helper)** whose system
  prompt is RENDERED from the presets (persona_catalog.helper_entry →
  model_presets.helper_prompt — rule (b): never hardcoded): triage questions,
  per-provider key steps + pages, the honesty rules, Ollama as the private
  path, hand-off to the Free-to-start tiles, and a standing refusal to take
  keys in chat (revoke-and-remint if pasted). No capabilities until WP3's
  register_model.
  TESTS: nucleus intelligence/tests.py FreeStartPresetTests (presets shape +
  honesty notes + provider values, helper prompt rendered from the data +
  the hard rules, separator-id exception incl. the native-provider wall
  held); frontend models-tab (tile pre-fill + notes + legal separator id,
  keyless/private Ollama wording). OWNER before release: try each preset
  against the real provider once — endpoints and free tiers move.
  **GROQ PRESET LIVE-VERIFIED 2026-10-30 (owner, dev stack)** — and the
  live check earned its keep twice: (1) Groq had DECOMMISSIONED the preset's
  llama-3.x ids in Aug 2026 (real 404) → the row now ships
  `openai/gpt-oss-120b` / `openai/gpt-oss-20b`, the production replacements
  and strong tool-callers; (2) the model CHECK's probe budget (max_tokens 5)
  starved REASONING models — gpt-oss spent the whole budget thinking,
  answered empty, and a working model failed its check with the
  context-length wording → budget raised to 1024 (model_check.py). After
  both fixes the owner registered Groq gpt-oss-120b live: tile → prefill →
  key → Check green → saved. The OTHER six presets still await their live
  try.
  **Part 3 (WP3) — THE SECURE KEY CARD — BUILT 2026-10-30, exactly as the
  hard rules demand.** The inside create_model (setup capability) pauses on
  its approval card like every setup write; the CARD carries a write-only
  password field ("Provider API key — typed here, never into the chat";
  empty = keyless endpoints). The typed key's whole life: the decision POST
  (ToolApprovalDecisionIn.secret) → an in-process one-time hand-off
  (chat/approvals.stash_secret/take_secret, 300 s TTL — NEVER in
  PausedRun.decisions, message metadata or any event; a process restart in
  the ms-wide window loses the key safely: the register runs keyless and the
  provider check refuses in words) → the resume's approvals[call].secret
  (relay.resume_paused_run, internal POST) → the engine's
  DeferredToolResults.metadata → ctx.tool_call_metadata in
  setup_tools.create_model → the gateway's api_key argument → encrypted at
  rest, has_api_key in results. It is never a tool argument, so it cannot
  enter the run state, the history, the audit anatomy or the memory store;
  history records only the card ("… wants to register a model · Allowed").
  GUARDS: a key on a deny is 400; a key on any held call that is not a setup
  create_model is 400 (a credential is never silently dropped); length cap.
  Card expiry rides the existing pause-expiry rule unchanged. TESTS: engine
  test_setup_tools st6 (pause → resume-with-secret → gateway got api_key;
  the secret in ZERO provider requests); nucleus chat/tests.py
  SecretKeyCardTests (rides the resume, stored nowhere, one-time take; the
  three refusals); frontend approval-row — 3 new card tests (field only on a
  setup registration, trimmed key rides Allow, empty = no key, Deny never
  sends one, no field for a reader who cannot decide). WP4 (one-click
  connects) still rides the setup-copilot week.
  **RULINGS 2026-10-30 evening (owner, in chat — "there should be free model
  button…", "these buttons should be there when first time user sign in…",
  "there should be persona which can be only called within configure
  channel…", 17:11 confirmations). Supersedes nothing; extends WP4 + the
  setup copilot:**
  1. **First-sign-in "Start free" screen** — shown to the owner (and any
     model-manager) whenever the server has ZERO registered models: headline
     **Connect OpenRouter** (official OAuth PKCE — the only true one-click;
     consent is the USER'S click, key arrives programmatically, :free models
     registered automatically), then the free tiles (Groq marked "recommended
     for agentic setup" — gpt-oss-120b / Kimi K2; Gemini; GitHub Models),
     **Use local Ollama** (probe + keyless register), and "I have my own
     key" → the normal dialog. Honesty notes ride every tile. Skippable; the
     same buttons live on in the models empty state. EXPLICITLY REFUSED
     (owner asked, Claude ruled it out, owner accepted): signing users up to
     providers automatically — provider-ToS violation + the no-automated-
     signups hard rule; the OAuth consent click IS the legitimate version.
     Owner-side prerequisite: register the NeuralOps app with OpenRouter.
  2. **Setup copilot persona, channel-locked** — auto-seeded, callable ONLY
     inside the configure channel (mentions elsewhere politely refuse; new
     scoping flag), carrying the setup capability (our own app's tools via
     the internal MCP door) on the user's free model. Its prompt: ask the
     PROJECT TYPE first, then configure the existing project to match —
     topics, draft model slots (free presets first, from the catalog),
     personas, MCP suggestions, invites. It does NOT create projects (owner:
     "we dont want configure to create project, but it will ask the project
     type and configure things accordingly"). **invite_user is pulled
     forward** onto the gateway/setup tool list (card-gated — it sends real
     email), un-parking it from the team build.
  3. **DRAFT MODELS ("fake ids, fill later")** — a `draft` state on
     ModelConfig: no key, no provider check at create, "waiting for key"
     badge, NOT seatable on any persona until a key arrives and the check
     passes. Drafts are creatable ONLY through the setup tools (configure
     copilot / MCP gateway) — the register dialog keeps requiring key +
     passed check, so the UI can never produce a half-configured model. The
     key arrives later by the two existing NON-CHAT roads only: the WP3
     secure card (copilot proposes update_model) or the model Edit dialog.
     Point of the design (owner): the copilot lays out the whole model
     lineup in conversation and a raw key never needs to exist in chat.
  Seeding (Claude's lean, owner did not object): one Setup copilot per
  PROJECT — every project's configure channel gets one. NOT BUILT YET —
  owner ruled discussion-only tonight ("dont start program, lets discuss")
  — EXCEPT the first slice, ruled and built the same evening (owner 18:51:
  "Neuralops Setup capability setup should be neccsaasy part of every
  project, may with some namespace"): **SETUP ROW SEEDING BUILT 2026-10-30.**
  Every project now carries a protected internal MCP row named
  **"NeuralOps Setup"** (the reserved namespace) with capability_config
  {"setup": {}} — provisioning seeds it (workspace/services.py
  ensure_setup_row, called from provision_project_folder_and_mcp) and
  migration **nucleus.0046_setup_capability_row** backfills existing
  projects (idempotent by the reserved name; reverse is a no-op so live
  personas never lose tools). Tick it on a persona and the app's own admin
  tools mount, approval-carded, caller's-rights. Tests: workspace
  SetupRowTests (seeded beside the Capabilities row, protected, auth NONE,
  never twice); workspace suite 164 green. VERIFIED LIVE the same evening:
  the owner registered Groq gpt-oss-120b and the row was mounted on his
  test persona in demo-project.
  **BUG found in that live test (owner 19:08: "model is again and again
  asking for the what kind of project is this?") — FIXED 2026-10-30 same
  hour.** ask_user Q&A lived ONLY on the card (message metadata
  "questions"), never in the message text — so the NEXT run's history
  (internal /topics/{id}/history/ → HistoryPolicy) carried no trace of what
  was asked and answered, and a prompt-following model re-asked its triage
  question on every mention. FIX: get_topic_history_internal now appends
  every ANSWERED question card to its persona message's served content —
  '[Asked the person: "…" — <name> answered: "…"]' — engine-facing only
  (the app keeps rendering cards from metadata); pending questions stay
  card-only (their run isn't finished); a paused reply whose text is empty
  now still serves its Q&A, so HistoryPolicy's empty-content drop no longer
  erases it. Tests: internal TopicHistoryInternalTests +2 (suite 14 OK).
  The copilot PROMPT also hardened (read the topic before asking; "give me
  the card" means call the tool) — prompt text lives with the owner until
  the seeded-copilot build carries it into the catalogue.
  **THE DEEPER BUG under the same live test (owner 19:12) — THE STARVING
  WINDOW, FIXED 2026-10-30.** The owner's Groq card was saved with
  context_window 8192 (the fallback default — the catalog has no row for
  openai/gpt-oss-120b) and max_output_tokens 16000 (the ruled 7b default):
  the reply budget exceeded the whole window, budget_for's input budget
  clamped to 1, and the fitter dropped EVERYTHING — history, retrieval,
  tool catalog ("budget: protected content … exceeds target 1") — so the
  persona was blind every run. Four fixes: (1) the owner's card corrected
  to 131072; (2) ENGINE floor — budget_for never lets the reply cap starve
  the prompt below half the window, worded warning (budget.py; test_budget
  +1, 7 OK); (3) DIALOGS — register/edit refuse a reply cap ≥ the context
  window, and an UNTOUCHED cap now follows the window prefill (fits to half
  on small-window models like a local llama3, back to 16000 on big ones) so
  the colliding defaults can't be saved by accident (models-tab 45 OK, tsc
  clean); (4) the fallback table learned gpt-oss/kimi-k2 (131072), prefix-
  tolerant. ALSO SEEN in the same logs, parked: Groq hard-rejects
  hallucinated tool calls ("attempted to call tool 'json'/'list_models'
  which was not in request.tools") — killed one reply run and every memory
  pass on gpt-oss; with real context restored it should subside, but a
  catch-and-retry (or tool-name scrub) in the engine is the durable fix —
  queued. Groq free-tier 429s observed mid-run auto-retried and passed.

- **MCP suggest-attach — RULED (owner, 2026-10-22 17:34: "option 2").** The
  persona may SEE the names + descriptions of the project's other MCP
  servers — never their tools, never a call — just enough to say "this
  project has X, which could answer this; someone with edit rights can
  attach it to me." Attach stays a HUMAN CLICK gated by the persona-edit
  right, once per persona+server; from the next reply the topic cache
  (layer 2) picks it up and the read-quiet/write-ask rules (layer 3) apply
  unchanged. The router points at the wall, never climbs it: no silent
  auto-attach, a crafted message must not be able to arm a persona. Found
  live: "what shopping tools do you have?" → "none" while Shopping (demo)
  sat one tick away. Build after the pass (Stage 4).
  **BUILT 2026-10-29.** Nucleus: PersonaInternal gains `other_servers`
  (internal/api.py OtherServerInternal — name + a 200-char one-liner and
  NOTHING else; the project's active external servers not attached to the
  persona, attached/internal/other-project rows excluded). Engine:
  PersonaSpec.other_servers → one STABLE prompt section (prompts/layout.py,
  priority 70 — drops before the catalog under budget pressure): "Tool
  servers that exist in this project but are NOT attached to you: … You
  cannot see or call their tools, and must never pretend to. … someone with
  persona-edit rights can attach it to you under Intelligence." No tool, no
  schema, no dial — the wall holds; an older engine ignores the field and an
  older nucleus simply sends none. The attach click itself is the personas
  tab's existing edit road — nothing new to build there. TESTS: nucleus
  internal/tests.py SuggestAttachInternalTests (names+lines only, shape
  pinned, attached/foreign/internal rows excluded, all-attached ⇒ []);
  engine tests/test_tools.py test_suggest_attach_names_the_projects_other_servers
  (section + wording in the request, ask_user stays the only tool, no
  section without the field). FIXED in the 2026-10-29 round: ot9 builds the
  layout with a bare SimpleNamespace persona, which the new section's plain
  attribute read broke (AttributeError) — layout.py now reads other_servers
  with getattr(…, ()) so lighter persona-shaped callers stay valid.
- **Setup copilot — ADMIN TOOLS ON THE GATEWAY (owner asked 2026-10-22: "ai
  can help me setting up models, mcps, users, personas" — NOT yet developed;
  the neuralops-mcp repo is only a shopping-tools demo).** CORRECTED after
  the live gateway test (2026-10-22 19:18): gateway tokens open ONLY the MCP
  endpoint (POST /api/v1/mcp/), not REST — by design, no master user. So the
  build is: EXTEND the gateway's tool list (gateway/api.py TOOL_DEFS +
  gateway/tools.py) with admin tools — register_model, check_model,
  create_persona, add_mcp_server, invite_user … — each permission-checked as
  the token's person, exactly like the dialogs. The same tools can then be
  mounted INSIDE for personas via the InternalActor door (X-NeuralOps-User
  carries the asking person; rights still theirs, writes still gated by
  approvals). One door, one rights rule, both worlds.
  THE OWNER'S TOOL LIST (ruled 2026-10-22 19:27, names normalized to the
  existing list_*/verb_* style):
  - models: list_models · create_model (runs the same pre-save provider check
    as the dialog) · update_model
  - personas: list_personas · create_persona · update_persona
  - users: list_users (invite_user later with the team build)
  - topics: list_topics (exists) · get_topic_messages (a topic's transcript,
    with a filter: AI replies only, or all messages) · create_topic ("add
    chat") · update_topic (rename/archive — "set_topics")
  Every one permission-checked as the calling person, same rights as the
  dialogs. NOTE for create_model/update_model: an api_key travels as a tool
  argument — never echoed back in results, never logged; results carry
  has_api_key only, like the REST API.
  **GATEWAY ADMIN TOOLS BUILT 2026-10-29 night (the owner's 10, on the same
  door — gateway/tools.py + TOOL_DEFS/dispatch in gateway/api.py; 18 tools
  total now).** list_models · create_model (refuses without
  accept_provider_terms; runs the dialog's pre-save provider check — a model
  that cannot answer is refused, not saved; key write-only, results carry
  has_api_key) · update_model (reach changes re-check first, stored key via
  config_id when none given) · list_personas · create_persona ·
  update_persona (prompt/format/name/model/steps/gate — patch_persona's own
  road) · list_users (the Members page's rule: any member) ·
  get_topic_messages (topic row-visibility, ai_only filter, newest-200 cap) ·
  create_topic · update_topic (rename under topic.update; archive AND restore
  under topic.archive). All thin front doors over the dialogs' services — no
  new business logic, rights as the calling person, invisible = nonexistent.
  TESTS: gateway/tests.py AdminGatewayToolTests (check-first + nothing-saved
  on a failing check + the key never in any result + Member walls; rename
  never re-checks, a reach change does, with the stored key; persona create/
  update/list with rights; members + topic transcript incl. ai_only + rename/
  archive/restore tiers) + the tools/list pin now names all 18.
  **MOUNTED INSIDE FOR PERSONAS — BUILT 2026-10-30 (the InternalActor door,
  exactly as ruled: one door, one rights rule, both worlds).** A persona
  whose internal capability row carries the **`setup`** key (the mcp-tab's
  built-in-capabilities dialog gained a "Server setup" checkbox — attach the
  row to the persona like any other) gets the ten admin tools INSIDE chat:
  engine `tools/setup_tools.py` is a FunctionToolset bound per reply to the
  ACTING person (job.user_id → X-NeuralOps-User + the internal key), every
  call forwarded to nucleus's own gateway (POST /api/v1/mcp/ tools/call), so
  the gateway's permission checks run AS that person — a missing right is a
  worded refusal. Mounted as a native-like capability (registry NATIVE_TOOLS
  "setup"; ToolsetBuilder wraps it in the framework's Toolset with id
  "setup"), so the approval gate applies: the SIX WRITES
  (create/update_model, create/update_persona, create/update_topic) are
  ACTING_NATIVE_TOOLS["setup"] — an interactive run pauses on the card, an
  unattended one refuses in words. **THE KEY RULE HOLDS BY SHAPE:** the
  inside create_model/update_model have NO api_key parameter at all — a key
  pasted in chat has nowhere to go; keyless providers (Ollama) register end
  to end, keyed ones are handed to the Register dialog until WP3's card.
  A gateway isError returns as "… refused: … Nothing changed." (honesty
  rule). TESTS: engine tests/test_setup_tools.py st1–st5 (headers + acting
  person + result round-trip, write pauses with the card and the gateway
  never called, unattended refusal, no-api_key-by-shape + exactly the ten
  tools, refusal as honest text); frontend mcp-capabilities "Server setup"
  entry pinned. Engine suite 150 passed / 5 skipped.
  ~~The secure key card (WP3)~~ **BUILT 2026-10-30** — see the free-LLM
  entry's Part 3 record above (the in-chat register_model road; the gateway
  road stays key-as-argument by the owner's ruling).
  **AUDIT "INVESTIGATE WITH A MODEL" — BUILT 2026-10-30.** No tools needed
  after all: `POST /projects/{id}/audit/investigate/` (REGISTERED BEFORE the
  {log_id} route — whose regex also matches "investigate" and answered 405)
  takes {question, model_config_id, topic_id?/msg_id?, limit≤50}; same
  project.audit right as reading; the model must be ATTACHED to the project
  (the chain-model-step rule); nucleus serializes the runs' anatomy (2k/field,
  80k total — newest survive the cap) into one prompt and rides the engine's
  EXISTING transform road (NexusAIClient.transform — Chains v2's bare model
  call); the answer is EPHEMERAL (stored nowhere, never a chat message) and
  bills kind=chat_reply source=audit_investigate like a chain model step.
  UI: an "Investigate with a model" box atop the audit dialog's runs —
  question, a picker of the project's attached models, Ask, the answer with
  "answered by X · examined N runs · not stored anywhere". TESTS: nucleus
  intelligence/tests.py InvestigateAuditTests (anatomy + question in the
  transform prompt with the stored key server-side, billed; Member 403 /
  unattached-model 400 / empty-scope 404 / empty-question 400 all BEFORE any
  model call; an engine refusal is a worded 502 and nothing bills); frontend
  context-panel audit describe +1 (attached-models-only picker, POST body
  pinned, ephemeral answer + footer). STILL ON THE SETUP-COPILOT WEEK: WP4
  one-click connects — the last piece, blocked on the vendor OAuth apps
  (portal-side).

- **DATA POD — large CSV analytics (owner's ask 2026-10-30: "we will make
  one runpod with duckdb + minio to handle large csv") — CODE BUILT
  2026-10-30; the owner deploys the pod.** New `data-pod/` in the repo: one
  docker compose (MinIO + a Python MCP server — FastMCP streamable-http on
  :8900/mcp behind a bearer wall, DATAPOD_TOKEN = the server dialog's
  client_secret). Tools, split for the approval gate: READS (readOnlyHint)
  list_files · describe_file · run_sql (SELECT-shaped ONLY — a keyword wall
  refuses writes/DDL/COPY; ≤500 rows, ≤~60k chars, fresh in-memory DuckDB
  per call reading s3:// straight from MinIO so only touched bytes move);
  WRITES (pause on cards) upload_url (presigned 1-h PUT — the big file goes
  person→pod, never through chat or the model) · export_result (COPY a
  SELECT's full result to a new .csv/.parquet + download link). Presigned
  links sign against S3_PUBLIC_ENDPOINT (RunPod proxy address) while the pod
  itself uses the internal address. Catalog gained a "Large CSV analytics
  (Data Pod)" tile (Data category, static_secrets — house glyph, no brand
  mark). server.py syntax-checked; the pod's own smoke run is the owner's
  deploy (README: cp .env.example .env → compose up → add server → Refresh
  tools → attach to personas). LATER IF WANTED: per-project buckets/tokens,
  parquet auto-conversion of hot CSVs, a size-capped upload road from the
  Files pane.

- MCP connector toggles ship WITH the bundled connectors (scope ruling: no
  dead switches) — MCP track.
- **Model Edit dialog — RULED (owner, 2026-10-28): lock Save until the
  model has passed a check.** A model that has never passed a check opens
  with Save locked; the person clicks **Check**, and on a pass Save unlocks.
  Once a model has passed, Save stays enabled for ordinary edits (name,
  notes, generation settings). If the person changes how it is reached
  (provider, API base, model id, key), Save locks again until a fresh check
  passes. Build: frontend (models-tab edit dialog, like Register) + a
  `last_checked_ok_at` (or similar) on ModelConfig so "has passed before"
  survives a reload (nucleus field + migration, set by the check endpoint).
  Tests: never-checked → Save locked; check passes → unlocked; checked model
  + rename → Save enabled; checked model + new key → locked until re-check.
  **BUILT (verified in code + green suites 2026-10-30).**
  `ModelConfig.last_check_ok_at` (migration **0043_model_check_stamp**), set
  ONLY by a passing check of the stored config (services.py stamps on pass;
  a reach change clears it), serialized on ModelConfigOut; the edit dialog
  locks Save (never-passed or reach changed) with the "Check the model
  first" hint and unlocks on a pass — older servers without the field keep
  Save enabled (supportsLock guard). Tests: nucleus intelligence/tests.py
  (stamp/clear/serialize matrix) + frontend models-tab (lock matrix per the
  ruling).
- gpt-5.x pricing rows in the price catalog — watch the Usage page's
  unpriced_rows (≥) on new models; the catalog refresh task may lag new ids.

- **BUG (found live 2026-10-27, @Dashboard + aaf-analytics): a chart after a
  tool call arrives as raw text.** The persona wrote a sentence ("I'll pull
  the revenue report…"), called the tool, then wrote `<<<OUTPUT:chart>>>` +
  a VALID chart description. The bubble showed it all as text, and the
  markdown renderer turned `<OUTPUT:chart>` into a link (CommonMark reads
  `<scheme:path>` as an autolink), so it showed as `<<[OUTPUT:chart](…/w)>>`.
  Likely cause: `_OUTPUT_RE` in
  `modules/nexus-ai/ai_engine/output_types/markers.py` only accepts an
  opener at the START of a line, and the text before and after the tool call
  is joined with no line break, so the marker sits mid-line and is ignored;
  `recover_unmarked` then refuses it too, because prose surrounds the JSON.
  FIX (for the developer):
  1. Where the run's text parts are joined into the final reply, join the
     part after a tool call to the part before it with a line break.
  2. In `parse_output_markers`, also accept an opener that comes straight
     after sentence-ending punctuation (`.`, `!`, `?`, `:`) — still refuse
     one inside a sentence. Keep the prose before the marker as a lead-in
     line rather than throwing it away (the frontend already shows prose +
     fenced chart this way: `findFencedChart`).
  3. Frontend safety net: never render `<OUTPUT:...>` / `<<<END_OUTPUT>>>`
     as links; strip stray markers from text bubbles.
  Tests: a reply "Sentence.<<<OUTPUT:chart>>>{…}<<<END_OUTPUT>>>" ends as
  type chart with the sentence kept; a sentence that only MENTIONS the
  marker stays text. Workaround today: the persona prompt says no text
  before tool calls on a chart answer.
  SEEN AGAIN 2026-10-27 20:49 with `<<OUTPUT:table>>` after "I need to run
  the daily dashboard data pulls fresh in this reply." — a whole HTML
  dashboard shown as raw code. Not chart-only: every marker type is hit, so
  fix 1 + 2 must cover html/table/form too, not just chart.
  ROOT CAUSE, most likely (seen 20:52): the sentence before the marker is the
  ROUTER's text. Reply shown: "I can't produce this dashboard in this pass —
  I have no analytics tools here, so I'd be inventing the numbers. Handing
  it to the model that can run the pulls.I'll start with the schema…" — the
  routing run streamed prose AND returned Escalate (ROUTER_INSTRUCTIONS says
  "never answer AND escalate", the model did both), and that prose stays in
  the reply, glued to the standard run's text with no line break. FIX 0
  (do first): when the routing run ends in Escalate, throw away any text it
  streamed (clear it from the bubble and from the saved reply); the user
  should only see the escalated run's answer. Test: a routing run that
  streams "Handing it over." then returns Escalate leaves no trace of that
  sentence in the final message.
  **BUILT (verified in code + green suites 2026-10-30).** FIX 0: the saved
  reply is the LAST run's text only (reply_generator.full_text) and the
  deep_escalation event clears the live bubble (relay → message-store, its
  test pins the exact live scenario). FIX 1: event_mapper inserts a line
  break when a second text part begins after a tool call. FIX 2:
  markers._GLUED_OPENER accepts an opener glued to sentence punctuation —
  ot10 covers chart AND table, every marker type goes through the same road.
  FIX 3: frontend stripLeakedMarkers + the autolink guard (directives.ts)
  so `<OUTPUT:…>` never renders as a link and stray markers are stripped.

- **BUG (found live 2026-10-27): the persona's "Default answer format" is
  ignored.** @Analyst is set to Text, yet "@Analyst how did revenue this
  month compare with September, per currency?" came back as a chart.
  `_resolve_name` in `modules/nexus-ai/ai_engine/output_types/resolver.py`
  only looks at (1) an explicit @chart-style directive in the message, then
  (2) the classifier on the message words ("compare" → chart). The persona
  setting is never consulted.
  FIX (for the developer): pass the persona's default format into
  `resolve_output_spec` and use the order: directive in the message →
  persona default (when it is not Auto) → classifier → text. A persona set
  to Auto keeps today's behaviour. Tests: Text persona + "compare X with Y"
  → text; same persona + "@chart" → chart; Auto persona → classifier.
  Workaround today: add `@text` to the message.
  **BUILT (verified in code + green suites 2026-10-30).** resolve_output_spec
  takes persona_default; order: message directive → persona default (when
  not Auto) → classifier → text; unknown value logs and falls through to the
  classifier. Tests ot12 (unit, incl. " Auto " and a junk value) and ot13
  (end-to-end through the trigger).

- **CHECK (seen live 2026-10-27, 20:59 and 21:41): "The model provider
  returned a server error" appears together with an approval card**, twice
  (run_command `date +%F`, then aaf build_dashboard), with the whole run
  taking under a second ("5 tool calls · 438 ms"). Suspected: it is NOT the
  provider — it is the 64 KB pause-save failure (see the approval-pause bug
  above) reported under the wrong message. Confirm in the nexus-ai log
  (RequestDataTooBig / 413 on the pause POST at those times). If so: when the
  pause cannot be saved, say that ("Couldn't hold this step for approval")
  and never blame the model provider.
  **CONFIRMED + BUILT (verified in code + green suites 2026-10-30).** It was
  the pause save, not the provider: fake_nucleus reproduces the bare 500
  (RequestDataTooBig shape); ai_system raises "Couldn't hold this step for
  approval — the run's state …" on a failed pause POST (test_approvals
  pins it), and chat/reasons.py maps that wording through to the bubble
  instead of the provider-error line (chat/tests_reasons.py).
