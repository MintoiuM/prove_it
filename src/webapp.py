"""CLI entry point for the web UI. Prefer: ``python -m src.web``."""

from src.web.app import main

if __name__ == "__main__":
    raise SystemExit(main())
