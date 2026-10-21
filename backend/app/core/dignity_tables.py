"""Essential-dignity rule tables: domiciles, exaltations, bounds, decans, triplicities.

Tables and their source statements only: ``core.essential_dignities`` looks a
longitude up in them.  Degree intervals are zero-based and half-open.
"""

from __future__ import annotations

from typing import Any, TypedDict

from .source_reading import DOROTHEUS_BOOK_I_ONLINE, cited

SIGNS = (
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces",
)
ELEMENTS = ("fire", "earth", "air", "water")
SEVEN_PLANETS = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
# Slowest to fastest: the order of the planetary hours, the faces and the firdaria partners.
CHALDEAN_ORDER = ("saturn", "jupiter", "mars", "sun", "venus", "mercury", "moon")

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


def _opposite_sign(sign: str) -> str:
    return SIGNS[(SIGNS.index(sign) + 6) % 12]


# Detriment and fall are the signs opposite the domiciles and the exaltation;
# derived here so the two tables above stay the only typed-out assignment.
DETRIMENT_SIGNS = {
    planet: tuple(sorted((_opposite_sign(sign) for sign in signs), key=SIGNS.index))
    for planet, signs in DOMICILE_SIGNS.items()
}
FALL_SIGNS = {planet: _opposite_sign(sign) for planet, sign in EXALTATION_SIGNS.items()}


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
# (Robbins numbering; Hübner 1998 merges it into I.21); the only table in I.21.
# Every cell was read against the English table (p.107) and the Greek table with
# its cumulative endpoints (p.106) in the same two copies as the Egyptian table.
# Libra, last segment: Mars as printed, not the LacusCurtius Saturn (the Libra
# row_exception gives the basis).  Robbins's apparatus readings (Proclus,
# Camerarius) stay out of the table and are disclosed in manuscript_variants.
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
    # The page-image check (see LILLY_RECEIVED_BOUNDS) stays internal.
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

# Closed vocabularies: every provenance value a profile emits comes from these.
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
_LILLY_SCAN_P104 = (
    "the scanned first edition, Wellcome copy, archive.org/details/b30338724 "
    "(leaves n137-n138)"
)
# Robbins's Latin apparatus to the Greek tables was read on these page images of
# one copy; the manuscripts and Camerarius's printings it reports were not read,
# so every variant it reports is secondary_only.
_ROBBINS_APPARATUS_READ_AT = (
    "the scanned 1964 reprint of Robbins (Loeb 1940), University of "
    "Toronto copy, Internet Archive manethowithengli00maneuoft, pages {pages}; "
    "Vat. gr. 1453 and Camerarius's printings were not read"
)
# Witnesses Robbins's apparatus names for a reading other than his table's.
MANUSCRIPT_VARIANT_WITNESSES = (
    "proclus_paraphrase_double_reading",
    "camerarius_printing",
)
BOUNDS_ROW_VERIFICATION_STATES = (
    "printed_table_transcription_not_rechecked",
    "generated_from_stated_textual_rule",
    "checked_against_first_edition_page_images",
    "corrected_against_first_edition_page_images",
    # Product reading kept; the difference from the cited transcription disclosed.
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

# Tests pin every cell.  Bounds are named as transmitted tables; the profile ids
# stay because renaming them would break stored requests.
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
        "manuscript_variants": [
            cited("Robbins 1940 p.97 n.2 (Latin apparatus to the Greek table on p.96)",
                  ("Robbins follows the tables of Vat. gr. 1453 (which contains "
                   "Proclus's Paraphrase); Camerarius's printing agrees except at "
                   "lines 26 and 28 of the Greek page, under Capricorn, where it "
                   "offers Venus 7 and Mars 5; the tables are in manuscripts "
                   "PLMNAD and omitted in VE"),
                  "secondary_only", _ROBBINS_APPARATUS_READ_AT.format(pages="n420"),
                  readings=[
                      {
                          "sign": "capricorn", "line": 3,
                          "witness": "camerarius_printing",
                          "table": ["venus", 8], "other": ["venus", 7],
                      },
                      {
                          "sign": "capricorn", "line": 5,
                          "witness": "camerarius_printing",
                          "table": ["mars", 4], "other": ["mars", 5],
                      },
                  ],
                  line_note=("Robbins names page lines 26 and 28; Venus and Mars occur in "
                             "Capricorn only at lines 3 and 5, which is where they are "
                             "recorded here"))
        ],
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
            "checked: Valens I.3; al-Bīrūnī, Tafhīm §453",
            "variant witness: Firmicus II.6 (Kroll-Skutsch) differs in Gemini, Cancer "
            "and Sagittarius (II.6.4-5, 10); the other nine signs agree",
            "not checked: Dorotheus via Hephaestio; Paulus ch.3; Abū Maʿshar, Abbr. 7.10",
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
                "reading": "original_language_read",
                "read_at": (
                    "the scanned 1964 reprint of Robbins, both copies named in "
                    "the evidence, pages n429-n430"
                ),
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
        # "other" is None where the apparatus gives only the planet.
        "manuscript_variants": [
            cited(("Robbins 1940 p.106 n.1, continued on p.107 (Latin apparatus "
                   "to the Greek table on p.106)"),
                  ("Robbins follows the tables found in Vat. gr. 1453, which "
                   "contains Proclus's Paraphrase; Camerarius's printing agrees "
                   "except at lines 4-5 under Capricorn, where its order is Mars 5, "
                   "Saturn 6; Proclus has some double readings, in Taurus, Cancer, "
                   "Leo, Libra, Scorpio, Capricorn and Pisces"),
                  "secondary_only", _ROBBINS_APPARATUS_READ_AT.format(pages="n429-n430"),
                  readings=[
                      {
                          "sign": "capricorn", "line": 4, "witness": "camerarius_printing",
                          "table": ["saturn", 6], "other": ["mars", 5],
                      },
                      {
                          "sign": "capricorn", "line": 5, "witness": "camerarius_printing",
                          "table": ["mars", 5], "other": ["saturn", 6],
                      },
                      {
                          "sign": "taurus", "line": 4, "witness": "proclus_paraphrase_double_reading",
                          "table": ["saturn", 2], "other": ["saturn", 4],
                      },
                      {
                          "sign": "cancer", "line": 2, "witness": "proclus_paraphrase_double_reading",
                          "table": ["jupiter", 7], "other": ["mercury", None],
                      },
                      {
                          "sign": "cancer", "line": 3, "witness": "proclus_paraphrase_double_reading",
                          "table": ["mercury", 7], "other": ["jupiter", None],
                      },
                      {
                          "sign": "leo", "line": 3, "witness": "proclus_paraphrase_double_reading",
                          "table": ["saturn", 6], "other": ["venus", None],
                      },
                      {
                          "sign": "libra", "line": 3, "witness": "proclus_paraphrase_double_reading",
                          "table": ["mercury", 5], "other": ["jupiter", 8],
                      },
                      {
                          "sign": "libra", "line": 4, "witness": "proclus_paraphrase_double_reading",
                          "table": ["jupiter", 8], "other": ["mercury", 5],
                      },
                      {
                          "sign": "scorpio", "line": 2, "witness": "proclus_paraphrase_double_reading",
                          "table": ["venus", 7], "other": ["jupiter", 8],
                      },
                      {
                          "sign": "scorpio", "line": 3, "witness": "proclus_paraphrase_double_reading",
                          "table": ["jupiter", 8], "other": ["venus", 7],
                      },
                      {
                          "sign": "capricorn", "line": 4, "witness": "proclus_paraphrase_double_reading",
                          "table": ["saturn", 6], "other": ["mars", None],
                      },
                      {
                          "sign": "capricorn", "line": 5, "witness": "proclus_paraphrase_double_reading",
                          "table": ["mars", 5], "other": ["saturn", None],
                      },
                      {
                          "sign": "pisces", "line": 4, "witness": "proclus_paraphrase_double_reading",
                          "table": ["mars", 5], "other": ["mars", 6],
                      },
                      {
                          "sign": "pisces", "line": 5, "witness": "proclus_paraphrase_double_reading",
                          "table": ["saturn", 5], "other": ["saturn", 4],
                      },
                  ],
                  relation_to_lilly_1647=("Lilly's p.104 Termes rows are this table with Proclus's other "
                                          "readings in Libra, Scorpio, Capricorn and Pisces; in Taurus "
                                          "Lilly has Saturn 4 (Proclus's other reading) and Mars 4, and in "
                                          "Leo Venus at line 3 (Proclus's other reading) in an otherwise "
                                          "different order; Cancer follows this table; Gemini differs "
                                          "where the apparatus records no variant"))
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
                "reading": "original_language_read",
                "read_at": f"{_LILLY_SCAN_P104} and the 1659 edition, p.104",
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
DECAN_READING_STATES = ("transmitted_text", "editorial_correction")

DECAN_SOURCE_DETAILS: dict[str, dict[str, Any]] = {
    "chaldean_planetary_faces_firmicus_ii_4_v1": {
        "complete_table_anchor": (
            "Firmicus Maternus, Mathesis II.4.3 (complete 36-face table; "
            "Kroll-Skutsch ed. 1897, vol. I p.45; chapter II.4 pp.44-46)"
        ),
        # Paulus and Firmicus may share a source: parallel, not independent.
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
        # All 36 faces re-read against II.4.3 in the archive.org OCR text of
        # Kroll-Skutsch 1897 vol. I (p.45); the page image was not viewed.
        "citation_verification": _ONLINE_TRANSCRIPTION_CHECKED,
        "citation_verification_evidence": (
            "Kroll-Skutsch 1897 vol. I p.45, II.4.3, every face, read in the "
            "archive.org OCR text of matheseoslibrivi01firmuoft"
        ),
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
                "reading": "original_language_read",
                "read_at": (
                    "Latin text, The Latin Library (manilius4.html), IV.310-362; "
                    "Housman 1920 p.43 and p.vi in the archive.org OCR text of "
                    "astronomiconrece04maniuoft; the scanned pages were not viewed"
                ),
            }
        ],
        # All 36 assignments re-read against the Latin of IV.312-362 in The
        # Latin Library; the cited printed editions were not opened.
        "citation_verification": _ONLINE_TRANSCRIPTION_CHECKED,
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
        "Schmidt's translation (Project Hindsight, 1994) p.30 not checked)"
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
    # Naibod is Lilly's attribution, never this profile's anchor; 'Ptolomy' follows
    # the page (pp.104-105).
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
            "Carmen Astrologicum I.1 (Pingree 1976 pp.161-162); use of the rulers I.4 "
            "(pp.163-164)"
        ),
        "third_ruler_term": "third_and_common_ruler",
        "third_ruler_term_source": (
            "Holden's Rhetorius per research report, not checked; Pingree has "
            "'then' (I.1), 'associate' (I.28), 'participant' (I.10)"
        ),
        "corroboration": cited(
            ("Vettius Valens, Anthologies II.1 (Kroll and Pingree II.1; Pingree "
             "pp.54-55 by Riley's /P/ markers)"),
            ("the same four triads by day and by night as Dorotheus, the third "
             "planet working with both sects"),
            "translation_read",
            ("Riley's translation, the PDF of his preliminary edition "
             "(Vettius_Valens_Riley.pdf), printed p.25 (PDF page 27)")),
        "cross_check_pending": ("B. Dykes, Carmen Astrologicum: The ʿUmar al-Ṭabarī "
                                "Translation, 2nd ed. (Cazimi Press, 2019) (not compared)"),
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
        # The table itself (I.1 pp.161-162), the use of the rulers (I.4
        # pp.163-164) and I.28 p.196, each with its reading in the register
        # entry's sources; the other fields say which citations are not checked.
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
        "location": "III.4 (Pingree 1986 numbering; Riley, CSUS PDF (2010) printed p.61)",
        "role": (
            "also_attested_exaltation_signs_source_also_supplies_"
            "exact_degrees_not_evaluated_by_this_profile"
        ),
    },
    {
        "work": "Firmicus Maternus, Mathesis",
        "location": "II.2 and II.3.5-6 (Kroll–Skutsch 1897, vol. I)",
        "role": (
            "also_attested_domiciles_and_exaltation_signs_source_"
            "also_supplies_exact_degrees_not_evaluated_by_this_profile"
        ),
    },
]
# Detriment and fall, each with its own witnesses: Ptolemy has the fall (his
# "depression") but no detriment, so the detriment cannot borrow his citation.
_ROBBINS_READ_AT = "Robbins translation (Loeb 1940), LacusCurtius"
_WRIGHT_READ_AT = "R. Ramsay Wright's translation (1934), archive.org OCR text"
_LILLY_READ_AT = "the scanned first edition, archive.org/details/b30338724 (leaves n137-n138)"
DEBILITY_COMPONENT_SOURCES = {
    "detriment": [
        cited("al-Bīrūnī, Kitāb al-tafhīm §442",
              ("wabāl: the signs opposite the domiciles of the planets are their "
               "detriments or debilities; the per-planet figure was not read"),
              "translation_read", _WRIGHT_READ_AT),
        cited(("William Lilly, Christian Astrology (1647) p.104 table, Detriment "
               "column; p.105"),
              ("one planet per sign; Venus in Aries 'is in a Signe opposite to one "
               "of her owne Houses, and so is said to be in her Detriment'"),
              "original_language_read", _LILLY_READ_AT),
        cited("Ptolemy, Tetrabiblos I.17 'Of the Houses' (Robbins pp.79-83; = Hübner 1998 I.18)",
              ("assigns the domiciles; names no detriment, nor does I.19, which "
               "gives exaltations and depressions"),
              "translation_read", _ROBBINS_READ_AT),
    ],
    "fall": [
        cited("Ptolemy, Tetrabiblos I.19 'Of Exaltations' (Robbins pp.89-91; = Hübner 1998 I.20)",
              ("each planet's depression is the sign diametrically opposite its "
               "exaltation; signs only, no degrees"),
              "translation_read", _ROBBINS_READ_AT),
        cited("Dorotheus of Sidon, Carmen Astrologicum I.2 (Pingree 1976 p.162)",
              "exaltation degrees; the descent is opposite the ascent", "translation_read",
              (f"{DOROTHEUS_BOOK_I_ONLINE}: I.2 on p.162, 'The descent of each one "
               "of them is opposite to its ascent'; the Arabic not checked")),
        cited("Vettius Valens, Anthologies III.4",
              ("each star has its depression at the point in opposition to its "
               "exaltation, with a table of degrees"),
              "translation_read",
              ("Riley's translation in a reformatted online copy (github "
               "janegca/latex-valens)")),
        cited("Firmicus Maternus, Mathesis II.3.1, II.3.5 (Kroll-Skutsch)",
              ("altitudines et deiectiones: each planet 'deicitur' in the degree "
               "opposite its exaltation"),
              "original_language_read", "Latin text, LacusCurtius"),
        cited("al-Bīrūnī, Kitāb al-tafhīm §443",
              ("hubūṭ: the signs and degrees opposite the exaltations are places of "
               "fall; three opinions on an exaltation's extent, one of them the "
               "whole sign"),
              "translation_read", _WRIGHT_READ_AT),
        cited(("William Lilly, Christian Astrology (1647) p.104 table, Fall column; "
               "p.105"),
              ("one planet per sign, by sign only; Saturn in Aries 'is opposite to "
               "Libra his Exaltation, and so is Infortunate'"),
              "original_language_read", _LILLY_READ_AT),
    ],
}
DEBILITY_PARTICIPANT_NOTE = (
    "Lilly's p.104 table also gives a fall to the Dragon's Head (Sagittarius) and "
    "Tail (Gemini), and al-Bīrūnī §443 exaltations for them; this profile covers "
    "the seven planets only."
)
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

# Peregrine: none of the five essential dignities, judged on one fixed set of
# tables (Lilly's own p.104 table), never on the profiles the request selected:
# the definition is Lilly's, and a mixture of tables is no author's.
PEREGRINE_PROFILE_ID = "lilly_1647_p112_v1"
PEREGRINE_SOURCE_REF = f"dignities/peregrine_{PEREGRINE_PROFILE_ID}"
PEREGRINE_SOURCE = (
    "William Lilly, Christian Astrology (1647) p.112, with pp.102-104"
)
# Lilly's p.104 column order; the closed set of dignities_held.
PEREGRINE_DIGNITIES = ("domicile", "exaltation", "triplicity", "term", "face")
# undetermined_*: the sect ruler of the triplicity alone decides, and the sect
# is unknown (date only) or the Sun is inside the near-horizon band.
PEREGRINE_STATUSES = (
    "peregrine",
    "not_peregrine",
    "undetermined_sect_unknown",
    "undetermined_sect_near_horizon",
)
PEREGRINE_BASIS = {
    "domicile_exaltation": DOMICILE_EXALTATION_PROFILE_ID,
    "triplicity": "lilly_triplicity_compact_1647_v1",
    "triplicity_rule": "sect_ruler_only",
    "bounds": "lilly_received_bounds_1647_v1",
    "face_decan": "chaldean_planetary_faces_firmicus_ii_4_v1",
    "scope": "fixed_lilly_1647_set_not_the_selected_profiles",
}
PEREGRINE_BASIS_NOTE = (
    "The triplicity table used, lilly_triplicity_compact_1647_v1, is labelled "
    "research-only when it is chosen as a table to show beside the others; here "
    "it is used only because the definition is Lilly's and so is the table, and "
    "the judgment does not make that table a recommended triplicity scheme."
)
PEREGRINE_RULE = (
    "A planet is peregrine when, at its degree, it holds none of the five "
    "essential dignities: whole-sign domicile or exaltation, the triplicity of "
    "the chart's sect ruler only (Lilly p.102), a term in Lilly's p.104 table, "
    "or a face (the Chaldean order, which Lilly's p.104 face column prints). "
    "Peregrine and detriment or fall can hold together. Reception does not "
    "remove peregrination: Bonatti lists the two as separate impediments, and "
    "Māshāʾallāh writes 'peregrinus, non receptus'. Only Lilly states that the "
    "sect ruler alone counts; Bonatti and Gadbury do not say."
)
# Recomputed from these tables by tests/backend/test_peregrine.py: the seven
# planets at every whole-degree midpoint by day and by night, 5,040 positions.
PEREGRINE_TABLE_DEPENDENCE = (
    "Of 5,040 positions (7 planets x 360 whole-degree midpoints x day and night), "
    "Robbins's Ptolemaic bounds in place of Lilly's change the judgment at 161 "
    "(3.2%), the Egyptian bounds at 463 (9.2%); the three Dorothean triplicity "
    "rulers in place of the sect ruler at 747 (14.8%); Egyptian bounds with the "
    "three rulers at 1,049 (20.8%)."
)
PEREGRINE_TERM_NOTE = (
    "The term is Arabic-Latin (al-Bīrūnī's gharīb, Latin peregrinus). The "
    "Hellenistic texts read describe a planet 'in alien signs and degrees' "
    "(Valens II.22 Kroll = II.23.24 Pingree) without defining it as a state."
)
_LILLY_SCAN = "the scanned first edition, archive.org/details/b30338724"
_BONATTI_SCAN = "the scanned Basel 1550 printing, archive.org/details/bub_gb_BgWuc5O-JzIC"
PEREGRINE_SOURCES = [
    cited("William Lilly, Christian Astrology (1647) p.112 'Peregrine'",
          ("a planet is peregrine 'in the degrees of any Signe wherein he hath no "
           "essentiall dignity'; Saturn in Aries 10° is peregrine, in 27° or 28° "
           "he is in his own term; the Sun in any part of Cancer is peregrine"),
          "original_language_read", f"{_LILLY_SCAN} (leaf n145)"),
    cited("William Lilly, Christian Astrology (1647) p.103",
          "a planet in its own face 'cannot then be called peregrine'", "original_language_read",
          f"{_LILLY_SCAN} (leaf n136)"),
    cited("William Lilly, Christian Astrology (1647) p.102",
          ("the Sun in Aries by night has his exaltation but no triplicity, "
           "which by night is Jupiter's; 'this doe generally in all the "
           "Planets, Mars excepted'"),
          "original_language_read", f"{_LILLY_SCAN} (leaf n135)"),
    cited("William Lilly, Christian Astrology (1647) p.104 table",
          ("the houses, exaltations, triplicities by day and night, terms and "
           "faces this judgment uses"),
          "original_language_read", f"{_LILLY_SCAN} (leaf n137)"),
    cited("William Lilly, Christian Astrology (1647) p.115 table",
          "Peregrine listed among the Debilities; its score is not used", "original_language_read",
          f"{_LILLY_SCAN} (leaf n148)"),
    cited("Guido Bonatti, De astronomia (Basel 1550) col.165",
          ("the eighth of ten impediments: 'ut sit peregrinus, hoc est, ut sit in "
           "loco in quo non habeat aliquam dignitatem'; not being received is "
           "listed as other impediments (the seventh and tenth)"),
          "original_language_read", f"{_BONATTI_SCAN} (leaf n100)"),
    cited("Guido Bonatti, De astronomia (Basel 1550) col.178",
          ("the 40th and 44th considerations: domicile, exaltation, triplicity, "
           "term and face are the dignities; 'facies non est tantae uirtutis'; a "
           "malefic in triplicity or face restrains its malice less"),
          "original_language_read", f"{_BONATTI_SCAN} (leaf n105)"),
    cited("Guido Bonatti, De astronomia (Basel 1550) col.181",
          ("the 55th consideration: one whose significator is peregrine will be "
           "'callidus, astutus, malitiosus', more inclined to evil than to good"),
          "original_language_read", f"{_BONATTI_SCAN} (leaf n106)"),
    cited("John Gadbury, The Doctrine of Nativities (London 1658) p.44",
          ("'Pergerine, or a Stranger, when he is out of all his essential "
           "Dignities, viz. his House, Exaltation, Triplicity, Term and Face'"),
          "original_language_read",
          ("the scanned 1658 edition, archive.org/details/the-doctrine-of-"
           "nativities-and-horary-questions-by-john-gadbury (leaf n32)")),
    cited("al-Bīrūnī, Kitāb al-tafhīm §493-494",
          ("a planet without dignity is a stranger (gharīb); in detriment or fall "
           "calamity is added; §494 ranks domicile, exaltation, term, triplicity "
           "and face"),
          "translation_read", "R. Ramsay Wright's translation (1934), archive.org OCR text"),
    cited("Māshāʾallāh, De cogitatione", "Saturn in Leo 'peregrinus, non receptus'",
          "translation_read",
          ("the Latin translation in Heller's edition (Nuremberg 1549), Warburg "
           "Institute scan fah765mesahw.pdf, PDF page 94 (sig. L iii r): 'qui erat in "
           "Leone peregrinus, no[n] receptus'; first found through Houlding, 'The "
           "Definition of Peregrine' (STA 2010); the Arabic is lost")),
    cited("Vettius Valens, Anthologies II.22 Kroll (= II.23.24 Pingree), Kroll 1908 p.89.30-32",
          ("malefics 'in alien signs and degrees' ruin livelihood; a description, "
           "not a defined state"),
          "translation_read",
          ("Riley's translation in a reformatted online copy (github janegca/latex-valens); "
           "the Kroll page and lines checked in the archive.org text of Kroll 1908 "
           "(bub_gb_OQ_gAAAAMAAJ); the Pingree page not checked online")),
]
