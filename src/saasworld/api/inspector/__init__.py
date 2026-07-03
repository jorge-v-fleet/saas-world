"""Inspector: a read-only UI over ``runs/`` mounted on the SaaS API server.

The router serves a self-contained single-page app and a small JSON API that scans the runs
directory and normalizes every run kind (LLM agent, random rollout, canonical CLI event log) into
one display shape. First view: the raw trajectory inspector.
"""

from .router import router

__all__ = ["router"]
