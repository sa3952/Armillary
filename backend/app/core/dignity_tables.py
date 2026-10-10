"""Essential-dignity rule tables: domiciles, exaltations, bounds, decans, triplicities.

Tables and their source statements only: ``core.essential_dignities`` looks a
longitude up in them.  Degree intervals are zero-based and half-open.
"""

from __future__ import annotations

from typing import Any, TypedDict

SIGNS = (
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces",
)
ELEMENTS = ("fire", "earth", "air", "water")

DOMICILE_EXALTATION_PROFILE_ID = (
    "traditional_seven_domicile_exaltation_signs_v1"
)
DOMICILE_SIGNS = {
    "sun": ("leo",),
    "moon": ("cancer",),
    "mercury": ("gemini", "virgo"),
    "venus": ("taurus", "libra"),
    "mars": ("aries", "scorpio"),
    "jupiter": ("sagittarius", "pisces"),
    "saturn": ("capricorn", "aquarius"),
}
EXALTATION_SIGNS = {
    "sun": "aries",
    "moon": "taurus",
    "mercury": "virgo",
    "venus": "pisces",
    "mars": "capricorn",
    "jupiter": "cancer",
    "saturn": "libra",
}


class _SectTriplicityRule(TypedDict):
    day: tuple[str, ...]
    night: tuple[str, ...]


class _PtolemyTriplicityRule(_SectTriplicityRule):
    principal: str | None
    # 原文的指派結構與次要共主；不計分。
    assigned: tuple[str, ...]
    secondary_day: str
    secondary_night: str
    structure: str


def _segments(*pairs: tuple[str, int]) -> tuple[tuple[str, int], ...]:
    if sum(length for _ruler, length in pairs) != 30:
        raise ValueError("each bounds sign must total 30 degrees")
    return pairs


# Ptolemy, Tetrabiblos I.20 (Robbins numbering; = Hübner 1998 I.21), Robbins 1940
# translation: the chapter runs pp.91-97 and the table is printed on p.97; p.99
# begins I.21, the Chaldaean terms (pages read against the printed Loeb).  The
# cells were read against the English table (p.97) and the Greek table with its
# cumulative endpoints (p.96) in two scanned copies; the copies are named in
# BOUNDS_SOURCE_DETAILS and the endpoints are pinned in the tests.
EGYPTIAN_BOUNDS = (
    _segments(("jupiter", 6), ("venus", 6), ("mercury", 8), ("mars", 5), ("saturn", 5)),
    _segments(("venus", 8), ("mercury", 6), ("jupiter", 8), ("saturn", 5), ("mars", 3)),
    _segments(("mercury", 6), ("jupiter", 6), ("venus", 5), ("mars", 7), ("saturn", 6)),
    _segments(("mars", 7), ("venus", 6), ("mercury", 6), ("jupiter", 7), ("saturn", 4)),
    _segments(("jupiter", 6), ("venus", 5), ("saturn", 7), ("mercury", 6), ("mars", 6)),
    _segments(("mercury", 7), ("venus", 10), ("jupiter", 4), ("mars", 7), ("saturn", 2)),
    _segments(("saturn", 6), ("mercury", 8), ("jupiter", 7), ("venus", 7), ("mars", 2)),
    _segments(("mars", 7), ("venus", 4), ("mercury", 8), ("jupiter", 5), ("saturn", 6)),
    _segments(("jupiter", 12), ("venus", 5), ("mercury", 4), ("saturn", 5), ("mars", 4)),
    _segments(("mercury", 7), ("jupiter", 7), ("venus", 8), ("saturn", 4), ("mars", 4)),
    _segments(("mercury", 7), ("venus", 6), ("jupiter", 7), ("mars", 5), ("saturn", 5)),
    _segments(("venus", 12), ("jupiter", 4), ("mercury", 3), ("mars", 9), ("saturn", 2)),
)

# The complete table printed at the end of Tetrabiblos I.21 in Robbins (1940), p.107
# (Robbins numbering; Hübner 1998 merges it into I.21); the second table of I.20-21
# taken together, the only one in I.21.
# Libra, last segment: the LacusCurtius transcription ends the row with Saturn.
# The printed Loeb (1964 reprint of the 1940 edition, two scanned copies) prints
# Mars in both the English table (p.107) and the Greek table (p.106), and the
# manuscript totals in Robbins p.108 n.1 (Mars 66°) hold only with Mars; this
# profile uses Mars.  Every cell was read against the English table (p.107) and
# the Greek table with its cumulative endpoints (p.106) in the same two copies
# as the Egyptian table, so the row status is the checked one and only Libra
# carries an exception, for the transcription difference.  The apparatus Robbins
# prints for Libra concerns lines 3-4 (Mercury/Jupiter), not line 5.
PTOLEMY_ROBBINS_BOUNDS = (
    _segments(("jupiter", 6), ("venus", 8), ("mercury", 7), ("mars", 5), ("saturn", 4)),
    _segments(("venus", 8), ("mercury", 7), ("jupiter", 7), ("saturn", 2), ("mars", 6)),
    _segments(("mercury", 7), ("jupiter", 6), ("venus", 7), ("mars", 6), ("saturn", 4)),
    _segments(("mars", 6), ("jupiter", 7), ("mercury", 7), ("venus", 7), ("saturn", 3)),
    _segments(("jupiter", 6), ("mercury", 7), ("saturn", 6), ("venus", 6), ("mars", 5)),
    _segments(("mercury", 7), ("venus", 6), ("jupiter", 5), ("saturn", 6), ("mars", 6)),
    _segments(("saturn", 6), ("venus", 5), ("mercury", 5), ("jupiter", 8), ("mars", 6)),
    _segments(("mars", 6), ("venus", 7), ("jupiter", 8), ("mercury", 6), ("saturn", 3)),
    _segments(("jupiter", 8), ("venus", 6), ("mercury", 5), ("saturn", 6), ("mars", 5)),
    _segments(("venus", 6), ("mercury", 6), ("jupiter", 7), ("saturn", 6), ("mars", 5)),
    _segments(("saturn", 6), ("mercury", 6), ("venus", 8), ("jupiter", 5), ("mars", 5)),
    _segments(("venus", 8), ("jupiter", 6), ("mercury", 6), ("mars", 5), ("saturn", 5)),
)

# Lilly, Christian Astrology (1647), p.104, cumulative term endpoints transcribed
# from the first-edition scan and converted here to segment lengths.  Every cell
# was re-read against page images of two first-edition copies and the 1659
# edition; Leo was the only row that differed from an earlier transcription
# (Jupiter 6, Venus 7, Saturn 6, Mercury 6, Mars 5) and follows the page.
LILLY_RECEIVED_BOUNDS = (
    _segments(("jupiter", 6), ("venus", 8), ("mercury", 7), ("mars", 5), ("saturn", 4)),
    _segments(("venus", 8), ("mercury", 7), ("jupiter", 7), ("saturn", 4), ("mars", 4)),
    _segments(("mercury", 7), ("jupiter", 7), ("venus", 7), ("saturn", 4), ("mars", 5)),
    _segments(("mars", 6), ("jupiter", 7), ("mercury", 7), ("venus", 7), ("saturn", 3)),
    _segments(("saturn", 6), ("mercury", 7), ("venus", 6), ("jupiter", 6), ("mars", 5)),
    _segments(("mercury", 7), ("venus", 6), ("jupiter", 5), ("saturn", 6), ("mars", 6)),
    _segments(("saturn", 6), ("venus", 5), ("jupiter", 8), ("mercury", 5), ("mars", 6)),
    _segments(("mars", 6), ("jupiter", 8), ("venus", 7), ("mercury", 6), ("saturn", 3)),
    _segments(("jupiter", 8), ("venus", 6), ("mercury", 5), ("saturn", 6), ("mars", 5)),
    _segments(("venus", 6), ("mercury", 6), ("jupiter", 7), ("mars", 6), ("saturn", 5)),
    _segments(("saturn", 6), ("mercury", 6), ("venus", 8), ("jupiter", 5), ("mars", 5)),
    _segments(("venus", 8), ("jupiter", 6), ("mercury", 6), ("mars", 6), ("saturn", 4)),
)

BOUNDS_TABLES = {
    "egyptian_bounds_robbins_1940_v1": EGYPTIAN_BOUNDS,
    "ptolemy_bounds_robbins_1940_v1": PTOLEMY_ROBBINS_BOUNDS,
    "lilly_received_bounds_1647_v1": LILLY_RECEIVED_BOUNDS,
}

# Short citations travel in every response (`source`); the full statements are
# register entries (method_sources.py).
ROBBINS_EGYPTIAN_TERMS_PAGES = "pp.91-97, table p.97"
BOUNDS_SOURCES = {
    "egyptian_bounds_robbins_1940_v1": (
        f"Ptolemy, Tetrabiblos I.20 (Robbins 1940 {ROBBINS_EGYPTIAN_TERMS_PAGES}; "
        "= Hübner I.21), Egyptian terms"
    ),
    "chaldaean_bounds_ptolemy_i_21_v1": (
        "Ptolemy, Tetrabiblos I.21 (Robbins 1940 pp.99-101), Chaldaean terms rule"
    ),
    "ptolemy_bounds_robbins_1940_v1": (
        "Tetrabiblos I.21 complete table, Robbins 1940 p.107"
    ),
    "lilly_received_bounds_1647_v1": (
        "William Lilly, Christian Astrology (1647) p.104"
    ),
}
BOUNDS_SOURCE_STATEMENTS = {
    "egyptian_bounds_robbins_1940_v1": (
        "Egyptian terms as reported by Ptolemy, Tetrabiblos I.20; "
        f"Frank E. Robbins trans., Loeb 1940, {ROBBINS_EGYPTIAN_TERMS_PAGES}; "
        "a transmitted table "
        "(Robbins's printed recension), not a single manuscript witness"
    ),
    "chaldaean_bounds_ptolemy_i_21_v1": (
        "Chaldaean terms as reported by Ptolemy, Tetrabiblos I.21: "
        "triplicity sequence, sect-dependent Saturn/Mercury order, "
        "lengths 8/7/6/5/4"
    ),
    "ptolemy_bounds_robbins_1940_v1": (
        "Ptolemaic terms, Robbins 1940 transmitted table: the complete "
        "table printed after Ptolemy's discussion in Tetrabiblos I.20-21, "
        "Frank E. Robbins trans., Loeb 1940, pp.103-107; authorship of the "
        "complete table is disputed in scholarship"
    ),
    # Every cell was checked against page images of two first-edition copies and
    # the 1659 edition; that process note is internal.
    "lilly_received_bounds_1647_v1": (
        "William Lilly, Christian Astrology (1647), p.104, Table of the "
        "Essential Dignities, Termes columns; Leo reads Saturn 6, Mercury 7, "
        "Venus 6, Jupiter 6, Mars 5"
    ),
}

def _planet_totals(table) -> dict[str, int]:
    totals: dict[str, int] = {}
    for row in table:
        for ruler, length in row:
            totals[ruler] = totals.get(ruler, 0) + length
    return totals


_LILLY_TOTALS = _planet_totals(LILLY_RECEIVED_BOUNDS)
_ROBBINS_TOTALS = _planet_totals(PTOLEMY_ROBBINS_BOUNDS)
# Lilly's printed Termes do not sum to the Ptolemaic totals; the product keeps
# the page and states the difference instead of normalising it.
LILLY_BOUNDS_PLANET_TOTALS_NOTE = (
    "Totals of the printed p.104 table as transcribed: "
    + ", ".join(
        f"{planet.capitalize()} {_LILLY_TOTALS[planet]}"
        for planet in ("saturn", "jupiter", "mars", "venus", "mercury")
    )
    + f" (Robbins p.108 n.1: Jupiter {_ROBBINS_TOTALS['jupiter']}, "
    f"Mars {_ROBBINS_TOTALS['mars']}); not normalised"
)

# Closed vocabularies for provenance metadata.  Every value a profile
# emits in these positions comes from one of these tuples.
CITATION_VERIFICATION_STATES = (
    "cited_from_methodology_research_report_not_independently_checked",
    # The cited passage was read on page images of the cited printed edition.
    "checked_against_cited_edition_pages",
    # Read in an online transcription of the cited edition, not its printed page.
    "checked_against_online_transcription_not_printed_page",
)
_RESEARCH_CITED = CITATION_VERIFICATION_STATES[0]
_EDITION_PAGES_CHECKED = CITATION_VERIFICATION_STATES[1]
_ONLINE_TRANSCRIPTION_CHECKED = CITATION_VERIFICATION_STATES[2]
# The copies read are the 1964 reprint; its imprint lists reprints of the 1940
# first printing with no revision notice, so they count as first-edition page
# images.  A silent plate correction between 1940 and 1964 cannot be excluded
# from these copies, which is why the evidence names the printing.
_ROBBINS_COPIES = (
    "Ptolemy, Tetrabiblos, trans. F. E. Robbins (Loeb Classical Library, with "
    "Manetho; first printed 1940, reprinted 1948, 1956, 1964), two scanned "
    "copies of the 1964 reprint: Internet Archive "
    "L350ManethoHistoryOfEgyptPtolemyTetrabiblos and University of Toronto "
    "copy manethowithengli00maneuoft"
)
BOUNDS_ROW_VERIFICATION_STATES = (
    "printed_table_transcription_not_rechecked",
    "generated_from_stated_textual_rule",
    "checked_against_first_edition_page_images",
    "corrected_against_first_edition_page_images",
    # The product reading is kept and the
    # difference from the cited public transcription is disclosed.
    "reading_differs_from_cited_transcription",
)
TERMS_ATTRIBUTION_STATES = (
    "traditional_name_reported_by_ptolemy",
    "system_reported_by_ptolemy",
    "complete_table_authorship_disputed",
    "named_author_printed_table",
)
CLAIM_LAYER_STATES = (
    "attested_in_cited_text",
    "transmitted_printed_table",
    "disputed_unresolved",
    "not_claimed",
)

# Tests pin every cell of every table.  Bounds are named as transmitted tables; the profile ids stay as they
# are because renaming them would break stored requests.
BOUNDS_SOURCE_DETAILS: dict[str, dict[str, Any]] = {
    "egyptian_bounds_robbins_1940_v1": {
        "attribution": "traditional_name_reported_by_ptolemy",
        "default_row_verification": "checked_against_first_edition_page_images",
        "default_row_verification_evidence": [
            _ROBBINS_COPIES,
            "p.97, English table 'Terms according to the Egyptians', every "
            "cell (both copies, Internet Archive page n420)",
            "p.96, Greek table of the Egyptian terms with cumulative "
            "endpoints to 30 in every sign (both copies, Internet Archive "
            "page n419)",
            "p.96 n.1: the totals some manuscripts add (Saturn 57°, Jupiter "
            "79°, Mars 66°, Venus 82°, Mercury 76°) equal this table's totals",
        ],
        "row_exceptions": [],
        "chapter_numbering": {
            "robbins_1940": "I.20",
            "hubner_1998": "I.21",
            "note": "Robbins table p.97",
        },
        "note": (
            "Ptolemy reports these as the Egyptian terms. The Robbins printing "
            "is one realization of a table that later witnesses transmit with "
            "local variants. 'Egyptian' is the name Ptolemy reports; Babylonian "
            "tablets preserve forerunners (Jones & Steele, ISAW Papers 1, 2011; "
            "Steele, JCS 67, 2015); no table is claimed for the tablets."
        ),
        # 見證清單依 Jones & Steele 2011 §1。
        "witnesses": [
            "checked: Firmicus II.6.4-5, 10; Valens I.3; al-Bīrūnī, Tafhīm §453",
            "not checked: Dorotheus via Hephaistio; Paulus ch.3; Abū Maʿshar, Abbr. 7.10",
        ],
    },
    "chaldaean_bounds_ptolemy_i_21_v1": {
        "attribution": "system_reported_by_ptolemy",
        "default_row_verification": "generated_from_stated_textual_rule",
        "row_exceptions": [],
        "chapter_numbering": {
            "robbins_1940": "I.21",
            "hubner_1998": "I.21",
            "note": "Robbins pp.99-101, prose rule, no table",
        },
        "note": (
            "Generated from the rule Ptolemy reports: the triplicity ruler "
            "sequence with Saturn and Mercury exchanging position, and so "
            "length, by sect. I.21 is the only known classical witness (Jones & "
            "Steele 2011 §1: 'attested in no other source')."
        ),
    },
    "ptolemy_bounds_robbins_1940_v1": {
        "attribution": "complete_table_authorship_disputed",
        "default_row_verification": "checked_against_first_edition_page_images",
        "default_row_verification_evidence": [
            _ROBBINS_COPIES,
            "p.107, English table 'Terms according to Ptolemy', every cell "
            "(both copies, Internet Archive page n430)",
            "p.106, Greek table with cumulative endpoints to 30 in every sign "
            "(both copies, Internet Archive page n429)",
        ],
        # The printed glyph has been read: the value is kept and the difference
        # from the cited transcription is disclosed.
        "row_exceptions": [
            {
                "sign": "libra",
                "row_verification": "reading_differs_from_cited_transcription",
                "row_changed": False,
                "segment_number": 5,
                "product_reading": "mars",
                "cited_transcription_reading": "saturn",
                "cited_transcription": (
                    "LacusCurtius (B. Thayer) online transcription of Robbins 1940"
                ),
                "basis_for_product_reading": (
                    "Robbins prints Mars in both tables (English p.107, Greek "
                    "p.106), and the manuscript totals in p.108 n.1 (Mars 66°) "
                    "hold only with Mars; his apparatus for Libra (p.107) "
                    "concerns lines 3-4 only"
                ),
                "printed_glyph_checked": True,
                "printed_reading": "mars",
                "printed_reading_evidence": [
                    "Ptolemy, Tetrabiblos, trans. F. E. Robbins (Loeb Classical "
                    "Library, with Manetho; first printed 1940, 1964 reprint), "
                    "p.107, English table 'Terms according to Ptolemy', Libra "
                    "column 5: Mars 6 (Internet Archive "
                    "L350ManethoHistoryOfEgyptPtolemyTetrabiblos, page n430)",
                    "the same page, University of Toronto copy (Internet Archive "
                    "manethowithengli00maneuoft, page n430)",
                    "p.106, Greek table, Ζυγοῦ line 5: Mars, 6, cumulative 30",
                    "p.108 n.1: the totals some manuscripts add after the tables "
                    "(Saturn 57°, Jupiter 79°, Mars 66°, Venus 82°, Mercury 76°) "
                    "hold only with Mars in Libra line 5",
                ],
            }
        ],
        "claim_layers": {
            "ptolemy_prose_discussion_of_terms": "attested_in_cited_text",
            "robbins_1940_numeric_table": "transmitted_printed_table",
            "complete_table_written_by_ptolemy": "disputed_unresolved",
            "ptolemy_invented_these_terms": "not_claimed",
        },
        "chapter_numbering": {
            "robbins_1940": "I.21",
            "hubner_1998": "I.21",
            "note": "Robbins pp.103-105 account, table p.107",
        },
        "note": (
            "Tolsa, 'The Table of Ptolemy's Terms (Tetr. 1.21)', Philologus 162.2 "
            "(2018) 247-264, DOI 10.1515/phil-2017-0023, argues the complete table "
            "is a late-antique systematization that entered the text c. 11th "
            "century (his argument, not consensus). The profile id names the printed table, not Ptolemy's "
            "authorship."
        ),
    },
    "lilly_received_bounds_1647_v1": {
        "attribution": "named_author_printed_table",
        "default_row_verification": "checked_against_first_edition_page_images",
        "source_priority": "Christian Astrology 1647 p.104 consolidated table",
        "table_heading": "'...Dignities of the Planets according to Ptolomy' (Lilly's heading)",
        # 書內行星章與 p.104 表的差異，不改表值。
        "intra_book_variants": (
            "Gemini Venus: chapter p.73 15-20, table ends 21; Sagittarius: Mercury "
            "chapter pp.76-77 15-20 and Saturn p.57 21-25, table 19/25"
        ),
        "planet_totals_note": LILLY_BOUNDS_PLANET_TOTALS_NOTE,
        "row_exceptions": [
            {
                "sign": "leo",
                "row_verification": "corrected_against_first_edition_page_images",
                "row_changed": True,
                "previous_recorded_row": [
                    ["jupiter", 6], ["venus", 7], ["saturn", 6],
                    ["mercury", 6], ["mars", 5],
                ],
                "evidence": [
                    "William Lilly, Christian Astrology (London, 1647), p.104, "
                    "Termes columns, Wellcome copy (Internet Archive b30338724, leaf 138)",
                    "second edition (1659), p.104",
                    "the same book's planet chapters: Saturn p.57, Mercury pp.76-77, "
                    "Venus p.73, Jupiter p.62, Mars p.66 list Leo 1-6, 7-13, 14-19, "
                    "20-25, 26-30; Mercury p.76 prints the 7-13 line under the Virgo "
                    "glyph and the 1-7 line under the Leo glyph (read by sequence as "
                    "Leo 7-13, Virgo 1-7)",
                ],
                # Every cell of p.104 was re-read; Leo was the only row that
                # differed, in ruler order only.
            }
        ],
    },
}

CHALDAEAN_DAY_ORDER = (
    ("jupiter", "venus", "saturn", "mercury", "mars"),
    ("venus", "saturn", "mercury", "mars", "jupiter"),
    ("saturn", "mercury", "mars", "jupiter", "venus"),
    ("mars", "jupiter", "venus", "saturn", "mercury"),
)
CHALDAEAN_LENGTHS = (8, 7, 6, 5, 4)

CHALDEAN_FACES = (
    ("mars", "sun", "venus"), ("mercury", "moon", "saturn"),
    ("jupiter", "mars", "sun"), ("venus", "mercury", "moon"),
    ("saturn", "jupiter", "mars"), ("sun", "venus", "mercury"),
    ("moon", "saturn", "jupiter"), ("mars", "sun", "venus"),
    ("mercury", "moon", "saturn"), ("jupiter", "mars", "sun"),
    ("venus", "mercury", "moon"), ("saturn", "jupiter", "mars"),
)

# Manilius, Astronomica IV, zodiacal decans.  Written out
# rather than generated by the cycle formula: the transmitted text leaves the
# cycle at Pisces, and the adopted reading is an editorial correction the
# profile must disclose, not a property of arithmetic.
MANILIUS_SIGN_DECANS = (
    ("aries", "taurus", "gemini"),          # aries
    ("cancer", "leo", "virgo"),             # taurus
    ("libra", "scorpio", "sagittarius"),    # gemini
    ("capricorn", "aquarius", "pisces"),    # cancer
    ("aries", "taurus", "gemini"),          # leo
    ("cancer", "leo", "virgo"),             # virgo
    ("libra", "scorpio", "sagittarius"),    # libra
    ("capricorn", "aquarius", "pisces"),    # scorpio
    ("aries", "taurus", "gemini"),          # sagittarius
    ("cancer", "leo", "virgo"),             # capricorn
    ("libra", "scorpio", "sagittarius"),    # aquarius
    ("capricorn", "aquarius", "pisces"),    # pisces: IV.359-360 corrected
)
# Raw witness: Pisces as the text transmits it (IV.358-362).
MANILIUS_TRANSMITTED_PISCES = ("aries", "taurus", "pisces")
DECAN_READING_STATES = ("transmitted_text", "editorial_correction")

DECAN_SOURCE_DETAILS: dict[str, dict[str, Any]] = {
    "chaldean_planetary_faces_firmicus_ii_4_v1": {
        "complete_table_anchor": (
            "Firmicus Maternus, Mathesis II.4.3 (complete 36-face table; "
            "Kroll-Skutsch ed. 1897, vol. I p.45; chapter II.4 pp.44-46)"
        ),
        # Paulus and Firmicus may share a source,
        # so the witness is parallel, not independent.
        "parallel_witness": (
            "Paulus Alexandrinus, Introduction ch.4 (Boer 1958 numbering, main "
            "text; Schmidt/Hand 1995 pp.9-10), 'seven-zoned sphere' (order and "
            "term per research report, not checked)"
        ),
        "later_witness": "Lilly 1647 p.104 faces columns",
        "earliest_attributed_tradition": (
            "Teucer of Babylon, transmitted through later compilations, not a "
            "surviving table (Hübner, Berichte zur Wissenschaftsgeschichte 39.1, "
            "2016, 36-51: 'first witness, if not the inventor'; abstract only)"
        ),
        "not_to_be_confused_with": (
            "Ptolemy's 'proper face', Tetrabiblos I.23 (Robbins pp.111-113); shares "
            "only the name 'Chaldaean' with the terms"
        ),
        "conventional_name_note": (
            "'Chaldean order' is the conventional modern name for this "
            "sequence; the profile does not claim the method begins with "
            "Firmicus"
        ),
        "editorial_corrections": [],
        "citation_verification": _RESEARCH_CITED,
    },
    "manilius_sign_decans_astronomica_iv_v1": {
        "editorial_corrections": [
            {
                "sign": "pisces",
                "decan_numbers": [1, 2],
                "transmitted_reading": ["aries", "taurus"],
                "adopted_reading": ["capricorn", "aquarius"],
                "passage": "IV.358-362",
                "cited_lines": "IV.359-360",
                "basis": (
                    "The transmitted readings break the sequence the poem "
                    "itself sets up. Housman, M. Manilii Astronomicon liber "
                    "quartus (1920) prints the transmitted Aries, Taurus at "
                    "IV.359-360; his note on p.43 and his decan table on p.vi "
                    "give Capricorn, Aquarius as the poem's own rule requires, "
                    "accepting Scaliger's view that the transmitted reading is "
                    "the poet's error. Goold (LCL 469) per research report, "
                    "pages not checked. One table is kept and the correction "
                    "disclosed."
                ),
            }
        ],
        "citation_verification": _RESEARCH_CITED,
    },
}

DECAN_SOURCES = {
    "chaldean_planetary_faces_firmicus_ii_4_v1": (
        "Firmicus Maternus, Mathesis II.4, planetary decans/faces in the "
        "order conventionally called Chaldean"
    ),
    "manilius_sign_decans_astronomica_iv_v1": (
        "Manilius, Astronomica IV.294-386 (decan assignments from "
        "IV.312ff.); Pisces decans 1-2 follow the editorial correction "
        "of IV.359-360 (transmitted text: Aries, Taurus)"
    ),
}

DOROTHEAN = {
    "fire": ("sun", "jupiter", "saturn"),
    "earth": ("venus", "moon", "mars"),
    "air": ("saturn", "mercury", "jupiter"),
    "water": ("venus", "mars", "moon"),
}
# 依 Hübner 1998 希臘文校勘本（I.19 = Robbins I.18），火／土／風三象先「交給」
# 兩顆星，再由 sect 決定誰取得第一主宰，另一顆保有共主的份（secondary）；水象留給 Mars，
# 日間 Venus、夜間 Moon 與之共主。Robbins 英譯（pp.83-87）與 Hübner 都寫兩星指派。
# day/night 決定 selected_rulers；次要共主只是並列的欄位，不計分。
PTOLEMY_TEXTUAL: dict[str, _PtolemyTriplicityRule] = {
    "fire": {
        "day": ("sun",), "night": ("jupiter",), "principal": None,
        "assigned": ("sun", "jupiter"),
        "secondary_day": "jupiter", "secondary_night": "sun",
        "structure": "paired_assignment_with_sect_priority",
    },
    "earth": {
        "day": ("venus",), "night": ("moon",), "principal": None,
        "assigned": ("venus", "moon"),
        "secondary_day": "moon", "secondary_night": "venus",
        "structure": "paired_assignment_with_sect_priority",
    },
    "air": {
        "day": ("saturn",), "night": ("mercury",), "principal": None,
        "assigned": ("saturn", "mercury"),
        "secondary_day": "mercury", "secondary_night": "saturn",
        "structure": "paired_assignment_with_sect_priority",
    },
    "water": {
        "day": ("mars", "venus"), "night": ("mars", "moon"), "principal": "mars",
        "assigned": ("mars",),
        "secondary_day": "venus", "secondary_night": "moon",
        "structure": "persistent_base_with_sect_co_ruler",
    },
}
LILLY_COMPACT: dict[str, _SectTriplicityRule] = {
    "fire": {"day": ("sun",), "night": ("jupiter",)},
    "earth": {"day": ("venus",), "night": ("moon",)},
    "air": {"day": ("saturn",), "night": ("mercury",)},
    "water": {"day": ("mars",), "night": ("mars",)},
}

TRIPLICITY_IDS = (
    "dorothean_triplicity_three_rulers_v1",
    "ptolemy_triplicity_textual_corulership_v1",
    "lilly_triplicity_compact_1647_v1",
)
TRIPLICITY_SOURCES = {
    TRIPLICITY_IDS[0]: "Dorotheus, Carmen Astrologicum I.1 (Pingree 1976 pp.161-162)",
    TRIPLICITY_IDS[1]: (
        "Ptolemy, Tetrabiblos I.18 (Robbins 1940 pp.83-87) = I.19 (Hübner 1998)"
    ),
    TRIPLICITY_IDS[2]: "William Lilly, Christian Astrology (1647) pp.104-105",
}
TRIPLICITY_SOURCE_STATEMENTS = {
    TRIPLICITY_IDS[0]: (
        "Dorotheus, Carmen Astrologicum I.1 (Arabic recension; Pingree 1976 "
        "pp.161-162): the first two rulers exchange by sect and the third ('the "
        "associate of these two', I.28 p.196) participates by day and by night; "
        "the Greek verse in Hephaestio I.6 gives the same four triads (read in an "
        "online transcription following CCAG/TLG; the Pingree 1973 edition and "
        "Schmidt 1994 p.30 not checked)"
    ),
    TRIPLICITY_IDS[1]: (
        "Ptolemy, Tetrabiblos I.18 in Frank E. Robbins trans. (1940) = I.19 "
        "in W. Hübner ed. (1998). Following Hübner, fire, earth and air are "
        "each assigned to two planets (Sun+Jupiter, Venus+Moon, Saturn+Mercury), "
        "sect giving first governance and the other planet keeping a share "
        "(secondary_ruler); water is left to Mars, with Venus by day and Moon "
        "by night as co-rulers. This product's earlier one-ruler-per-sect table "
        "was its own simplification: Robbins (pp.83-87) and Hübner "
        "both assign two planets. secondary_ruler adds no score."
        # Checked against Robbins pp.83-87 and the PAL online Hübner text I.19.
    ),
    # Lilly's own attribution is stated;
    # Naibod is named as Lilly's attribution, never as this profile's anchor.
    # Spelling follows the page ('Ptolomy' on pp.104-105).
    TRIPLICITY_IDS[2]: (
        "William Lilly, Christian Astrology (1647), p.104, day/night "
        "triplicity table, headed 'according to Ptolomy', columns Di. and Noc. "
        "only; p.105: Mars 'ruleth onely that Triplicity both day and night', "
        "which Lilly attributes to Ptolomy and Naibod (Naibod 1560 not checked). "
        "This is Lilly's printed table, not the Dorothean table without its "
        "third ruler and not Ptolemy's co-rulership text"
    ),
}

ADDITIONAL_SHARE_APPLICATION_STATES = ("disclosed_not_applied",)
TRIPLICITY_SOURCE_DETAILS: dict[str, dict[str, Any]] = {
    TRIPLICITY_IDS[0]: {
        "chapter": (
            "Carmen Astrologicum I.1 (Pingree pp.161-162); use of the rulers I.4 "
            "(pp.163-164, not checked)"
        ),
        "third_ruler_term": "third_and_common_ruler",
        "third_ruler_term_source": (
            "Holden's Rhetorius per research report, not checked; Pingree has "
            "'then' (I.1), 'associate' (I.28), 'participant' (I.10)"
        ),
        "corroboration": "Valens II.1-2 (Pingree pp.54-56; Riley/Griscti pp.89-92; not checked)",
        "cross_check_pending": "Dykes, Dorotheus's Carmen Astrologicum, 2nd ed. (not compared)",
        "sign_specific_additional_shares": [
            {
                "sign": "virgo",
                "planet": "mercury",
                "application": "disclosed_not_applied",
                "basis": (
                    "Pingree I.1 p.162 'and in Virgo is also a share for "
                    "Mercury' (page checked) and the Greek verse in Hephaestio "
                    "I.6 (online transcription only). A sign-specific share, not "
                    "a fourth earth ruler; not added to the rulers."
                ),
            }
        ],
        # The table itself (I.1 pp.161-162) and I.28 p.196; the other fields
        # say which of their citations are not checked.
        "citation_verification": _EDITION_PAGES_CHECKED,
    },
    TRIPLICITY_IDS[1]: {
        "chapter_numbering": {
            "robbins_1940": "I.18",
            "hubner_1998": "I.19",
            "robbins_1940_pages": "pp.83-87",
            "locator": "PAL ed. 9 text 1, 〈I.19〉 Περὶ τριγώνων",
            "concordance_note": "Robbins I.11-I.20 = Hübner I.12-I.21 (Robbins I.10 is split)",
        },
        # Robbins in the LacusCurtius transcription and Hübner in the PAL online text.
        "citation_verification": _ONLINE_TRANSCRIPTION_CHECKED,
    },
    TRIPLICITY_IDS[2]: {
        "water_rule": "mars_alone_by_day_and_night",
        "not_an_alias_of": [TRIPLICITY_IDS[0], TRIPLICITY_IDS[1]],
        "note": (
            "Fire, earth and air coincide with the first two Dorothean rulers, "
            "but water does not: by day Dorotheus gives Venus and Lilly gives "
            "Mars. Lilly keeps Mars for water by day and night without "
            "Ptolemy's Venus/Moon co-rulers."
        ),
        "citation_verification": _RESEARCH_CITED,
    },
}


DOMICILE_EXALTATION_SOURCES = [
    {
        "work": "Ptolemy, Tetrabiblos",
        "location": (
            "I.17 (Robbins, LCL 435, 1940, pp.79-83 = Hübner 1998 I.18) "
            "and I.19 (Robbins; = Hübner I.20)"
        ),
        "role": (
            "whole_sign_domicile_and_exaltation_basis_without_"
            "exact_degrees_in_the_cited_chapters"
        ),
    },
    {
        "work": "Dorotheus of Sidon, Carmen Astrologicum",
        "location": "I.1 (houses of the planets) and I.2 (exaltations), Pingree 1976 p.162",
        "role": (
            "also_attested_sign_assignments_source_also_supplies_"
            "exact_degrees_not_evaluated_by_this_profile"
        ),
    },
    {
        "work": "Vettius Valens, Anthologies",
        "location": "III.4 (Pingree 1986 numbering; Riley, CSUS PDF (2010) p.61)",
        "role": (
            "also_attested_exaltation_signs_source_also_supplies_"
            "exact_degrees_not_evaluated_by_this_profile"
        ),
    },
    {
        "work": "Firmicus Maternus, Mathesis",
        "location": "II.2 and II.3.5-6 (Kroll-Skutsch-Ziegler)",
        "role": (
            "also_attested_domiciles_and_exaltation_signs_source_"
            "also_supplies_exact_degrees_not_evaluated_by_this_profile"
        ),
    },
]
DOMICILE_EXALTATION_SOURCE_SCOPE_NOTE = (
    "Ptolemy I.17 and I.19 support the sign-level output used here. "
    "The Dorotheus, Valens, and Firmicus passages, which also attest "
    "these assignments, transmit exact-degree traditions that this "
    "profile deliberately does not evaluate; their inclusion does not "
    "imply that ancient traditions were sign-only. Whether these "
    "witnesses are independent of Ptolemy has not been evaluated. For "
    "manuscript variation in the exaltation degrees see Ossendrijver "
    "(2025), Journal for the History of Astronomy 56.4: 396-411, table 2, "
    "DOI 10.1177/00218286251353245 (table 2 not consulted; checked at the "
    "bibliography level only)."
)
