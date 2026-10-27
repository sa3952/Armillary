"""The rule tables of 〈出生時間換算的規則與出處〉(/zh-TW/methods/birth-time-conversion).

Everything the page states about a period or a source is rendered here from backend/app/civil_time_sources.json, the
file the time-conversion route answers with, so the page and the route cannot disagree.  The file is a pinned copy of
the tz database (tests/backend/test_civil_time_sources.py holds it to the installed one); the build also re-reads each
period's offset from zoneinfo at its start, and refuses to render a page the running database contradicts.

The fragment writes, each on a line of its own:

- ``{{civil_time_rule_tables}}``: per region a table with one row per source row, then the region's every transition
  in a <details>;
- ``{{civil_time_archive_notes}}``: per source row, what we read and where the original is held;

and, inline, ``{{civil_time_tzdb_checked}}``, ``{{civil_time_period_count}}``, ``{{civil_time_source_count}}`` and
``{{civil_time_level_count:<level>}}`` (``read_original``, ``read_transcription``, ``relayed``, or ``not_cited``).
"""

from __future__ import annotations

import datetime as dtmod
import html
import json
import re
from collections.abc import Callable
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
SOURCES_PATH = ROOT / "backend" / "app" / "civil_time_sources.json"
PLACEHOLDER = re.compile(r"\{\{civil_time_[a-z_:]+\}\}")
_TABLES = re.compile(r"^(?P<indent>[ \t]*)\{\{civil_time_rule_tables\}\}$", re.MULTILINE)
_NOTES = re.compile(r"^(?P<indent>[ \t]*)\{\{civil_time_archive_notes\}\}$", re.MULTILINE)
_LEVEL_COUNT = re.compile(r"\{\{civil_time_level_count:(?P<level>[a-z_]+)\}\}")

REGIONS = (("taiwan", "臺灣", ("Asia/Taipei",)), ("hong_kong", "香港", ("Asia/Hong_Kong",)),
    ("macau", "澳門", ("Asia/Macau",)), ("mainland_china", "中國", ("Asia/Shanghai", "Asia/Urumqi")),)
ZONE_NOTES = {"Asia/Shanghai": "北京時間", "Asia/Urumqi": "新疆時間"}
UTC = dtmod.timezone.utc
# The rule tables' columns.  Each cell repeats its column's name as data-label: on a phone the stylesheet lays a row
# out as a card and shows the name beside the value.
RULE_COLUMNS = ("規則", "期間（當地鐘面）", "UTC 偏移", "依據文件", "核到哪一層")

def _offset(text: str) -> dtmod.timedelta:
    sign = -1 if text[0] == "-" else 1
    parts = [int(part) for part in text[1:].split(":")] + [0, 0]
    return sign * dtmod.timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2])

def _instant(text: str | None) -> dtmod.datetime | None:
    return None if text is None else dtmod.datetime.fromisoformat(text[:-1]).replace(tzinfo=UTC)

def _start(row: dict) -> dtmod.datetime:
    instant = _instant(row["from_utc"])
    if instant is None:
        raise ValueError(f"only a zone's first period may lack a start: {row['zone']}")
    return instant

def _wall(instant: dtmod.datetime, offset: str) -> str:
    local = (instant + _offset(offset)).replace(tzinfo=None)
    return local.strftime("%Y-%m-%d %H:%M:%S" if local.second else "%Y-%m-%d %H:%M")

def _clock_change(instant: dtmod.datetime, before: str, after: str) -> str:
    old, new = _wall(instant, before), _wall(instant, after)
    if old[:10] == new[:10]:
        new = new[11:]
    return f"{old} → {new}"

def load(path: Path = SOURCES_PATH) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    def state(instant: dtmod.datetime, zone: str) -> tuple:
        local = instant.astimezone(ZoneInfo(zone))
        return local.utcoffset(), local.tzname(), bool(local.dst())
    def stated(row: dict) -> tuple:
        return _offset(row["utc_offset"]), row["abbreviation"], row["summer_time"]
    previous: dict[str, dict] = {}
    for row in document["periods"]:
        start = _instant(row["from_utc"])
        before = previous.get(row["zone"])
        previous[row["zone"]] = row
        if start is None:
            continue
        if state(start,
            row["zone"]) != stated(row) or (before is not None and state(start - dtmod.timedelta(seconds=1),
            row["zone"]) != stated(before)):
            raise ValueError(
                f"the installed tz database disagrees with the source table at {row['zone']} "
                f"{row['from_utc']}; regenerate nothing until tests/backend/test_civil_time_sources.py passes"
            )
    return document

def _periods(document: dict, zone: str) -> list[dict]:
    return [row for row in document["periods"] if row["zone"] == zone]

def _level_badge(document: dict, level: str | None) -> str:
    if level is None:
        return '<span class="mono">未引用</span>'
    return f'<span class="mono">{html.escape(document["verification_levels"][level])}</span>'

# The calculate page's labels for the same codes (frontend/zh-TW/labels.js civil_time_regime);
# tests/integration/test_frontend_labels.py holds the two equal.
REGIME_LABELS = {"local_mean_time": "地方平時（依經度推算）", "standard_time": "標準時",
    "summer_time": "夏令時間（日光節約時間）", "japan_standard_time": "日本中央標準時", "wartime_time": "戰時時間"}

def _regime_label(regime: str) -> str:
    return REGIME_LABELS[regime]

def _years(years: list[int]) -> str:
    runs: list[list[int]] = []
    for year in sorted(set(years)):
        if runs and year == runs[-1][1] + 1:
            runs[-1][1] = year
        else:
            runs.append([year, year])
    return "、".join(str(a) if a == b else f"{a}–{b}" for a, b in runs)

def _stretch(rows: list[dict], following: dict[int, dict]) -> str:
    summers = [row for row in rows if row["summer_time"] and row["regime"] == "summer_time"]
    if summers:
        years: list[int] = []
        for row in summers:
            first_year = (_start(row) + _offset(row["utc_offset"])).year
            after = following.get(id(row))
            last_year = (_start(after) + _offset(row["utc_offset"])).year if after else first_year
            years += range(first_year, last_year + 1)
        others = [
            _regime_label(regime) for regime in dict.fromkeys(row["regime"] for row in rows)
            if regime not in ("summer_time", "standard_time")
        ]
        tail = f"，以及{'、'.join(others)}" if others else ""
        return f"{_years(years)} 年的夏令時間（{len(summers)} 段{tail}）；逐段時刻見下方轉換表"
    first = rows[0]
    start = _instant(first["from_utc"])
    begin = "1900 年以前" if start is None else _wall(start, first["utc_offset"])
    last = rows[-1]
    after = following.get(id(last))
    if after is None:
        return f"{begin} 起至今"
    return f"{begin} 至 {_wall(_start(after), last['utc_offset'])}"

def _region_table(document: dict, key: str, name: str, zones: tuple[str, ...], number: int, indent: str) -> list[str]:
    lines = [f'<h3 id="rules-{key}">{html.escape(name)}</h3>']
    for zone in zones:
        periods = _periods(document, zone)
        following = {id(row): periods[index + 1] for index, row in enumerate(periods[:-1])}
        groups: dict[str, list[dict]] = {}
        for row in periods:
            groups.setdefault(row["source"], []).append(row)
        zone_slug = zone.split("/")[1].lower().replace("_", "-")
        caption_id = f"tab-{key}-{zone_slug}"
        label = f"{name}（{ZONE_NOTES[zone]}，{zone}）" if zone in ZONE_NOTES else f"{name}（{zone}）"
        # The roles restate what the elements already are: WebKit drops a table's semantics once CSS changes its
        # display, which the phone layout does.
        lines += [
            f'<div class="spec-scroll" tabindex="0" role="region" aria-labelledby="{caption_id}">',
            '  <table class="spec ct-rules" role="table">',
            f'    <caption id="{caption_id}">表 {number}　{html.escape(label)}的規則與出處</caption>',
            '    <thead role="rowgroup"><tr role="row">'
            + "".join(f'<th scope="col" role="columnheader">{column}</th>' for column in RULE_COLUMNS)
            + "</tr></thead>",
            '    <tbody role="rowgroup">',
        ]
        for source_key, rows in groups.items():
            source = document["sources"].get(source_key)
            offsets = "／".join(dict.fromkeys(row["utc_offset"] for row in rows))
            if source is None:
                title = "，".join(dict.fromkeys(_regime_label(row["regime"]) for row in rows))
                cells = (html.escape(title), html.escape(_stretch(rows, following)), html.escape(offsets),
                         "沒有可引用的文件；時區資料庫的值是它自己的推定", _level_badge(document, None))
                row_id = f"src-{zone_slug}-not-cited"
            else:
                cells = (f'<a href="#note-{source_key}">{html.escape(source["title"])}</a>', html.escape(_stretch(rows, following)),
                    html.escape(offsets), html.escape(source["document"]),
                    _level_badge(document, source["verification_level"]))
                row_id = f"src-{zone_slug}-{source_key}"
            lines.append(
                f'      <tr id="{row_id}" role="row">'
                + "".join(
                    f'<td role="cell" data-label="{column}">{cell}</td>'
                    for column, cell in zip(RULE_COLUMNS, cells, strict=True)
                )
                + "</tr>"
            )
        lines += ["    </tbody>", "  </table>", "</div>"]
        # The first period is the one in effect on 1900-01-01; its own start, if any, is before the product's range and
        # has no earlier period here.
        transitions = periods[1:]
        previous = {id(row): periods[index] for index, row in enumerate(transitions)}
        lines += [
            '<details class="ct-transitions">',
            f"  <summary>{html.escape(label)}逐段轉換時刻（{len(transitions)} 次）</summary>",
            '  <div class="spec-scroll" tabindex="0" role="region" '
            f'aria-label="{html.escape(label)}逐段轉換時刻（可橫向捲動）">',
            '    <table class="spec">',
            '      <thead><tr><th scope="col">世界時</th><th scope="col">當地鐘面</th>'
            '<th scope="col">UTC 偏移</th><th scope="col">之後是</th><th scope="col">規則</th></tr></thead>',
            "      <tbody>",
        ]
        for row in transitions:
            start = _start(row)
            before = previous[id(row)]
            source = document["sources"].get(row["source"])
            rule = (f'<a href="#note-{row["source"]}">{html.escape(source["title"])}</a>' if source else "未引用")
            cells = (html.escape(start.strftime("%Y-%m-%d %H:%M" + (":%S" if start.second else ""))),
                html.escape(_clock_change(start, before["utc_offset"], row["utc_offset"])),
                html.escape(f"{before['utc_offset']} → {row['utc_offset']}"),
                html.escape(_regime_label(row["regime"])), rule)
            lines.append('        <tr><td class="mono">' + "</td><td>".join(cells) + "</td></tr>")
        lines += ["      </tbody>", "    </table>", "  </div>", "</details>"]
        number += 1
    return [indent + line if line else line for line in lines]

def rule_tables(document: dict, indent: str) -> str:
    lines: list[str] = []
    number = 1
    for key, name, zones in REGIONS:
        lines += _region_table(document, key, name, zones, number, indent)
        number += len(zones)
    return "\n".join(lines)

def archive_notes(document: dict, indent: str) -> str:
    lines = ['<ol class="ct-notes">']
    for key, source in document["sources"].items():
        read = "；".join(f'<a href="{html.escape(item["url"],
            quote=True)}">{html.escape(item["label"])}</a>' for item in source["read"])
        holder = source["holder"]
        where = ""
        if holder["name"]:
            where = (
                f'<a href="{html.escape(holder["url"], quote=True)}">{html.escape(holder["name"])}</a>'
                if holder["url"] else html.escape(holder["name"])
            ) + "。"
        lines.append(
            f'  <li id="note-{key}"><b>{html.escape(source["title"])}</b>：{html.escape(source["document"])}'
            f"。我們讀過的：{read}。我們核到：{_level_badge(document, source['verification_level'])}。"
            f"原件：{where}{html.escape(holder['note'])}</li>"
        )
    lines.append("</ol>")
    return "\n".join(indent + line for line in lines)

def fill(body: str, load_document: Callable[[], dict] = load) -> str:
    if not PLACEHOLDER.search(body):
        return body
    document = load_document()
    body = _TABLES.sub(lambda match: rule_tables(document, match.group("indent")), body)
    body = _NOTES.sub(lambda match: archive_notes(document, match.group("indent")), body)
    levels = [source["verification_level"] for source in document["sources"].values()]
    def level_count(match: re.Match) -> str:
        level = match.group("level")
        if level == "not_cited":
            return str(sum(1 for row in document["periods"] if row["source"] == "not_cited"))
        if level not in document["verification_levels"]:
            raise ValueError(f"unknown verification level placeholder: {level}")
        return str(levels.count(level))
    body = _LEVEL_COUNT.sub(level_count, body)
    body = (body.replace("{{civil_time_tzdb_checked}}",
        html.escape(document["tzdb_version_checked"])) .replace("{{civil_time_period_count}}",
        str(len(document["periods"]))) .replace("{{civil_time_source_count}}", str(len(document["sources"]))))
    leftover = PLACEHOLDER.search(body)
    if leftover is not None:
        raise ValueError("a civil-time placeholder must stand on a line of its own: " + leftover.group(0))
    return body
