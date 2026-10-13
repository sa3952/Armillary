"""The public glossary: every entry of the calculator's glossary drawer
(scripts/frontend/scripts/glossary.js), in the drawer's order and words, so the
page and the drawer cannot say two different things; and the entry count its
prose quotes."""
from __future__ import annotations

import html
import json
import shutil
import subprocess

from ._common import ROOT, zh


FRAGMENT = "methods-glossary"
GLOSSARY_SCRIPT = ROOT / "scripts/frontend/scripts/glossary.js"


def entries() -> list[dict]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is required to read the glossary entries")
    script = "const G=require(process.argv[1]);process.stdout.write(JSON.stringify({e:G.ENTRIES,t:G.TEXT}));"
    completed = subprocess.run([node, "-e", script, str(GLOSSARY_SCRIPT)],
                               cwd=ROOT, capture_output=True, text=True, check=False, timeout=30)
    if completed.returncode != 0:
        raise RuntimeError("the glossary entries could not be read: " + completed.stderr.strip())
    found = json.loads(completed.stdout)["e"]
    if not found or len({entry["key"] for entry in found}) != len(found):
        raise RuntimeError("the glossary has no entries or repeats a key")
    return found


def _entry(entry: dict) -> str:
    term = html.escape(entry["term"])
    if entry.get("en"):
        term += f' <span class="en" lang="en">{html.escape(entry["en"])}</span>'
    return "\n".join([
        f'        <div class="gl-item" id="{entry["key"]}">',
        f"          <dt>{term}</dt>",
        f'          <dd><p>{html.escape(entry["text"])}</p>'
        f'<p class="gl-where">在結果頁：{html.escape(entry["chapter"])}</p></dd>',
        "        </div>",
    ])


def build() -> tuple[dict[str, str], list[str]]:
    found = entries()
    block = "\n".join(['      <dl class="gl-list">', *(_entry(entry) for entry in found), "      </dl>"])
    return {"glossary-entries": block}, [f"共{zh(len(found))}條"]
