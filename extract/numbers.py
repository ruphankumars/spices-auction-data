"""Number cleanup for OCR'd Indian-format figures (e.g. 4,73,51,795.00)."""
import re

# OCR confusions inside numbers
_FIX = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "l": "1", "I": "1", "|": "1",
                      "S": "5", "$": "5", "§": "5", "B": "8", "Z": "2", "'": "", "‘": ""})
NUM = re.compile(r"(?<![\w/])[\dOoQSl$§]?[\d,. ]*\d[\d]*(?:\.\d+)?(?![\w/-])")


def clean_token(tok, decimals=None):
    """Return float or None. decimals: expected decimal places (3 for kg, 2 for Rs)."""
    t = tok.strip().translate(_FIX)
    t = re.sub(r"(?<=\d)\s+(?=[\d,.])|(?<=[,.])\s+(?=\d)", "", t)  # '48 ,951' / '2,066. 100'
    t = t.strip(".,")
    if not re.fullmatch(r"[\d,.]+", t) or not re.search(r"\d", t):
        return None
    # comma typed for decimal point: 1,569,000 where kg expect 3 decimals
    if decimals and "." not in t and re.search(r",\d{%d}$" % decimals, t):
        t = t[: -decimals - 1] + "." + t[-decimals:]
    if t.count(".") > 1:  # '1.026.567.00' -> keep last as decimal
        head, _, dec = t.rpartition(".")
        t = head.replace(".", "") + "." + dec
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return None


def numbers_in(line, decimals=None):
    """All numeric values in a line, in order (skips licence-like tokens with '/')."""
    out = []
    line = re.sub(r"\[[^\]]*\]|\(\s*S\s*[l1I]?\.?\s*No[^)]*\)+|S\s*[l1I]\.?\s*No\.?\s*[\d()&and\s-]+", " ", line)
    for m in re.finditer(r"(?<![A-Za-z])[\dOQS$§][\d,.\s]*\d(?:\.\d+)?|\d", line):
        s = m.group(0)
        # split runs like '16,234.900 4,059.800' (space between two full numbers)
        for part in re.split(r"(?<=\.\d\d)\s+|(?<=\.\d\d\d)\s+", s):
            v = clean_token(part, decimals)
            if v is not None:
                out.append(v)
    return out
