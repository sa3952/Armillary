# Noto fonts: chart wheel glyph outlines

`frontend/zh-TW/chart-glyphs.js` holds 27 SVG paths taken from the outlines of three fonts licensed under the
SIL Open Font License 1.1. The fonts are not in this repository; only the extracted paths are, and they carry the
copyright lines and the full licence text in their header. `scripts/frontend/chart_glyphs.py` re-creates the file
from the three font files and refuses any file whose SHA-256 is not the one below.

| Font | Version (name table) | Source（google/fonts commit `8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5`） | Git blob | SHA-256 |
|---|---|---|---|---|
| Noto Sans Symbols | 2.003 | `ofl/notosanssymbols/NotoSansSymbols[wght].ttf`; upstream notofonts/symbols `b61fa7f86fb7d4163ee11d46d0977393f98d4f7a` | `a0061bfbcbbec27bf2b280fc8c49ea42cf7cb7ab` | `f7e7e04b4a24b6c78893d50cbfd2b2f6cae49617ab047bfef668d252adb128f7` |
| Noto Sans Symbols 2 | 2.008 | `ofl/notosanssymbols2/NotoSansSymbols2-Regular.ttf`; upstream notofonts/symbols `25b00f0d3f40873a005287514ba2a48558655314` | `caf89dd0e60e23ac39ce18da823095959d409437` | `7d5fb73b7ca67a6798101741f5d280a3d016a56a197afcd4199dbb57b4b82a21` |
| Noto Sans | 2.015 | `ofl/notosans/NotoSans[wdth,wght].ttf`; upstream notofonts/latin-greek-cyrillic | `75575046c015ff623a848096a15779867ba71453` | `bfb7bb691513f12e734dc346c03a03f784912432d7e3fa8e56efcf906fe86b3d` |

Download URL pattern: `https://raw.githubusercontent.com/google/fonts/<commit>/<path>` (retrieved 2026-10-11).
Each file's Git blob hash was compared with the one the GitHub contents API lists for that path before use.

Glyphs taken: U+2609 ☉ from Noto Sans Symbols 2; U+211E ℞ from Noto Sans; from Noto Sans Symbols U+260A ☊,
U+260B ☋, U+263D ☽, U+263F ☿, U+2640 ♀, U+2642–U+2647 ♂♃♄♅♆♇, U+26B7 ⚷, U+26B8 ⚸ and the twelve signs U+2648–U+2653.
Each outline is the default instance's (Regular) TrueType contour, converted without simplification.

Licence texts: `OFL-noto-sans-symbols.txt`（the same file in both Symbols directories, blob
`7c95767f5c669c448148e7e6c8fc4ee2c85128b1`）and `OFL-noto-sans.txt`（blob
`6843f31878c9945e1e71e1baa275546b4eefead8`）, copied byte for byte except the one trailing space at the end of
line 21, which the repository's whitespace check refuses. Neither declares a Reserved Font Name; the
derived glyph set is still not called by any font's name.

The article figures（`scripts/frontend/figures/_fx.py`）reuse the same paths, read from `chart-glyphs.js`：each
article page with figures carries the glyphs it draws as SVG `<symbol>`s in one sprite, whose `<metadata>`
holds the copyright lines and the full licence text, as the script's header does.
