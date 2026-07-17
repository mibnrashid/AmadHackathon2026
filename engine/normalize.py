"""Layer 1 building block: normalize(raw) -> a canonical, matchable string.

Strips corruption noise (prefixes, ref ids, city codes, symbols) then applies
Arabic normalization (CLAUDE.md rule 2): unify alef, unify ya, strip tashkeel +
tatweel, convert Arabic-Indic digits to ASCII. Without this step Arabic fuzzy
matching silently fails.
"""

import re

ALEF_VARIANTS = "أإآ"
TASHKEEL_RE = re.compile(r"[ً-ْ]")
TATWEEL = "ـ"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
ARABIC_DIGIT_MAP = {d: str(i) for i, d in enumerate(ARABIC_DIGITS)}

# Known noise prefixes (CLAUDE.md / DATA_SPEC corruption operators), including
# aggregator-app wraps ("JAHEZ*<merchant>") -- the true merchant is what's
# wrapped, not the app, so the app token is noise to strip just like POS/SP*.
PREFIX_RE = re.compile(
    r"^(POS\s+|SP\s*\*\s*|MADA\s+|APPLEPAY\s*\*\s*|"
    r"JAHEZ\s*\*\s*|HUNGERSTATION\s*\*\s*|TOYOU\s*\*\s*|MRSOOL\s*\*\s*)",
    re.IGNORECASE,
)
CITY_SUFFIX_RE = re.compile(r"\s+(RYD|JED|DMM|SA)$", re.IGNORECASE)
ID_SUFFIX_RE = re.compile(r"([_#]\d+|\s\d{3,6})$")
NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+")


def normalize_arabic_digits(s: str) -> str:
    return "".join(ARABIC_DIGIT_MAP.get(ch, ch) for ch in s)


def normalize_arabic_text(s: str) -> str:
    for a in ALEF_VARIANTS:
        s = s.replace(a, "ا")
    s = s.replace("ى", "ي")
    s = TASHKEEL_RE.sub("", s)
    s = s.replace(TATWEEL, "")
    return s


def normalize(raw: str) -> str:
    s = (raw or "").strip()
    s = normalize_arabic_digits(s)

    while True:
        stripped = PREFIX_RE.sub("", s).strip()
        if stripped == s:
            break
        s = stripped

    while True:
        stripped = CITY_SUFFIX_RE.sub("", s)
        stripped = ID_SUFFIX_RE.sub("", stripped).strip()
        if stripped == s:
            break
        s = stripped

    s = normalize_arabic_text(s)
    s = re.sub(r"[_\-]+", " ", s)
    s = NON_WORD_RE.sub(" ", s)
    s = WHITESPACE_RE.sub(" ", s).strip()
    s = s.casefold()
    return s
