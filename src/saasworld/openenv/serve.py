"""uvicorn entrypoint for the OpenEnv env server — single process, localhost, port 8092.

Kept off the Tool API's 8080 so both can run side by side. Start with:
    python -m saasworld.openenv.serve
"""

from __future__ import annotations


def main() -> None:
    import uvicorn

    from .server import create_env_app

    uvicorn.run(create_env_app(), host="127.0.0.1", port=8092, workers=1)


if __name__ == "__main__":
    main()
