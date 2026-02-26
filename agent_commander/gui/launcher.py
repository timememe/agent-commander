"""Entry point for PyInstaller-frozen Agent Commander."""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Launch the GUI, handling frozen-app path setup."""
    if getattr(sys, "frozen", False):
        app_dir = os.path.dirname(sys.executable)
        os.environ.setdefault("AGENT_COMMANDER_APP_DIR", app_dir)
        os.environ.setdefault("AGENT_COMMANDER_FROZEN", "1")

    # Set sys.argv so typer dispatches to the gui command.
    sys.argv = [sys.argv[0], "gui"]

    from agent_commander.cli.commands import app

    app()


if __name__ == "__main__":
    main()
