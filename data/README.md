# World dataset

One canonical, single-writer world, expressed entirely as data (no behavior in code).
Scoped to the **CTO branch** for now; the rest of the org and future domains extend without rework.

## Layout

- `world/org.json` — whole company as data; `tier` gates who is live.
- `world/company.json` — company identity + stage + reserved future-module seams.
- `actions.json` — the agent's action space (verbs, args, clock class, effects); the only way the world is mutated.
- `personas/<npc>.json` — per-NPC **base** pack (durable identity / voice / scope / behavior).
- `templates/<archetype>.json` — reusable scenario archetype (assumptions + variable slots + eval shapes), with a companion `.md` that explains it in plain language.
- `scenarios/<name>/` — a concrete scenario: `seed` (projects·tasks·blockers·surfaces), `personas.overlay`, `timeline`, `eval`, plus a `README.md` summarizing it for humans.

Every template and scenario carries a plain-language companion doc — read those first; the JSON is the machine-readable form of the same thing.

## Canonical store = namespaced partitions

- **core (on):** `org · projects · tasks · blockers · surfaces`
- **reserved (off):** `customers (cust.) · financials (fin.) · seasonality (seas.)`

All presentations — agent inbox, org chart, an NPC's scoped view, the eval fact-view — are **derived projections** of this one store. Never copies, never hand-authored in parallel (that's how views drift).

## NPC tiers (`org.json`)

- `agent` — PM A, the target under test.
- `active` — full stateful NPC: base pack + scoped view + autonomous wake-ups. **CTO branch only, for now.**
- `reference` — in the chart for structure / mentions; no behavior. Promote to `active` to bring online.

## Base vs. scenario overlay — the extensibility hinge

- **Base persona (here):** identity, voice, `allowed_intents`, `view_scope`, behavior params — reused by every scenario.
- **Overlay (per scenario):** `goals`, `knowledge_scope` (gated facts / the blocker), `escalation_triggers` — the situation-specific tension.

Same NPC stays consistent across scenarios; each scenario injects only its conflict.

## Extending — all data, no code

- **New coworker:** add an `org` node + a base persona file.
- **Bring a branch online (COO / CFO):** flip its nodes `reference → active`, add base packs.
- **New domain (customers / financials / seasonality):** enable the module, populate its namespaced partition. `view_scope` filters and eval predicates already reference IDs, so they pick it up automatically.
