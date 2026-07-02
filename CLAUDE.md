# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

**Greenfield.** As of this writing the repo contains only `docs/problem-def.md` — no source, no build tooling, no tests. There are no commands to run yet. When you add tooling (package manager, test runner, entrypoint), document the commands here.

## What this project is

A **simulation environment for a project manager's first week at a small-to-medium SaaS company**. An agent is dropped into a simulated work week and must drive real PM work through internal tool surfaces (chat, email, calendar, task tracking, docs, meeting/transcript capture). The system evaluates whether the agent's actions actually improved outcomes — not whether it was merely busy. Full brief: `docs/problem-def.md`.

The interesting problems are *systems* problems, not surface mimicry: state transitions, event delivery, information discoverability, long-horizon consistency, and defensible grading. A strong single-node design is explicitly preferred over a distributed one.

## Non-negotiable constraints (from the brief)

- **Single repository.** A reviewer clones it, starts the full system locally, and exercises the main flows using documented commands. Keep `README.md` authoritative for setup / start / drive-flows / run-evaluation.
- **Simulated time is decoupled from wall-clock inference latency.** Time advances by simulation, never by how long the model takes to think.
- **At least one fully-authored PM scenario** must ship: seeded company state, tool data, coworker personas, and evaluation ground truth.
- **Evaluation must resist reward hacking** — reward improved outcomes and sound decisions over superficial activity. Grading must be inspectable: score components, example outcomes, and *why* the evaluator is hard to game.
- If model-based verification is used anywhere, be explicit about *why* it's needed, *what inputs* it sees, and *how* results are kept stable enough to trust.

## Design axes that must stay legible

The brief asks that these choices be readable in the final system — treat them as the architectural spine, not implementation details to bury:

- **Sync vs async advancement** — what advances synchronously with an agent action vs. what advances in the background (NPC outreach, response delays, scheduled events).
- **State ownership** — how scenario/world state is owned and mutated; who is the single writer.
- **Event scheduling & delivery** — how events are scheduled against simulated time and delivered to the agent and NPCs.
- **NPC modeling** — multiple stateful coworkers with distinct roles, proactive outreach, and realistic response delays.
- **Scenario scaling** — how the design grows to many scenarios *without collapsing into prompt spaghetti or hand-authored one-offs*. Favor data-driven scenario authoring over bespoke code per scenario.

## Working notes

- Architecture is intentionally unprescribed — design decisions are yours to make and must be defensible from first principles. Coding agents may help, but the decisions should be legible in the system.
- Prefer clear semantics over decomposition. Don't distribute what a single node handles cleanly.

## Work style

- Documents:
  - Strive for very summarized descriptions — no filler, no restating the obvious.
  - Prefer structured, indented bullet points over prose paragraphs to express layered thoughts.
- Code:
  - Aim for lean, not-bloated code — smallest thing that reads clearly.
  - Keep comments brief: 1–2 lines max, only where intent isn't obvious from the code.
