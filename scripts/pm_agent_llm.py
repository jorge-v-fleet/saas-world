#!/usr/bin/env python3
"""A real LLM agent that plays the PM and drives a saas-world OpenEnv episode.

The LLM-backed counterpart to the rule-based ``examples/pm_agent.py``: instead of a hand-written
policy, Claude decides each action. Nothing about the policy is hard-coded — the tool set and system
prompt are derived from ``data/actions.json`` (the action space) and the live observation, so any
change to the catalog or scenario is reflected the next time you run this. The agent talks to a
running env server over HTTP (`SaasWorldEnv`), decides with Claude tool-use, and the loop maps each
tool call to `env.step`.

Point-of-view is enforced here, not by the env: the env returns the full world snapshot, but this
script projects it to what a PM may legitimately see (public projects/tasks/people, the agent's own
message feed, and only *surfaced* blockers). The hidden blocker is invisible until a coworker
reveals it — so discovery is real, not handed over.

Run:
    # 1) start the env server with the NPC parser LIVE (novel messages must classify) + a scratch
    #    cassette so the committed one is never touched:
    SAASWORLD_LLM_MODE=record SAASWORLD_CASSETTE=/tmp/agent_cassette.jsonl \
        ANTHROPIC_API_KEY=sk-... saasworld-env-serve
    # 2) run the agent (needs ANTHROPIC_API_KEY too — it's the PM's brain):
    ANTHROPIC_API_KEY=sk-... python scripts/pm_agent_llm.py --scenario checkout-not-ready

    python scripts/pm_agent_llm.py --print-tools   # inspect derived tools + prompt, no API call
    python scripts/pm_agent_llm.py --self-test     # fixed policy offline (no key) to smoke it
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from saasworld.openenv import SaasWorldAction, SaasWorldEnv  # noqa: E402
from saasworld.trajectory.actionlog import step_row, write_run  # noqa: E402

AGENT = "org.pm_a"
_ROOT = Path(__file__).resolve().parents[1]
_ACTIONS = json.loads((_ROOT / "data" / "actions.json").read_text())["actions"]

# ── tool set, derived from the action catalog ────────────────────────────────────────────────

_ARRAY_HINT, _INT_HINT = ("[",), ("mins", "duration", "min")


def _arg_schema(args: dict[str, Any]) -> dict[str, Any]:
    """Turn a catalog verb's informal args ({"to":"id|channel","refs":"[id]?"}) into a JSON schema.

    `?` on the key or the value means optional; `[...]` -> array; a mins/duration hint -> integer;
    a nested dict (e.g. update_task.set) -> object. The Tool API validates for real and its errors
    feed back to the model, so a loose schema is fine — it only guides field names."""
    props: dict[str, Any] = {}
    required: list[str] = []
    for raw_key, hint in args.items():
        key = raw_key.rstrip("?")
        optional = raw_key.endswith("?") or (isinstance(hint, str) and hint.endswith("?"))
        if isinstance(hint, dict):
            props[key] = {"type": "object", "description": f"fields: {', '.join(hint)}"}
        elif isinstance(hint, str) and any(h in hint for h in _ARRAY_HINT):
            props[key] = {"type": "array", "items": {"type": "string"}, "description": hint}
        elif isinstance(hint, str) and any(h in hint for h in _INT_HINT):
            props[key] = {"type": "integer", "description": hint}
        else:
            props[key] = {"type": "string", "description": str(hint)}
        if not optional:
            required.append(key)
    return {"type": "object", "properties": props, "required": required}


def build_tools() -> list[dict[str, Any]]:
    """One Anthropic tool per catalog verb + a synthetic `finish` to end the week."""
    tools: list[dict[str, Any]] = []
    for a in _ACTIONS:
        desc = a.get("_effect") or a.get("returns") or a.get("reads") or a["id"]
        tools.append({
            "name": a["id"],
            "description": f"[{a['class']}] {desc}",
            "input_schema": _arg_schema(a.get("args", {})),
        })
    tools.append({
        "name": "finish",
        "description": "End the week: call when you believe the real PM work is done.",
        "input_schema": {"type": "object", "properties": {
            "summary": {"type": "string", "description": "one-line rationale"}}, "required": []},
    })
    return tools


def build_system_prompt() -> str:
    """PM role + sim mechanics + the action menu, all sourced from the catalog."""
    menu = "\n".join(f"- {a['id']} [{a['class']}]: "
                     f"{a.get('_effect') or a.get('returns') or a.get('reads') or ''}"[:140]
                     for a in _ACTIONS)
    return (
        f"You are {AGENT}, a newly-hired Product Manager in your first week at a small SaaS "
        "company.\n"
        "Time is simulated in minutes, written as D<day>T<HH:MM> offsets from D1T00:00. Every\n"
        "action is instantaneous EXCEPT `wait` and `attend_meeting`, which release the clock so\n"
        "scheduled events and coworkers' replies fire. Coworkers do NOT volunteer bad news — you\n"
        "must ask them directly, then `wait` for the reply to arrive. World state changes ONLY\n"
        "through your actions; looking busy earns nothing. You are graded on real outcomes:\n"
        "surface hidden risks, make the right go/no-go call with a concrete plan, and inform the\n"
        "right stakeholders with the real reason (attach structured `refs` to be unambiguous).\n\n"
        "Each turn you get your current point of view (projects, tasks, people, your messages,\n"
        "surfaced blockers, sim clock). Act via tool calls. When the work is done, call finish.\n\n"
        f"Available actions:\n{menu}"
    )


# ── point-of-view projection (info-hiding lives here, not in the env) ─────────────────────────

def _surfaced_blockers(state: dict[str, Any]) -> dict[str, Any]:
    """Walk the nested blockers partition; expose only those a coworker has already surfaced."""
    out: dict[str, Any] = {}

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            if "surfaced" in node:
                if node.get("surfaced"):
                    out[prefix] = node
            else:
                for k, v in node.items():
                    walk(f"{prefix}.{k}" if prefix else k, v)

    walk("", state.get("blockers", {}))
    return out


def project_view(state: dict[str, Any]) -> dict[str, Any]:
    """What a PM may legitimately see. Unsurfaced blockers are omitted entirely — discover them."""
    mine = [m for m in state.get("messages", [])
            if m.get("to") in (AGENT, None) or m.get("from") == AGENT]
    return {
        "projects": state.get("projects", {}),
        "tasks": state.get("tasks", {}),
        "people": state.get("org", {}),
        "my_messages": mine[-12:],
        "surfaced_blockers": _surfaced_blockers(state),
        "docs": [{"id": d.get("id"), "title": d.get("title")} for d in state.get("docs", [])],
        "calendar": state.get("calendar", []),
    }


def _tool_result(obs: Any, horizon: int) -> str:
    """The JSON a tool call returns to the model: sim status + action outcome + refreshed POV."""
    payload = {
        "sim_time": obs.sim_time, "horizon": horizon, "done": obs.done,
        "result": obs.metadata.get("error") or obs.ack,
        "events": [f"{e.get('actor')}->{e.get('kind')}" for e in obs.events],
        "view": project_view(obs.state),
    }
    return json.dumps(payload, default=str)


# ── brains: real (Claude) and scripted (offline harness self-test) ────────────────────────────

class ClaudeBrain:
    """The PM's brain: Anthropic tool-use."""

    def __init__(self, model: str) -> None:
        import anthropic  # lazy: only when actually running the real agent

        self._client = anthropic.Anthropic()
        self.model = model

    def respond(self, system: str, messages: list[dict[str, Any]],
                tools: list[dict[str, Any]]) -> Any:
        return self._client.messages.create(
            model=self.model, system=system, messages=messages, tools=tools, max_tokens=1024)


_Step = tuple[str, dict[str, Any]]  # one scripted tool call: (verb, args)


def _off(offset: str) -> int:
    """`D<day>T<HH:MM>` -> sim-minutes from D1T00:00 (D1 is the first working day)."""
    m = re.fullmatch(r"D(\d+)T(\d{2}):(\d{2})", offset)
    d, hh, mm = int(m[1]), int(m[2]), int(m[3])
    return (d - 1) * 1440 + hh * 60 + mm


def _grab(pattern: str, blob: Any) -> str | None:
    """First capture group of `pattern` over the JSON-dumped `blob` (an eval assert / gate)."""
    m = re.search(pattern, json.dumps(blob))
    return m.group(1) if m else None


def _load_instance(sdir: Path) -> tuple[str, dict[str, Any] | None]:
    """Read an instance dir → (archetype, targets). Archetype is provenance.template_id; the
    hand-authored checkout has none → ("checkout", None) and needs no targets. For the data-driven
    archetypes the graded ids live literally in eval.json's JMESPath asserts and timeline gates."""
    scenario = json.loads((sdir / "scenario.json").read_text())
    arch = scenario.get("provenance", {}).get("template_id")
    if arch not in ("delivery-slip", "release-triage"):
        return "checkout", None
    ev = json.loads((sdir / "eval.json").read_text())
    tl = json.loads((sdir / "timeline.json").read_text())["scripted"]
    preds = {p["id"]: p.get("assert", {})
             for cp in ev["checkpoints"] for p in cp.get("predicates", [])}
    t: dict[str, Any] = {
        "horizon": max(_off(cp["at"]) for cp in ev["checkpoints"]),
        "stakeholder": _grab(r"to=='([^']+)'", preds.get("stakeholder_informed")),
        "ref": _grab(r"references=='([^']+)'", preds.get("stakeholder_informed")),
        "gonogo": (preds.get("correct_gonogo", {}).get("in", {}).get("set") or ["ship"])[0],
    }
    if arch == "delivery-slip":
        t["critical"] = _grab(r"about=='([^']+)'", preds.get("status_truthful"))
        t["replan"] = _grab(r"action=='([^']+)'", preds.get("replan_recorded"))
    else:  # release-triage: validation meetings + their titles come from the timeline gates
        t["critical"] = _grab(r"about=='([^']+)'", preds.get("status_recorded"))
        t["meetings"] = [(_grab(r"title=='([^']+)'", e["gated_on"]), e["at"])
                         for e in tl if e.get("type") == "system_effect"
                         and "title==" in json.dumps(e.get("gated_on", {}))]
    return arch, t


class ScriptedBrain:
    """Scripted policy for `--self-test` — proves the loop/logging without an API key.

    Default (`pad_steps == 0`): the 6-step solve → grade path, unchanged. With `pad_steps > 0`
    it splits into three phases: (A) the same real solve locks in reward > 0.5, (B) `pad_steps`
    realistic PM actions grow the trajectory without touching graded fields — mostly non-advancing
    observes/edits, but every `_PAD_CADENCE` rows a small budgeted `wait` advances the clock so the
    activity spreads across the week, then (C) one big `wait` crosses the horizon and `finish`.
    Exactly one tool call per `respond`, so the counter `self._i` alone tells the current phase.

    With `seed` set, `random.Random(seed)` reproducibly varies length, action mix, timing and
    decision polish so repeated `--self-test` runs form a distribution. `seed is None` uses no rng
    at all and is byte-identical to the deterministic policy. The solve always keeps the be_b2 msg,
    a wait, and a gonogo decision about proj.checkout, so the 0.60 reward floor holds per seed.

    Given a `scenario_dir`, the archetype (provenance.template_id) picks the solve: the two
    data-driven archetypes (delivery-slip / release-triage) read their graded ids + horizon from
    the instance and emit the gating actions (decisions / validation meetings) UP FRONT at t≈0;
    the padding then advances the clock past every timeline gate (budget = horizon − margin, above
    the last gate yet below the horizon) so all system_effects fire. checkout (or no dir) keeps the
    original hardcoded solve/budget verbatim. Seeded polish varies only non-floor components (may
    omit the stakeholder message, may pick a wrong gonogo action) so the core gates always hold."""

    # Phase-B rotation of verb "kinds" cycled by padding index; ids are pulled live from the view.
    _ROTATION = ("read_inbox", "read_channel", "read_doc", "get_tasks", "get_calendar",
                 "get_people", "get_transcript", "send_message", "update_doc", "create_task",
                 "book_meeting")
    _PAD_CADENCE = 5         # emit one time-advancing wait per ~5 padding rows
    _PAD_WAIT_BUDGET = 6400  # total sim-min to spread across padding (< 6780 horizon; solve ~120)
    _WAIT_CUSHION = 6300     # hard cap on cumulative interleaved wait (< horizon) under seed jitter

    def __init__(self, pad_steps: int = 0, seed: int | None = None,
                 scenario_dir: Path | None = None) -> None:
        self._rng = random.Random(seed) if seed is not None else None
        self._pad_steps = max(0, pad_steps)
        self._wait_total = 0  # cumulative interleaved wait min emitted (clamped by seed jitter)
        self._rot_offset = 0  # rotation start offset — shifts the verb cycle (seeded only)
        self._text_base = 0   # numbering offset — varies status/note text (seeded only)
        rng = self._rng

        self._archetype, targets = "checkout", None
        if scenario_dir is not None and Path(scenario_dir).exists():
            self._archetype, targets = _load_instance(Path(scenario_dir))

        if rng is not None and self._pad_steps:
            lo = min(max(500, self._pad_steps // 2), self._pad_steps)
            self._pad_steps = rng.randint(lo, self._pad_steps)  # varied trajectory length per seed
            self._rot_offset = rng.randrange(len(self._ROTATION))
            self._text_base = rng.randint(0, 9)

        # Defaults are the checkout constants; the data-driven archetypes override from the horizon.
        self._pad_budget = self._PAD_WAIT_BUDGET  # sizes per_wait (unseeded cumulative target)
        self._wait_cushion = self._WAIT_CUSHION   # hard cap on seeded cumulative (< horizon)

        # Phase A: the reward-bearing solve. Phase C: cross the horizon for terminal scoring, end.
        if self._archetype == "delivery-slip":
            self._solve, self._terminal = self._delivery_solve(targets, rng)
            self._horizon_budget(targets["horizon"])
        elif self._archetype == "release-triage":
            self._solve, self._terminal = self._triage_solve(targets, rng)
            self._horizon_budget(targets["horizon"])
        elif rng is None:
            self._solve = [
                ("send_message", {"to": "org.be_b2", "body": "Is the PSP ready for Friday?",
                                  "refs": ["task.psp_integration"]}),
                ("wait", {"duration": 120}),
                ("record_decision", {"about": "proj.checkout", "type": "gonogo",
                                     "action": "reschedule", "new_date": "D8T17:00",
                                     "owner": "org.be_b2"}),
                ("send_message", {"to": "org.cto",
                                  "body": "Checkout slips: PSP cert is the blocker.",
                                  "refs": ["blocker.psp_cert"]}),
            ]
            self._terminal = self._checkout_terminal()
        else:
            # A weaker "proceed" call (15%) still records the decision but loses correct_action.
            action = "proceed" if rng.random() < 0.15 else rng.choice(["reschedule",
                                                                        "hold_and_mitigate"])
            decision = {"about": "proj.checkout", "type": "gonogo", "action": action}
            if rng.random() < 0.70:  # new_date+owner → the decision_comms artifact holds
                decision["new_date"] = "D8T17:00"
                decision["owner"] = "org.be_b2"
            self._solve = [
                ("send_message", {"to": "org.be_b2", "body": "Is the PSP ready for Friday?",
                                  "refs": ["task.psp_integration"]}),
                ("wait", {"duration": 120}),
                ("record_decision", decision),
            ]
            if rng.random() < 0.75:  # the CTO stakeholder message → stakeholder_informed
                self._solve.append(
                    ("send_message", {"to": "org.cto",
                                      "body": "Checkout slips: PSP cert is the blocker.",
                                      "refs": ["blocker.psp_cert"]}))
            self._terminal = self._checkout_terminal()
        # Budget invariant: ~pad_steps//CADENCE interleaved waits × per_wait ≈ pad_budget, so the
        # cumulative advance stays < horizon for ANY pad_steps and phase B never truncates early.
        n_waits = max(1, self._pad_steps // self._PAD_CADENCE)
        self._per_wait = max(1, self._pad_budget // n_waits)
        self._i = 0  # count of tool calls emitted so far == the phase cursor

    @staticmethod
    def _checkout_terminal() -> list[_Step]:
        return [("wait", {"duration": 7000}),
                ("finish", {"summary": "surfaced blocker, rescheduled, informed CTO"})]

    def _horizon_budget(self, horizon: int, margin: int = 400) -> None:
        """Padding advance target from the instance horizon: it must exceed the last gate offset
        (so every system_effect fires) yet stay below H (so padding never ends the episode)."""
        self._pad_budget = self._wait_cushion = max(1, horizon - margin)

    @staticmethod
    def _terminal_for(horizon: int) -> list[_Step]:
        """Terminal wait large enough to cross H from ~H−margin (and from t≈0 when unpadded)."""
        return [("wait", {"duration": max(7000, horizon)}),
                ("finish", {"summary": "surfaced risks, recorded decisions, informed stakeholder"})]

    def _delivery_solve(self, t: dict[str, Any],
                        rng: random.Random | None) -> tuple[list[_Step], list[_Step]]:
        """status (truthful) + replan reallocate (gates w1→f2) + inform + go/no-go ship. The two
        gating decisions always hold; seeded may drop the message (−.10) or mis-call go/no-go."""
        crit, stake, ref = t["critical"], t["stakeholder"], t["ref"]
        solve = [
            ("record_decision", {"about": crit, "type": "status"}),
            ("record_decision", {"about": crit, "type": "replan", "action": t["replan"]}),
        ]
        inform = rng is None or rng.random() < 0.75
        action = t["gonogo"] if (rng is None or rng.random() < 0.8) else "hold"
        if inform:
            solve.append(("send_message", {"to": stake, "refs": [ref],
                          "body": f"{crit} is at risk; reallocating the contended engineer."}))
        solve.append(("record_decision", {"about": crit, "type": "gonogo", "action": action}))
        return solve, self._terminal_for(t["horizon"])

    def _triage_solve(self, t: dict[str, Any],
                      rng: random.Random | None) -> tuple[list[_Step], list[_Step]]:
        """triage (gates bug fix) + one validation meeting per gated title + honest status + inform
        + go/no-go ship. The triage decision + meetings always hold; seeded polish is only the
        message and go/no-go action, so validated_*/bug_resolved/triaged/status stay a floor."""
        crit, stake, ref = t["critical"], t["stakeholder"], t["ref"]
        solve: list[_Step] = [("record_decision", {"about": crit, "type": "triage"})]
        for title, at in t["meetings"]:  # book before its gate offset — appended live at t≈0
            solve.append(("book_meeting", {"title": title, "attendees": [AGENT],
                                           "at": at, "duration": 30}))
        solve.append(("record_decision", {"about": crit, "type": "status"}))
        inform = rng is None or rng.random() < 0.75
        action = t["gonogo"] if (rng is None or rng.random() < 0.8) else "hold"
        if inform:
            solve.append(("send_message", {"to": stake, "refs": [ref],
                          "body": f"{crit} release: validating functionality, triaging the bug."}))
        solve.append(("record_decision", {"about": crit, "type": "gonogo", "action": action}))
        return solve, self._terminal_for(t["horizon"])

    def respond(self, system: str, messages: list[dict[str, Any]],
                tools: list[dict[str, Any]]) -> Any:
        verb, args = self._next(_latest_view(messages))
        self._i += 1
        block = SimpleNamespace(type="tool_use", id=f"t{self._i}", name=verb, input=args)
        return SimpleNamespace(content=[block], stop_reason="tool_use")

    def _next(self, view: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        i = self._i
        if i < len(self._solve):
            return self._solve[i]                       # phase A — the solve
        k = i - len(self._solve)
        if k < self._pad_steps:
            return self._pad_action(k, view)            # phase B — padding
        t = k - self._pad_steps                         # phase C — terminal (clamped)
        return self._terminal[min(t, len(self._terminal) - 1)]

    def _pad_action(self, k: int, view: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """One realistic PM action, cycling verbs & ids so the trajectory stays varied.

        On cadence slots emits a budgeted `wait` (advances the clock); otherwise a non-advancing
        observe/edit. Verbs needing an id fall back to a no-arg observe when the view has none."""
        if k % self._PAD_CADENCE == self._PAD_CADENCE - 1:  # cadence slot — advance the clock
            if self._rng is None:
                return ("wait", {"duration": self._per_wait})
            # Jitter the wait, clamped on a running total so cumulative advance ≤ cushion < horizon.
            jittered = self._rng.randint(int(self._per_wait * 0.6), int(self._per_wait * 1.2))
            dur = min(jittered, max(0, self._wait_cushion - self._wait_total))
            self._wait_total += dur
            return ("wait", {"duration": dur})
        docs = [d["id"] for d in view.get("docs", []) if isinstance(d, dict) and d.get("id")]
        projects = list(view.get("projects", {}))
        people = list(view.get("people", {}))
        meetings = [c["id"] for c in view.get("calendar", [])
                    if isinstance(c, dict) and c.get("id")]
        idx = k + self._rot_offset  # seeded start offset shifts the verb cycle (0 when unseeded)
        kind = self._ROTATION[idx % len(self._ROTATION)]
        n = idx // len(self._ROTATION) + self._text_base  # varies ids/text across full passes

        def pick(ids: list[str]) -> str | None:
            return ids[k % len(ids)] if ids else None

        if kind == "read_channel":                       # no channels in the PM view → observe
            return ("read_inbox", {})
        if kind == "read_doc":
            d = pick(docs)
            return ("read_doc", {"doc": d}) if d else ("get_tasks", {})
        if kind == "get_transcript":
            m = pick(meetings)
            return ("get_transcript", {"meeting": m}) if m else ("get_calendar", {})
        if kind == "send_message":
            return ("send_message", {"to": pick(people) or "org.cto",
                                     "body": f"Status update #{n + 1}: checkout on track."})
        if kind == "update_doc":
            note = f"Status note #{n + 1}: no new blockers."
            d = pick(docs)
            return ("update_doc", {"doc": d, "body": note}) if d else \
                   ("create_doc", {"title": f"Status log {n + 1}", "body": note})
        if kind == "create_task":
            pr = pick(projects)
            return ("create_task", {"project": pr, "title": f"Follow-up #{n + 1}",
                                    "owner": pick(people) or AGENT}) if pr else ("get_tasks", {})
        if kind == "book_meeting":
            return ("book_meeting", {"title": f"Sync #{n + 1}",
                                     "attendees": [pick(people) or AGENT],
                                     "at": "D5T10:00", "duration": 30})
        return (kind, {})  # read_inbox / get_tasks / get_calendar / get_people — no-arg observes


# ── block accessors (uniform over anthropic objects and scripted namespaces) ──────────────────

def _battr(b: Any, key: str) -> Any:
    return b.get(key) if isinstance(b, dict) else getattr(b, key, None)


def _latest_view(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Pull the most recent point-of-view the loop fed back via a tool_result (for scripted padding
    to read live ids). Returns {} on the very first turn, before any tool has run."""
    for msg in reversed(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "tool_result":
                try:
                    return json.loads(blk.get("content") or "{}").get("view", {})
                except (TypeError, ValueError):
                    return {}
    return {}


def _to_dicts(content: list[Any]) -> list[dict[str, Any]]:
    """Normalize a response's blocks (anthropic objects or scripted namespaces) to API dicts."""
    out: list[dict[str, Any]] = []
    for b in content:
        t = _battr(b, "type")
        if t == "text":
            out.append({"type": "text", "text": _battr(b, "text") or ""})
        elif t == "tool_use":
            out.append({"type": "tool_use", "id": _battr(b, "id"),
                        "name": _battr(b, "name"), "input": _battr(b, "input")})
    return out


# ── the episode loop ─────────────────────────────────────────────────────────────────────────

def run_episode(env: SaasWorldEnv, brain: Any, scenario: str, out_dir: Path,
                max_turns: int = 24, max_weeks: float | None = None) -> dict[str, Any]:
    tools = build_tools()
    system = build_system_prompt()

    reset = env.reset(scenario=scenario, max_weeks=max_weeks)
    horizon = int(reset.observation.metadata.get("horizon", 0))
    deadline = reset.observation.metadata.get("deadline")
    print(f"● reset  scenario={scenario}  horizon={horizon}  deadline={deadline}  "
          f"sim_time={reset.observation.sim_time}")

    first = ("You are starting your first week. Current point of view:\n"
             f"{json.dumps(project_view(reset.observation.state), default=str)}\n\n"
             "Decide and act with the tools. Remember to `wait` after messaging so replies arrive.")
    messages: list[dict[str, Any]] = [{"role": "user", "content": first}]

    traj: list[dict[str, Any]] = []
    final = reset
    turn = 0
    exit_reason = "max_turns"  # default: fell out of the turn budget without wrapping up
    while turn < max_turns:
        turn += 1
        resp = brain.respond(system, messages, tools)
        content = _to_dicts(resp.content)
        messages.append({"role": "assistant", "content": content})
        tool_uses = [b for b in content if b["type"] == "tool_use"]
        if not tool_uses:
            print(f"  turn {turn}: model returned no tool call — ending")
            exit_reason = "no_action"
            break

        results, finished = [], False
        for tu in tool_uses:
            verb, args = tu["name"], tu["input"] or {}
            if verb == "finish":
                print(f"  turn {turn}: finish — {args.get('summary', '')}")
                finished = True
                results.append({"type": "tool_result", "tool_use_id": tu["id"],
                                "content": "acknowledged"})
                continue
            final = env.step(SaasWorldAction(verb, args))
            o = final.observation
            err = o.metadata.get("error")
            tag = f"ERR {err['code']}" if err else f"t={o.sim_time} done={o.done}"
            print(f"  turn {turn}: {verb}({json.dumps(args, default=str)[:70]}) -> {tag}")
            traj.append(step_row(turn, verb, args, o))
            results.append({"type": "tool_result", "tool_use_id": tu["id"],
                            "content": _tool_result(o, horizon)})
        messages.append({"role": "user", "content": results})
        if finished or final.observation.done:
            exit_reason = "finish" if finished else "env_done"
            break

    if not final.observation.done:  # close the episode so it gets a terminal grade
        print("  (force-closing for the terminal score — agent did not wrap up in budget)")
        close_by = max(horizon, int(deadline or 0)) + 60  # cross whichever terminal binds
        final = env.step(SaasWorldAction("wait", {"duration": max(1, close_by)}))
        traj.append(step_row(turn + 1, "wait", {"auto_close": True}, final.observation))

    canonical = env.trajectory()  # canonical kernel event log for replay/timeline tools
    return _persist(out_dir, scenario, brain, horizon, messages, traj, final, exit_reason,
                    canonical)


def _persist(out_dir: Path, scenario: str, brain: Any, horizon: int,
             messages: list[dict[str, Any]], traj: list[dict[str, Any]],
             final: Any, exit_reason: str, canonical: dict[str, Any] | None = None
             ) -> dict[str, Any]:
    o = final.observation
    outcome = o.metadata.get("outcome")  # env verdict: "completed" | "timeout"
    manifest = {
        "kind": "agent", "scenario": scenario, "brain": type(brain).__name__,
        "model": getattr(brain, "model", None), "actions": len(traj),
        "horizon": horizon, "sim_time": o.sim_time, "final_reward": final.reward,
        "outcome": outcome, "exit_reason": exit_reason,
    }
    write_run(out_dir, manifest=manifest, rows=traj,
              score=o.metadata.get("score"), messages=messages, canonical=canonical)
    verdict = "TIMEOUT (failure)" if outcome == "timeout" else outcome or "?"
    print(f"\n● done  reward={final.reward}  outcome={verdict}  exit={exit_reason}  "
          f"actions={len(traj)}  -> {out_dir}/")
    return {"reward": final.reward, "outcome": outcome, "actions": len(traj),
            "out_dir": str(out_dir)}


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Real LLM PM agent driving a saas-world episode.")
    p.add_argument("--url", default="http://127.0.0.1:8092", help="env server base URL")
    p.add_argument("--scenario", default="checkout-not-ready")
    p.add_argument("--model", default="claude-sonnet-5")
    p.add_argument("--max-turns", type=int, default=24)
    p.add_argument("--max-weeks", type=float, default=None,
                   help="hard time budget in simulated weeks; exceeding it force-closes the "
                        "episode as a timeout failure (reward 0.0)")
    p.add_argument("--out", default=None, help="output dir (default runs/agent-<scenario>-<ts>)")
    p.add_argument("--print-tools", action="store_true", help="print derived tools + prompt, exit")
    p.add_argument("--self-test", action="store_true", help="drive a fixed policy offline (no key)")
    p.add_argument("--pad-steps", type=int, default=0,
                   help="after the scripted solve, emit N realistic non-advancing PM actions to "
                        "grow the trajectory, then cross the horizon — for producing long "
                        "inspectable trajectories (only with --self-test)")
    p.add_argument("--seed", type=int, default=None,
                   help="seed the scripted policy's randomness (length, action mix, timing, "
                        "decision polish) so repeated --self-test runs form a distribution; only "
                        "with --self-test")
    args = p.parse_args()

    if args.print_tools:
        print(json.dumps(build_tools(), indent=2))
        print("\n=== SYSTEM PROMPT ===\n" + build_system_prompt())
        return

    stamp = int(time.time())
    out = Path(args.out) if args.out else _ROOT / "runs" / f"agent-{args.scenario}-{stamp}"
    env = SaasWorldEnv(args.url)
    if not env.health():
        sys.exit(f"env server not reachable at {args.url} — start it with `saasworld-env-serve`")
    pad = args.pad_steps if args.self_test else 0  # padding only applies in scripted mode
    seed = args.seed if args.self_test else None   # seeding only applies in scripted mode
    sdir = _ROOT / "data" / "scenarios" / args.scenario  # lets the scripted brain read graded ids
    brain: Any = ScriptedBrain(pad, seed, sdir) if args.self_test else ClaudeBrain(args.model)
    # Auto-bump the loop budget so padding + solve + terminal + finish all fit without --max-turns.
    max_turns = max(args.max_turns, pad + 12) if pad > 0 else args.max_turns
    run_episode(env, brain, args.scenario, out, max_turns, args.max_weeks)


if __name__ == "__main__":
    main()
