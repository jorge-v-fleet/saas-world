---
marp: true
theme: default
paginate: true
title: saas-world
author: Jorge Vizcayno
---

<!-- _paginate: false -->

# SaaS World

### An environment for a PM of a SaaS company.

<br>

**Jorge Vizcayno**

---

## The problem

Drop an agent into a simulated PM work-week and see if it can actually do the job.

- **Time advances by simulation**, through a work week, decoupled from how long the model thinks.
- The agent works only through **internal tool surfaces**: chat, email, calendar, task tracking, docs, meeting capture.
- **Coworkers are stateful**: own goals, background activity, proactive outreach, realistic reply delays.
- The agent must **discover blockers, resolve conflicts, prioritize tradeoffs, keep projects moving.**
- The system **grades whether outcomes actually improved**, not whether the agent looked busy.

---

## System at a glance

Two boundaries define the design: **build-time vs runtime**, and a **single writer** for all world state.

```diagram-system
BUILD-TIME  (all randomness resolved offline)
  Data Substrate  ──▶  Seeding Engine  ──▶  Frozen Scenario Instance
  world·personas·      sample→bind→assemble      seed·overlay·timeline
  templates            →project-eval→gate→freeze  ·eval  + content hash
                                                    │  loads unchanged
                                                    ▼
RUNTIME  (deterministic; consumes the instance as-is)
  Agent ─▶ Tool API ─▶ ┌───────────────┐ ◀──▶ World State Store
                       │    KERNEL      │
                       │  single writer │ ◀──▶ NPC Engine
                       │  + event queue │       (rule core + LLM parser)
                       └───────────────┘
                               │  every event appended
                               ▼
                       Trajectory Store ──▶ Evaluator ──▶ Operator CLI / Inspector
```

**Design invariant:** the LLM is an *authority-less classifier*. All truth, scoring, and disclosure live in deterministic code + state.

---

## Simulation Kernel: the clock & single writer

- Holds `SimClock` + an **event queue** (min-heap by sim-time). **Next-event progression**: time jumps to the next scheduled event, never tracks wall-clock.
- The **only path that mutates world state**: every change is an event applied here. One writer ⇒ no races, fully replayable.
- **Three action classes are the sync/async spine:**
  - `observe`: zero-duration, no mutation; scoped read. *Clock still.*
  - `mutate`: zero-duration state delta + immediate ack; may schedule follow-ups. *Clock still.*
  - `advance`: carries a duration; **the only class that moves time.** `wait` is the simplest, no privileged "advance time" verb.
- Interface: `schedule(event)` · `advance_until(release)` · `now()`.

> Answers *what is synchronous vs background*: agent mutations are instant; NPC replies, wake-ups, and scheduled pressure fire during an `advance` jump, delivered as time-ordered notifications.

---

## World State Store: how the world is defined

The world is a set of **namespaced partitions**, one typed store per concern, and every fact lives at a **path** (`tasks.f2.done`, `projects.feature_x.true_status`). That same path grammar is what actions write and what the grader reads.

- **Core partitions (live):** `org · projects · tasks · blockers · surfaces` + the tool surfaces `chat · email · calendar · docs · decisions · messages`.
- **Tiers gate who is live:** `agent` (the PM under test) · `active` (full stateful NPC) · `reference` (org structure / mentions only). Promote a coworker by flipping a tier: no code.
- **Reads are typed & scoped; writes happen *only* via Kernel-applied events**: one mutation path. Snapshot / restore gives exact replay.

It's just data, loaded from `data/world/*`:

```json
company  { "id":"co.nimbus", "name":"Nimbus", "product":"B2B analytics SaaS", "stage":"series-b" }
org.node { "id":"org.fe_a1", "title":"Frontend Engineer", "name":"Sam Torres",
           "reports_to":"org.pm_a", "tier":"active" }
task     { "tasks.f2": { "project":"feature_x", "owner":"org.fe_a1",
                         "done":false, "critical_path":true } }
```

<p class="foot">Reserved for the future: <code>cust · fin · seas</code> (customers / financials / seasonality): declared but disabled today, enabled as new scenarios need them.</p>

---

## World State: how it changes

Every change is an **event carrying a delta** (`op · path · value`), applied by the Kernel as the **single writer**. Reward-bearing facts flip only when the agent does the real work that *gates* them. No verb writes the field directly.

```diagram-transition
START · seed.json                     EVENT ev.validate_f1 @ D6T15:00        NEXT STATE
  tasks.f1.validated       = false      gated_on: calendar[title=='validate f1'] ✓
  blockers.regression.resolved = false  delta:    set tasks.f1.validated = true   tasks.f1.validated: false → true
  projects.billing_v2.true_status = at_risk
        └─ agent books "validate f1" ─▶        └─ Kernel applies (single writer) ─▶
```

> `tasks.f1.validated` flips **only because the agent booked the validation**: the field is otherwise unwritable. Same shape for every fact: seed value → gated event → one applied delta → next state.

---

## Tool API: the agent's only surface

- Uniform envelope: **`verb + args`** → validated (arg schema + preconditions + the actor's view scope) → one event. The catalog is **data** (`data/actions.json`); adding a verb is a data entry, not new code.
- Each catalog entry: `id · class · args · effect (delta DSL) · emits · pre · returns`. **Three classes by clock effect:** `observe · mutate · advance`.
- **Prose can't earn score**: to move the grade the agent emits structured fields (`record_decision`, or a message's `refs`), which the grader reads directly.

```
send_message    { to, body, refs? }                     mutate  → append messages; emits npc_reply @ now+delay
record_decision { about, type, action?, new_date?, owner? }  mutate  → append decisions   (the reward-bearing verb)
wait            { duration }                            advance → release clock to now + duration
```

> **Example:** `send_message{ to:"org.be_b2", body:"is payments ready for Friday?", refs:["blocker.psp_cert"] }` → parsed to intent `ask_status` → schedules the coworker's reply. `refs` is the structured pointer the grader trusts, never the prose.

---

## NPC Engine: stateful coworkers

- Per-persona **decision core is deterministic**: rules / state machine over a scoped world view + goals.
- The **LLM is parser-only**: free text → a fixed intent set, and renders a reply *in voice*, inventing no facts and holding no authority.
- **Reactive replies** at `now + persona.delay`; **autonomous self-scheduled wake-ups** give each coworker independent cadence and proactive outreach.
- A **blocker surfaces only via an NPC's reveal**: no agent action can flip `blocker.*.surfaced`, so discovery stays real.

```diagram-npc
agent free-text ─▶ LLM parser ─▶ deterministic ──┬─▶ world effect via Kernel
   message         text→intent    decision core   │     (e.g. reveal blocker)
                                  scoped view+goals└─▶ reply in voice @ now + delay
```

> **Example:** agent asks *"is payments ready for launch?"* → parser → intent `ask_status(payments)` → Priya's decision core fires her **reveal**: `blocker.psp_cert.surfaced = true` (no agent verb can set it) **+** a voiced reply: *"Not yet, the PSP cert clears Thursday."*, delivered at `now + delay`.

---

## Seeding Engine & Scenario Loader: everything is data

- **Seeding Engine (build-time only)** turns a template + seed into that instance:
  `sample` → `bind` → `assemble` → **`project-eval`** (co-generate the grader from the *same* resolved facts, so world & eval can't drift) → **`gate + freeze`**.
  - **Content-addressed:** `(template_id, seed, substrate_hash, generator_version)` → byte-identical instance. Loader **re-hashes and refuses to run on `dataset_version` mismatch**: a run can never silently drift from the data it claims.
  - **This is how it scales to many scenarios** without prompt-spaghetti: archetype = one declarative template; instances = a seed. No LLM anywhere in generate→freeze.
- **Loader** consumes a **frozen instance unchanged** (`seed.json · personas.overlay.json · timeline.json · eval.json + manifest`): no code per scenario, no generation at load.

> A **frozen instance** *is* the whole scenario as data, load it and the world is live:
> `seed.json` (initial world state) · `personas.overlay.json` (per-NPC goals + delays) ·
> `timeline.json` (scheduled + gated events) · `eval.json` (ground truth) ·
> `manifest` (content hashes + provenance).

---

## Evaluator: deterministic, inspectable, un-gameable

- Grades **structured facts against predicates at checkpoints**, never text-vs-text. Reads the *trajectory* (event log + state reconstructed by projection).
- LLM here is an **extractor only** (free text → structured claims); a **deterministic rubric** scores them. **No LLM judge.** Claims are credited only if **consistent with world state** → injection-resistant.
- **Grade == replayable:** scores the exact bytes we persist; re-runnable offline against a stored trajectory.

| run | behavior | score |
|---|---|---|
| **A · real work** | messages the right coworker, records the decision, blocker clears | **1.0** |
| **B · reward-hacky** | 10 chat messages, hand-sets `status=in_progress`, no decision | **0.0** |

> Activity without real outcomes scores ~0. That's the whole point.

---

## Trajectory Store & Observability

- Every rollout persisted as a **replay-grade `trajectory.jsonl`**: one record per turn (`verb · args · sim_time · events`) + snapshots + manifest (`scenario_id`, `seed`, `agent_version`, hashes).
- **Any-POV views** (agent / NPC / operator / grader) are **reconstructed on demand** by projecting the log, never materialized.
- A **derived, rebuildable DuckDB index** powers cross-run queries.
- **Operator CLI + Inspector UI** (`localhost:8092/inspector`): drive, inspect, replay a run; read-only over `runs/`.

One causal chain, verbatim from a run: the `wait` advances the clock and the NPC's deferred reply fires:

```
{ "turn":1, "sim_time":0,   "verb":"send_message", "events":["agent->send_message"],  "args":{"to":"org.be_b2","body":"PSP ready Friday?"} }
{ "turn":2, "sim_time":120, "verb":"wait",         "events":["org.be_b2->npc_reply"], "args":{"duration":120} }
```

---

## Rollout trajectory examples

Every run is fully inspectable: score breakdown, event timeline, and the cohort distribution.

```shots
score-inspector.png   → score
traj-timeline.png     → trajectory timeline
rollout-distro.png    → distribution
inspector: http://127.0.0.1:8092/inspector
```

---

## Challenges

- **Growing breadth without regressions.**
  - New PM cases and wider world coverage can't silently break existing scenarios or their graders.
- **Keeping eval verifiers correct.**
  - As cases multiply, ground-truth predicates must stay faithful, never drifting into **verbatim string-matching** or **misreading what "improved" means**: provably right per case, resistant to both false credit and missed credit.

## Future improvements

- **Richer NPC agency, up to multi-agent.**
  - Give coworkers enough autonomy to act across their own objectives, and potentially a **multi-agent strategy** for more relaxed, open-ended exploration, while keeping **every run deterministic** through the NPC players.
- **More drivers of world state.**
  - Bring the reserved partitions online (`cust · fin · seas`: customers, revenue, seasonality) so **business dynamics move the world**, not just the people in it. Needs deeper data and explicit assumptions first.
