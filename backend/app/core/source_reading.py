"""How far a cited source was read: one closed set for the published register.

Every citation in the method source register that says how far it was read
carries one of these, strongest first.  `original_language_read` is the text
in the language its author wrote it in, read at the cited place.
`translation_read` is a translation read in full at the cited place; any
translation is `translation_read`, including a medieval Latin translation of an
Arabic work (Hermann of Carinthia's Abū Maʿshar, John of Seville's al-Qabīṣī),
however old the translation is; `secondary_only` is what a named secondary work
reports, the cited text itself unread; `bibliographic_only` is the reference
alone (title, chapter or page) checked, its content unread.
"""

from __future__ import annotations

import re
from typing import Final

# Words that say a translation was what was read: in the read_at any mention
# of a translation; in the citation only the forms that name the translation
# cited ("trans. Robbins", "Latin of Hermann"), since a citation may mention
# another translation's numbering beside an original it cites.  An entry
# carrying them is not `original_language_read`; the register refuses the pair.
TRANSLATION_MARKERS_READ_AT: Final = re.compile(r"(?i)\btranslat|\btrans\.|\btr\.")
TRANSLATION_MARKERS_CITATION: Final = re.compile(
    r"(?i)\btrans\.|\btr\.|\btranslated by\b|\bLatin of\b"
)

SOURCE_READING_LEVELS: Final = (
    "original_language_read",
    "translation_read",
    "secondary_only",
    "bibliographic_only",
)

# A locus the method research notes name, carried as a citation object while
# the record does not say what was read: only the reference is claimed.
LEVEL_PENDING_RESEARCH_NOTES: Final = (
    "level pending: a passage named by the method research notes and not "
    "independently verified; the record does not say what was read, so only the "
    "reference is claimed until that is confirmed"
)


def reference_only(citation: str, says: str, read_at: str = LEVEL_PENDING_RESEARCH_NOTES) -> dict:
    """A citation object claiming the reference alone (`bibliographic_only`)."""
    return {
        "citation": citation,
        "says": says,
        "reading": SOURCE_READING_LEVELS[3],
        "read_at": read_at,
    }
