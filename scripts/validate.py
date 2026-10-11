"""Run the supported Linux/Python development checks from any directory."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKS = (
    ("ruff", "check", "custom_components", "tests", "scripts"),
    ("ruff", "format", "--check", "custom_components", "tests", "scripts"),
    ("mypy", "custom_components/freebox_ultra_ultimate"),
    ("compileall", "-q", "custom_components"),
    ("pytest", "-q", "--timeout=30"),
)


def main() -> None:
    for check in CHECKS:
        print("Validating:", " ".join(check), flush=True)
        subprocess.run([sys.executable, "-m", *check], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
