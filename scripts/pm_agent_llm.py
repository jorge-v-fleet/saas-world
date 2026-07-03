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


class ScriptedBrain:
    """Deterministic policy for `--self-test` — proves the loop/logging without an API key."""

    def __init__(self) -> None:
        self._plan = [
            ("send_message", {"to": "org.be_b2", "body": "Is the PSP ready for Friday?",
                              "refs": ["task.psp_integration"]}),
            ("wait", {"duration": 120}),
            ("record_decision", {"about": "proj.checkout", "type": "gonogo", "action": "reschedule",
                                 "new_date": "D8T17:00", "owner": "org.be_b2"}),
            ("send_message", {"to": "org.cto", "body": "Checkout slips: PSP cert is the blocker.",
                              "refs": ["blocker.psp_cert"]}),
            ("wait", {"duration": 7000}),
            ("finish", {"summary": "surfaced blocker, rescheduled, informed CTO"}),
        ]
        self._i = 0

    def respond(self, system: str, messages: list[dict[str, Any]],
                tools: list[dict[str, Any]]) -> Any:
        verb, args = self._plan[min(self._i, len(self._plan) - 1)]
        self._i += 1
        block = SimpleNamespace(type="tool_use", id=f"t{self._i}", name=verb, input=args)
        return SimpleNamespace(content=[block], stop_reason="tool_use")


# ── block accessors (uniform over anthropic objects and scripted namespaces) ──────────────────

def _battr(b: Any, key: str) -> Any:
    return b.get(key) if isinstance(b, dict) else getattr(b, key, None)


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
    brain: Any = ScriptedBrain() if args.self_test else ClaudeBrain(args.model)
    run_episode(env, brain, args.scenario, out, args.max_turns, args.max_weeks)


if __name__ == "__main__":
    main()
