"""Invoice cover: rebuild "which lots did each buyer take" from the Buyers Statement alone.

The Buyers Statement prints, per invoice, a buyer, total kilos and total rupees. Every sold lot belongs
to exactly one invoice, so the lots must split into groups whose kilos AND rupees equal each invoice
to the paisa. Solving that puzzle (an exact cover) gives, with no further reading of the page:
  - the buyer of every lot, including lots whose statement page is missing from the PDF,
  - which lots were withdrawn (the ones left over),
  - an independent check of every lot's weight and price.
"""
import glob, os, re
from rows import num_tokens, variants

STMT = re.compile(r"(BUYERS?|BIDDERS?)\W{0,3}\s*STATEMENT", re.I)
DECTOK = re.compile(r"\d[.,]\d{2,3}$")


def _name(prefix):
    p = re.sub(r"\b\d{2}[A-Z0-9]{8,}\b.*$", "", prefix)           # cut at GSTIN
    p = re.split(r"\s(?:C\.?S\.?/|CS/|SBL)", " " + p)[0]
    words = [w for w in re.sub(r"[^A-Za-z&. ]", " ", p).split() if len(w) > 1 or w == "&"]
    for stop in ("KERALA", "BODINAYAKANUR", "IDUKKI", "THEVARAM", "CUMBUM", "KUMILY"):
        if len(words) > 1 and words[-1].upper() == stop:
            words.pop()
    return " ".join(words).upper().strip(" .")


def parse_invoices(d, lo, hi, sold, value, rmin, rmax, partial=False):
    """Invoices [(buyer, kg, rupees)] from the first OCR pass whose list adds up to the printed totals."""
    best = None
    for dd in d.split(","):
        inv, seen = [], set()
        for f in sorted(glob.glob(f"{dd}/p-*.txt")):
            pg = int(re.findall(r"\d+", os.path.basename(f))[0])
            t = open(f, errors="ignore").read()
            if not (lo <= pg <= hi) or not STMT.search(t):
                continue
            for ln in t.split("\n"):
                if re.search(r"\btotal\b|tota[l!]|\bstate\b|\bsales\b", ln, re.I):
                    continue
                toks = [x for x in num_tokens(ln) if DECTOK.search(x[2].strip(" |"))]
                if len(toks) < 2:
                    continue
                kg = variants(toks[-2][2].strip(" |")); amt = variants(toks[-1][2].strip(" |"))
                if not kg or not amt or kg[0] <= 0 or not (rmin - 1 <= amt[0] / kg[0] <= rmax + 1):
                    continue
                key = (round(kg[0], 2), round(amt[0], 2))
                if key in seen:
                    continue  # a statement page scanned twice
                seen.add(key)
                inv.append((_name(ln[: toks[-2][0]]), key[0], key[1]))
        if inv and abs(sum(i[1] for i in inv) - sold) < 0.05 and abs(sum(i[2] for i in inv) - value) < 1.0:
            return inv
        if inv and (best is None or abs(sum(i[1] for i in inv) - sold) < abs(sum(i[1] for i in best) - sold)):
            best = inv
    return ("partial", best) if partial else None


def _subsets(items, tq, tv, cap=1_200_000, want=2):
    """All subsets (up to `want`) of items [(id, grams, rupees)] hitting both targets. None if too big."""
    half = len(items) // 2

    def sums(part, off):
        out = [(0, 0.0, 0)]
        for i, (_, g, v) in enumerate(part):
            bit = 1 << (i + off)
            out += [(q + g, vv + v, m | bit) for q, vv, m in out if q + g <= tq + 5]
            if len(out) > cap:
                raise OverflowError
        return out
    try:
        A, B = sums(items[:half], 0), sums(items[half:], half)
    except OverflowError:
        return None
    idx = {}
    for q, v, m in A:
        idx.setdefault(q, []).append((v, m))
    sols = []
    for q, v, m in B:
        for dq in (-1, 0, 1):
            for va, ma in idx.get(tq - q + dq, ()):
                if abs(va + v - tv) <= 0.06:
                    sols.append(m | ma)
                    if len(sols) >= want:
                        return sols
    return sols


def cover(lots, invoices):
    """lots: {lot: (kg, rate)}; invoices: [(buyer, kg, rupees)].
    Returns ({lot: invoice index}, unsolved invoice indexes)."""
    pool = {k: (int(round(q * 1000)), round(q * r, 2)) for k, (q, r) in lots.items()}
    assign, todo = {}, set(range(len(invoices)))
    progress = True
    while todo and progress:
        progress = False
        for i in sorted(todo, key=lambda j: invoices[j][1]):
            _, kg, amt = invoices[i]
            items = [(k, g, v) for k, (g, v) in sorted(pool.items())]
            sols = _subsets(items, int(round(kg * 1000)), amt)
            if sols is None or len(sols) != 1:
                continue  # too big for now, impossible, or ambiguous: retry when the pool is smaller
            for j, (k, _, _) in enumerate(items):
                if sols[0] >> j & 1:
                    assign[k] = i; del pool[k]
            todo.discard(i); progress = True
    return assign, sorted(todo)
