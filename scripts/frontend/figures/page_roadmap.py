"""The roadmap's status tables: the counts they state, from the request schema, the star catalogue, the options
catalogue and the surface list; and the validation run's size and station probes, from the run's configuration."""
from __future__ import annotations

from . import _site, page_validation
from ._common import zh, zh_quantity

FRAGMENT = "roadmap"
# The station check: each of the 448 station zero crossings the validation report found was probed at these offsets
# (the report, §10).
STATION_ZEROS = 448
STATION_PROBES = ("-6h", "-1h", "+1h", "+6h")

def build() -> tuple[dict[str, str], list[str]]:
    site = _site.product()
    quoted = [
        f"（{page_validation.START.year}–{page_validation.END.year}、{zh(len(page_validation.BODIES))}個天體）",
        f"{STATION_ZEROS} 個停滯零點、{STATION_ZEROS * len(STATION_PROBES):,} 個 ±1h／±6h probes",
        f"計算頁相位組{zh(_site.catalogue_group_sizes()['aspects'])}項控制",
        f"{zh(_site.count('aspect_set_profile'))}套相位集合、{zh_quantity(_site.count('aspect_orb_profile'))}套具名容許度表、"
        f"{zh(_site.count('partile_profile'))}種同度判準",
        f"界{zh(_site.count('bounds_profile'))}套、面／旬{zh_quantity(_site.count('decan_profile'))}套、"
        f"三分性{zh(_site.count('triplicity_profile'))}套",
        f"太陽中心真高度 ±{round(site['sect_band_degrees'] * 60)} 角分",
        f"出生時刻精度{zh(len(site['precisions']))}選一",
        f"{zh(_site.surface_count())}個公開介面",
    ]
    return {}, quoted
