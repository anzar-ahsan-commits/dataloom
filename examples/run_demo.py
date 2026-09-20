"""One-command, cross-platform bootstrap and complete offline demonstration."""

from __future__ import annotations

import os
import subprocess
import venv
from pathlib import Path


def main() -> None:
    """Install the core in an isolated environment and run the fictional demo."""
    root = Path(__file__).resolve().parents[1]
    if os.environ.get("DATALOOM_DEMO_BOOTSTRAPPED") != "1":
        environment = root / ".demo-venv"
        interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not interpreter.exists():
            venv.create(environment, with_pip=True)
        subprocess.run(
            [str(interpreter), "-m", "pip", "install", "--quiet", "-e", str(root)], check=True
        )
        subprocess.run(
            [str(interpreter), str(Path(__file__).resolve())],
            check=True,
            env={**os.environ, "DATALOOM_DEMO_BOOTSTRAPPED": "1"},
            cwd=root,
        )
        return
    from dataloom.demo import run_demo

    run_demo(root)


if __name__ == "__main__":
    main()
