"""Typer application root: subcommands, global flags, and exit-code mapping.

Groups the three layers — build-time (``generate/validate/freeze``), runtime
(``load/step/advance/observe/run-eval``) and observability (``traj …``). Every command prints the
shared envelope (human by default, ``--json`` for machines) and maps failures to exit codes:
0 ok · 1 runtime · 2 usage · 3 integrity.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import typer

from . import build, runtime, traj
from .render import CliError, Payload, render

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Operator CLI for the SaaS-world simulation.")
traj_app = typer.Typer(no_args_is_help=True, help="Inspect and replay persisted trajectories.")
app.add_typer(traj_app, name="traj")

JsonOpt = Annotated[bool, typer.Option("--json", help="Emit the machine-readable envelope.")]
BackendOpt = Annotated[str, typer.Option("--backend", envvar="SAASWORLD_BACKEND",
                                         help="embedded (default) or http.")]
UrlOpt = Annotated[str, typer.Option("--url", help="HTTP backend endpoint.")]

_DEFAULT_URL = "http://127.0.0.1:8080"


def _emit(command: str, json_mode: bool, fn: Callable[[], Payload]) -> None:
    """Run a handler, print its envelope, and translate failures into the right exit code."""
    try:
        payload = fn()
    except CliError as e:
        render(command, False, json_mode, None, e)
        raise typer.Exit(e.exit_code) from e
    except Exception as e:  # unexpected: emit a structured envelope, never a raw traceback
        err = CliError("runtime", f"internal error: {type(e).__name__}")
        render(command, False, json_mode, None, err)
        raise typer.Exit(err.exit_code) from e
    render(command, True, json_mode, payload, None)


# ---- build-time -----------------------------------------------------------------------------

@app.command()
def generate(archetype: str, seed: Annotated[int, typer.Option("--seed")],
             out: Annotated[str | None, typer.Option("--out")] = None,
             json_mode: JsonOpt = False) -> None:
    """Generate a candidate scenario instance from an archetype + seed (offline)."""
    _emit("generate", json_mode, lambda: build.generate(archetype, seed, out))


@app.command()
def validate(instance: str, json_mode: JsonOpt = False) -> None:
    """Run the validity gate over a candidate instance (offline)."""
    _emit("validate", json_mode, lambda: build.validate(instance))


@app.command()
def freeze(instance: str, json_mode: JsonOpt = False) -> None:
    """Content-hash + provenance-stamp an instance, marking it immutable (offline)."""
    _emit("freeze", json_mode, lambda: build.freeze(instance))


# ---- runtime --------------------------------------------------------------------------------

@app.command()
def load(instance: str,
         agent_version: Annotated[str, typer.Option("--agent-version")] = "baseline",
         backend: BackendOpt = "embedded", url: UrlOpt = _DEFAULT_URL,
         json_mode: JsonOpt = False) -> None:
    """Load a frozen instance, seed the world, open a run; prints the run_id."""
    _emit("load", json_mode, lambda: runtime.load(instance, agent_version, backend, url))


@app.command()
def step(run: Annotated[str, typer.Option("--run")],
         verb: Annotated[str, typer.Option("--verb")],
         args: Annotated[str | None, typer.Option("--args")] = None,
         backend: BackendOpt = "embedded", url: UrlOpt = _DEFAULT_URL,
         json_mode: JsonOpt = False) -> None:
    """Drive one agent action through the Tool API; returns the observation."""
    _emit("step", json_mode, lambda: runtime.step(run, verb, args, backend, url))


@app.command()
def advance(run: Annotated[str, typer.Option("--run")],
            to: Annotated[int | None, typer.Option("--to")] = None,
            by: Annotated[int | None, typer.Option("--by")] = None,
            backend: BackendOpt = "embedded", url: UrlOpt = _DEFAULT_URL,
            json_mode: JsonOpt = False) -> None:
    """Release the clock to a sim-time / by minutes; returns every event that fired."""
    _emit("advance", json_mode, lambda: runtime.advance(run, to, by, backend, url))


@app.command()
def observe(run: Annotated[str, typer.Option("--run")],
            actor: Annotated[str, typer.Option("--actor")] = "agent",
            path: Annotated[str | None, typer.Option("--path")] = None,
            backend: BackendOpt = "embedded", url: UrlOpt = _DEFAULT_URL,
            json_mode: JsonOpt = False) -> None:
    """Inspect current state (no event emitted)."""
    _emit("observe", json_mode, lambda: runtime.observe(run, actor, path, backend, url))


@app.command("run-eval")
def run_eval(run: Annotated[str, typer.Option("--run")], json_mode: JsonOpt = False) -> None:
    """Score the trajectory at its checkpoints; prints the weighted breakdown."""
    _emit("run-eval", json_mode, lambda: runtime.run_eval(run))


# ---- observability --------------------------------------------------------------------------

@traj_app.command("ls")
def traj_ls(scenario: Annotated[str | None, typer.Option("--scenario")] = None,
            agent_version: Annotated[str | None, typer.Option("--agent-version")] = None,
            json_mode: JsonOpt = False) -> None:
    """List runs from the derived index."""
    _emit("traj.ls", json_mode, lambda: traj.ls(scenario, agent_version))


@traj_app.command("show")
def traj_show(run_id: str, frm: Annotated[int | None, typer.Option("--from")] = None,
              to: Annotated[int | None, typer.Option("--to")] = None,
              json_mode: JsonOpt = False) -> None:
    """Print the canonical event log (operator POV)."""
    _emit("traj.show", json_mode, lambda: traj.show(run_id, frm, to))


@traj_app.command("replay")
def traj_replay(run_id: str, json_mode: JsonOpt = False) -> None:
    """Deterministically reconstruct the episode (no model calls); exit 3 on divergence."""
    _emit("traj.replay", json_mode, lambda: traj.replay_run(run_id))


@traj_app.command("pov")
def traj_pov(run_id: str, actor: Annotated[str, typer.Option("--actor")],
             at: Annotated[int, typer.Option("--at")],
             npc: Annotated[str | None, typer.Option("--npc")] = None,
             json_mode: JsonOpt = False) -> None:
    """Project the log through an actor's view scope at a sim-time."""
    _emit("traj.pov", json_mode, lambda: traj.pov(run_id, actor, at, npc))


@traj_app.command("query")
def traj_query(regression: Annotated[bool, typer.Option("--regression")] = False,
               instance_hash: Annotated[str | None, typer.Option("--instance-hash")] = None,
               failure_clusters: Annotated[bool, typer.Option("--failure-clusters")] = False,
               reward_hack: Annotated[bool, typer.Option("--reward-hack")] = False,
               sql: Annotated[str | None, typer.Option("--sql")] = None,
               json_mode: JsonOpt = False) -> None:
    """Cross-trajectory analyses over the index (regression / clusters / reward-hack / sql)."""
    _emit("traj.query", json_mode,
          lambda: traj.query(regression, instance_hash, failure_clusters, reward_hack, sql))


if __name__ == "__main__":
    app()
