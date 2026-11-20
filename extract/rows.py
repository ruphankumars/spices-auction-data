"""Generic lot-row extractor for OCR'd auction report lines.

Core idea: a sold lot row contains quantity q, rate r and value v with q*r == v.
OCR damages digits, decimal points and commas, so for each numeric token we try a
small set of plausible repairs and keep the (q, r, v) triple whose arithmetic holds.
That both finds the rows and verifies them.
"""
import re
from itertools import product

# characters OCR commonly substitutes for digits
DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "C": "0", "l": "1", "I": "1", "i": "1",
                           "S": "5", "s": "5", "$": "5", "§": "5",
                           "B": "8", "g": "9", "Z": "2", "z": "2", "?": "7"})
NUMLIKE = re.compile(r"[\d$§OoSIl|!BZ][\d$§OoSIl|!BZ,.'’ ]*[\d$§OoSIl|!BZ]|\d")


def _clean(tok):
    t = tok.translate(DIGIT_FIX).replace("'", "").replace("’", "").replace(" ", "")
    return t if re.fullmatch(r"[\d,.]+", t) and re.search(r"\d", t) else None


def variants(tok):
    """Plausible numeric readings of one OCR token, most likely first."""
    t = _clean(tok)
    if not t:
        return []
    out = []
    def add(s):
        try:
            x = float(s)
        except ValueError:
            return
        if x not in out:
            out.append(x)
    seps = [m.start() for m in re.finditer(r"[.,]", t)]
    digits = t.replace(",", "").replace(".", "")
    if seps:
        last = seps[-1]
        dec = len(t) - last - 1
        if dec in (1, 2, 3):  # last separator is the decimal point (may be OCR'd as comma)
            add(digits[: len(digits) - dec] + "." + digits[len(digits) - dec:])
        if dec in (3, 4):  # a table border read as an extra trailing digit
            d2 = digits[:-1]
            add(d2[: len(d2) - (dec - 1)] + "." + d2[len(d2) - (dec - 1):])
        add(digits)  # all separators were thousands commas
    else:
        add(digits)
        for d in (2, 3, 1):  # decimal point lost
            if len(digits) > d:
                add(digits[:-d] + "." + digits[-d:])
    return out


_FUSED = re.compile(r"(?<![\w.,])(\d{1,4}[.,]\d{3})(\d{4}[.,][\dOQC]{2})(\d{5,8}[.,][\dOQC]{1,2})?")


def _unfuse(line):
    """'444.6003123.001388485.80' -> '444.600 3123.00 1388485.80' (columns printed without gaps)."""
    line = re.sub(r"(\d{2,4}\.\d{3})(?=\d{2,4}\.\d{3}\b)", r"\1 ", line)  # qty qty
    def rep(m):
        return " ".join(g for g in m.groups() if g)
    line = _FUSED.sub(rep, line)
    return re.sub(r"(\d\.[\dOQC]{2})(?=\d{5,8}\.[\dOQC]{2})", r"\1 ", line)


def num_tokens(line):
    """(start, end, text) for every number-like run in the line."""
    toks = []
    line = re.sub(r"[|!/;:\]\[{}()'\"“”‘’`]", " ", line)
    line = _unfuse(line)
    for m in re.finditer(r"\S+", line):
        toks.append((m.start(), m.end(), m.group()))
    # merge "16 ,234.900" / "629. 400" style splits
    merged = []
    for s, e, t in toks:
        if merged and (t[:1] in ",." or merged[-1][2][-1:] in ",.") and _clean(merged[-1][2]) and _clean(t):
            ps, _, pt = merged[-1]
            merged[-1] = (ps, e, pt + t)
        else:
            merged.append((s, e, t))
    return [(s, e, t) for s, e, t in merged if _clean(t.strip("(){}[]:;*\"“”'_-—~=»«"))]


def find_triple(line, qmax=3000, rmin=1000, rmax=8000, tol=0.00002):
    """Return best (q, r, v, idx_q, idx_v, toks, repaired) on a line, or None."""
    toks = num_tokens(line)
    vals = [variants(t.strip("(){}[]:;*\"“”'_-—~=»«")) for _, _, t in toks]
    best = None
    n = len(toks)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, min(n, j + 3)):  # value is right after rate (maybe 1 gap)
                for (a, qa), (b, rb), (c, vc) in product(enumerate(vals[i]), enumerate(vals[j]), enumerate(vals[k])):
                    if not (0 < qa <= qmax and rmin <= rb <= rmax and vc >= 1000):
                        continue
                    if not re.search(r"\d[.,]\d", toks[i][2]) or qa < 5:
                        continue  # lot weights always carry decimals; bag counts and serials do not
                    if abs(qa * rb - vc) <= 0.6:  # exact to the paisa (allow rounding)
                        cost = a + b + c + (k - j - 1) + (j - i - 1) * 0.5
                        if best is None or cost < best[0]:
                            best = (cost, qa, rb, vc, i, j, k)
    if not best:
        # fallback: q and r read cleanly, value has 1-2 misread digits. q*r tells us what it must be.
        for i in range(n):
            for j in range(i + 1, n):
                for qa in vals[i][:2]:
                    for rb in vals[j][:1]:
                        if not (5 <= qa <= qmax and rmin <= rb <= rmax and re.search(r"\d[.,]\d", toks[i][2])):
                            continue
                        exp = f"{qa * rb:.2f}".replace(".", "")
                        for k in range(j + 1, min(n, j + 3)):
                            t = _clean(toks[k][2].strip("(){}[]:;*\"“”'_-—~=»«")) or ""
                            dg = t.replace(",", "").replace(".", "")
                            if len(dg) == len(exp) and len(exp) >= 6:
                                miss = sum(a != b for a, b in zip(dg, exp))
                                if miss <= 2:
                                    c = 3 + miss + (j - i - 1) * 0.5
                                    if best is None or c < best[0]:
                                        best = (c, qa, rb, round(qa * rb, 2), i, j, k)
    if not best:
        return None
    cost, q, r, v, i, j, k = best
    vp = (vals[k] or [v])[0]
    return dict(q=round(q, 3), r=round(r, 2), v=round(v, 2), vp=vp, toks=toks, i=i, j=j, k=k, repaired=cost > 0,
                derived=cost >= 3)


def find_qty_rate(line, qmax=3000, rmin=300, rmax=10000):
    """Lot-list rows without a value column (KCPMC/CPMCS): lot bags qty rate CODE grade ltr."""
    toks = num_tokens(line)
    vals = [variants(t.strip("(){}[]:;*\"“”'_-—~=»«")) for _, _, t in toks]
    for j in range(1, len(toks)):
        for rb in vals[j][:1]:
            if rmin <= rb <= rmax and "," in toks[j][2] or (rmin <= rb <= rmax and "." in toks[j][2]):
                for qa in vals[j - 1][:2]:
                    if 0 < qa <= qmax and "." in toks[j - 1][2].replace(",", "."):
                        return dict(q=round(qa, 3), r=round(rb, 2), toks=toks, j=j)
    return None


def find_pairs(line, rmin, rmax, qmax=3000):
    """(lot, qty, rate) groups from lot lists that print no value column (may repeat across a line)."""
    toks = num_tokens(line)
    out = []
    for j in range(1, len(toks)):
        tq, tr = toks[j - 1][2], toks[j][2]
        if not re.search(r"\d[.,]\d{2,3}$", tq.strip(" |")) or not re.search(r"[.,]\d{2}$", tr.strip(" |")):
            continue
        vq, vr = variants(tq), variants(tr)
        if not vq or not vr or not (0 < vq[0] <= qmax and rmin - 0.5 <= vr[0] <= rmax + 0.5):
            continue
        lot = None
        for b in range(j - 2, max(-1, j - 4), -1):
            t = toks[b][2].translate(DIGIT_FIX)
            if t.isdigit() and len(t) <= 4:
                lot = int(t)
        out.append(dict(lot=lot, q=round(vq[0], 3), r=round(vr[0], 2)))
    return out
