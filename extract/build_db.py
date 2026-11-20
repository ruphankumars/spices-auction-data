"""Build the auction database from OCR text.

usage: python build_db.py <ocr_out_dir> <manifest.json> <truth.json> <db.sqlite>

Tables
  reports   one row per PDF (source link, checksum)
  auctions  one row per auction (a PDF can hold 2 branches); summary figures
  lots      one row per sold lot found and arithmetic-verified (qty x rate = value)
"""
import glob, json, math, os, re, sqlite3, sys
from rows import find_triple, find_pairs, num_tokens, variants
from decode import mine, decode
from invoice import parse_invoices, cover
from summary import read_report

STOP = re.compile(r"\b(CR|C\.R|SBL|GSTIN|CS|C\.S|PD|P|D|NIL|WD|WITH DRAWN)\b\.?", re.I)
JUNK_WORD = re.compile(r"^[A-Za-z&.,'-]{2,}$")


def alpha_words(s):
    s = re.sub(r"[|!;:\[\]{}()\"“”‘’`_~=»«*—–]+", " ", s)
    out = []
    for w in s.split():
        if JUNK_WORD.match(w) and not re.search(r"\d", w):
            out.append(w.strip(".,-"))
        elif out and re.search(r"\d", w) and len(out) >= 1:
            # a number after words ends the name
            break
    return [w for w in out if w]


def clean_name(words):
    # drop registration markers and stray single letters at the ends
    ws = [w for w in words if w.upper() not in {"CR", "SBL", "CS", "GSTIN", "WD"}]
    while ws and len(ws[-1]) <= 1:
        ws.pop()
    while ws and len(ws[0]) <= 1:
        ws.pop(0)
    name = " ".join(ws).upper()
    name = re.sub(r"\s+", " ", name).strip(" .,-")
    return name if len(name) >= 3 else ""


def seller_from_prefix(prefix):
    # prefix: "<sl/lot numbers> <grade?> SELLER NAME CR. <reg no>"
    p = re.split(r"\s(?:CR|C\.R|OR|QR|ER|€R)[\s.,]", " " + prefix + " ", maxsplit=1)[0]
    return clean_name(alpha_words(p))


def buyer_from_suffix(suffix):
    s = re.split(r"(?:SBL|S8L|5BL|\bC\.?\s?S[./]|€[S5$]|\(S/|\bCS\b)", suffix, maxsplit=1)[0]
    return clean_name(alpha_words(s))


def lot_from_prefix(prefix):
    toks = re.findall(r"[0-9OoSIl]{1,4}", prefix[:20])
    for t in toks[:2]:
        t2 = t.translate(str.maketrans("OoSIl", "00511"))
        if t2.isdigit():
            return int(t2)
    return None


LOTLINE = re.compile(r"^\W*(\d{1,4})\W+(\d{1,3})\W+([\d,]+\.\d{1,3})\W+([\d,]+\.\d\d)\W+([A-Z][A-Z0-9&.]{1,7})\b")


def page_files(d):
    fs = []
    for dd in d.split(","):  # several OCR passes of the same pages; verified rows are merged
        fs += glob.glob(f"{dd}/p-*.txt")
    return sorted(fs, key=lambda x: int(re.findall(r"\d+", os.path.basename(x))[0]))


LOTKEY = re.compile(r"\W{0,4}([0-9OoIl]{2,3})(?=\s)")
LOTFIX = str.maketrans("OoIl", "0011")
WDRAWN = re.compile(r"\bW\.?D\b|WITH\s?DRAWN|[HM]ITH DRAWN", re.I)
DEC = re.compile(r"\d[.,]\d{2,3}$")


def split_row(ln):
    """Text before the first and after the last decimal number of a row (names live there)."""
    toks = [t for t in num_tokens(ln) if DEC.search(t[2].strip(" |"))]
    if not toks:
        return ln, "", []
    return ln[: toks[0][0]], ln[toks[-1][1]:], toks


def extract_report(d, rmin=1000, rmax=8000):
    """Decode every OCR pass of a report and merge. Returns (rows, value-less candidates)."""
    lines, stmt = [], {}
    for f in page_files(d):
        pg = int(re.findall(r"\d+", os.path.basename(f))[0])
        txt = open(f, errors="ignore").read()
        st = stmt.setdefault(pg, [0, 0]); st[1] += 1
        if re.search(r"(BUYERS?|BIDDERS?)\W{0,3}\s*STATEMENT|TRADERS?\s+NAME", txt[:1500], re.I):
            st[0] += 1
        lines += [(pg, ln.rstrip("\n")) for ln in txt.split("\n")]
    # invoice pages (Buyers Statement) list totals per buyer, not lots
    lines = [(pg, ln) for pg, ln in lines if stmt[pg][0] * 2 < stmt[pg][1]]
    inv = mine([ln for _, ln in lines])
    rows, aux, pairs, wd = {}, {}, {}, set()
    # second round: a lot that no single reading decodes is decoded from all its readings pooled together
    groups, done = {}, set()
    for pg, ln in lines:
        m = LOTKEY.match(ln)
        if m and not WDRAWN.search(ln):
            groups.setdefault(int(m.group(1).translate(LOTFIX)), []).append((pg, ln))
    work = [(pg, ln, None) for pg, ln in lines]
    for pg, ln, gk in work:
        if WDRAWN.search(ln):  # withdrawn lot: it has a bid price but was not sold
            for pr in find_pairs(ln, rmin, rmax):
                wd.add((pr["q"], pr["r"]))
            continue
        d1 = decode(ln, inv, rmin, rmax)
        t = None if d1 else find_triple(ln, rmin=rmin - 1, rmax=rmax + 1)
        if d1 or t:
            if d1:
                q, r, v, score, full, pen = d1["q"], d1["r"], d1["v"], d1["score"], int(d1["full"]), d1["pen"]
            else:
                q, r, v, score, full, pen = t["q"], t["r"], t["v"], 2 if t["derived"] else 3, int(not t["derived"]), 2
            prefix, suffix, dtoks = split_row(ln)
            ql = None
            for _, _, tt in dtoks:
                pv = variants(tt.strip(" |"))
                if pv and 0 < q - pv[0] <= 5:
                    ql = pv[0]; break
            m = LOTKEY.match(ln)
            if m and (full or score >= 4):
                done.add((pg, int(m.group(1).translate(LOTFIX))))
            rec = dict(page=pg, lot=lot_from_prefix(prefix), seller=seller_from_prefix(prefix),
                       buyer=buyer_from_suffix(suffix), q=q, r=r, v=v, repaired=int(not full), line=ln.strip(),
                       votes=1, score=score, full=full, ql=ql, pen=pen)
            key = (round(q, 3), round(r))
            old = rows.get(key)
            if old:
                old["votes"] += 1; old["score"] = max(old["score"], score); old["full"] = max(old["full"], full)
                old["pen"] = min(old["pen"], pen)
                old["repaired"] = min(old["repaired"], rec["repaired"]); old["ql"] = old.get("ql") or ql
                for fld in ("seller", "buyer", "lot"):
                    if not old[fld] and rec[fld]:
                        old[fld] = rec[fld]
            else:
                rows[key] = rec
            continue
        if WDRAWN.search(ln):
            for pr in find_pairs(ln, rmin, rmax):
                wd.add((pr["q"], pr["r"]))
            continue
        for pr in find_pairs(ln, rmin, rmax):
            k2 = (pr["q"], pr["r"])
            e = pairs.setdefault(k2, dict(pr, votes=0, page=pg, line=ln.strip()))
            e["votes"] += 1
            if e["lot"] is None:
                e["lot"] = pr["lot"]
        m = LOTLINE.match(ln.replace("—", " "))
        if m:
            vq = variants(m.group(3)); vr = variants(m.group(4))
            if vq and vr:
                aux[(round(vq[0], 1), round(vr[0]))] = dict(lot=int(m.group(1)), code=m.group(5))
    for lot, pl in groups.items():
        pages = sorted({pg for pg, _ in pl})
        todo = [pg for pg in pages if (pg, lot) not in done]
        if not todo or len(pl) < 2 or len(pl) > 16:
            continue
        lns = [ln for _, ln in pl]
        d1 = decode("   ".join(lns), inv, rmin, rmax)
        if d1 and (round(d1["q"], 3), round(d1["r"])) not in rows:
            best = max(lns, key=len)
            prefix, suffix, _ = split_row(best)
            rows[(round(d1["q"], 3), round(d1["r"]))] = dict(
                page=todo[0], lot=lot, seller=seller_from_prefix(prefix), buyer=buyer_from_suffix(suffix), q=d1["q"],
                r=d1["r"], v=d1["v"], repaired=1, line=best.strip(), votes=1, score=min(d1["score"], 4),
                full=int(d1["full"]), ql=None, pen=d1["pen"], pooled=1)
    for rec in rows.values():
        a = aux.get((round(rec["q"], 1), round(rec["r"])))
        if a:
            rec["lot"] = rec["lot"] or a["lot"]
            if not rec["buyer"]:
                rec["buyer"] = a["code"]
    out = list(rows.values())
    cands = []
    for (q, r), e in sorted(pairs.items(), key=lambda kv: -kv[1]["votes"]):
        if (q, r) in wd:
            continue  # withdrawn lot: it has a bid price but was not sold
        a = aux.get((round(q, 1), round(r)), {})
        cands.append(dict(page=e["page"], lot=e["lot"], seller="", buyer=a.get("code", ""), q=q, r=r, v=round(q * r, 2),
                          repaired=0, line=e["line"], votes=e["votes"], score=0, full=0, novalue=1, ql=None))
    return out, cands, wd


def _near(a, b, fmt, maxdiff):
    x, y = fmt % a, fmt % b
    return len(x) == len(y) and 0 < sum(c != d for c, d in zip(x, y)) <= maxdiff


def strong(r):
    return r["score"] >= 5 or (r["votes"] >= 2 and (r["full"] or r["score"] >= 4))


def resolve(rows):
    """Readings of one lot that differ by a misread digit or a decimal shift: keep the best-supported."""
    rows.sort(key=lambda r: (-r["full"], -r["score"], -r["votes"]))
    keep = []
    for r in rows:
        clash = None
        for k in keep:
            same_r = round(k["r"]) == round(r["r"])
            if (same_r and _near(k["q"], r["q"], "%.3f", 1)) or \
               (abs(k["q"] - r["q"]) < 0.001 and _near(k["r"], r["r"], "%.2f", 1)) or \
               (same_r and (abs(k["q"] - r["q"] * 10) < 0.05 or abs(k["q"] * 10 - r["q"]) < 0.05)) or \
               abs(k["v"] - r["v"]) < 0.6:
                clash = k; break
        if clash and not strong(r):
            for fld in ("seller", "buyer", "lot"):
                if not clash[fld] and r[fld]:
                    clash[fld] = r[fld]
            continue
        keep.append(r)
    return keep


SLIP = re.compile(r"(?<![\d.,])([0-9OoIlZzSsB]{2,3})\s+[^\d\n]{0,3}(\d{1,3}[.,]\s?\d{2})\s*[^\d\n]{0,3}\s*(\d[.,]?\s?\d{3}[.,]\s?\d{2})(?!\d)")
SLIPFIX = str.maketrans("OoIlZzSsB", "001122558")


def lot_slip(d, lo, hi, rmin, rmax, fixes):
    """A 'LOT SLIP' page lists every lot as (lot, kilos, rate) in columns. Consensus across OCR passes."""
    from collections import Counter, defaultdict
    votes = defaultdict(Counter)
    names = defaultdict(Counter)
    for dd in d.split(","):
        for f in glob.glob(f"{dd}/p-*.txt"):
            pg = int(re.findall(r"\d+", os.path.basename(f))[0])
            t = open(f, errors="ignore").read()
            if not (lo <= pg <= hi) or not re.search(r"LOT\s+SLIP", t, re.I):
                continue
            for m in SLIP.finditer(t):
                q = variants(m.group(2).replace(" ", "")); r = variants(m.group(3).replace(" ", ""))
                if q and r and rmin - 0.5 <= r[0] <= rmax + 0.5 and 5 <= q[0] < 1500:
                    votes[int(m.group(1).translate(SLIPFIX))][(q[0], r[0])] += 1
    lots = {lot: c.most_common(1)[0][0] + ("ocr",) for lot, c in votes.items() if c}
    for lot, (q, r) in (fixes or {}).items():
        lots[int(lot)] = (q, float(r), "claude-read")
    # lot numbers run consecutively: keep the main run, drop stray misread numbers
    ks, best, cur = sorted(lots), [], []
    for k in ks:
        cur = cur + [k] if cur and k - cur[-1] <= 3 else [k]
        if len(cur) > len(best):
            best = cur
    return {k: lots[k] for k in best}


def clashes(a, b):
    same_r = round(a["r"]) == round(b["r"])
    return (same_r and _near(a["q"], b["q"], "%.3f", 1)) or \
           (abs(a["q"] - b["q"]) < 0.001 and _near(a["r"], b["r"], "%.2f", 1)) or \
           (same_r and (abs(a["q"] - b["q"] * 10) < 0.05 or abs(a["q"] * 10 - b["q"]) < 0.05)) or \
           abs(a["v"] - b["v"]) < 0.6


def subset_close(U, tq, tv, limit=64):
    """Ledger closure: the subset of uncertain rows whose kg AND rupees both hit the printed remainder.
    Exact meet-in-the-middle search. tq in grams (int), tv in rupees. Returns list of rows or None."""
    if tq < -50 or sum(u["_g"] for u in U) < tq - 50:
        return None
    if abs(tq) <= 1 and abs(tv) <= 0.6:
        return []
    U = U[:limit]
    total_g, total_v = sum(u["_g"] for u in U), sum(u["v"] for u in U)
    if total_g - tq < tq:  # fewer rows to leave out than to take: search for the left-out set instead
        out = subset_close(U, total_g - tq, total_v - tv, limit) if total_g - tq >= -50 else None
        if out is None:
            return None
        drop = {id(u) for u in out}
        return [u for u in U if id(u) not in drop]
    half = len(U) // 2

    def sums(items, off):
        out = [(0, 0.0, 0)]
        for i, u in enumerate(items):
            g, v, bit = u["_g"], u["v"], 1 << (i + off)
            out += [(q + g, vv + v, m | bit) for q, vv, m in out if q + g <= tq + 50]
            if len(out) > 1_500_000:
                raise OverflowError
        return out
    try:
        A, Bs = sums(U[:half], 0), sums(U[half:], half)
    except OverflowError:
        return None
    idx = {}
    for q, v, m in A:
        idx.setdefault(q // 100, []).append((q, v, m))
    best = None
    for q, v, m in Bs:
        need = tq - q
        for b in (need // 100 - 1, need // 100, need // 100 + 1):
            for qa, va, ma in idx.get(b, ()):
                if abs(qa - need) <= 1:
                    err = abs(va + v - tv)
                    if err <= 0.6 and (best is None or err < best[0]):
                        best = (err, m | ma)
    if best is None:
        return None
    return [u for i, u in enumerate(U) if best[1] >> i & 1]


def from_slip(slip, rows, wdset, s, invoices):
    """The slip's kilos add up to the printed arrivals, so it is the complete lot list (weight, price).
    The Buyers Statement then says which lots were sold and to whom (invoice cover); the decoded rows add
    the seller names where their page exists."""
    by_qr = {}
    for r in rows:
        by_qr.setdefault((round(r["q"], 2), round(r["r"])), r)
    assign, todo = cover({k: (q, r) for k, (q, r, _) in slip.items()}, invoices) if invoices else ({}, [1])
    left = sum(slip[k][0] for k in slip if k not in assign)
    if todo or abs(left - (s["arrivals"] - s["sold"])) > 0.05:
        return rows, "open"
    out = []
    for lot, inv_i in sorted(assign.items()):
        q, r, src = slip[lot]
        rec = by_qr.get((round(q, 2), round(r)))
        if rec:
            rec = dict(rec, lot=lot, buyer=invoices[inv_i][0] or rec["buyer"])
        else:
            rec = dict(page=0, lot=lot, seller="", buyer=invoices[inv_i][0], q=q, r=r, v=round(q * r, 2),
                       repaired=int(src != "ocr"), votes=1, score=0, full=0, invoice=1,
                       line=f"(lot slip + buyers statement; this lot's own page is not in the PDF; price {src})")
        out.append(rec)
    return out, "closed"


def select(rows, cands, sold, value):
    """Split candidates into certain and uncertain rows, then let the printed totals decide the uncertain ones."""
    for r in rows + cands:
        r["_g"] = int(round(r["q"] * 1000))
    rows.sort(key=lambda r: (-r["full"], -r["score"], -r["votes"]))
    qs = sorted(r["q"] for r in rows) or [100]
    med = qs[len(qs) // 2]
    far = lambda r: abs(math.log(r["q"] / med))
    ghost = set()
    for a in rows:  # decimal-point ghosts (29.90 read as 2990): keep the plainer reading, else the usual lot size
        for b in rows:
            if a is not b and round(a["r"]) == round(b["r"]) and any(abs(a["q"] - b["q"] * m) < 0.05 for m in (10, 100)):
                ka = (a.get("pen", 0), far(a)); kb = (b.get("pen", 0), far(b))
                ghost.add(id(a) if ka > kb else id(b))
    # same physical line read two ways: rows sharing 3+ printed numbers are one lot; keep the stronger
    def ntoks(r):
        return {t for t in re.findall(r"\d+[.,]\d{2,3}", r.get("line", "")) if len(t) >= 6}
    srt = sorted(rows, key=lambda r: (-r["full"], -r["score"], -r["votes"]))
    for i, a in enumerate(srt):
        if id(a) in ghost:
            continue
        ta = ntoks(a)
        for b in srt[i + 1:]:
            if id(b) not in ghost and len(ta & ntoks(b)) >= 3 and not (abs(a["q"] - b["q"]) < 0.001 and round(a["r"]) == round(b["r"])):
                ghost.add(id(b))
    rows = [r for r in rows if id(r) not in ghost]
    S, U = [], []
    for r in rows:
        clash = any(clashes(r, k) for k in S)
        # 5+ agreeing numbers on a row cannot be a misreading, so near-identical lots are both real
        (S if r["score"] >= 5 or (strong(r) and not clash) else U).append(r)
    grid = lambda c: abs(c["q"] * 20 - round(c["q"] * 20)) < 1e-6 and abs(c["r"] - round(c["r"])) < 1e-6
    pool = [u for u in U if grid(u)] + [
        c for c in cands if c["votes"] >= 2 and c["lot"] is not None and grid(c)
        and not any(abs(c["q"] - k["q"]) < 0.001 and round(c["r"]) == round(k["r"]) for k in S + U)]
    tq = int(round(sold * 1000)) - sum(r["_g"] for r in S)
    tv = value - sum(r["v"] for r in S)
    # the more uncertain rows offered, the likelier a chance fit: certify only from a short list
    pick = subset_close(pool[:22], tq, tv)
    if pick is not None:
        return S + pick, "closed"
    # no exact closure: keep the well-supported rows, never above the printed total
    out, total = list(S), sum(r["q"] for r in S)
    for r in pool:
        weak = not (r["full"] or r["score"] >= 3 or r.get("novalue"))
        if weak or (r.get("novalue") and total + r["q"] > sold + 0.05):
            continue
        if any(clashes(r, k) for k in out) and not r["full"]:
            continue
        out.append(r); total += r["q"]
    # one lot still missing? the printed totals give its weight and price exactly
    dq = sold - total
    dv = value - sum(r["v"] for r in out)
    if dq >= 5:
        rr = round(dv / dq)
        if abs(dv - dq * rr) <= 0.5 and abs(dq * 10 - round(dq * 10)) < 0.01:
            out.append(dict(page=0, lot=None, seller="", buyer="", q=round(dq, 3), r=float(rr), v=round(dv, 2), repaired=1,
                            line="(inferred from the report totals)", votes=0, score=0, full=0, novalue=1, inferred=1))
            return out, "closed*"
    return out, "open"


def assign_lots(rows, d):
    """Lot numbers by vote across every OCR line that carries a row's exact quantity and rate.
    Lot lists print 'LOT QTY ...' (the number right before the quantity is the lot); seller statements
    print 'S.No Lot Name ...' (the second leading number is the lot)."""
    from collections import Counter, defaultdict
    fix = str.maketrans("OoQDIl|", "0000111")
    idx = defaultdict(list)
    for r in rows:
        for qf in {"%.3f" % r["q"], "%.2f" % r["q"], "%.1f" % r["q"]}:
            idx[qf].append(r)
    votes = defaultdict(Counter)
    names = defaultdict(Counter)
    for dd in d.split(","):
        for f in glob.glob(f"{dd}/p-*.txt"):
            for ln in open(f, errors="ignore"):
                toks = ln.replace(",", "").split()
                lead = []
                for t in toks[:4]:
                    t2 = t.strip("|[](){}.:;-").translate(fix)
                    if t2.isdigit() and len(t2) <= 4:
                        lead.append(int(t2))
                    else:
                        break
                if not lead or len(lead) > 3:
                    continue
                nums = set(re.findall(r"\d+\.\d+", ln.replace(",", "")))
                for qf in nums & set(idx):
                    for r in idx[qf]:
                        rf = {"%.2f" % r["r"], "%.0f" % r["r"]}
                        if not (rf & nums) and not any(("%.0f" % r["r"]) == t.replace(",", "") for t in toks):
                            continue
                        pos = len(lead)
                        nxt = toks[pos].replace(",", "") if pos < len(toks) else ""
                        is_list = bool(re.match(r"^\d+\.\d+$", nxt))  # numbers then quantity: a lot list
                        if is_list:
                            votes[id(r)][lead[0]] += 3
                            tail = re.split(r"\d[\d,]*\.\d+|\b\d{3,4}\b", ln)[-1]
                            bn = buyer_from_suffix(" " + tail)
                            if len(bn) >= 4:
                                names[id(r)][bn] += 1
                        elif len(lead) >= 2:
                            votes[id(r)][lead[1]] += 2
                        else:
                            votes[id(r)][lead[0]] += 1
    for r in rows:
        if not r.get("buyer") and names[id(r)]:
            r["buyer"] = names[id(r)].most_common(1)[0][0]
    taken = {}
    order = sorted(rows, key=lambda r: -max(votes[id(r)].values(), default=0))
    for r in order:
        for lot, v in votes[id(r)].most_common():
            if lot not in taken and 0 < lot < 1000:
                taken[lot] = r; r["lot"] = lot; break
        else:
            if votes[id(r)] or r.get("lot") in taken:
                r["lot"] = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS reports(
  report_id TEXT PRIMARY KEY, listing_rank INT, auctioneer TEXT, listed_date TEXT,
  source_url TEXT, sha256 TEXT, bytes INT);
CREATE TABLE IF NOT EXISTS auctions(
  auction_id TEXT PRIMARY KEY, report_id TEXT, auctioneer TEXT, branch TEXT, auction_date TEXT,
  auction_no INT, arrivals_kg REAL, sold_kg REAL, withdrawn_kg REAL, value_rs REAL,
  max_rs REAL, min_rs REAL, avg_rs REAL, summary_source TEXT,
  lots_found INT, lots_kg REAL, coverage_pct REAL);
CREATE TABLE IF NOT EXISTS lots(
  auction_id TEXT, lot_no INT, seller TEXT, buyer TEXT, qty_kg REAL, rate_rs REAL, value_rs REAL,
  page INT, ocr_repaired INT, verified INT, source_line TEXT);
"""

SHORT = {"SPECIALITY INDIAN FOOD PARKS EXPORTS PRIVATE LIMITED": "SIFEX"}


def main(ocr_dir, manifest, truth_path, db):
    man = {os.path.splitext(m["file"])[0]: m for m in json.load(open(manifest))}
    truth = json.load(open(truth_path)) if os.path.exists(truth_path) else {}
    reads = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "claude_reads.json")))
    con = sqlite3.connect(db); con.executescript(SCHEMA)
    for t in ("reports", "auctions", "lots"):
        con.execute(f"DELETE FROM {t}")
    for rid, m in sorted(man.items()):
        con.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?)",
                    (rid, m["rank"], m["auctioneer"], m["date"], m["url"], m["sha256"], m["bytes"]))
        dd0 = ",".join(os.path.join(o, rid) for o in ocr_dir.split(","))
        auto = rid not in truth
        summ = read_report(dd0) if auto else truth[rid]
        if not summ:
            print("no summary found:", rid); continue
        if auto:  # printed max/min are only hints; search half to double the (checked) average price
            lo_r = min(x["avg"] for x in summ) / 2; hi_r = max(x["avg"] for x in summ) * 2
        else:
            lo_r = min(x.get("min", 1000) for x in summ); hi_r = max(x.get("max", 8000) for x in summ)
        lots, cands, wdset = extract_report(",".join(os.path.join(o, rid) for o in ocr_dir.split(",")), lo_r, hi_r)
        aucs = []
        for s in summ:
            aid = f"{rid}{('_' + s['branch']) if s.get('branch') else ''}"
            aucs.append((aid, s))
        # multi-branch PDFs: assign lots by page order (branch pages are contiguous);
        # CPA: Bodinayakanur branch starts at its own Form D page (p-11)
        bounds = [(x["first_page"], x["last_page"]) for x in summ] if auto else \
            {"0007_CPA_13_11_2026_001": [(1, 10), (11, 999)]}.get(rid, [(1, 999)] * len(aucs))
        for (aid, s), (lo, hi) in zip(aucs, bounds):
            mine = [l for l in lots if lo <= l["page"] <= hi]
            if auto:  # max / min price from rows that several engines read identically
                sr = [l["r"] for l in mine if l["full"] and l["votes"] >= 3 and l["score"] >= 4]
                if sr:
                    if not s.get("min") or min(sr) < s["min"] - 0.5 or not any(abs(x - s["min"]) < 0.5 for x in sr):
                        s["min"] = min(sr) if not s.get("min") or min(sr) < s["min"] else s["min"]
                    if not s.get("max") or max(sr) > s["max"] + 0.5:
                        s["max"] = max(sr)
            if s.get("min"):
                mine = [l for l in mine if s["min"] - 0.5 <= l["r"] <= s["max"] + 0.5]
            from collections import Counter
            dif = Counter(round(l["q"] - l["ql"], 2) for l in mine if l.get("ql"))
            if dif and dif.most_common(1)[0][1] > 0.4 * len(mine):  # billed qty = listed qty + fixed sample weight
                d0 = dif.most_common(1)[0][0]  # totals in the report use the listed (net) quantity
                for l in mine:
                    l["q"] = round(l["q"] - d0, 3); l["v"] = round(l["q"] * l["r"], 2)
            fx = reads.get(rid, {}) if lo == 1 else {}
            for d0 in fx.get("drop", []):
                mine = [l for l in mine if not (abs(l["q"] - d0["q"]) < 0.001 and round(l["r"]) == d0["r"])]
            for a0 in fx.get("add", []):
                if not any(abs(l["q"] - a0["q"]) < 0.001 and round(l["r"]) == a0["r"] for l in mine):
                    mine.append(dict(page=a0["page"], lot=a0["serial"], seller=a0["seller"], buyer=a0["buyer"], q=a0["q"],
                                     r=float(a0["r"]), v=round(a0["q"] * a0["r"], 2), repaired=1, votes=1, score=9, full=1,
                                     line="(read from the page image by Claude; refund and commission confirm it)"))
            status = "open"
            slip = lot_slip(",".join(os.path.join(o, rid) for o in ocr_dir.split(",")), lo, hi, s.get("min", 1000),
                            s.get("max", 8000), reads.get(rid, {}).get("slip") if lo == 1 else None)
            dd = ",".join(os.path.join(o, rid) for o in ocr_dir.split(","))
            if slip and s.get("arrivals") and abs(sum(v[0] for v in slip.values()) - s["arrivals"]) < 0.05:
                inv = parse_invoices(dd, lo, hi, s["sold"], s["value"], s.get("min", 1000), s.get("max", 8000))
                mine, status = from_slip(slip, mine, wdset, s, inv)
            if status == "open" and s.get("sold"):
                mine, status = select(mine, [c for c in cands if lo <= c["page"] <= hi], s["sold"], s["value"])
            if not any(l.get("invoice") for l in mine):
                assign_lots(mine, ",".join(os.path.join(o, rid) for o in ocr_dir.split(",")))
            kg = sum(l["q"] for l in mine)
            con.execute("INSERT INTO auctions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (aid, rid, m["auctioneer"], s.get("branch", ""), s.get("date"), s.get("auction_no"),
                         s.get("arrivals"), s.get("sold"), s.get("withdrawn"), s.get("value"),
                         s.get("max"), s.get("min"), s.get("avg"), status, len(mine), round(kg, 3),
                         round(100 * kg / s["sold"], 1) if s.get("sold") else None))
            for l in mine:
                con.execute("INSERT INTO lots VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (aid, l["lot"], l["seller"], l["buyer"], l["q"], l["r"], l["v"], l["page"],
                             l["repaired"], 2 if l.get("inferred") else (3 if l.get("invoice") else (0 if l.get("novalue") else 1)),
                             l["line"][:300]))
    con.commit()
    for r in con.execute("SELECT auction_id, lots_found, lots_kg, sold_kg, coverage_pct FROM auctions"):
        print(r)


if __name__ == "__main__":
    main(*sys.argv[1:5])
