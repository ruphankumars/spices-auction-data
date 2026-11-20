"""Checksum decoding of lot rows.

A lot row is a codeword with two free numbers (quantity q, rate r). Everything else printed on the
row is a function of them: value = q*r, sample refund = a*r, commission = b*(value + a*r), GST = c*commission ...
The constants differ per auctioneer, so they are MINED from rows that already verify, then used to
decode rows where OCR damaged one or two numbers: any (q, r) hypothesis is accepted only when enough
independent printed numbers on the row agree with it.
"""
import math
import re
from collections import Counter
from rows import num_tokens, variants, find_triple

STRIP = "(){}[]:;*\"“”'_-—~=»«|"
TOL = 0.06


def line_values(line, k=3):
    """[(token_text, [numeric variants])] for every number-like token."""
    out = []
    for _, _, t in num_tokens(line):
        t = t.strip(STRIP)
        v = variants(t)[:k]
        if v:
            out.append((t, v))
    return out


def _modes(pairs, n_rows, share=0.15, rel=2.5e-4):
    """Dense clusters of ratio values. pairs = [(ratio, scale)] where scale turns a ratio error into rupees.
    Returns [(constant, tolerance_in_rupees)]."""
    vals = sorted(pairs)
    out, used, need = [], [False] * len(vals), max(8, share * n_rows)
    for _ in range(4):
        best, j = (0, 0, 0), 0
        for i in range(len(vals)):
            if used[i]:
                continue
            while vals[i][0] - vals[j][0] > rel * vals[i][0] or used[j]:
                j += 1
            cnt = sum(1 for k in range(j, i + 1) if not used[k])
            if cnt > best[0]:
                best = (cnt, j, i)
        cnt, j, i = best
        if cnt < need:
            break
        grp = [vals[k] for k in range(j, i + 1) if not used[k]]
        const = grp[len(grp) // 2][0]
        res = sorted(abs(r - const) * sc for r, sc in grp)
        p90 = res[int(0.9 * (len(res) - 1))]
        tol = 0.06 if p90 <= 0.06 else (0.51 if p90 <= 0.51 else None)
        for k in range(j, i + 1):
            used[k] = True
        if tol:
            out.append((const, tol))
    return out


def mine(lines):
    """Find the row formulas of one report from its already-verified rows."""
    ver = []
    for ln in lines:
        t = find_triple(ln)
        if t and not t["derived"]:
            ver.append((t["q"], t["r"], t["v"], [v[0] for _, v in line_values(ln)]))
    n = len(ver)
    inv = dict(alpha=[], beta=[], combo=[], n=n)
    if n < 8:
        return inv
    skip = lambda x, q, r, v: x <= 0 or abs(x - q) < 0.01 or abs(x - r) < 0.01 or abs(x - v) < 0.6
    al = [(x / r, r) for q, r, v, xs in ver for x in set(xs) if not skip(x, q, r, v) and 0.5 < x / r < 12]
    inv["alpha"] = _modes(al, n)
    be = [(x / v, v) for q, r, v, xs in ver for x in set(xs) if not skip(x, q, r, v) and 0.001 < x / v < 0.9]
    inv["beta"] = _modes(be, n)
    for a, _ in inv["alpha"] or [(2.85, 0.06)]:
        co = [(x / (v + a * r), v + a * r) for q, r, v, xs in ver for x in set(xs)
              if not skip(x, q, r, v) and 0.001 < x / (v + a * r) < 0.9]
        for b, tol in _modes(co, n):
            if not any(abs(b - b0) < 3e-4 * b0 for b0, _ in inv["beta"]):
                inv["combo"].append((a, b, tol))
    return inv


def predictions(q, r, inv):
    v = q * r
    p = {"q": (q, 0.0006), "r": (r, 0.011), "v": (v, 0.6)}
    for i, (a, tol) in enumerate(inv["alpha"]):
        p[f"a{i}"] = (a * r, tol)
    for i, (b, tol) in enumerate(inv["beta"]):
        p[f"b{i}"] = (b * v, tol)
    for i, (a, b, tol) in enumerate(inv["combo"]):
        p[f"c{i}"] = (b * (v + a * r), tol)
    return p


def decode(line, inv, rmin, rmax, qmax=3000):
    """Best (q, r) for a row, with the number of printed numbers that confirm it."""
    toks = line_values(line)
    if len(toks) < 3:
        return None
    allv = [(i, x) for i, (_, vs) in enumerate(toks) for x in vs if x > 0]
    rank = {(i, x): k for i, (_, vs) in enumerate(toks) for k, x in enumerate(vs)}
    # amounts and weights carry decimals; short integers are lot numbers, bag counts, litre weights
    amt = [bool(re.search(r"\d[.,]\d", t)) or len(re.sub(r"\D", "", t)) >= 5 for t, _ in toks]
    amt = [bool(re.search(r"\d[.,]\d", t)) or len(re.sub(r"\D", "", t)) >= 5 for t, _ in toks]
    R = set()
    for i, x in allv:
        if rmin - 0.5 <= x <= rmax + 0.5 and re.search(r"\d[.,]\d", toks[i][0]):
            R.add(float(round(x)))  # paise of a rate are always .00, whatever a faint print reads
        for a, tol in inv["alpha"]:
            rr = x / a
            if rmin - 0.5 <= rr <= rmax + 0.5 and abs(rr - round(rr)) <= (0.03 if tol < 0.1 else 0.2):
                R.add(float(round(rr)))
    # a rate can also be recovered from the commission: commission = b * (q + a) * r, and from
    # commission together with value: a * r = commission / b - value
    big = [(i, x) for i, x in allv if amt[i]]
    qtok = {round(x, 3) for i, x in big if 5 <= x <= qmax and abs(x * 20 - round(x * 20)) < 1e-6
            and re.search(r"[.,]\d", toks[i][0])}
    for a, b, tol in inv["combo"]:
        for i, x in big:
            for q in qtok:
                rr = x / (b * (q + a))
                if rmin - 0.5 <= rr <= rmax + 0.5 and abs(rr - round(rr)) <= 0.035:
                    R.add(float(round(rr)))
            for j, y in big:
                if j != i and y > 20 * x:
                    rr = (x / b - y) / a
                    if rmin - 3 <= rr <= rmax + 3:
                        for cand in range(int(round(rr)) - 2, int(round(rr)) + 3):
                            if rmin - 0.5 <= cand <= rmax + 0.5 and abs(y / cand * 20 - round(y / cand * 20)) < 0.002:
                                R.add(float(cand))
    for i, x in big:  # value / quantity is a whole number of rupees
        for q in qtok:
            rr = x / q
            if rmin - 0.5 <= rr <= rmax + 0.5 and abs(rr - round(rr)) <= 0.002:
                R.add(float(round(rr)))
    best = None
    for r in R:
        Q = set()
        for i, x in allv:
            if 5 <= x <= qmax and re.search(r"[.,]\d", toks[i][0]) and abs(x * 20 - round(x * 20)) < 1e-6:
                Q.add(round(x, 3))  # lots are weighed to 0.1 kg (0.05 at most)
            cand_v = [x] + [x / b for b, _ in inv["beta"]] + [x / b - a * r for a, b, _ in inv["combo"]]
            for vv in cand_v:
                qq = vv / r
                if 5 <= qq <= qmax and abs(qq * 20 - round(qq * 20)) < 0.05:
                    Q.add(round(round(qq * 20) / 20, 3))
        for q in Q:
            pred = predictions(q, r, inv)
            hits, pen, weak_r = {}, {}, set()
            for i, x in allv:
                for k, (pv, tol) in pred.items():
                    if abs(x - pv) <= tol:
                        dg = re.sub(r"\D", "", toks[i][0])
                        if amt[i] or (k == "q" and len(dg) >= 3 and dg.rstrip("0") == ("%g" % pv).replace(".", "")
                                                     and len(dg) > len(("%g" % pv).replace(".", ""))):
                            hits.setdefault(k, set()).add(i)
                        elif k == "r":
                            weak_r.add(i); hits.setdefault(k, set()).add(i)
                        else:
                            continue
                        pen[i] = min(pen.get(i, 9), rank[(i, x)]); break
            # near misses: a printed number one digit away from what (q, r) predicts is weak evidence (half weight)
            used = set().union(*hits.values()) if hits else set()
            soft = {}
            for i, x in allv:
                if i in used or not amt[i] or rank[(i, x)] > 0:
                    continue
                for k, (pv, tol) in pred.items():
                    if k in soft or (k in hits and not (k == "q" and len(hits["q"]) == 1)):
                        continue
                    fmt = "%.3f" if k == "q" else "%.2f"
                    a_ = fmt % x
                    alts = {fmt % pv} if k in "qrv" else {fmt % pv, fmt % (math.floor(pv * 10) / 10), fmt % (math.ceil(pv * 10) / 10)}
                    if any(len(a_) == len(b_) and sum(c1 != c2 for c1, c2 in zip(a_, b_)) == 1 for b_ in alts):
                        soft[k] = i; used.add(i); break
            w = lambda k: 1.0 if k in hits else (0.5 if k in soft else 0.0)
            keys = set(hits) | set(soft)
            nq = min(2, len(hits["q"]) + (0.5 if "q" in soft else 0)) if "q" in hits else w("q")
            nr = w("r")
            if "r" in hits and hits["r"] <= weak_r:
                nr = 0.5  # rate printed without its paise
            if nr == 0 and "q" in hits and "v" in hits:
                nr = 0.5  # printed value / printed quantity came out a whole rupee rate
            na = sum(w(k) for k in keys if k[0] == "a")
            npr = sum(w(k) for k in keys if k[0] in "vbc")
            exact = len(hits)
            units = nq + nr + na + npr
            ok = bool(nq + npr >= 2 and nr + na + npr >= 2 and units >= 3 and (npr >= 1 or units >= 4)
                      and exact >= 2 and ("q" in hits or "r" in hits or exact >= 3
                                          or sum(1 for k in hits if k[0] in "vbc") >= 2))
            key = (ok, units, -sum(pen.values()), "v" in hits)
            if best is None or key > best[0]:
                best = (key, q, r, hits, units, sum(pen.values()))
    if not best or not best[0][0]:
        return None
    _, q, r, hits, n, pen = best
    return dict(q=q, r=r, v=round(q * r, 2), kinds=",".join(sorted(hits)), score=n, full={"q", "r", "v"} <= set(hits), pen=pen)
