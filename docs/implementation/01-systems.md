# Implementation — systems to build

High-level definition of what we build, distilled from `../research/`. Each system lists its **responsibility**, **interface**, **what state it owns/mutates**, and **dependencies**. Design invariant across all of it: **the LLM is an authority-less classifier; all truth, scoring, and disclosure live in deterministic code and state.**

## Systems

1. **Simulation Kernel** — the clock + event loop.
   - Responsibility: hold `SimClock`, `EventQueue` (min-heap by sim-time); pop due events, apply, enqueue follow-ups. Next-event time progression; sim-time ≠ wall-clock.
   - Interface: `schedule(event)`, `advance_until(release)`, `now()`.
   - Owns/mutates: the clock and queue. **Single writer** — the only path that mutates World State.
   - Depends on: World State (applies effects), NPC Engine + Evaluator (as event handlers).

2. **World State Store** — the company world model.
   - Responsibility: company/projects/tasks/deps/blockers + per-surface stores (chat, email, calendar, docs, transcripts). Snapshot/restore.
   - Interface: typed reads; **writes only via Kernel-applied events**.
   - Owns/mutates: all durable world facts.
   - Depends on: nothing (leaf); mutated exclusively through the Kernel.

3. **Tool API (Action Space)** — the agent's only surface.
   - Responsibility: expose actions (`send_message`, `read_inbox`, `create_task`, `book_meeting`, `record_decision`, `wait`…). Each action = an event; `wait`/durationed actions release the clock (no special "advance time" verb).
   - Interface: one uniform action call → validated → enqueued event; returns immediate observation.
   - Owns/mutates: nothing directly — emits events to the Kernel.
   - Depends on: Kernel, World State (for read-back observations).

4. **NPC Engine** — stateful coworkers.
   - Responsibility: per-persona **decision core (deterministic rules/state machine)** over a scoped world view + goals; **LLM parser only** (free-text → fixed intent set; render reply in voice, no invented facts). Reactive replies at `now+delay`; autonomous **self-scheduled wake-ups** for independent cadence.
   - Interface: `on_event(event) → (state effects, scheduled events)`.
   - Owns/mutates: NPC internal state; world effects go through the Kernel.
   - Depends on: Kernel, World State (scoped reads), Scenario (persona packs), Determinism layer (cached LLM parser).

5. **Scenario Loader & World Dataset** — everything is data.
   - Responsibility: load a **frozen scenario instance** (`seed.json` · `personas.overlay.json` · `timeline.json` · `eval.json` + `scenario.json` manifest) emitted by the Seeding Engine, **unchanged** — seed state, per-NPC overlay, event timeline, eval ground truth. No code-per-scenario; no generation at load.
   - Interface: `load(instance) → seeds World State, registers NPCs, schedules events, hands ground truth to Evaluator`.
   - Owns/mutates: initial state only (at load).
   - Depends on: World State, NPC Engine, Kernel, Evaluator; consumes Seeding Engine output.

6. **Seeding Engine (build-time)** — turns templates + seeds into frozen instances.
   - Responsibility: resolve all variability **offline** into a frozen scenario. Pipeline: `sample` (seeded PRNG fills template slots) → `bind` (slots → real substrate IDs; only `active`-tier NPCs eligible) → `assemble` (materialize seed/overlay/timeline) → `project-eval` (**co-generate `eval.json` from the same resolved facts** so world and grader can't drift) → `gate + freeze` (validity gate, then write instance + manifest with content hash + provenance).
   - Interface: `generate <archetype> --seed N` · `validate <instance>` · `freeze <instance>` (extends the Operator CLI).
   - Owns/mutates: writes frozen instances to `scenarios/`; reads base substrate read-only. **Never runs during a graded episode.**
   - Depends on: Data Substrate (`data/world`, `data/personas`, `data/templates`); gate may invoke reference solvers (only their deterministic *score* gates — generation itself is rule-based).
   - Determinism: only seeded randomness; `(template, seed, substrate_hash, generator_version)` → byte-identical instance. No LLM in the generate→freeze path.

7. **Evaluator** — deterministic-first scoring, reads the trajectory.
   - Responsibility: predicate checks at checkpoints — reads the **trajectory** (event log + state-at-checkpoint reconstructed by projection, not a separate snapshot feed); state deltas carry the score. **LLM extractor (parser-only)** turns free-text artifacts into structured claims a deterministic rubric grades. No LLM judge. Injection-resistant: claims credited only if consistent with state. **Grade == replayable** (scores the same bytes we persist); re-runnable offline against a stored trajectory (re-grade without re-running the episode).
   - Interface: `score(trajectory, ground_truth) → weighted result`; emits checkpoint/score records **back into the trajectory**.
   - Owns/mutates: nothing in the world — read-only over the trajectory; its score records are appended (append-only, not a cycle: reads seq < checkpoint, appends new).
   - Depends on: the trajectory (event log + snapshots emitted by Kernel 1 / World State 2, durably the Trajectory Store 10), Scenario ground truth, cached extractor (LLM guard).

8. **Agent Harness** — drives the agent under test.
   - Responsibility: run the agent loop against the Tool API; deliver observations/notifications; enforce turn/step boundaries.
   - Interface: `step()` — one agent action → observation.
   - Owns/mutates: agent-side conversation/session only.
   - Depends on: Tool API.

9. **Operator CLI & Observability** — how a reviewer drives it.
   - Responsibility: seed/step/inspect/run-eval; expose event log, state inspection, trace. Maps to the README main flows.
   - Interface: CLI commands over Kernel/Harness/Evaluator.
   - Owns/mutates: nothing — control + read.
   - Depends on: all of the above; reads the Trajectory Store for observability.

10. **Trajectory Store** — persist every rollout for replay + cross-run analysis.
   - Responsibility: write each episode as a replay-grade `trajectory.jsonl` (canonical event log + `caused_by` chain) + periodic snapshots + manifest (scenario hash, seed, agent version); maintain a **derived, rebuildable** DuckDB/SQLite index over runs for cross-trajectory queries. **Any-POV views (agent/NPC/operator/grader) reconstructed on demand** by projecting the log — never materialized. Full spec: `../research/06-trajectory-store.md`.
   - Interface: `record(event)` (append), `replay(run_id)`, `project(run_id, actor, at)`, `query(...)`.
   - Owns/mutates: `runs/` files + the derived index; reads the canonical event log.
   - Depends on: Kernel event log + World State snapshots (systems 1, 2) — the **single capture point**. Read by the Evaluator (7), which appends its checkpoint/score records; consumed by Operator/Observability (9).

## Cross-cutting invariant: Determinism (a property, not a system)

- **Determinism is a guarantee, not a component** — there is no "determinism engine." It's enforced inside systems that already exist:
  - single writer + one event queue + next-event clock, no wall-clock coupling (Kernel, 1)
  - seeded PRNG resolved offline into frozen, immutable instances (Seeding Engine 6 → Scenario Loader 5)
  - LLM calls at temp 0 + seed, cached by `(state, context hash)` (NPC Engine 4, Evaluator 7)
  - state snapshot/restore (World State, 2)
- **Replay is not a separate system either — it *is* the Trajectory Store (10).** The store persists the canonical event log + snapshots + cached LLM outputs, so `replay(run_id)` reconstructs an episode byte-exactly with no model calls. What we *require* is the store; determinism is the property that makes its replay exact.
- **Build-time vs runtime boundary:** the Seeding Engine (6) resolves all randomness offline into frozen instances; runtime (1–5, 7–10) consumes them unchanged, so the single-writer + one-queue determinism is never perturbed at grade time.

## Build order (suggested)

- Kernel + World State + Tool API → smallest loop that advances time and mutates state.
- Scenario Loader + one **hand-authored** frozen instance → world seeds and one NPC replies.
- Evaluator (deterministic predicates only) → score the seeded scenario.
- NPC LLM parser + eval extractor (temp 0 + seed + cached/logged calls) → free-text surfaces.
- Seeding Engine → generate instances from a template + seed, with co-generated eval + validity gate (replaces hand-authoring as the scaling path).
- Trajectory Store → persist the event log to `trajectory.jsonl` + manifest from the first runnable loop (cheap; it's the log already emitted). Add the derived index once cross-run queries are wanted.
- Operator CLI + Observability → reviewer can drive the main flows (incl. `generate/validate/freeze`) and inspect/replay trajectories.
