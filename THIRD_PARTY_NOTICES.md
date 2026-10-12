# Third-party notices

This repository is a combined work. The project's own files are licensed under AGPL-3.0-only; the
components below keep the licences their own authors granted, and nothing in this file or in the
project's licence replaces them.

## Licences at a glance

| Component | Copyright holder | Licence as granted | Where the text is |
|---|---|---|---|
| Armillary (this project's own code and documents) | Sebastian | AGPL-3.0-only | `LICENSE` |
| pyswisseph 2.10.3.2 (Python binding) | Stanislas Marquis, 2007–2023 | AGPL-3.0-or-later | `third_party/pyswisseph/LICENSE.txt`; header of `pyswisseph.c` in the sdist |
| Swiss Ephemeris (C library compiled into the extension) | Astrodienst AG, 1997–2021 | Dual licence; this project uses the GNU AGPL route | SWISS_EPHEMERIS_LICENSE in `third_party/pyswisseph/` |
| Swephelp (helper library compiled into the extension) | Stanislas Marquis | GPL-2.0-or-later | SWEPHELP_LICENSE in `third_party/pyswisseph/` |
| Ephemeris files (`backend/ephe/`) | Astrodienst AG | Swiss Ephemeris licence, GNU AGPL route | SWISS_EPHEMERIS_LICENSE in `third_party/pyswisseph/`; basis in `deploy/ephemeris.provenance.json` |
| Chart glyph outlines (`frontend/zh-TW/chart-glyphs.js`) | The Noto Project Authors, 2022 | OFL-1.1 | `third_party/noto-fonts/` |
| GeoNames place data | GeoNames | CC-BY-4.0 | below, "Place data" |
| Taiwan Ministry of the Interior place names | Department of Land Administration | Taiwan Government Data Open License 1.0 | below, "Place data" |
| Python dependencies | their authors | their own licences | each package's source distribution on PyPI, named by the SHA-256 in the requirement locks; below, "Debian base and other dependencies" |

## Swiss Ephemeris and pyswisseph

This application uses`pyswisseph 2.10.3.2`（Copyright © 2007–2023 Stanislas Marquis, AGPL-3.0-or-later）,
incorporating Swiss Ephemeris：Copyright © 1997–2021 Astrodienst AG, Switzerland. Swiss Ephemeris is
dual-licensed；this project uses the GNU AGPL route. Exact source and original notices are under
`third_party/pyswisseph/`in the Corresponding Source tree. Attribution does not imply endorsement.

The ephemeris files in `backend/ephe/` are distributed with Swiss Ephemeris under its dual licence, GNU
AGPL route. Astrodienst's Swiss Ephemeris pages name no licence specific to these files（checked 2026-10-11）;
its documentation says "All actual software and data are found in the public download area"
（<https://www.astro.com/swisseph/swisseph.htm>, §1.1）. The record, with the date and sources, is
`licence_basis` in `deploy/ephemeris.provenance.json`.

The extension also compiles the bundled **Swephelp** helper sources. Swephelp states that it is not part of
Swiss Ephemeris itself and identifies Stanislas Marquis as its author, under the GNU GPL version 2 or (at your
option) any later version（GPL-2.0-or-later）. Its original README and license text are inside `third_party/pyswisseph/pyswisseph-2.10.3.2.tar.gz`; the publication exporter also preserves them
beside that exact sdist as `SWEPHELP_README.txt` and `SWEPHELP_LICENSE`.

## Place data

- GeoNames`cities500`：<https://download.geonames.org/export/dump/cities500.zip>，
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，attribution to GeoNames.
- GeoNames`admin1CodesASCII`、`admin2Codes`、`alternateNamesV2`（administrative-area names and
  Traditional-Chinese place names in the labels）：<https://download.geonames.org/export/dump/admin1CodesASCII.txt>、
  <https://download.geonames.org/export/dump/admin2Codes.txt>、
  <https://download.geonames.org/export/dump/alternateNamesV2.zip>，
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)，attribution to GeoNames.
- Taiwan Ministry of the Interior administrative and settlement names：
  <https://data.gov.tw/dataset/40281>、<https://data.gov.tw/dataset/53677>，
  [Taiwan Government Data Open License 1.0](https://data.gov.tw/license)，attribution to the
  Department of Land Administration. Attribution statement：內政部地政司 2026「臺灣地區地名資料_行政區域類」、
  「臺灣地區地名資料_聚落類」（retrieved 2026-10-09；no dataset version number is published）。此開放資料依政府資料
  開放授權條款 (Open Government Data License) 進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料
  開放授權條款：https://data.gov.tw/license.

Coordinates are representative points, not verified addresses；neither provider endorses this service.

## Chart glyphs

The chart wheel's astrological symbols are SVG paths taken from the outlines of Noto Sans Symbols 2.003,
Noto Sans Symbols 2 2.008 and Noto Sans 2.015：Copyright 2022 The Noto Project Authors
（<https://github.com/notofonts/symbols>, <https://github.com/notofonts/latin-greek-cyrillic>），licensed under the
[SIL Open Font License 1.1](https://openfontlicense.org). The paths are distributed under that licence; the
copyright lines and the full licence text are in the header of `frontend/zh-TW/chart-glyphs.js` and in
`third_party/noto-fonts/`, with each font's version and checksum. No font file is distributed.

## Star catalogue checks

The fixed-star positions the service computes come from the bundled Swiss Ephemeris star catalogue
(`backend/ephe/sefstars.txt`). Our tests check them against values read from two services of the
Centre de Données astronomiques de Strasbourg (CDS); those values are used for checking only and are not
distributed with the service.

- This research has made use of the SIMBAD database, operated at CDS, Strasbourg, France
  （Wenger et al. 2000, A&AS 143, 9）.
- This research has made use of the VizieR catalogue access tool, CDS, Strasbourg, France
  （Ochsenbein et al. 2000, A&AS 143, 23）, for the Hipparcos new reduction（van Leeuwen 2007, A&A 474,
  653; VizieR I/311）.

## Source location

Named paths are relative to the Corresponding Source tree, not the runtime image. For an eligible hosted
release, use the exact 40-character revision reported by the service at：

```text
https://github.com/sa3952/Armillary/tree/<public_source_revision>
```

Release engineering verifies anonymous reachability. Do not infer a deployed revision from the latest
branch. The runtime image contains notices and license text but not locks、manifests or source archives.

## Debian base and other dependencies

The image uses the digest-pinned Debian-based Python image named in`deploy/Dockerfile`. It is not
currently conveyed through a registry or to a third party；this notice is not a Debian source offer. If
that changes, Debian source-fulfilment must be reassessed before conveyance.

The other Python dependencies are permissively licensed and this tree does not carry their archives. Their
exact versions and SHA-256 hashes are pinned in `deploy/requirements.lock`（production）、
`deploy/build-requirements.lock`（build）and `backend/requirements-dev.lock`（development）, and
`publication/third_party_source_lock.json` names each one's single source distribution on PyPI by its SHA-256.
Each package's licence text is inside its source distribution and its installed metadata. To obtain every
source distribution and check it against those hashes:

```bash
python -m scripts.publication.prepare_third_party_sources \
  --runtime-lock deploy/requirements.lock --build-lock deploy/build-requirements.lock \
  --development-lock backend/requirements-dev.lock \
  --source-lock publication/third_party_source_lock.json \
  --destination /SAFE/OUTSIDE/SOURCE/dependency-sources
```

It downloads over HTTPS from PyPI and fails unless the package set equals the locks, PyPI's declared hash and the
downloaded bytes both equal the locked one, and each archive carries licence files. Release engineering runs the
same command before publishing any release that changes a lock.
