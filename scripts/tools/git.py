"""Git as the scripts run it: one call with a chosen failure, and the clean
checkout refusal the gates share."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
import subprocess
from typing import Literal, overload


@overload
def git(root: Path, *arguments: str, error: Callable[[str], BaseException] | None = None,
        env: Mapping[str, str] | None = None, text: Literal[True] = True,
        timeout: float | None = None) -> str: ...


@overload
def git(root: Path, *arguments: str, error: Callable[[str], BaseException] | None = None,
        env: Mapping[str, str] | None = None, text: Literal[False],
        timeout: float | None = None) -> bytes: ...


def git(root: Path, *arguments: str, error: Callable[[str], BaseException] | None = None,
        env: Mapping[str, str] | None = None, text: bool = True,
        timeout: float | None = None) -> str | bytes:
    """The standard output of `git arguments` run in `root`.

    Without `error` a failure raises subprocess.CalledProcessError (or the
    OSError of a missing git); with it, `error("git <command> failed: <why>")`.
    """
    command = ["git", *arguments]
    if error is None:
        return subprocess.run(command, cwd=root, env=env, capture_output=True, text=text,
                              check=True, timeout=timeout).stdout
    try:
        completed = subprocess.run(command, cwd=root, env=env, capture_output=True, text=text,
                                   check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as failure:
        raise error(f"git {' '.join(arguments[:2])} failed: {failure}") from None
    if completed.returncode != 0:
        stderr = completed.stderr if text else completed.stderr.decode("utf-8", "replace")
        raise error(f"git {' '.join(arguments[:2])} failed: {stderr.strip()}") from None
    return completed.stdout


def require_clean_head(
    root: Path, expected: str | None = None, *, error: Callable[[str], BaseException] = RuntimeError,
    dirty: str = "the checkout is not clean", moved: str = "the checkout HEAD is not the expected revision",
    untracked_all: bool = False,
) -> str:
    """HEAD of `root`, refused with `error` when the tree has a staged, unstaged
    or untracked change (`dirty`) or HEAD is not `expected` (`moved`).

    `untracked_all` has git list every untracked file rather than its directory.
    """
    head = git(root, "rev-parse", "HEAD", error=error).strip()
    status = git(root, "status", "--porcelain=v1", *(("--untracked-files=all",) if untracked_all else ()),
                 error=error)
    if status:
        raise error(dirty)
    if expected is not None and head != expected:
        raise error(moved)
    return head
