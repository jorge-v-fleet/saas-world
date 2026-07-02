"""uvicorn entrypoint — single process, one worker, localhost only."""

from __future__ import annotations


def main() -> None:
    import uvicorn

    from .api.app import create_app

    uvicorn.run(create_app(), host="127.0.0.1", port=8080, workers=1)


if __name__ == "__main__":
    main()
