# Wave 3 spec — Evaluator (deterministic predicates only): score the seeded scenario

Third buildable slice (`01-systems.md` system 7, the deterministic-predicate slice). Goal: **read the trajectory produced by driving the discover loop, project state at each checkpoint, grade the ground-truth predicates against real fields, and emit a weighted score back into the trajectory** — fully deterministic, no LLM.

- **Stack:** Python 3.12+, on top of Waves 1–2 (Kernel + World State + Tool API + Scenario Loader + rule-based NPC). Still **single process, no Docker, no external services, no new deps.**
- **Trajectory (this wave):** the **in-memory event log + snapshots the Kernel emits** during a run (no durable Trajectory Store yet — that's Wave 6; the Store is only its durable form). The Evaluator reads this, it does not consume a separate live-state feed.
- **Out of scope (later waves):** the **LLM eval extractor** for genuinely free-text artifacts (Wave 4 — `05-...`); the durable Trajectory Store + re-grade-from-file CLI (Wave 6); autonomous NPCs; the Seeding Engine. In Wave 3, `decision_comms` grades **only its state-grounded portion from a structured `record_decision`**, or is marked **pending** when only a free-text artifact exists.

## The one deferral that shapes this wave

- The eval extractor (Wave 4) is what turns a free-text artifact (status doc, decision email) → structured claims. It doesn't exist yet.
- **Seam:** `eval.json.artifact_predicates[].prefer_structured == true`. When a structured `record_decision(about='proj.checkout')` action is present, the rubric reads its **fields directly** (deterministic) and applies each field's `requires_state` state-grounding check — no extraction needed. This is fully gradable in Wave 3.
- When **only** a free-text `fallback_source` (`doc|email`) exists, the predicate is scored **`pending`** (contributes 0, flagged, not failed) and deferred to Wave 4. Wave 4 drops the extractor in front of the **same rubric field-grading** — the rubric's `requires_state` contract is unchanged across waves.

## Design rules carried from research

- **Grade == replayable** (`03`): the Evaluator scores the **same bytes the run persists** (event log + reconstructed state), so a stored trajectory re-grades to the identical score with no episode re-run and no model call.
- **Fact vs. predicate, never text-vs-text** (`03`): every predicate reads a **real structured field** — field equality, set membership, existence, a changed-since-seed check — never prose, never string similarity.
- **State-grounding is the anti-gaming primitive** (`03`): a claim (incl. the state-grounded part of `decision_comms`) is credited **only if world state backs it**. Reward-bearing predicates read fields (`blockers.*.surfaced`, decision correctness, `blocked_by`) that **only `system`/NPC-reveal can write** under Wave 1's constrained-write guard — so activity padding (10 messages, hand-set `task.status`) touches **no graded field** and scores 0.
- **Read-only over the trajectory; append-only records** (`01`): the Evaluator mutates nothing in the world. It reads events with `seq < checkpoint` and **appends new** checkpoint/score records — not a cycle (score records are never read by predicates).
- **Weights are data, validated** (`04`): weights come from `eval.json` (co-generated with the world); the rubric validates the union sums to **1.0** on load, refuses otherwise.
- **No LLM, no privilege:** the Evaluator is pure deterministic code; it never mutates state, never reveals a fact, never sees free prose in this wave.

## Contracts (new shapes)

- **Trajectory** (read-only input; in-memory this wave): `{ events: [Event], snapshots: [{sim_time, seq, state}] }` — the Wave 1 `Event` log + periodic `WorldState.snapshot()`s the Kernel emits. Carries the **seed state** as `snapshots[0]` (baseline for `changed`).
- **Ground truth** (`eval.json`, handed over by the Scenario Loader in Wave 2): `checkpoints[].predicates[]` + top-level `artifact_predicates[]`; each predicate = `{ id, w, assert|source, ... }`.
- **PredicateResult:** `{ id, weight, credit: float∈[0,1], weighted: weight*credit, status: "pass|fail|pending", reason: str, reads_real_field: bool }`.
- **CheckpointScore:** `{ checkpoint_id, at: sim_time, predicates: [PredicateResult], subtotal: float }`.
- **WeightedResult** (the `score(...)` return): `{ scenario_id, checkpoints: [CheckpointScore], artifact_results: [PredicateResult], final: float∈[0,1], weights_sum: 1.0 }`.
- **Score record** (appended to the trajectory): `Event{ seq: <new>, sim_time: checkpoint.at, actor: "evaluator", kind: "checkpoint_score" | "final_score", payload: CheckpointScore | WeightedResult, caused_by: null }`. Append-only; higher `seq` than anything it read.

## System specs

### 7. Evaluator (deterministic predicates only — no LLM this wave)
- **Responsibility:** at each checkpoint `at`, reconstruct **state-at-checkpoint by projecting the trajectory**, evaluate every ground-truth predicate against real fields, take the weighted sum, and append checkpoint/final score records back into the trajectory.
- **Interface (mirrors `01`):** `score(trajectory, ground_truth) -> WeightedResult` — read-only over the trajectory, append-only score records. Pure function of `(trajectory, ground_truth)`: same bytes → same score.
- **Owns/mutates:** nothing in the world. Emits only its own `checkpoint_score` / `final_score` records (append-only).
- **Depends on:** the trajectory (event log + snapshots, systems 1/2), the Scenario ground truth (system 5). Reuses Wave 1 `WorldState.restore/apply` + path reads for projection — no new state machinery.

### Projection (state-at-checkpoint, reused primitive)
- **Responsibility:** `project(trajectory, at) -> state` — deterministically reconstruct world state as of sim-time `at`: restore the latest `snapshot` with `sim_time <= at`, then re-apply (via the Wave 1 delta path, `source="system"`) every event with `sim_time <= at` in `(sim_time, seq)` order.
- **Baseline for `changed`:** `project(trajectory, t0)` (== `snapshots[0]`) is the **seed state**; a `changed` predicate compares checkpoint-state vs. this baseline.
- Read-only; never mutates the live world — projects onto a throwaway `WorldState`.

### Predicate evaluator (pure, deterministic — the predicate kinds)
- One pure function per kind, each `(*, state, baseline?) -> (credit∈[0,1], reason)`; each reads a **real graded field** by path, never trusts prose. Kinds (bound from `eval.json`):

  | kind | `eval.json` shape | evaluation | credit |
  |---|---|---|---|
  | **field equality** | `assert: { path, eq }` | `read(state, path) == eq` | 1/0 |
  | **set / enum membership** | `assert: { in: { path, set } }` | `read(state, path) in set` | 1/0 |
  | **existence** | `assert: { exists: "coll[?<filter>]" }` | filter-match over a collection → non-empty | 1/0 |
  | **message-match** | `assert: { exists: "messages[?to==X && references==Y]" }` | existence over `surfaces.chat/email` messages matching `to` + `references`/`refs` | 1/0 |
  | **changed** | `assert: { path, changed: true }` | `read(state, path) != read(baseline, path)` | 1/0 |
  | **any (disjunction)** | `assert: { any: [ <assert>, ... ] }` | boolean OR of sub-asserts (each a kind above) | 1/0 |
  | **state-grounded `decision_comms`** | `source: "action:record_decision(...)"` + `score.{field}.{w, requires_state}` | read each structured field from the `record_decision` action; credit a field's sub-`w` **only if** its `requires_state` holds against `state` | Σ sub-w ∈ [0,1] |

- **Concrete bindings for `checkout-not-ready`:**
  - `blocker_surfaced` → field equality: `blockers.blocker.psp_cert.surfaced == true` (flips **only** via Priya's reveal — un-gameable).
  - `acted_on_blocker` → any: `projects.proj.checkout.launch_date` **changed** OR `decisions[?type=='gonogo' && about=='proj.checkout']` **exists**.
  - `correct_action` → set membership: `decisions.gonogo['proj.checkout'].action ∈ {reschedule, hold_and_mitigate}` (set derived at seed-time from `launch_date_movable`, carried in `eval.json`).
  - `stakeholder_informed` → message-match: `messages[?to=='org.cto' && references=='blocker.psp_cert']` exists.
  - `decision_comms` → state-grounded: from the `record_decision` action's fields — `cites_blocker` (w0.5, requires `blockers.blocker.psp_cert.surfaced==true`), `new_date` (w0.3, requires `projects.proj.checkout.launch_date` changed), `owner` (w0.2, requires an `org` node with that id). **If only a free-text artifact exists → `pending` (Wave 4).**
- **Path & filter reader:** a tiny deterministic helper — dotted-path read + index (`decisions.gonogo['proj.checkout']`) + a minimal list `[?a==X && b==Y]` filter matcher over list-of-dicts. **No new dep** (hand-rolled, ~closed subset; not full JMESPath). Missing path → predicate `fail` with a reason, never a crash.

### Scoring (weighted sum, partial credit)
- **Rubric load/validate** (`rubric.py`): parse `eval.json`; bind each predicate to its kind; **validate the union of all `w` (checkpoint predicates + `artifact_predicates`) sums to 1.0** (± float epsilon) — refuse otherwise. Mirror Wave 2's `-m validation` weights-sum check, now enforced by the grader itself.
- **Per predicate:** `weighted = w * credit`, `credit ∈ [0,1]` (binary kinds → {0,1}; `decision_comms` → fractional). `pending` contributes `weighted = 0` but is reported distinctly from `fail`.
- **Per checkpoint:** `subtotal = Σ weighted` over its predicates.
- **Final:** `final = Σ weighted` over **all** predicates (checkpoints + artifact) ∈ [0,1]. One checkpoint (`chk.final`) here, so `final == subtotal + artifact_results`.
- **Emit:** append a `checkpoint_score` record per checkpoint and one `final_score` record — into the trajectory, append-only, `seq` above everything read.

## How it works (score the discover loop)

1. Drive Waves 1–2 end-to-end (Loader seeds `checkout-not-ready`; agent discovers the blocker via Priya; records a go/no-go; messages the CTO) → the Kernel emits an event log + snapshots = **the trajectory**. `snapshots[0]` = seed state.
2. Loader hands `eval.json` to the Evaluator; `rubric.load` validates weights sum to 1.0.
3. For checkpoint `chk.final` (`at = D5T17:00`): `state = project(trajectory, at)`; `baseline = project(trajectory, t0)`.
4. Evaluate each predicate against `state` (+ `baseline` for `changed`):
   - `blocker_surfaced`: `surfaced == true` → **pass 0.30**.
   - `acted_on_blocker`: `launch_date` changed OR gonogo exists → **pass 0.30**.
   - `correct_action`: `action ∈ set` → **pass 0.15**.
   - `stakeholder_informed`: CTO message references `blocker.psp_cert` → **pass 0.10**.
   - `decision_comms`: structured `record_decision` present → sub-fields graded with `requires_state` → **≤ 0.15** (or `pending` if only free text).
5. `final = Σ weighted`; append `checkpoint_score` + `final_score` records. Real-work run → high (up to 1.0); activity-only run → **~0** (no graded field moved).
6. **Re-grade == replay:** re-running `score(trajectory, ground_truth)` on the same trajectory yields the byte-identical result — no episode re-run, no model call.

## Anti-gaming (why padding scores 0)

- Reward-bearing predicates read the **real derived/graded fields** — `blockers.*.surfaced`, `decisions.gonogo[...].action`, `blocked_by`, `launch_date` — which the Wave 1 constrained-write guard lets **only `source="system"`** (an NPC reveal / a validated `record_decision` effect) write.
- The agent has **no write path** to those fields: sending 10 chat messages, hand-setting `task.status = in_progress`, or writing prose asserting success touches **no graded field** → every predicate reads its unchanged real value → `credit = 0`.
- `decision_comms` compounds it: even a note claiming *"vendor=stripe, blocker cleared"* earns 0 unless the state actually backs each claim (`requires_state`) — the free-text credit is a bonus **on top of** a real state delta, never a standalone source.

## Testing strategy

Isolated suite (own directory + `evaluator` marker) plus cross-system integration + golden. Isolation via a **hand-built in-memory trajectory** (event log + snapshots) — the evaluator needs no live Kernel/API to unit-test.

- **Unit — `-m evaluator`** (`tests/evaluator/`):
  - **Predicate table** — each kind with a true **and** a false case against a fixed `state`: field equality (`surfaced` true/false); set membership (`action` in-set / out-of-set); existence (gonogo decision present/absent); message-match (CTO message referencing the blocker / referencing something else / absent); `changed` (`launch_date` moved / unchanged vs. baseline); `any` (neither / one / both sub-asserts); state-grounded `decision_comms` (all sub-claims backed → 0.15; a claim contradicting state → its sub-w withheld; only free-text artifact → `pending`).
  - **Weights validation** — a rubric whose weights sum to 1.0 loads; one summing to ≠1.0 **refuses**.
  - **Partial credit** — unblock + act but skip the note → `0.30+0.30+0.15+0.10 = 0.85`; `decision_comms` with 2 of 3 sub-claims backed → fractional; asserts exact weighted arithmetic.
  - **Projection** — `project(trajectory, at)` restores nearest snapshot ≤ at + replays events ≤ at in `(sim_time, seq)` order; `baseline == snapshots[0]`; read-only (live world untouched).
  - **Append-only** — score records get `seq` above everything read; predicates never read a score record (no cycle).
- **Integration — `-m integration`** (`tests/integration/`): mirror the two-runs example in `03`.
  - **Run A (real work):** drive the Wave 2 discover flow via the Tool API (message Priya → reveal → `record_decision(reschedule)` → message CTO referencing the blocker) → `score(trajectory, eval.json)` → **assert final ≈ 1.0** with the expected per-predicate breakdown.
  - **Run B (activity only):** send N messages + hand-set `task.status` (no reveal, no decision) → **assert final ≈ 0.0** (every graded predicate 0; guard held).
- **Golden — `-m golden`** (`tests/golden/`): a **fixed committed trajectory** (event log + snapshots) → `score(...)` → assert **byte-identical** score breakdown (per-predicate credit/weighted + final) against a stored golden. Extends the Wave 1/2 golden; regenerate with `--update-golden`. Flagship proof of grade==replayable.
- **Validation — `-m validation`** (extend): every `eval.json` predicate binds to a known kind; every `assert.path` resolves to a real partition; `requires_state` paths resolve; weights sum to 1.0.

Reuse the Wave 1 pytest-marker convention; register `evaluator` in `pyproject.toml`.

## How to run

```
pytest -m evaluator       # predicate table + weights + partial credit + projection (in-memory trajectory)
pytest -m integration     # drive discover flow -> score: real work ~1.0, activity-only ~0.0
pytest -m golden          # fixed trajectory -> byte-identical score breakdown
pytest                    # all (Waves 1-3)
ruff check . && mypy src

# score a run manually (single process)
python -m saasworld.serve
# load checkout-not-ready, drive the discover flow over /rpc, then score the emitted trajectory
```

## Single service vs Docker

- **Unchanged from Waves 1–2: single process, no Docker, no external services, no new deps.** The Evaluator is pure deterministic Python over the in-memory trajectory — no LLM (that's Wave 4), no DB (the durable Trajectory Store is Wave 6). Tests stay in-process (hand-built trajectories + `TestClient`, no port).

## Project layout (additions)

```
pyproject.toml            # + marker: evaluator
src/saasworld/
  eval/
    predicates.py         # pure predicate kinds (eq / in / exists / message-match / changed / any / state-grounded)
    score.py              # weighted sum + partial credit + per-checkpoint/final + emit records
    rubric.py             # load eval.json, bind predicates to kinds, validate weights sum to 1.0
    project.py            # project(trajectory, at): restore snapshot <= at + replay events <= at (baseline @ t0)
    paths.py              # dotted-path read + index + minimal [?a==X && b==Y] filter matcher (no new dep)
tests/
  evaluator/              # predicate table, weights validation, partial credit, projection, append-only
  golden/*.jsonl          # + fixed trajectory + golden score breakdown
  # integration/ extended with the two-runs (real work / activity-only) scoring
```

## Definition of done (Wave 3)

- `score(trajectory, ground_truth)` grades `checkout-not-ready` from a trajectory produced by driving the discover flow: real work → high (up to 1.0), activity-only → ~0.0.
- Every predicate kind (field equality, set membership, existence, message-match, changed, any, state-grounded `decision_comms`) passes its true/false table; `decision_comms` grades its structured state-grounded part and marks a free-text-only artifact **`pending`** (deferred to Wave 4).
- Weights are validated to sum to **1.0** on load; partial credit is exact weighted arithmetic.
- The Evaluator is **read-only over the trajectory** and appends `checkpoint_score`/`final_score` records (append-only, `seq` above everything read — no cycle).
- **Grade == replayable:** re-scoring the same trajectory is byte-identical (golden green); no episode re-run, **no LLM**.
- Anti-gaming holds: activity padding + hand-set fields move no graded predicate (integration Run B == ~0).
- `evaluator` marker green; Waves 1–2 markers still green; `ruff` + `mypy` clean; **How to run** works from a clean checkout with only a venv.

## As built (deltas from spec)

- **`correct_action` read path reconciled to the list-filter form.** `record_decision` appends to a flat `decisions` list, which cannot back the dotted-index `decisions.gonogo['proj.checkout'].action`. Fixed in `eval.json` (the Evaluator owns it) to `decisions[?type=='gonogo' && about=='proj.checkout'].action`; `record_decision`'s storage was left untouched. `paths.py` still implements `['index']` (dict subscript + list natural-key) for other reads.
- **Integration Run A/B drive at the Kernel/event level**, not the live `send_message`/parser path — a directly-scheduled system `reveal` (the same system-sourced delta the NPC produces), the real `record_decision` effect, and a CTO chat-append. This keeps scoring independent of the Wave 4 NPC-trigger rewrite.
- **Projection is a separate in-memory implementation** (`eval/project.py`) over `{events, snapshots}`; it mirrors `trajectory.replay.state_at` (disk-based) — unification is a later task, not a Wave 3 dependency.

## Milestones

1. `eval/paths.py` (dotted-path read + index + filter matcher) + `eval/project.py` (projection + baseline) → projection unit tests green.
2. `eval/predicates.py` (all kinds) → predicate table (`-m evaluator`) green with hand-built states.
3. `eval/rubric.py` (load/bind/validate weights==1.0) + `eval/score.py` (weighted sum + partial credit + emit records) → weights + partial-credit tests green.
4. Wire `score(...)` over a discover-flow trajectory → `-m integration` two-runs (real work ~1.0 / activity-only ~0.0) green.
5. Fixed trajectory + golden score breakdown → `-m golden` byte-identical; **DoD met**.
