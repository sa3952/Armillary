"""One checked subprocess call for the gate and audit scripts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import subprocess


def run_checked(
    command: list[str], *, error: Callable[[str], BaseException], cwd: Path | None = None,
    timeout: float, check: bool = True, env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `command` capturing text; with `check`, a non-zero exit raises
    `error` naming the exit code, the command and the end of its output."""
    completed = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True,
                               timeout=timeout, env=env)
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise error(f"command failed ({completed.returncode}): {' '.join(command[:4])}: {detail[-2000:]}")
    return completed
