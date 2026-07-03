# Case `delivery-slip` — long-horizon delivery under internal execution slip

Data-only scenario case. Ships as one template (`data/templates/delivery-slip.json`) plus a frozen
scenario — **no `src/` change**. §7 lists the authoring constraints that keep it that way.

## 1. Premise

- `org.pm_a` owns a portfolio (2 projects) and must land one **target feature** by a fixed date
  (~`D10`). The feature is **three functionalities** (`f1`, `f2`, `f3`), each `done:false` at seed.
- One engineer (`$holder`) owns the critical-path functionality `f2` **and** a competing work item
  `w1` (a task in the *other* project) that is currently marked high-priority and eating their time.
- Mid-week (~`D3`) `$holder` reports the slip in standup/chat: `f2` will land **days late** because
  `w1` is consuming them. Left alone, `f2` misses `D10` → the feature can't ship full scope.
- The naive PM keeps the rosy plan (project `reported_status: on_track`) and lets the slip stand.
  The competent PM **detects it, replans (reallocates), records honest status, tells the
  stakeholder, and makes the correct go/no-go.**

## 2. How this differs from `release-triage`

| | `release-triage` | `delivery-slip` |
|---|---|---|
| Interrupt | external regression in prod | internal engineer slip / contention |
| Nothing is *broken* | a bug to fix | a plan to re-sequence |
| Correct core move | triage + fix first | reallocate/deprioritize, then replan |
| Failure mode punished | shipping on top of a live bug | shipping a stale plan / hiding the slip |

Same engine, same anti-gaming spine (system-sourced + denied graded fields, gated completions),
different PM skill: **schedule-risk management**, not incident response.

## 3. World blueprint (flat ids — see §7)

- **projects** (2, both `reported_status: on_track`, system-only `true_status`):
  - `feature_x` — the target feature. `owner: $agent`, `launch_date: $deadline_offset`,
    `true_status: at_risk`.
  - `platform` — the other project. `true_status: on_track`. Holds the competing work `w1`.
- **tasks** (flat ids):
  - `f1` — project `feature_x`, owner `$holder`, `done:false`. Lands on schedule (not at risk).
  - `f2` — project `feature_x`, owner `$holder`, `done:false`, `slipped:true`, `critical_path:true`.
    The one at risk; recovers only via a gated flip (§5).
  - `f3` — project `feature_x`, owner `$holder2`, `done:false`. Lands on schedule.
  - `w1` — project `platform`, owner `$holder`, `priority:high`, `deprioritized:false`.
    The contention source; deprioritizing it frees `$holder` to finish `f2`.
- **surfaces:** kickoff email from `$stakeholder` ("feature_x ships this sprint — keep me honest");
  `chan.feature_x` release channel (members: agent, holder, holder2, stakeholder); `D1` standup;
  a `doc.plan` that still claims `on_track`.
- **personas / overlays:** `$holder` (wants to be unblocked, won't hit the date while `w1` is hot);
  `$stakeholder` (wants the date; accepts a concrete revised plan, not silence).

## 4. Graded outcomes (weights = 1.0)

| id | w | assertion (eval DSL) | why un-gameable |
|---|---|---|---|
| `status_truthful` | 0.15 | `decisions[?type=='status' && about=='feature_x']` | grounded in system-only `true_status` — rosy `reported_status` earns nothing |
| `replan_recorded` | 0.15 | `decisions[?type=='replan' && action=='reallocate']` | free enum, but scored only for the right call |
| `w1_deprioritized` | 0.15 | `tasks.w1.deprioritized == true` | system-sourced + **denied**; flips only via gated effect on the agent's reprioritize action |
| `f2_recovered` | 0.25 | `tasks.f2.done == true` | system-sourced + **denied**; gated on `w1` deprioritized **before `D8`** — busywork can't flip it |
| `stakeholder_informed` | 0.10 | `messages[?to=='$stakeholder' && references=='feature_x']` | must name the at-risk feature specifically |
| `correct_gonogo` | 0.20 | `decisions[?type=='gonogo' && about=='feature_x'].action in $correct_set` | correct only once `f2` recovered; `$correct_set` is draw-derived |

`f1`/`f3` complete on schedule as plain system facts (not graded) — grading targets the *slipping*
path, keeping the signal on the PM's judgment rather than on work that was never at risk.

## 5. Anti-gaming: denied paths + gated flips (all data)

- **Denied paths:** `projects.*.true_status`, `tasks.*.done`, `tasks.*.deprioritized`.
  The agent can never hand-set the truth, a completion, or the reprioritization.
- **Gated completions (timeline `system_effect`, fire only if the precondition holds):**
  - `ev.deprioritize_w1` — `set tasks.w1.deprioritized=true` **iff** the agent recorded the
    reallocation (`decisions[?type=='replan' && action=='reallocate']`).
  - `ev.recover_f2` (at ~`D8`) — `set tasks.f2.done=true` **iff** `tasks.w1.deprioritized==true`.
    Chains off the first, so `f2` recovers only when the PM actually freed the engineer in time.
- Everything graded is either a system-flipped fact behind a denied path, or a recorded decision
  scored for correctness — so chatter / hand-set task status touches nothing.

## 6. Reference solvers (validity gate: competent → 1.0, lazy → 0.0)

- **competent** (real work, full score): record `replan/reallocate` → system flips
  `w1.deprioritized` → system flips `f2.done` → record honest `status` → message `$stakeholder`
  with the revised plan → record `gonogo=ship` → advance to the checkpoint.
- **lazy** (chatter only, ~0): five upbeat messages to `chan.feature_x`, then advance. Touches no
  graded field.

## 7. Authoring constraints (what the generic engine expects)

Not code to change — the guardrails that keep the template data-only. The generic solver runner
references a few binding names, so the template must provide them:

- bind **`critical_project`** = `feature_x`.
- derive **`deadline_day`** (`day_of $deadline_offset`) and **`correct_set`** (drives `gonogo`;
  `correct_set[0]` is the competent solver's `correct_action`).
- a chat channel **`chan.<critical_project>`** (= `chan.feature_x`) for the lazy solver's target.
- **flat, single-segment ids** for every denied entity (`f2`, `w1`, `feature_x`) so the 3-segment
  denied globs (`tasks.*.done`) match the write path.
- model the competing work `w1` as a **task** (not a new partition) — a new partition would need
  loader code and break the data-only promise.
- **Guard the bind in `coherence`.** The binder ignores the `owned_by agent` selector and picks any
  project by RNG, so a seed can mis-bind `critical_project` to `platform`. Because the graded tasks
  (`f1`/`f2`/`f3`) reference `$critical_project`, a coherence invariant on the critical-path task's
  project pins it: `field_eq {path: tasks[?critical_path==true], field: project} eq feature_x`. A
  mis-bound seed then fails coherence and `find_valid_seed` resamples past it — so **every generated
  instance is valid by construction**, not just the pinned example seed. General pattern: whenever an
  entity slot the binder can't constrain must resolve to a specific world id, assert it in
  `coherence`.

## 8. Open decisions (defaults in **bold**)

1. **Correct strategy — single or branching?**
   - **v1: single strategy = reallocate** (fixed deadline; recover `f2`, ship full scope). Cleanest
     gate.
   - v2 option: sample `f2.required` true/false → correct move branches
     (`reallocate`+`ship` vs `cut_scope`+`ship_reduced`), `correct_set` derived via `select`.
     Stronger anti-memorization, ~2× solver logic. Land v1 first.
2. **Slip cause draw:** `blocker.type` (reuse the slot name) sampled from
   **`["pulled_onto_other_work", "underestimated_task"]`** — flavors the holder's report and the
   `w1` framing; grading identical either way.
3. **How many functionalities:** **3** (one slipping). Bump to 4–5 later for more coverage weight.
4. **Deadline:** **fixed `D10`** for v1 (movable-date branching folds into decision 1's v2).
5. **New graded verb?** **No** — reuse `record_decision(type='replan'|'status'|'gonogo')` +
   `send_message`. Nothing new in the catalog.

## 9. Next steps (after the shape is signed off)

1. Fold edits into this file.
2. Author `data/templates/delivery-slip.json` via the scenario-author agent, mirroring
   `release-triage.json` (slots, bind_order, activate, derive, world, blockers, timeline gated
   effects, denied_paths, eval_shapes, coherence, solvers, example_binding).
3. `generate delivery-slip <seed>` → `validate` (gate passes) → `freeze`.
4. Add an integration test mirroring `tests/integration/test_release_triage.py`.
5. Confirm `hidden-critical-blocker` seed 1206 stays byte-identical and `make check` is green.
