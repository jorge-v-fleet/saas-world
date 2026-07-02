# Architecture proposal (v0 — to iterate)

## Core stance

- Single node, **single writer**: one Simulation Kernel owns all world state; nothing else mutates it.
- **Discrete-event, explicit sim-clock**: an event queue ordered by sim-time; the clock advances by events, never by wall-clock / inference latency.
- **Scenarios are data**: seed world + personas + scheduled events + eval ground truth, loaded into the kernel. No code-per-scenario.

## Pieces

- **Kernel** — holds `SimClock`, `EventQueue` (min-heap by sim-time), and the world `State`. Pops due events, applies them, may enqueue follow-ups.
- **World State** — company/projects/tasks/deps/blockers + per-surface stores (chat, email, calendar, docs, transcripts).
- **Tool API** — thin adapters the agent calls (send_message, create_task, book_meeting, read_inbox…). Each call = an event → state mutation + optional scheduled follow-up.
- **NPC engine** — stateful coworker personas, split into two layers so behavior stays deterministic:
  - **Decision core (deterministic)** — a scripted state machine + rules over the NPC's **scoped world-state view** + goals/constraints. **The only layer that mutates world state or schedules events**, so it's the only layer grading depends on. Replies are scheduled at `now + realistic_delay` (latency ≠ sim-time); each NPC also runs on its own cadence via **self-scheduled wake-ups** (see below).
  - **LLM as parser only (the LLM does *not* decide or act)** — a thin, schema-constrained adapter with exactly two jobs: (1) map the agent's **free-form message → one of a fixed set of intents** the decision core understands, and (2) render the core's chosen reply in the persona's voice. It **cannot invent world facts** — only surface facts already in the NPC's known state. It exists solely because chat/email input is free text; most turns the rules classify directly and never call it.
  - **Determinism guards** — temp 0 + fixed seed; cache keyed by `(NPC state, context hash)`; log every call and replay from the log so eval reruns are reproducible. Grading is **state-based, not prose-based**, so parser phrasing never leaks into scores.
- **Evaluator** — reads state snapshots + event log at checkpoints. Deterministic state-delta checks carry the score; for free-text artifacts an **LLM extractor (parser-only, no scoring)** pulls structured claims that a deterministic rubric grades. No LLM judge.
- **Operator/CLI** — start/seed scenario, step the agent, inspect state, run eval. (No agent-facing "advance time" verb — the clock only moves via durationed actions in the action space; any manual operator advance is a debug affordance over the same event path.)

## Scenario = the world dataset

- Since the LLM only parses, **everything that defines a coworker lives in data** — the scenario dataset is the single source that seeds the environment. No behavior hidden in code.
- A scenario bundles: **seed world state**, one **persona pack per NPC**, a **background event timeline**, and **eval ground truth**.
- **Persona pack (per NPC / per role)** — the dataset that configures each coworker's LLM+rules:
  - **Identity/role** — name, title, reporting line, relationships.
  - **Goals & constraints** — private objectives that drive the decision core (why they push back, stall, or escalate).
  - **Knowledge scope** — the facts this NPC holds and *may reveal* — the gated info the agent must discover (blockers live here).
  - **Voice/persona** — style the parser uses to render replies (rendering only; never a source of facts).
  - **Allowed intents** — the fixed set the parser maps free-form messages into.
  - **Behavior params** — response-delay distribution, wake-up cadence, escalation triggers.
- Because packs are **uniform data**, scaling to many scenarios = authoring more datasets, not more code — the anti-prompt-spaghetti guarantee. Same schema also feeds eval (ground truth references the same NPC/knowledge IDs).
- **Authoring → generation.** Hand-authoring one instance is the floor; scaling is a **build-time seeding engine** that turns an archetype template + seed into a frozen instance (world + persona overlays + timeline + **co-generated eval**), gated for solvability. Substrate lives in `data/`; full spec in `04-seeding-engine.md`.

## How time advances (next-event, not agent-driven)

- **What moves the clock is the next scheduled event — not the agent.** The agent is one event source among many; coworkers, meetings, and timers are peers on the same queue.
- **Next-event jump**: the clock advances straight to the timestamp of the next due event, then fires it (and any others at that time) in order. No wasted ticks between events.
- **Clock release lives in the action space, not in a special method.** There is no privileged "advance time" API — **`wait` is just another action** alongside `send_message`/`create_task`; it differs only in that it **carries a duration**. Any durationed action releases the clock the same way. This keeps one uniform action interface and one code path for advancing time.
- When an action carries a duration, **every coworker/background event in that window resolves in timestamp order** — replies land, mockups get pushed, a blocker surfaces.
- So the agent doesn't *cause* coworker work; it only controls **how far the observer's clock is allowed to move**. Nothing is "frozen because the agent is special" — the world simply doesn't advance past pending events until something releases the clock.

### Coworkers advancing "in parallel"

- Parallelism is an **illusion from interleaving timestamped events on one shared timeline** — not real threads, not a free-running clock.
- Each coworker acts by itself through three event flavors, all on the same queue:
  - **Scripted** — scenario timeline (`designer pushes mockups @ Tue 14:00`).
  - **Reactive** — replies to the agent at `now + realistic_delay`.
  - **Autonomous** — a recurring **self-scheduled wake-up**: on fire, the NPC re-plans against its goals, mutates state, and schedules its *next* wake-up. This recurring self-reschedule is what gives each coworker an independent tempo — no background loop needed.
- **Why not a free-running/real-time clock:** it would recouple sim-time to wall-clock and destroy determinism (the brief forbids this). Same seeds + one event queue → identical interleaving → **replayable, stable grading**.

## What advances when

- **Synchronous** with an agent action: its direct state mutation + immediate tool response (read inbox, create task). Zero-duration actions don't move the clock.
- **Asynchronous** (fires when a durationed action releases the clock to its timestamp): NPC replies, autonomous NPC wake-ups, meetings starting, blockers surfacing, stakeholder pressure escalating.
- **Interruptions** fit the same model: events landing inside a durationed action's window are delivered as notifications on the agent's next observation, still ordered by timestamp.

## Evaluation (deterministic-first, no LLM judge)

- **No LLM judge.** Holistic quality scoring is stochastic and reward-hackable (fluent-but-empty output games it) — we avoid it entirely.
- **Reward = state deltas** vs. ground truth (τ-bench style): blocker resolved? dependency unblocked? meeting booked with right people? decision recorded? — structured facts → **exact programmatic checks**, at intermediate checkpoints and end state. Not message/activity counts.
- **Free-text artifacts = extraction, not judgment.** For irreducibly prose outputs (status doc, decision email), the LLM converts prose → **structured claims against a fixed question schema** (`mentions decision X? names owner Z? states deadline?`) → booleans/fields. A **deterministic rubric** then compares those fields to ground truth and assigns the score. The LLM never sees the rubric or emits a number — **same parser-only stance as the NPC layer**.
  - Prefer to remove even this: make reward-bearing outputs **structured** (e.g. a `record_decision` action) so grading reads structure directly and the extractor disappears.
- **Stability guards (model-verification bar from the brief):**
  - *Why*: only for genuinely free-text artifacts. *Inputs*: just the artifact + fixed extraction schema, nothing else.
  - *How stable*: temp 0 + seed; narrow yes/no/field pulls (far more stable than quality ratings); cache + log + replay so a score reproduces exactly; **disagreement → flag for human review, never average**.
  - Keep any extracted-semantic component a **small, bounded slice**; deterministic state checks carry the weight.
- **Injection resistance**: an extracted claim is credited only if **consistent with world state**, the parser never sees the rubric/score, and agent text is treated as inert data — so prompt-injection can flip a bit but capture no reward. Worked example + full defense list in `03-eval-example.md`.

## Diagram

```
                 ┌────────────────────────────────────────────┐
   Operator/CLI  │              SIMULATION KERNEL              │
  ┌───────────┐  │   (single writer; sim-clock ≠ wall-clock)   │
  │ seed/step │──┼─▶ ┌──────────┐   ┌──────────────────────┐   │
  │ advance   │  │   │ SimClock │──▶│ EventQueue (by time) │   │
  │ inspect   │  │   └──────────┘   └───────────┬──────────┘   │
  └───────────┘  │                    pop due   │ enqueue      │
                 │                              ▼ follow-ups    │
  ┌───────────┐  │  Tool API      ┌─────────────────────────┐  │
  │  Agent    │──┼─▶ send_msg ───▶│      World State        │  │
  │ under test│◀─┼── read_inbox   │ company·projects·tasks  │  │
  └───────────┘  │   create_task  │ deps·blockers · chat/   │  │
                 │                │ email/cal/docs/transcript│  │
                 │        ▲       └───────────┬─────────────┘  │
                 │        │ scheduled reply   │ snapshot        │
                 │  ┌─────┴───────┐           ▼                 │
                 │  │ NPC engine  │    ┌──────────────┐         │
                 │  │ decision    │    │ Evaluator    │         │
                 │  │ core (rules)│    │ state deltas │         │
                 │  │ +LLM parser │    │ +LLM extract │         │
                 │  └─────────────┘    └──────────────┘         │
                 └────────────────────────────────────────────┘

  Scenario (data) ─▶ seeds State · registers NPC personas ·
                     schedules background events · defines eval ground truth
```

## Open questions (for next pass)

- Which actions carry a duration (release the clock) vs. are instantaneous — and can the agent ever be interrupted mid-action?
- NPC wake-up cadence: fixed interval per persona, goal-triggered, or event-driven only? Cap re-planning cost per sim-hour.
- Snapshot/replay for deterministic eval reruns.
- NPC reply determinism (seed/temperature, or cache) for stable grading.
