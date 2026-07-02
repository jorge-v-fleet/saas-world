"""Offline entrypoint: `python -m saasworld.engine <generate|validate|freeze> ...`.

A thin argument shim over the engine library — no running service, no Kernel, no graded run. The
operator CLI surfaces the same verbs on `saasworld ...`.
"""

from __future__ import annotations

import argparse
import sys

from . import freeze, generate, validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m saasworld.engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="sample->bind->assemble->project_eval; write a candidate")
    g.add_argument("archetype")
    g.add_argument("--seed", type=int, required=True)
    g.add_argument("--out", default=None)

    v = sub.add_parser("validate", help="run the validity gate over an instance")
    v.add_argument("instance")

    f = sub.add_parser("freeze", help="content-hash + provenance-stamp an instance")
    f.add_argument("instance")

    args = parser.parse_args(argv)

    if args.cmd == "generate":
        res = generate(args.archetype, args.seed, args.out)
        print(f"wrote {res.out_dir}")
        print(f"activate: {', '.join(res.activate)}")
        print(f"summary: {res.summary}")
        return 0
    if args.cmd == "validate":
        verdict = validate(args.instance)
        print(f"coherence={verdict.coherence} solvable_floor={verdict.solvable_floor} "
              f"nontrivial_ceiling={verdict.nontrivial_ceiling}")
        print(f"{'PASS' if verdict.passed else 'REJECT'}: {verdict.reason}")
        return 0 if verdict.passed else 1
    frozen = freeze(args.instance)
    print(f"instance_hash: {frozen.instance_hash}")
    print(f"provenance: {frozen.provenance}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
