# sparkDash Lane-Control Buttons — Spec

Status: DRAFT for Victor review · 2026-09-26
Owner: Spark
Depends on: `spark-lane` harness (`~/recipe-db/spark-bench/ops/spark-lane`), proven
working end-to-end 2026-09-26 (all 4 lanes boot + verify + tear down).

---

## 1. Goal

Put **one-click lane control** on the sparkDash dashboard: pick a lane, bring it
up / take it down / rotate to it, from the UI — so any model or human can drive
the fleet without an agent in the loop and without SSH-groping the nodes.

Non-goal: replacing `spark-lane`. The dashboard is a **front end over the proven
harness**; all the correctness (occupancy guards, recipe fidelity, canary verify,
no auto-restart) stays in `spark-lane`. The server shells out to it and streams
progress. We do NOT reimplement lanelogic in JS.

---

## 2. The lane model (what the buttons control)

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

---

## 3. Architecture

```
sparkDash React UI (LaneControlPanel)
        │  POST /api/lanes/:lane/up | /down | /rotate  → 202 {jobId}
        │  GET  /api/lanes/jobs/:jobId                 → job state + live log
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
concurrent rotations can wedge the fleet. One active job at a time, period.

### 4.2 Endpoints (follow existing `/api/sparks/...` conventions)

| method | path | body | returns |
|---|---|---|---|
| `GET` | `/api/lanes` | — | `{lanes:[{id,nodes,endpoint,model,status,occupant}]}` (from `spark-lane lanes` + live census) |
| `GET` | `/api/lanes/status` | — | live census (what's up where) |
| `POST` | `/api/lanes/:lane/up` | `{confirm?}` | `202 {jobId}` |
| `POST` | `/api/lanes/:lane/down` | `{confirm:true}` | `202 {jobId}` |
| `POST` | `/api/lanes/:lane/rotate` | `{confirm:true, endLane?}` | `202 {jobId}` |
| `POST` | `/api/lanes/:lane/verify` | — | `202 {jobId}` |
| `GET` | `/api/lanes/jobs/:jobId` | — | `{state, lane, verb, progress:[...], result}` |
| `POST` | `/api/lanes/jobs/:jobId/cancel` | — | `202` (SIGTERM the child) |

Design notes:
- Long ops return **202 + jobId**; the UI polls `GET /jobs/:jobId` (DecodeBench
  does exactly this and it works). No long-held HTTP request.
- `verb` is validated against an allow-list `["up","down","rotate","verify"]`;
  `lane` against the list from `spark-lane lanes`. Anything else → 400. (Same
  discipline as `isAllowedTargetHost` in `validate.js`.)
- **No shell interpolation of user input** — spawn with an args array:
  `spawn("bash", [SPARK_LANE_PATH, verb, lane], {cwd: BENCH_DIR})`. Never string-concat
  into a shell.

### 4.3 spark-lane changes needed (small)

1. **Add `spark-lane lanes --json`** → machine-readable lane table
   (`[{id,nodes[],endpoint,model}]`). Today `lanes` is human-formatted.
2. **Add `spark-lane status --json`** → machine-readable census.
3. Confirm exit codes are stable: `0`=PASS, `1`=FAIL, `124`=timeout (already true
   via `timeout_run`). The server maps exit code → job `state`.

Everything else (occupancy guard, recipe fidelity, canary, no auto-restart) is
**already in spark-lane and must not be duplicated**.

---

## 5. Frontend spec

### 5.1 New component: `src/components/SparkPage/LaneControlPanel.tsx`

Placed on the **Overview page** (fleet-level, since lanes span units), plus a
compact status strip on each SparkPage showing "this unit is part of lane X".

Layout:

```
┌─ Lane Control ──────────────────────────────── [⟳ refresh] ─┐
│  ◉ creative-engine   spark2        :7862+:8765   ● down      │
│  ○ dsv41-tp3         spark1,3,4    :8000         ● SERVING   │
│  ○ dsv41-tp4         spark1-4      :8000         ● SERVING   │
│  ○ glm53-tp3         spark1,3,4    :8888         ● down      │
│                                                              │
│  [ Rotate → dsv41-tp4 ▾ ]   [ Verify ]   [ Take down ]       │
│                                                              │
│  ── job: rotate → dsv41-tp4  (running, 4m12s) ──             │
│  [6/7] wait healthy … endpoint up after 300s                 │
│  [8/7] canary … TEXT[ready] tok=2          [Cancel]          │
└──────────────────────────────────────────────────────────────┘
```

Buttons:
- **Rotate → \<lane\>**: primary action. Rotates to the selected lane (parks
  whatever's running, brings it up). This is the one-shot.
- **Verify**: read-only health check on a lane, no teardown.
- **Take down**: parks the selected lane. Destructive → confirm dialog.
- **Up**: bring a lane up without parking others (only valid if nodes free).
- **Stop current job**: cancels the running job (SIGTERM child).
- Live progress pane streams the `spark-lane` step lines (`[n/N] step …`) so the
  15–25 min boot is visibly progressing, not a dead spinner.

Reuse: `ConfirmShutdownDialog.tsx` pattern for the destructive confirm.

### 5.2 API client additions (`src/api/client.ts`)

```ts
export function listLanes(): Promise<{lanes: LaneInfo[]}>
export function laneStatus(): Promise<LaneCensus>
export function startLaneJob(lane, verb, opts?): Promise<{jobId}>
export function getLaneJob(jobId): Promise<LaneJob>
export function cancelLaneJob(jobId): Promise<void>
```

---

## 6. Safety model (non-negotiable)

These mirror the `spark-lane` hard rules and the GB10 operations skill.

1. **Single-flight.** One lane job fleet-wide at a time. Second request → `409`.
   Concurrent rotations = wedge risk. Enforced server-side, not just hidden buttons.
2. **No auto-restart, ever.** No `--restart` policy, no watchdog that restarts a
   lane. GB10 hard rule: never auto-restart an unverified vLLM/SGLang config. The
   buttons are user-initiated only.
3. **Occupancy guard stays in spark-lane.** The UI does not decide what's safe to
   launch on; `spark-lane` refuses and the UI surfaces the refusal (`409`/`FAIL`
   with the harness's `NEXT:` hint).
4. **Destructive ops require explicit confirm.** `down` and `rotate` need
   `{confirm:true}` + a dialog. Never a bare click that tears down production `:8000`.
5. **Auth.** The API is currently unauthenticated (tailnet-only approved ceiling).
   Lane control is **more destructive** than the existing power buttons, so:
   - keep tailnet-only (no wider exposure without fresh approval), AND
   - require a **lane-control token** (`X-Lane-Token`, from server env / secretsStore)
     for any non-GET `/api/lanes/*` — a second gate beyond the tailnet. GET status
     stays open (read-only).
6. **Bounds.** Per-job wall-clock ceiling (reuse `ENGINE_MAX_WAIT`, 3h) + a hard
   server-side kill; a stuck job is cancellable and auto-expires.
7. **Audit.** Every job records `{who, lane, verb, startedAt, endedAt, result}` to a
   log file (`logs/lane-control.jsonl`) — who rotated the fleet and when.
8. **No artifact deletion.** `down` never deletes weights/images (spark-lane already
   honours this); the UI adds no delete button.

---

## 7. Build plan (phased, each phase independently useful)

**Phase 1 — read-only lane panel** (low risk, ship first)
- `spark-lane lanes --json` + `status --json`.
- `GET /api/lanes`, `GET /api/lanes/status`.
- `LaneControlPanel` showing live lanes + serving state + verify button only.
- Value: a real fleet lane view in the dashboard; zero destructive surface yet.

**Phase 2 — one-shot rotate**
- `LaneManager` + job endpoints + `POST /rotate` (guarded, confirm + token).
- Live progress streaming from the job log.
- Value: the headline feature — "rotate the fleet to lane X" from the UI.

**Phase 3 — up / down / cancel + audit**
- Remaining verbs, confirm dialogs, `logs/lane-control.jsonl`, job history view.

**Phase 4 — polish**
- Per-Spark "member of lane X" strip; job history tab; token management in Settings.

---

## 8. Acceptance criteria (production gate)

The buttons are "done" only when, from the UI on a live fleet:

1. The panel lists every lane `spark-lane` knows, with correct live status.
2. `Rotate → dsv41-tp4` parks the running lane, brings dsv41-tp4 up, and the panel
   shows **SERVING** — verified by the panel's own canary, not the exit code alone.
3. A second rotate while one is running is refused with a clear `409`.
4. `Take down` on the serving lane requires confirm and then genuinely frees the nodes.
5. Killing the browser mid-job does not kill the job (server-owned); reopening shows
   the job still running/finished.
6. After a full rotate-all, the fleet is left on the requested end lane (the
   `--end` bug fixed 2026-09-26 must not reappear).
7. Every destructive action is in `logs/lane-control.jsonl` with a timestamp.

---

## 9. Open decisions for Victor

1. **Token gate** — do you want the `X-Lane-Token` second gate (§6.5), or is
   tailnet-only enough given the dashboard already exposes power controls?
2. **Placement** — fleet-level Overview panel only, or also per-Spark strips?
3. **Rotate-all button** — expose a one-click "run the full rotation test"
   (`rotate-all.sh`) in the UI, or keep that as an agent/cron-only diagnostic?
4. **Confirm strength** — dialog only, or dialog + type-the-lane-name to confirm
   (high-friction) for `down`?
5. **End-lane selector** — should `Rotate →` always land on one fixed default
   (dsv41-tp4), or expose the end-lane choice per click?