# Archetype-agnostic Seeding Engine + `release-triage` (long-horizon)

Draft for approval. **North star:** `generate <archetype>` must work for *any* archetype defined in
`data/templates/`, with **no `src/` change per archetype**. Today the gate, solvers, eval
projection, denied-paths, and the reveal mechanic are hardcoded to `hidden-critical-blocker`; that
makes `generate` effectively a single scenario. This spec makes the engine a **generic interpreter
of a declarative template**, then adds `release-triage` as the first *data-only* archetype to prove
it. Longer horizon is already data (offset-based clock) — kept, but it was never the blocker.

## Principle: what is data vs. what is code

- **Data (per archetype, in the template):** slots, world blueprint, timeline, **coherence
  invariants**, **denied paths**, **system-flip rules** (reveal / gated-completion), **reference
  solvers** (competent + lazy action scripts), eval predicate shapes + weights.
- **Code (archetype-agnostic, written once, every archetype rides free):** the invariant
  interpreter, the solver-script runner, the flip-mechanic handlers, the write-guard, the scorer,
  sample→bind→assemble→project. No archetype name ever appears in `src/`.

## Generalizations (the refactor — each is behavior-preserving for archetype #1)

1. **Denied paths become instance data.** `state/guard.py` today hardcodes `DENIED_PATHS`. Change:
   the template declares `denied_paths`; `project_eval` writes them into the frozen instance;
   `loader` injects them into the `WorldState` guard at load. A small base set stays as the floor.
   *Effect:* a new archetype can protect new graded fields (`validated`, `true_status`,
   `bug.resolved`) with zero code.
2. **Reveal mechanic reads its target from data.** `npc/decision.py` hardcodes
   `blockers.{blocker}.surfaced`. Change: the `knowledge_scope` item already carries
   `on_reveal`; the core applies *that* declared delta (`{op,path,value}`) instead of a fixed path.
   *Effect:* any system-sourced flip an NPC can grant is data-driven.
3. **Coherence becomes a declarative invariant list.** `gate.check_coherence` hardcodes the
   single-blocker rules. Change: template declares `coherence` as assertions in the **existing eval
   DSL** (`count`, `exists`, `for_each`, `denied_path`, `weights_sum`, `substrate` lookups); a
   generic evaluator interprets them. Port archetype #1's five invariants verbatim into its template
   as data.
4. **Reference solvers become action scripts.** `engine/solvers.py` hardcodes two Python
   trajectories. Change: template declares `solvers.competent` / `solvers.lazy` as ordered steps
   (`{at, kind, actor, args|body|deltas}`); a generic runner binds `$slot` tokens (reuse
   `render.substitute`), schedules each step (catalog verbs via `bind_effect`, or raw
   `npc_reply`/system deltas), advances, and returns `score(...).final`. The gate still reads only
   the final score. *This is the key bet — see "Design bet" below.*
5. **Eval projection derives its referenced ids** from the bound predicates instead of the
   hardcoded `_referenced_ids` set; the `decision_comms` grounding path moves into the eval data
   (drop the `_BLOCKER_SURFACED` module constant in `eval/predicates.py`).
6. **Generic gated-completion timeline event** (new, archetype-agnostic): a scripted event that
   applies a system delta **only if a state precondition holds** — e.g. `validated=true` fires only
   if the agent booked the matching validation. Mirrors the reveal-gate's anti-gaming, expressed as
   data: `{at, system_effect:[deltas], gated_on:<DSL assert>}`.
7. **Generic binding.** `engine/bind.py` hardcodes the four slots (`blocker.holder`,
   `critical_project`, `stakeholder`, `pointer`) and the activate rule. Change: bind resolves
   **every entity slot the template declares** (`sample_from` selector → substrate query → seeded
   choice → id keyed by slot name), and computes `activate` from a **template-declared rule**
   (default: all bound NPC ids + declared managers). Archetype #1 declares its existing four slots
   and the same activate rule, so its `Binding` is unchanged.
8. **Generic assembly.** `engine/assemble.py` hardcodes a single-project world, a
   critical-blocker-plus-distractors list, and holder/stakeholder/pointer overlays. Change: assemble
   becomes a thin generic `substitute(blueprint, bindings)` over template-declared `world` (projects
   **as a list**, tasks, blockers, surfaces), `overlays` (map keyed by persona-binding token), and
   `timeline`. All archetype-#1 structural specifics (the one-project selection, distractor
   expansion, the holder/stakeholder/pointer overlay keys, derived bindings like `task_due` /
   `correct_set`) move **into its template as declarative data**. The seeded byte-output must stay
   identical — the golden test is the guard.

**Acceptance gate for every phase:** `hidden-critical-blocker` still generates a **byte-identical**
frozen instance at seed 1206 (same `instance_hash`) and the full suite stays green. The refactor
moves logic from Python into archetype #1's own template without changing its output.

## Design bet — data-driven solvers

A validity gate needs only two trajectories per archetype: a **competent** one that must reach full
score, and a **lazy** one that must score ~0. Both are short, deterministic, ordered sequences —
expressible as data and run by one generic runner. Fully general "solve any scenario" AI is *not*
needed and explicitly avoided. If a future archetype needs branching a script can't express, the
runner can fall back to a registered Python solver by name — but v1 archetypes must be scriptable.

## `release-triage` — the first data-only archetype

Once the engine is generic, this ships as **template data only, no `src/` change**. (Open questions
resolved with defaults; say the word to change any.)

- **Premise:** `org.pm_a` owns a portfolio (≥2 projects); must ship one critical feature by ~`D10`;
  the feature is **4–5 functionalities**, each needing a **scheduled validation**; a **critical bug
  in shipped code** is reported ~`D3` and must be triaged *first*.
- **Graded (weights = 1.0):** portfolio-status truthfulness `0.25` · validation coverage `0.30` ·
  interrupt triage/preemption `0.25` · release go/no-go + comms `0.20`.
- **Denied (data):** `projects.*.true_status`, `tasks.*.validated`, `blockers.*.resolved`.
- **Flips (data):** validations complete via **gated-completion** events (only if the agent booked
  them); bug resolves via a gated system event; status truth read via `decision_comms` grounding.
- **Verbs — reuse, none new:** `book_meeting` (schedule validation; avoids the `create_task`
  dotted-id bug), `record_decision(type='triage'|'gonogo')` (free enum), `send_message`/`update_doc`.
- **Defaults chosen:** name `release-triage`; validation = **gated-completion** (un-gameable);
  functionalities **sampled 4–5**; deadline **both movable & fixed** draws (changes correct go/no-go).

## Phased plan (build only after approval)

| Phase | Work | Proves |
|---|---|---|
| 0 | Add `coherence`/`solvers`/`denied_paths` blocks to `hidden-critical-blocker.json` as data (mirroring current code) | template can express archetype #1 fully |
| 1 | Per-instance denied paths (template → instance → guard) | new graded fields protectable via data |
| 2 | Data-driven reveal target (`on_reveal` delta) | flips generalized |
| 3 | Generic coherence interpreter; port #1's invariants to data | gate archetype-agnostic |
| 4 | Generic solver-script runner; port #1's solvers to data | floor/ceiling gates archetype-agnostic |
| 5 | Eval projection derives ids; drop `_BLOCKER_SURFACED` | eval archetype-agnostic |
| 6 | Generic gated-completion timeline event | validation/bug-resolve expressible in data |
| 7 | Author `release-triage.json` (scenario-author agent) → generate → validate → freeze → smoke | **any archetype out of the box** |

Each phase ends green + byte-identical archetype #1. Phase 7 must require **zero** new `src/` code —
that is the definition of done for "generate is not useless."

## Confirm to proceed

- Approve the **generic-interpreter refactor** (phases 0–6) as the way to make `generate`
  archetype-agnostic, then `release-triage` as data (phase 7)?
- Approve the **data-driven solver** bet (scriptable competent/lazy per template, Python fallback
  only if ever needed)?
