#!/usr/bin/env python3
"""Run one off-host check and tell the phone when it fails.

    python -m scripts.deployment.notify_phone --title "Armillary watch" -- \\
        python -m scripts.deployment.watch_public_site --release-record RECORD_JSON

The check's own output is printed unchanged and its exit status is this
command's exit status, whether or not the notification went out: a scheduler
that reads the status still sees the failure when the phone channel is down.
Only a non-zero exit sends anything.  The notification is an ntfy message to
the topic URL in `--topic-file` (default ~/.config/armillary/ntfy_topic_url),
a file outside the repository that only its owner may read (mode 0600).  The
message carries the check's title, its exit status and its output lines, which
name what failed and nothing about any visitor; the topic URL is never part of
the message or of anything printed.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
import stat
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_TOPIC_FILE = Path.home() / ".config/armillary/ntfy_topic_url"
MAX_BODY_BYTES = 3000  # ntfy turns a longer message into an attachment
MAX_LINES = 20

Post = Callable[[str, bytes, dict[str, str]], int]


class TopicError(ValueError):
    pass


def read_topic(path: Path) -> str:
    try:
        mode = path.stat().st_mode
    except OSError:
        raise TopicError(f"no topic file at {path}") from None
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise TopicError(f"{path} is readable by others; chmod 600 it")
    url = path.read_text(encoding="utf-8").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or not parts.path.strip("/") or parts.query or parts.fragment:
        raise TopicError(f"{path} does not hold one https topic URL")
    return url


def payload(title: str, status: int, output: str) -> tuple[bytes, dict[str, str]]:
    lines = [line for line in output.splitlines() if line.strip()]
    shown = lines[:MAX_LINES]
    if len(lines) > MAX_LINES: shown.append(f"... and {len(lines) - MAX_LINES} more lines")
    data = (f"exit {status}\n" + ("\n".join(shown) if shown else "(no output)")).encode("utf-8")
    if len(data) > MAX_BODY_BYTES:
        data = data[: MAX_BODY_BYTES - 4].decode("utf-8", "ignore").encode("utf-8") + b"\n..."
    ascii_title = title.encode("ascii", "replace").decode("ascii")
    return data, {"Title": ascii_title, "Priority": "high", "Tags": "warning"}


def post(url: str, data: bytes, headers: dict[str, str]) -> int:
    request = Request(url, data=data, headers=headers, method="POST")
    with urlopen(request, timeout=20) as response:  # noqa: S310 - https checked in read_topic
        return response.status


def notify(title: str, status: int, output: str, *, topic_file: Path, send: Post = post) -> str | None:
    """None when sent; otherwise why not, never naming the topic URL."""
    try:
        url = read_topic(topic_file)
    except TopicError as error:
        return str(error)
    data, headers = payload(title, status, output)
    try:
        answered = send(url, data, headers)
    except Exception as error:  # noqa: BLE001 - a failure to notify is reported, never raised
        return f"notification failed: {type(error).__name__}"
    return None if 200 <= answered < 300 else f"notification answered HTTP {answered}"


def main(argv: Sequence[str] | None = None, *, send: Post = post) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", required=True)
    parser.add_argument("--topic-file", type=Path, default=DEFAULT_TOPIC_FILE)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    command = arguments.command[1:] if arguments.command[:1] == ["--"] else arguments.command
    if not command: parser.error("give the check to run after --")
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
        status, output = completed.returncode, completed.stdout + completed.stderr
    except OSError as error:
        status, output = 127, f"cannot start the check: {type(error).__name__}\n"
    sys.stdout.write(output)
    if status != 0:
        problem = notify(arguments.title, status, output, topic_file=arguments.topic_file, send=send)
        if problem: print(f"NOTIFY FAILED: {problem}", file=sys.stderr)
    return status


if __name__ == "__main__": raise SystemExit(main())
