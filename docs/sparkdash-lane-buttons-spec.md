# sparkDash Lane-Control Switches — Spec

Status: DRAFT rev2 (manual up/down model) for Victor review · 2026-09-26
Owner: Spark
Depends on: `spark-lane` harness (`~/recipe-db/spark-bench/ops/spark-lane`), proven
working end-to-end 2026-09-26 (all 4 lanes boot + verify + tear down).

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
| `POST` | `/api/lanes/:lane/verify` | — | `202 {jobId}` |
| `GET` | `/api/lanes/jobs/:jobId` | — | `{state, lane, verb, progress:[...], result}` |
| `POST` | `/api/lanes/jobs/:jobId/cancel` | — | `202` (SIGTERM the child) |

Design notes:
- `verb` ∈ `["up","down","verify"]`. **No `rotate`, no `endLane`.**
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
   (`[{id,nodes[],endpoint,model}]`). Today `lanes` is human-formatted.
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

Layout — each lane is a row with a state-dependent primary switch:

```
┌─ Lane Control ──────────────────────────────── [⟳ refresh] ─┐
│  creative-engine   spark2      :7862+:8765   ● down         │
│      [ Put up ]                                              │
│                                                              │
│  dsv41-tp3         spark1,3,4  :8000         ● SERVING      │
│      [ Pull down ]  [ Verify ]                               │
│                                                              │
│  dsv41-tp4         spark1-4    :8000         ● down         │
│      [ Put up ]   ⚠ blocked by glm53-tp3 (spark1,3,4)        │
│      [ Pull down glm53-tp3 ]                                 │
│                                                              │
│  glm53-tp3         spark1,3,4  :8888         ● SERVING      │
│      [ Pull down ]  [ Verify ]                               │
│                                                              │
│  ── job: down dsv41-tp3  (running, 1m04s) ──                 │
│  [2/3] verify torn down … all required nodes released        │
│                                                              │
│  [ Cancel running job ]                                      │
└──────────────────────────────────────────────────────────────┘
```

Per-lane controls:
- **Put up** — shown when the lane is down. Calls `POST .../up`. If blocked, the
  button is annotated with the blocker plus a one-click **Pull down \<blocker\>**.
- **Pull down** — shown when the lane is up. Calls `POST .../down`. Destructive →
  confirm dialog.
- **Verify** — read-only health check (no teardown).
- Live progress pane streams the `spark-lane` step lines (`[n/N] step …`) so a 15-min
  boot is visibly progressing, not a dead spinner.
- **Cancel running job** — SIGTERM the current job.

Reuse: `ConfirmShutdownDialog.tsx` pattern for the destructive confirm on `down`.

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
6. **Auth.** The API is currently unauthenticated (tailnet-only approved ceiling).
   Lane control is **more destructive** than the existing power buttons, so:
   - keep tailnet-only (no wider exposure without fresh approval), AND
   - require a **lane-control token** (`X-Lane-Token`, from server env / secretsStore)
     for any non-GET `/api/lanes/*` — a second gate beyond the tailnet. GET status
     stays open (read-only).
7. **Bounds.** Per-job wall-clock ceiling (reuse `ENGINE_MAX_WAIT`, 3h) + a hard
   server-side kill; a stuck job is cancellable and auto-expires.
8. **Audit.** Every job records `{who, lane, verb, startedAt, endedAt, result}` to a
   log file (`logs/lane-control.jsonl`) — who took down / brought up what, and when.
9. **No artifact deletion.** `down` never deletes weights/images (spark-lane already
   honours this); the UI adds no delete button.

---

## 7. Build plan (phased, each phase independently useful)

**Phase 1 — read-only lane panel** (low risk, ship first)
- `spark-lane lanes --json` + `status --json`.
- `GET /api/lanes`, `GET /api/lanes/status` (incl. blockers).
- `LaneControlPanel` showing live lanes + serving/down state + verify button only.
- Value: a real fleet lane view in the dashboard; zero destructive surface yet.

**Phase 2 — the switches**
- `LaneManager` + job endpoints + `POST /up` and `POST /down` (guarded, confirm + token).
- Blocker display + inline "Pull down \<blocker\>" button.
- Live progress streaming from the job log.
- Value: the headline feature — put up / pull down any lane from the UI.

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
4. **Put up** on a lane whose nodes are busy shows the blocker and the inline
   "Pull down \<blocker\>" button — and never auto-parks anything.
5. Up then Down on any lane, in any order, leaves the fleet exactly in the state the
   clicks imply (no ordering bug possible).
6. A second operation while one is running is refused with a clear `409`.
7. Killing the browser mid-job does not kill the job (server-owned); reopening shows
   the job still running/finished.
8. Every destructive action is in `logs/lane-control.jsonl` with a timestamp.

---

## 9. Open decisions for Victor

1. **Token gate** — want the `X-Lane-Token` second gate (§6.6), or is tailnet-only
   enough given the dashboard already exposes power controls?
2. **Placement** — fleet-level Overview panel only, or also per-Spark strips?
3. **Scope of "whatever I want"** — just the registered lanes (each a recipe in the
   harness), or do you also want to bring up an arbitrary model/recipe that isn't yet
   a registered lane? (Adding a lane = adding it to `spark-lane`; the UI follows
   automatically.)
4. **Confirm strength** — dialog only, or dialog + type-the-lane-name for `down`?
5. **Multi-select** — single lane at a time, or select several lanes and Down/Up them
   in one explicit action (still no auto-parking)?