"""Read an auction's printed totals from OCR text, self-checked.

The summary page has its own checksum: average price = total value / quantity sold, and
arrivals = sold + withdrawn. Candidates for each figure are collected from every OCR pass by the
words on the line; the combination that satisfies the checksum (with most votes) is taken.
A report can hold several auctions (branches): each 'Advance Auction Report' page starts a new one.
"""
import glob, os, re
from collections import Counter
from itertools import product
from rows import num_tokens, variants

STRIP = "(){}[]:;*\"“”'_-—~=»«|₹/"
KEYS = {
    "sold": re.compile(r"sold", re.I),
    "value": re.compile(r"value|cost of cardamom", re.I),
    "avg": re.compile(r"aver", re.I),
    "max": re.compile(r"maxim", re.I),
    "min": re.compile(r"minim", re.I),
    "arrivals": re.compile(r"arrival", re.I),
    "withdrawn": re.compile(r"withdrawn|with drawn", re.I),
    "auction_no": re.compile(r"auction\s*(no|number)", re.I),
}
FORM_D = re.compile(r"advance\s+auction\s+report|form\s*-?\s*d\b|^\W*auction\s+report\W*$", re.I | re.M)
DATE = re.compile(r"(\d{1,2})\s*[-/.]\s*(\d{1,2}|[A-Za-z]{3})\s*[-/.]\s*(20\d\d)")
MON = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def nums(line):
    out = []
    for _, _, t in num_tokens(line):
        v = variants(t.strip(STRIP))
        if v and re.search(r"\d[.,]\d", t):
            out.append(v[0])
    return out


def page_texts(d):
    """{page: [text per OCR pass]}"""
    pages = {}
    for dd in d.split(","):
        for f in glob.glob(f"{dd}/p-*.txt"):
            pg = int(re.findall(r"\d+", os.path.basename(f))[0])
            pages.setdefault(pg, []).append(open(f, errors="ignore").read())
    return pages


def summary_pages(pages):
    """Pages that start an auction summary (most passes see the 'Advance Auction Report' heading)."""
    starts = []
    for pg in sorted(pages):
        hits = sum(1 for t in pages[pg] if FORM_D.search(t[:600]) and re.search(r"arrival", t, re.I))
        if hits >= max(1, len(pages[pg]) // 3):
            starts.append(pg)
    return starts or [min(pages)]


def read_summary(texts, extra_texts=()):
    """texts: OCR passes of one summary page (+ continuation). Returns dict or None."""
    cand = {k: Counter() for k in KEYS}
    dates = Counter()
    for t in list(texts) + list(extra_texts):
        lines = t.split("\n")
        for i, ln in enumerate(lines):
            for k, rx in KEYS.items():
                if not rx.search(ln):
                    continue
                ns = nums(ln) or (nums(lines[i + 1]) if i + 1 < len(lines) and k in ("max", "min") else [])
                if k == "auction_no":
                    m = re.search(r"(?:no|number)\W*(\d{1,3})\b", ln, re.I)
                    if m:
                        cand[k][int(m.group(1))] += 1
                    continue
                for x in ns:
                    cand[k][round(x, 2)] += 1
                if len(ns) == 2 and k in ("sold", "value", "arrivals", "withdrawn"):  # two state columns
                    cand[k][round(ns[0] + ns[1], 2)] += 1
            m = DATE.search(ln)
            if m and re.search(r"date", ln, re.I):
                mo = MON.get(m.group(2).lower()[:3]) if not m.group(2).isdigit() else int(m.group(2))
                if mo and 1 <= mo <= 12 and 1 <= int(m.group(1)) <= 31:
                    dates[f"{m.group(3)}-{mo:02d}-{int(m.group(1)):02d}"] += 1
    best = None
    S = [x for x in cand["sold"] if x >= 50]
    V = [x for x in cand["value"] if x >= 1e5]
    A = [x for x in cand["avg"] if 500 <= x <= 10000]
    for s, v, a in product(S, V, A):
        if abs(v / s - a) <= 0.011:
            score = cand["sold"][s] + cand["value"][v] + cand["avg"][a]
            if best is None or score > best[0]:
                best = (score, s, v, a)
    if not best:
        return None
    _, s, v, a = best
    out = dict(sold=s, value=v, avg=a, date=dates.most_common(1)[0][0] if dates else None,
               auction_no=cand["auction_no"].most_common(1)[0][0] if cand["auction_no"] else None)
    mx = [x for x, _ in cand["max"].most_common() if a <= x <= 10000 and abs(x - round(x)) < 0.011]
    mn = [x for x, _ in cand["min"].most_common() if 300 <= x <= a and abs(x - round(x)) < 0.011]
    out["max"] = mx[0] if mx else None
    out["min"] = mn[0] if mn else None
    # arrivals = sold + withdrawn
    pair = None
    for ar, cnt in cand["arrivals"].most_common():
        if ar < s - 0.05:
            continue
        w = round(ar - s, 2)
        sc = cnt + cand["withdrawn"].get(w, 0) * 2 + (1 if w == 0 else 0)
        if pair is None or sc > pair[0]:
            pair = (sc, ar, w)
    out["arrivals"], out["withdrawn"] = (pair[1], pair[2]) if pair else (None, None)
    return out


def read_report(d):
    pages = page_texts(d)
    starts = summary_pages(pages)
    allp = sorted(pages)
    res = []
    for i, pg in enumerate(starts):
        end = starts[i + 1] - 1 if i + 1 < len(starts) else allp[-1]
        nxt = pages.get(pg + 1, []) if pg + 1 <= end else []
        body = [t for p in allp if pg < p <= end for t in pages[p]]
        s = read_summary(pages[pg] + nxt) or read_summary(pages[pg] + nxt, body)
        if s:
            s.update(first_page=pg, last_page=end)
            res.append(s)
    return res


if __name__ == "__main__":
    import json, sys
    truth = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "truth_batch1.json")))
    dirs = sys.argv[1].split(",")
    ok = bad = 0
    for rid in sorted(k for k in truth if not k.startswith("_")):
        got = read_report(",".join(os.path.join(o, rid) for o in dirs))
        for i, t in enumerate(truth[rid]):
            g = got[i] if i < len(got) else {}
            diff = [k for k in ("sold", "value", "avg", "max", "min", "arrivals", "withdrawn", "date", "auction_no")
                    if g.get(k) != t.get(k) and not (isinstance(t.get(k), float) and g.get(k) is not None and abs(g[k] - t[k]) < 0.011)]
            ok += not diff; bad += bool(diff)
            print(f"{rid[:24]:24s} {'OK ' if not diff else 'DIFF'} {[(k, g.get(k), t.get(k)) for k in diff]}")
    print(ok, "match,", bad, "differ")
