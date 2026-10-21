"""The public glossary: every entry of the calculator's glossary drawer
(scripts/frontend/scripts/glossary.js), in the drawer's order and words, so the
page and the drawer cannot say two different things; and the entry count its
prose quotes."""
from __future__ import annotations

import html

from ._common import ROOT, node_json, zh


FRAGMENT = "methods-glossary"
GLOSSARY_SCRIPT = ROOT / "scripts/frontend/scripts/glossary.js"


def entries() -> list[dict]:
    found = node_json("const G=require(process.argv[1]);process.stdout.write(JSON.stringify(G.ENTRIES));",
                      GLOSSARY_SCRIPT, what="read the glossary entries")
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
