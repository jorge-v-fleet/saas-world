# Landscape — how comparable environments are built

## Summary

- The strongest analogs simulate a **company**, not a chatbot: self-hosted tool surfaces + stateful coworkers + outcome-based grading.
- Two design poles worth stealing from:
  - **TheAgentCompany** — realism via real self-hosted apps (chat/docs/tasks/devops), NPC coworkers, checkpoint grading.
  - **τ-bench / τ²-bench** — rigor via a **user simulator** + **DB-state reward** (final state hashed against ground truth).
- Our brief adds the hard part neither fully centers: **simulated time decoupled from wall-clock**, with background activity that advances on its own clock.

## Closest prior art

- **TheAgentCompany** (CMU, NeurIPS 2025) — small software company on GitLab/Plane/RocketChat/ownCloud; 175 role-based tasks incl. Project Manager.
  - Borrow: role-scoped tasks; **simulated colleagues as LLM NPCs**; hybrid **checkpoint + result** grading (deterministic first, LLM-judge only where needed); Docker-reset environment.
  - Diverge: it wires *real* apps (heavy, no explicit sim-clock). We want a lightweight in-process world model with an explicit simulated clock.
- **τ-bench / τ²-bench** (Sierra + Princeton) — tool-agent-**user** interaction; retail/airline domains.
  - Borrow: **user/NPC simulated by an LLM**; reward = **final DB state == target** (hash compare) + info correctness, *not* tool-call syntax. τ² adds dual-control (user also holds tools).
  - Lesson: state-based reward resists activity-padding; this is our anti-reward-hack backbone.
- **The Agent's First Day** (2026) — "trainee" agent's first day; grades **dynamic scheduling of streaming tasks by priority, active exploration to cut hallucination, learning across tasks**. Almost exactly our framing — mine for eval dimensions.
- **SimuHome** — tick-based, temporally-aware sim; **discrete ticks, deterministic transitions, sim-time decouples from real time with acceleration**. Direct model for our clock/event engine.

## Supporting references

- **Discrete-event simulation** — event queue ordered by sim-time; state advances only at events; wall-clock ≠ sim-clock. The canonical pattern for our kernel.
- **π-Bench / SentinelBench** — long-horizon, proactive/monitoring agents; motivate proactive NPC outreach + long-consistency checks.
- **UserBench** — Gym-style interactive env for user-centric agents; a clean env/step API shape to imitate.
- **smolagents** (Hugging Face) — lightweight code-first agent framework; a candidate driver/harness for the agent under test (not the world itself).

## Takeaways for our build

- Grading = **deterministic state checks first, constrained LLM-judge only for fuzzy artifacts** (did the doc communicate the decision?), with fixed rubric inputs + multi-vote for stability.
- Scenarios must be **declarative data** (seed state, personas, event timeline, ground truth), loaded into one kernel — the explicit defense against per-scenario code / prompt spaghetti.
- NPCs are **event-triggered LLM policies whose replies are scheduled at sim-time + realistic delay** — inference latency never advances the sim clock.

## Sources

- TheAgentCompany — [paper](https://arxiv.org/abs/2412.14161) · [code](https://github.com/TheAgentCompany/TheAgentCompany) · [NeurIPS 2025 PDF](https://papers.nips.cc/paper_files/paper/2025/file/0d744742f6fac4d1134c019b7cef3c8a-Paper-Datasets_and_Benchmarks_Track.pdf)
- τ-bench — [paper](https://arxiv.org/abs/2406.12045) · τ²-bench — [code](https://github.com/sierra-research/tau2-bench)
- The Agent's First Day — [paper](https://arxiv.org/abs/2601.08173)
- SimuHome — [paper](https://arxiv.org/pdf/2509.24282)
- π-Bench — [paper](https://arxiv.org/pdf/2605.14678) · SentinelBench — [paper](https://arxiv.org/html/2606.05342)
- UserBench — [paper](https://huggingface.co/papers/2507.22034)
- smolagents — [docs](https://huggingface.co/learn/agents-course/unit2/smolagents/introduction) · [site](https://smolagents.org/)
- Discrete-event simulation — [overview](https://en.wikipedia.org/wiki/Discrete-event_simulation)
