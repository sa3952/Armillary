"""The site's default locale, read from frontend/surfaces.json so the builders do not hard-code `zh-TW` per path."""

from __future__ import annotations

import json
from pathlib import Path

SURFACE_MANIFEST = Path(__file__).resolve().parents[2] / "frontend" / "surfaces.json"
DEFAULT_LOCALE: str = json.loads(SURFACE_MANIFEST.read_text(encoding="utf-8"))["default_locale"]
