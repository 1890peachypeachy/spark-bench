# sparkDash Lane-Control Switches — Spec

Status: DRAFT rev3 (multi-select + co-tenancy gates) for Victor review · 2026-09-26
Owner: Spark
Depends on: `spark-lane` harness (`~/recipe-db/spark-bench/ops/spark-lane`), proven
working end-to-end 2026-09-26 (all 4 lanes boot + verify + tear down).

**rev3 decisions (Victor, 2026-09-26):** Overview panel only. Registered lanes,
more added over time. **Multi-select, gated by node-disjointness** (see §2.5 — this
is the core of rev3). Token gate: tailnet-only, no extra password (consistent with
the existing power buttons). Confirm: simple dialog for a single lane, type-to-confirm
for the production lane.

**rev2 change:** Victor does not want rotation. The unit of control is a plain
**up / down switch per lane**. The user decides what comes down and what goes up.
No prescribed sequence, no automatic parking, no end-lane. This removes the entire
class of rotation-ordering bugs; there is no ordering left to get wrong.

---

## 1. Goal

Put **manual lane switches** on the sparkDash dashboard: for each lane, **Put up**
and **Pull down** — so you can bring a lane up or take it down on demand, in any
order you like, without an agent in the loop and without SSH-groping the nodes.

Non-goal: rotation, auto-parking, or any automatic sequencing. Non-goal: replacing
`spark-lane`. The dashboard is a **front end over the proven harness**; all the
correctness (occupancy guard, recipe fidelity, canary verify, no auto-restart) stays
in `spark-lane`. The server shells out to it and streams progress. We do NOT
reimplement lane logic in JS.

---

## 2. The lane model (what the switches control)

Lanes are defined by `spark-lane`, not hardcoded in the UI:

| lane | nodes | endpoint | model |
|---|---|---|---|
| `creative-engine` | spark2 | :7862 + :8765 | ming-image / design layers |
| `dsv41-tp3` | spark1,3,4 | :8000/v1 | deepseek-v4.1-flash |
| `dsv41-tp4` | spark1,2,3,4 | :8000/v1 | deepseek-v4.1-flash |
| `glm53-tp3` | spark1,3,4 | :8888/v1 | GLM-5.3-Flash-EXL3 |

**Requirement R0:** the lane list is fetched from `spark-lane lanes`, so a new lane
added to the harness appears in the UI with no dashboard change. The UI must never
carry its own hardcoded lane table.

**Requirement R1:** `up` and `down` are independent, direct actions. `up X` means
"bring X up"; `down Y` means "take Y down". The UI never bundles them into a sequence.

**Requirement R2 (multi-select):** the user can select several lanes and Put-up /
Pull-down them as one action. The selection is gated (see §2.5) — a set that collides
is refused with the named conflict, never silently reordered.

---

## 2.5 Co-tenancy gates — node-disjointness (the core rule)

**One rule governs everything:** two lanes can be up at the same time **iff their
node sets are disjoint.** No hardcoded pair list; the gate is computed from the node
set each lane declares.

Node requirements (authority: `spark-lane lane_nodes()`):

| lane | nodes | co-tenancy implication |
|---|---|---|
| `creative-engine` | spark2 | can pair with anything that avoids spark2 |
| `dsv41-tp3` | spark1, spark3, spark4 | pairs with anything on spark2 only |
| `glm53-tp3` | spark1, spark3, spark4 | **collides with dsv41-tp3** (same nodes) |
| `dsv41-tp4` | spark1, spark2, spark3, spark4 | **owns every node → only up alone** |

Worked examples (Victor's, verbatim in effect):

| selection | node sets | verdict |
|---|---|---|
| `{dsv41-tp3, creative-engine}` | `{1,3,4} ∪ {2}` | **ALLOWED** — disjoint |
| `{dsv41-tp3, dsv41-tp1}` (future tp1 on spark2) | `{1,3,4} ∪ {2}` | **ALLOWED** — disjoint |
| `{dsv41-tp4, anything}` | `{1,2,3,4} ∪ …` | **BLOCKED** — tp4 needs all Sparks clear |
| `{dsv41-tp3, glm53-tp3}` | `{1,3,4} ∪ {1,3,4}` | **BLOCKED** — same nodes |

**Gate algorithm (for a proposed Put-up set S):**

```
blocked = []
for each lane L in S:
    for each node n in nodes(L):
        holder = current occupant of n   # from live census
        if holder is a lane also in S:   continue   # same set, fine
        if holder is non-empty:          blocked += {L, n, holder}
for each unordered pair (A,B) in S:
    if nodes(A) ∩ nodes(B) ≠ ∅:          blocked += {A,B, shared nodes}
launchable = (blocked is empty)
```

If `launchable`: the server runs each `up` (order irrelevant — the sets are disjoint).
If not: **refuse and name the conflict** — *"dsv41-tp4 needs spark2, held by
creative-engine"* or *"dsv41-tp3 and glm53-tp3 both need spark1,3,4"* — and offer the
inline **Pull down \<holder\>** action. The user resolves it by clicking; nothing is
auto-parked.

**Why this is future-proof:** adding a lane = declaring its nodes. `dsv41-tp1`
(spark2), a future `qwen-tp2` (spark1,2), whatever — the gate computes the allowed
combinations automatically. There is no table of permitted pairs to maintain.

**Authority split:** `spark-lane` owns the lane→nodes map (single source of truth,
exposed via `lanes --json`) AND still enforces its own per-node occupancy guard at
launch time. The server/UI compute the *preview* (to grey out impossible selections);
the harness is the final authority. Belt and braces — the UI can never over-permit.

---

## 3. Architecture

```
sparkDash React UI (LaneControlPanel)
        │  POST /api/lanes/:lane/up   → 202 {jobId}
        │  POST /api/lanes/:lane/down → 202 {jobId}
        │  GET  /api/lanes/jobs/:jobId → job state + live log
        ▼
sparkDash Express server (new  server/lanes/LaneManager.js)
        │  spawns:  bash .../ops/spark-lane <verb> <lane>
        │  parses structured output → job state machine
        ▼
spark-lane  (existing, unchanged correctness)
        │  ssh → nodes, docker, canary verify
        ▼
DGX Spark fleet
```

Server runs on the **same Mac mini** as `spark-lane` and the SSH keys, so it can
spawn the harness directly. No new remote path, no new credentials.

---

## 4. Backend spec

### 4.1 New module: `server/lanes/LaneManager.js`

Mirror the proven `DecodeBenchManager` shape (`server/collectors/DecodeBench.js`):

- `start({lane, verb})` → throws `409` if a job is **already active** (single-flight,
  see §6), else returns `{jobId, lane, verb, state:"running", startedAt, log:[]}`.
- `get(jobId)`, `list()`, `cancel(jobId)`.
- Keeps a bounded ring buffer of recent job history (last ~20), like DecodeBench.

**Single-flight is fleet-wide, not per-spark.** A lane spans 3–4 nodes, so two
concurrent up/down operations can wedge the fleet. One active job at a time, period.

### 4.2 Endpoints (follow existing `/api/sparks/...` conventions)

| method | path | body | returns |
|---|---|---|---|
| `GET` | `/api/lanes` | — | `{lanes:[{id,nodes,endpoint,model,status,blockers}]}` |
| `GET` | `/api/lanes/status` | — | live census (what's up where, per node) |
| `POST` | `/api/lanes/:lane/up` | `{confirm?}` | `202 {jobId}` — refuses if nodes busy |
| `POST` | `/api/lanes/:lane/down` | `{confirm:true}` | `202 {jobId}` |
| `POST` | `/api/lanes/batch` | `{up:[lane…], down:[lane…], confirm:true}` | `202 {jobId}` — gated (rev3) |
| `POST` | `/api/lanes/:lane/verify` | — | `202 {jobId}` |
| `POST` | `/api/lanes/check` | `{up:[lane…], down:[lane…]}` | `200 {launchable, blocked:[…]}` — dry-run gate |
| `GET` | `/api/lanes/jobs/:jobId` | — | `{state, lane, verb, progress:[...], result}` |
| `POST` | `/api/lanes/jobs/:jobId/cancel` | — | `202` (SIGTERM the child) |

Design notes:
- `verb` ∈ `["up","down","verify"]`. **No `rotate`, no `endLane`.**
- `POST /api/lanes/batch` is the multi-select action: `up` lists lanes to bring up,
  `down` lists lanes to take down. The server (a) applies the §2.5 node-disjointness
  gate to `up ∪ (already-up minus down)`, (b) refuses with named conflicts if the
  result collides, else (c) runs `down`s first (free nodes), then `up`s. The
  *decision* is 100% the user's; the server only orders downs-before-ups because
  that is physically required.
- `POST /api/lanes/check` powers the live gate preview in the UI (no side effects).
- Long ops return **202 + jobId**; the UI polls `GET /jobs/:jobId` (DecodeBench does
  exactly this and it works). No long-held HTTP request.
- `lane` is validated against the list from `spark-lane lanes`. Anything else → 400.
  (Same discipline as `isAllowedTargetHost` in `validate.js`.)
- **No shell interpolation of user input** — spawn with an args array:
  `spawn("bash", [SPARK_LANE_PATH, verb, lane], {cwd: BENCH_DIR})`. Never string-concat
  into a shell.

### 4.3 Blocker reporting (replaces rotation's auto-parking)

`spark-lane up X` already refuses when X's nodes are held by another lane, and names
the holders (`nodes already taken: spark1(glm53-tp3) ...`). The UI must **surface
that as a first-class state**, not a dead-end error:

- `GET /api/lanes` returns `blockers: [{lane:"glm53-tp3", nodes:["spark1","spark3","spark4"]}]`
  for any lane that can't come up right now.
- The panel renders: *"Can't put up dsv41-tp4 — spark1,3,4 busy with glm53-tp3"* and
  offers the inline **Pull down glm53-tp3** button next to it.
- The user clicks Down on the blocker, then Up on the target. **Two explicit user
  actions — never an automatic park.** That is the whole point of this model.

No auto-parking code path exists in the UI or the server. The server never issues a
`down` the user didn't click.

### 4.4 spark-lane changes needed (small)

1. **Add `spark-lane lanes --json`** → machine-readable lane table
   (`[{id,nodes[],endpoint,model}]`) — **must include the `nodes` array** (`lane_nodes()`
   already computes it), because the §2.5 gate is built from it. Today `lanes` is
   human-formatted.
2. **Add `spark-lane status --json`** → machine-readable census (incl. occupant lane
   per node, so the UI can compute blockers).
3. Confirm exit codes are stable: `0`=PASS, `1`=FAIL, `124`=timeout (already true via
   `timeout_run`). The server maps exit code → job `state`.

Everything else (occupancy guard, recipe fidelity, canary, no auto-restart) is
**already in spark-lane and must not be duplicated**.

---

## 5. Frontend spec

### 5.1 New component: `src/components/SparkPage/LaneControlPanel.tsx`

Placed on the **Overview page** (fleet-level, since lanes span units).

Layout — each lane is a selectable row with checkboxes and a live gate banner:

```
┌─ Lane Control ──────────────────────────────── [⟳ refresh] ─┐
│  ☑ creative-engine   spark2      :7862+:8765   ● down        │
│  ☐ dsv41-tp3         spark1,3,4  :8000         ● SERVING     │
│  ☑ dsv41-tp4         spark1-4    :8000         ● down        │
│      ⚠ can't launch with creative-engine (both need spark2)  │
│  ☐ glm53-tp3         spark1,3,4  :8888         ● SERVING     │
│                                                              │
│  1 selected for put-up                                       │
│  [ Put up selected ]   [ Pull down selected ]                │
│                                                              │
│  ── job: up creative-engine  (running, 1m04s) ──             │
│  [3/5] design lab … container started                        │
│                                                              │
│  [ Cancel running job ]                                      │
└──────────────────────────────────────────────────────────────┘

✓ valid selection example:
│  ☑ creative-engine   spark2      ● down     → can launch     │
│  ☑ dsv41-tp3         spark1,3,4  ● down     → can launch     │
│  [ Put up selected ]   (2 lanes, disjoint — green)           │
```

Per-lane controls:
- **Checkbox** — select lanes for a batch action.
- **Put up selected** — enabled only when the whole selection passes the §2.5 gate.
  An impossible selection shows the named conflict inline and the button is disabled
  with the reason (or, per §2.5, offers **Pull down \<holder\>**).
- **Pull down selected** — downs every selected lane that is currently up.
- **Verify** — on any single lane; read-only health check.
- Live progress pane streams the `spark-lane` step lines (`[n/N] step …`) so a 15-min
  boot is visibly progressing, not a dead spinner.
- **Cancel running job** — SIGTERM the current job.

The gate is recomputed live as boxes are ticked, so you can *see* that
`{creative-engine, dsv41-tp3}` is launchable and `{dsv41-tp4, creative-engine}` is not
before you click anything.

Reuse: `ConfirmShutdownDialog.tsx` pattern for the destructive confirm on `down`
(simple dialog for one lane; type-the-lane-name for the production lane, per rev3
decision).

### 5.2 API client additions (`src/api/client.ts`)

```ts
export function listLanes(): Promise<{lanes: LaneInfo[]}>
export function laneStatus(): Promise<LaneCensus>
export function laneUp(lane, opts?): Promise<{jobId}>
export function laneDown(lane, opts?): Promise<{jobId}>
export function laneVerify(lane): Promise<{jobId}>
export function getLaneJob(jobId): Promise<LaneJob>
export function cancelLaneJob(jobId): Promise<void>
```

---

## 6. Safety model (non-negotiable)

These mirror the `spark-lane` hard rules and the GB10 operations skill.

1. **Single-flight.** One lane job fleet-wide at a time. Second request → `409`.
   Concurrent up/down operations = wedge risk. Enforced server-side.
2. **No auto-restart, ever.** No `--restart` policy, no watchdog that restarts a lane.
   GB10 hard rule: never auto-restart an unverified vLLM/SGLang config. Switches are
   user-initiated only.
3. **No automatic anything.** The server never issues an `up` or `down` the user did
   not click. Blockers are *reported*, never auto-resolved. (This is the rev2 core.)
4. **Occupancy guard stays in spark-lane.** The UI does not decide what's safe to
   launch on; `spark-lane` refuses and the UI surfaces the refusal as a blocker.
5. **Destructive ops require explicit confirm.** `down` needs `{confirm:true}` + a
   dialog. Never a bare click that kills production `:8000`.
6. **Auth — tailnet-only (decided).** No extra password, consistent with the existing
   power buttons. The API stays reachable only on the Tailscale network; any wider
   exposure needs fresh approval. Revisit a token gate if the dashboard ever becomes
   reachable off-tailnet.
6b. **The §2.5 gate is enforced server-side, not just in the UI.** A batch whose
   `up ∪ (up minus down)` set collides is refused with named conflicts before any
   child is spawned. The UI greying-out is a convenience; the server is the gate.
7. **Bounds.** Per-job wall-clock ceiling (reuse `ENGINE_MAX_WAIT`, 3h) + a hard
   server-side kill; a stuck job is cancellable and auto-expires.
8. **Audit.** Every job records `{who, lane, verb, startedAt, endedAt, result}` to a
   log file (`logs/lane-control.jsonl`) — who took down / brought up what, and when.
9. **No artifact deletion.** `down` never deletes weights/images (spark-lane already
   honours this); the UI adds no delete button.

---

## 7. Build plan (phased, each phase independently useful)

**Phase 1 — read-only lane panel** ✅ **SHIPPED 2026-09-26**
- `spark-lane lanes --json` + `status --json` (spark-bench `f764561`).
- `GET /api/lanes`, `GET /api/lanes/status` (read-only, 20s TTL cache).
- `LaneControlPanel` on the Overview page (sparkdash fork `07df77b`); shows live
  lanes + serving/down/partial state + `blocked by <lane>`.
- Verified live on :5555 and the tailnet URL against the real fleet.
- Value: a real fleet lane view in the dashboard; zero destructive surface.
- NOTE: Phase 1 ships *display* only — no Verify button yet (it needs the Phase 2 job
  machinery). That is deliberate: Phase 1 has no POST surface at all.

**Phase 2 — the switches (single + multi-select, gated)**
- `LaneManager` + job endpoints + `POST /up`, `POST /down`, `POST /batch`, `POST /check`.
- §2.5 node-disjointness gate: server-enforced + live UI preview (grey out impossible
  selections, name the conflict).
- Blocker display + inline "Pull down \<holder\>" action (never auto-parked).
- Live progress streaming from the job log.
- Value: the headline feature — put up / pull down any lane, or a compatible set, from
  the UI.

**Phase 3 — cancel + audit**
- `Cancel running job`, confirm dialogs, `logs/lane-control.jsonl`, job history view.

**Phase 4 — polish**
- Per-Spark "member of lane X" strip; job history tab; token management in Settings.

---

## 8. Acceptance criteria (production gate)

The switches are "done" only when, from the UI on a live fleet:

1. The panel lists every lane `spark-lane` knows, with correct live status.
2. **Pull down** on a serving lane (confirm) genuinely frees its nodes and the row
   flips to **down**.
3. **Put up** on a free lane brings it up and the row shows **SERVING** — verified by
   the panel's own canary, not the exit code alone.
4. **Multi-select, valid:** selecting `{creative-engine, dsv41-tp3}` shows green and
   **Put up selected** brings both up (they don't collide).
5. **Multi-select, invalid:** selecting `{dsv41-tp4, creative-engine}` shows the named
   conflict and **Put up selected** stays disabled — and nothing is auto-parked.
6. **tp4 gate:** with any lane up, **Put up dsv41-tp4** is refused with *"needs all
   Sparks clear"* naming the holder, and offers **Pull down \<holder\>**.
7. Up then Down on any lane, in any order, leaves the fleet exactly in the state the
   clicks imply (no ordering bug possible).
8. A second operation while one is running is refused with a clear `409`.
9. Killing the browser mid-job does not kill the job (server-owned); reopening shows
   the job still running/finished.
10. Every destructive action is in `logs/lane-control.jsonl` with a timestamp.

---

## 9. Decisions (resolved by Victor, 2026-09-26)

1. **Token gate** — **tailnet-only, no extra password.** Consistent with the existing
   power buttons. (No wider exposure without fresh approval; still revisit if the
   dashboard is ever reachable off-tailnet.)
2. **Placement** — **Overview panel only.**
3. **Scope** — **registered lanes** (each a recipe in `spark-lane`); more will be added
   over time. The UI reads the live lane list, so new lanes appear automatically; the
   §2.5 gate handles their co-tenancy with no code change.
4. **Confirm strength** — **simple dialog for a single lane; type-the-lane-name for the
   production lane** (`:8000`, what the agents depend on).
5. **Multi-select** — **yes, with the §2.5 node-disjointness gates.** Downs run before
   ups (physically required); the *choice* of what goes down/up is always the user's.