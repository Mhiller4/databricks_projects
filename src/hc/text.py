"""Text normalisation shared by the cleaner, facility_master, the external sources and tests.

Scraped text arrives with junk that breaks dashboards and speech:
  * escape sequences stored as text: a backslash followed by n / r / t ("Cardiology\\nUrology")
  * real control characters (line breaks, tabs) and invisible ones (non-breaking / zero-width space, BOM)
  * HTML entities (&amp; &quot; &#39; &nbsp;)
clean_text() (Spark) and clean_text_py() (Python) turn all of them into single spaces and trim. The
lookbehind leaves an escaped backslash alone so JSON text stays parseable. Spark is imported lazily so
this module works without pyspark.
"""

from __future__ import annotations

import re

ESCAPED_WS = r"(?<!\\)\\[nrt]"
CONTROL_CHARS = r"[\x00-\x1F\x7F\x{00A0}\x{200B}-\x{200D}\x{FEFF}]"
LIST_SPLIT = r",|;|\||(?<!\\)\\[nrt]|[\r\n\t]+"  # separators inside free-text list fields
HTML_ENTITIES = (("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"), ("&#039;", "'"), ("&nbsp;", " "), ("&lt;", "<"), ("&gt;", ">"))


def clean_text(col):
    """Spark Column -> Column: escapes, control/invisible chars and HTML entities -> single spaces, trimmed."""
    from pyspark.sql import functions as F

    c = col.cast("string")
    for a, b in HTML_ENTITIES:
        c = F.regexp_replace(c, a, b)
    c = F.regexp_replace(c, ESCAPED_WS, " ")
    c = F.regexp_replace(c, CONTROL_CHARS, " ")
    c = F.regexp_replace(c, r" {2,}", " ")
    return F.trim(c)


def clean_text_py(v: str | None) -> str | None:
    """Python twin of clean_text()."""
    if v is None:
        return None
    for a, b in HTML_ENTITIES:
        v = v.replace(a, b)
    v = re.sub(r"(?<!\\)\\[nrt]", " ", v)
    v = re.sub("[\x00-\x1f\x7f\u00a0\u200b-\u200d\ufeff]", " ", v)
    return re.sub(r" {2,}", " ", v).strip()


def split_list_py(v: str | None) -> list[str]:
    """Python twin of the Spark list split: 'A, B\\nC; D' -> ['A', 'B', 'C', 'D']."""
    if not v:
        return []
    parts = re.split(r",|;|\||(?<!\\)\\[nrt]|[\r\n\t]+", v)
    return [x for x in (clean_text_py(p) for p in parts) if x and len(x) > 1]
