# Wave 2 spec — Scenario Loader + one hand-authored instance + one NPC replies

Second buildable slice (`01-systems.md` systems 5 + 4). Goal: **load the hand-authored frozen instance, seed the world from it, and have one coworker react to a message with a rule-based reply** — proving the load → seed → reactive-reply → clock-drain loop end to end, still deterministic and with no LLM.

- **Stack:** Python 3.12+, on top of Wave 1 (Kernel + World State + Tool API). Still **single process, no Docker, no external services** (the NPC is rule-based in this wave).
- **Instance:** `data/scenarios/checkout-not-ready/` (`seed.json` · `personas.overlay.json` · `timeline.json` · `eval.json` · `scenario.json`) — already hand-authored.
- **Out of scope (later waves):** the **LLM parser** (free-text → intent) and voice rendering, the **Evaluator** scoring, autonomous NPC wake-ups, the Seeding Engine, the Trajectory Store.

## The one deferral that shapes this wave

- The NPC LLM parser (Wave 4) is what maps a free-text message body → an intent. It doesn't exist yet.
- **Seam:** in Wave 2 `send_message` carries an optional **structured `intent`** (one of the persona's `allowed_intents`). The NPC **decision core consumes an intent** and never sees free text. Wave 4 drops the parser in front of the same decision core and removes the structured arg — the decision core's contract is unchanged across waves.
- Likewise the reply is produced as a **structured `reply`** by the decision core; a Wave-2 **static template renderer** turns it into text. Wave 4 swaps that renderer for the LLM voice renderer. Same split as parser-vs-decision.

## Design rules carried from research

- **Single writer:** NPC world-effects go through the Kernel like everything else; the NPC is an **event handler**, not a second writer.
- **Determinism:** rule-based decision core, no wall-clock, no randomness. Same instance + same action script → byte-identical event log + snapshot.
- **Constrained write:** the blocker reveal flips `blockers.*.surfaced`, a denied path — so the reveal delta is **`source="system"`** (an NPC reveal), never agent-sourced.
- **Everything is data:** NPC behavior = base persona (`data/personas/*`) ⊕ scenario overlay; no per-scenario code.
- **Frozen instance is consumed unchanged**, and its `dataset_version` is validated on load.

## Contracts (new shapes)

- **Frozen instance** (per `04`/`06`): `seed.json` (projects/tasks/blockers/surfaces), `personas.overlay.json` (per-NPC `goals` · `knowledge_scope` · reveal gates), `timeline.json` (scheduled background events), `eval.json` (ground truth — parked for the Evaluator), `scenario.json` (manifest: `scenario_id`, `dataset_version`, provenance).
- **NPC runtime config** = base persona ⊕ overlay: `identity/voice/allowed_intents/view_scope/behavior` (base) + `goals/knowledge_scope/escalation_triggers` (overlay).
- **Decision core:** `decide(npc, intent, args, view) -> Decision{reply: structured | None, deltas: [Delta], follow_ups: [EventSpec]}` — pure function of (intent, scoped view, npc config).
- **New event kinds:** `npc_react{npc, intent, args}` (trigger, at `now`) and `deliver_reply{to, reply}` (delivery, at `now + response_delay`).
- **`send_message` arg (Wave 2 seam):** optional `intent: <one of allowed_intents>` alongside `to/body/refs`.

## System specs

### 5. Scenario Loader
- **Responsibility:** load a frozen instance and stand up the world: validate → seed → register NPCs → schedule timeline → hand eval ground truth to the Evaluator (parked in this wave).
- **API:** `load(path) -> LoadedScenario` — populates `WorldState` from `seed.json`; builds each active NPC's runtime config (base ⊕ overlay) and registers it with the NPC Engine; `kernel.schedule(...)` for every `timeline.json` entry; returns the ground-truth handle.
- **Validation:** recompute `dataset_version` over the dataset and compare to `scenario.json`; **refuse to load on mismatch** (no silent drift).
- **Owns/mutates:** initial state at load only.

### content addressing (shared primitive)
- **Responsibility:** the hashing the loader validates against — implemented here, reused by the Seeding Engine later.
- **API:** `canonicalize(file)` (sort keys, normalize whitespace, strip `_`-prefixed annotation fields) → `sha256`; `subtree_hash(dir)`; `dataset_version(dataset)`; `instance_hash(instance)`.
- Deterministic + machine-independent; formatting/notes never change a hash.

### 4. NPC Engine (reactive, rule-based — no LLM this wave)
- **Responsibility:** register as the Kernel handler for `npc_react`; on trigger, run the **decision core** over the NPC's scoped view + config and (a) schedule a `deliver_reply` at `now + behavior.response_delay`, (b) emit any reveal deltas.
- **Reveal gating:** the overlay's `reveal.gate` (`ask_direct` / `needs_rapport` / `needs_help_offer`) decides whether the incoming `intent` unlocks the gated fact in `knowledge_scope`. On reveal, flip `blockers.<id>.surfaced` via a **`system`-sourced** delta.
- **Reply rendering (Wave 2):** `render(reply, persona) -> text` from a static per-intent template table. (Wave 4 replaces this with the LLM voice renderer.)
- **Deferred:** autonomous self-scheduled wake-ups (this wave is reactive only — "one NPC replies").

### Kernel extension (small)
- Add a **handler registry**: `register(kind, handler)`; `apply` dispatches by `event.kind` to a registered handler, else falls back to the Wave 1 default (apply payload `deltas` + `follow_ups`). The NPC Engine registers `npc_react`; a delivery handler registers `deliver_reply` (appends the reply to the target inbox). Backward-compatible with Wave 1.

## How the loop works (discover-a-blocker)

1. Loader seeds `checkout-not-ready`; Priya (`npc.be_b2`) registered with the overlay holding the gated `psp_cert` blocker; timeline events scheduled.
2. Agent `send_message{to: Priya, body, intent: ask_status(payments)}` → *mutate*: append to channel; emit `npc_react{Priya, ask_status, ...}` at `now`.
3. Kernel dispatches `npc_react` → NPC Engine → decision core: gate satisfied → `Decision{reply, deltas:[reveal psp_cert], follow_ups:[deliver_reply @ now+delay]}`. Reveal applied `source="system"`.
4. Agent `wait{duration}` → `advance_until` drains `deliver_reply` → reply appended to the agent's inbox; appears in `events_since`, time-ordered.
5. State now shows `blockers.psp_cert.surfaced == true` — the blocker is discovered.

## Testing strategy

- **`-m content`** (`tests/content/`): canonicalization (key sort, whitespace, `_`-field stripping); `sha256`/subtree determinism; `dataset_version` stable across reformatting; changing a real field flips it; `instance_hash`.
- **`-m scenario`** (`tests/scenario/`): seeded state matches `seed.json`; base⊕overlay merge; timeline entries scheduled into the Kernel; **`dataset_version` mismatch → refuses** (tamper a file in a temp copy).
- **`-m npc`** (`tests/npc/`): decision core maps `intent → reply`; **reveal only when the gate is satisfied** (table over the three gates); reply scheduled at `now + response_delay`; reveal delta is `source="system"`; deterministic given fixed config/view. Uses a fake Kernel.
- **`-m integration`**: the discover loop above end-to-end via the Tool API + real Kernel/State — reply lands in the inbox, `psp_cert.surfaced == true`, ordering correct; and a **timeline** background event fires at its `sim_time` during `advance`.
- **`-m golden`**: a fixed load + discover action script → byte-identical event log + final snapshot (extends the Wave 1 golden).
- **`-m validation`**: instance schema — `seed/overlay/timeline/eval` well-formed; `eval` weights sum to 1.0; `knowledge_scope` references resolve to real ids; manifest carries `dataset_version` + provenance.

## How to run

```
pytest -m content         # hashing primitive
pytest -m scenario        # loader
pytest -m npc             # decision core + reply
pytest -m integration     # discover loop + timeline
pytest -m golden          # determinism
pytest                    # all (Wave 1 + Wave 2)
ruff check . && mypy src

# drive it manually (single process)
python -m saasworld.serve
# load, message Priya, advance, read inbox — via /rpc calls
```

## Single service vs Docker

- Unchanged from Wave 1: **single process, no Docker, no external services.** The NPC is rule-based, so still no LLM/API. Tests remain in-process (`TestClient`, no port).

## Project layout (additions)

```
src/saasworld/
  content_hash.py          # canonicalize + sha256 + subtree + dataset_version/instance_hash
  scenario/
    loader.py              # validate + seed + register NPCs + schedule timeline
  npc/
    engine.py              # handler registration; npc_react -> decision -> deliver_reply
    decision.py            # rule-based decision core (consumes structured intent)
    reply.py               # static template renderer (replaced by LLM voice in Wave 4)
  kernel.py                # + handler registry (register/dispatch by event.kind)
tests/
  content/ scenario/ npc/  # new tiers (+ integration/golden extended)
```

## Definition of done

- Loads `checkout-not-ready` with `dataset_version` validated; refuses a tampered copy.
- Agent message (structured intent) → after `advance`, a rule-based reply is delivered and `blockers.psp_cert.surfaced` flips (system-sourced), deterministically.
- A timeline background event fires during `advance`.
- New markers (`content`, `scenario`, `npc`) green; Wave 1 markers still green; `ruff` + `mypy` clean.

## As built (deltas from spec)

- **`dataset_version` is validate-if-present.** The frozen `scenario.json` ships without a `dataset_version` field, so the loader always recomputes the version over instance content (`seed`+`overlay`+`timeline`+`eval`, excluding the manifest) and refuses only when the manifest *declares* one that mismatches. `LoadedScenario` always returns the computed version. (Follow-up: bake `dataset_version` into the committed instance so load is a hard integrity gate.)
- **Same-`now` cascade drains in the mutate path**, not the kernel. `advance_until` keeps its single `pop_due` pass; the zero-duration mutate drains events scheduled at `now` so `npc_react` + the reveal fire synchronously at send time, while the delayed `deliver_reply` drains on the later `wait`. Kernel untouched.
- **Dotted ids** (`blocker.psp_cert`, `proj.checkout`) seed into nested storage via dot-walking so eval-ground-truth paths (`blockers.blocker.psp_cert.surfaced`) resolve; channels stay whole-key addressed.

## Milestones

1. `content_hash` → `-m content` green.
2. `scenario/loader` (validate + seed + register + schedule) → `-m scenario` green.
3. `npc` (decision core + reply renderer + engine handlers) → `-m npc` green.
4. Kernel handler registry + wire `send_message → npc_react → deliver_reply` → `-m integration` green.
5. Golden discover script → `-m golden` green; **DoD met**.
