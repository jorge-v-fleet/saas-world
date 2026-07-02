# Action space

How the agent changes the world, and how those changes drive its evolution. Companion to `02` (Tool API + how time advances) and `03` (what the grader reads). Catalog as data: `../../data/actions.json`.

## Principles

- **Actions are the only writer-facing surface.** The agent never touches state directly — it emits an action → one event → the single writer applies it. NPC decision cores reach that same single writer via intents; both are gated by per-actor scope (`view_scope` / permission) — one catalog, scoped per actor. No other path mutates the world.
- **Uniform envelope, data-driven catalog.** Every action shares one shape (verb + args); adding a verb is a data entry, not a bespoke code path.
- **Three classes, by clock effect** — the sync/async spine:
  - **observe** — zero-duration, no mutation; returns a view scoped to the agent. Clock still.
  - **mutate** — zero-duration; synchronous state delta + immediate ack; may schedule follow-up events. Clock still.
  - **advance** — carries a duration; releases the clock to `now + duration`. The **only** class that moves time. `wait` is the simplest; there is no privileged advance-time verb.
- **Free text is quarantined to bodies.** Only message / email / doc bodies are free text, mapped to intent/claims by the parser-only layer. Everything reward-bearing is structured (`record_decision`) so grading reads fields, not prose.
- **Constrained write surface — the anti-gaming backbone.** No action can write derived or graded fields (`blockers.*.surfaced`, `tasks.*.blocked_by`, decision correctness). Those move only via the world's own rules or an NPC reveal. Superficial edits (mark a task in-progress, send 20 messages) touch nothing the grader reads.

## Anatomy of an action

Each catalog entry: `id · class · args · effect (a declarative delta DSL — set/append/increment/link over namespaced paths) · emits (follow-up events) · pre (guards) · returns (observation)`. The DSL keeps the engine generic and lets the single writer enforce the constrained-write guard in one place (no delta may target a derived/graded field). Examples:

- `send_message{to, body, refs?}` — *mutate*. Effect: append to chat. Emits: `npc_reply @ now + persona.response_delay`; body → intent. `refs` are optional structured pointers (e.g. a blocker id) the grader reads deterministically, without trusting the prose.
- `record_decision{about, type, action?, new_date?, owner?, rationale?}` — *mutate*. Effect: write a structured decision. The reward-bearing action; grading reads it directly.
- `wait{duration}` — *advance*. Effect: release the clock to `now + duration`; the next-event jump fires all due events in time order. No mutation of its own.

## How the world evolves — one action → one step

1. Agent emits `verb + args`.
2. Kernel validates against the catalog: arg schema + preconditions + the agent's view/permission scope.
3. Enqueue as an event at the current sim-time.
4. Single writer applies the effect (synchronous for zero-duration classes).
5. The action may **emit follow-ups**: an NPC reactive reply at `now + delay`, a `meeting_start`, etc. (A blocker surfacing is emitted by the NPC's reveal — never by the agent's action.)
6. If the action is **advance**, release the clock: the next-event jump fires every due event — NPC replies, autonomous wake-ups, scheduled pressure — in timestamp order.
7. Return the **observation**: the immediate ack plus any events that landed since the last observation, ordered by time.

**Interruption:** events landing inside an `advance` window are not true interrupts — they're delivered as notifications on the next observation, still time-ordered (per `02`). Optional **preemptable `advance`**: the kernel may cut the jump short at the timestamp of a `priority=urgent` event and return early — still next-event and deterministic.

## Catalog

- **observe:** `read_inbox · read_channel · get_calendar · get_tasks · read_doc · get_people · get_transcript`
- **mutate:** `send_message · send_email · create_task · update_task · book_meeting · create_doc · update_doc · record_decision`
- **advance:** `wait · attend_meeting`

## On the checkout scenario

- **Discover:** `send_message{to: Sam, "what's blocking the UI?"}` → intent `ask_status` → Sam points to Priya. `send_message{to: Priya, "is payments ready for launch?"}` → intent `ask_status about payments` → Priya's reveal flips `blocker.psp_cert.surfaced` (no agent verb can set it).
- **Act:** `record_decision{about: proj.checkout, type: gonogo, action: reschedule, new_date: D8T17:00, owner: org.be_b2}`.
- **Inform:** `send_message{to: org.cto, body, refs: [blocker.psp_cert]}` → satisfies "stakeholder informed" — credited only if `surfaced == true`.
- **Advance:** `wait{4h}` between sends so replies land.
- **Non-scoring:** `update_task{task, set: {status: "in_progress"}}` changes a field the grader never reads.

