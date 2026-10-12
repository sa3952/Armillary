"""The site's default locale, read from frontend/surfaces.json.

The manifest owns which locales the site declares and which is the default;
the builders take the default from here instead of writing `zh-TW` beside each
path, so the shipped directory and every page link follow the one declaration.
"""

from __future__ import annotations

import json
from pathlib import Path

SURFACE_MANIFEST = Path(__file__).resolve().parents[2] / "frontend" / "surfaces.json"
DEFAULT_LOCALE: str = json.loads(SURFACE_MANIFEST.read_text(encoding="utf-8"))["default_locale"]
