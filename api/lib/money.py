"""Money conversion helpers. Integer paise only — no float ever touches
an amount, in either direction.

A float can't hold 0.10 exactly, so `int(float("1234.10") * 100)` can
land on 123409. Everything here works on the digit strings instead, so
the conversion is exact by construction.
"""

import re

_CLEAN_RE = re.compile(r"[^\d.\-]")
_TRAILING_MARKER_RE = re.compile(r"\b(CR|DR)\b\s*$", re.IGNORECASE)
# Stripped before digit cleaning: the '.' in "Rs." must not be mistaken
# for a decimal point.
_CURRENCY_RE = re.compile(r"(?:₹|\bRs\.?|\bINR\b)", re.IGNORECASE)


def _indian_group(digits: str) -> str:
    """Group digits the Indian way: last 3, then pairs. 12345678 -> 1,23,45,678."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def paise_to_rupee_string(paise: int, *, symbol: str = "") -> str:
    """123456789 -> '12,34,567.89'. Sign is dropped; callers put the value
    in a debit or credit column instead."""
    if not isinstance(paise, int):
        raise TypeError(f"paise must be int, got {type(paise).__name__}")
    value = abs(paise)
    rupees, sub = divmod(value, 100)
    return f"{symbol}{_indian_group(str(rupees))}.{sub:02d}"


def rupee_string_to_paise(text: str) -> int:
    """'₹ 12,34,567.89' / '12,34,567.89 CR' / '(1,234.50)' -> integer paise.

    Handles currency symbols, thousands separators, whitespace, a
    trailing CR/DR marker, and accounting-style parenthesised negatives.
    Never constructs a float.
    """
    if text is None:
        raise ValueError("empty amount")
    s = str(text).strip()
    if not s:
        raise ValueError("empty amount")

    negative = False

    s = _CURRENCY_RE.sub(" ", s).strip()

    # Accounting style: (1,234.50) means negative.
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()

    marker = _TRAILING_MARKER_RE.search(s)
    if marker:
        if marker.group(1).upper() == "DR":
            negative = True
        s = _TRAILING_MARKER_RE.sub("", s).strip()

    s = _CLEAN_RE.sub("", s)

    if s.startswith("-"):
        negative = True
        s = s[1:]
    s = s.replace("-", "")

    if not s or s == ".":
        raise ValueError(f"no digits in amount: {text!r}")

    if "." in s:
        whole, _, frac = s.partition(".")
        frac = frac.replace(".", "")
    else:
        whole, frac = s, ""

    whole = whole or "0"
    frac = (frac + "00")[:2]

    paise = int(whole) * 100 + int(frac)
    return -paise if negative else paise
