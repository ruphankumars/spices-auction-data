"""Normalise names and export lots/auctions CSVs for the dashboard.

usage: python export.py <db.sqlite> <out_dir>
"""
import csv, difflib, re, sqlite3, sys
from collections import Counter

FIX = {"SPKES": "SPICES", "SPLCES": "SPICES", "SPIGES": "SPICES", "SRICES": "SPICES", "SPICEG": "SPICES",
       "SPICESAND": "SPICES AND", "TRADERS.": "TRADERS"}


GENERIC = {"SPICES", "TRADERS", "CARDAMOM", "EXPORTS", "COMPANY", "TRADING", "CARDAMOM CUMBUM", "SPICES TRADING"}


PLACE = re.compile(r"^(BOD|BOO|8OD|CUMBUM|KUMIL|THENI|PUTTAD|VANDAN|NEDUM|KATTAP|MUNNAR|THEVAR|PAMPA|CHELLAR|ERODE|"
                   r"CHETTU|MUNIYAR|KOCHI|COCHIN|MADURAI|CHENNAI|SANTHAN|PULIYAN|NIRAPP|ANAKKARA|VANDIPER|ADIMALI)")
KEEP = {"LTD", "PVT", "CO", "&", "AND", "KL", "TN", "SONS", "LLP", "INC", "IMPEX", "AGRO", "HUB", "PARK"}


def tidy(n):
    n = (n or "").upper().replace("&", " & ")
    n = re.sub(r"[^A-Z0-9& .-]", " ", n)
    n = " ".join(FIX.get(w, w) for w in n.split())
    n = re.sub(r"\b(SPICES)(AND)\b", r"\1 \2", n)
    ws = n.split()
    while len(ws) > 1 and (PLACE.match(ws[-1]) or (len(ws[-1]) <= 4 and ws[-1] not in KEEP)):
        ws.pop()
    n = " ".join(ws).strip(" .-")
    n = re.sub(r"\b([A-Z])\.\s?([A-Z])\b", r"\1\2", n)  # V.R -> VR
    return "" if n in GENERIC or len(n) < 3 else n


def canon_map(names):
    """Map each spelling to the most frequent near-identical spelling."""
    cnt = Counter(n for n in names if n)
    key = lambda s: re.sub(r"[^A-Z0-9]", "", s)
    order = [n for n, _ in cnt.most_common()]
    canon, reps = {}, []
    for n in order:
        k = key(n)
        best = None
        for r in reps:
            kr = key(r)
            if k == kr or (len(k) >= 6 and difflib.SequenceMatcher(None, k, kr).ratio() >= 0.88):
                best = r; break
        if best is None:
            reps.append(n); best = n
        canon[n] = best
    # truncated names: merge a name into a longer one it is the start of (keep the longest form)
    reps.sort(key=lambda r: -len(key(r)))
    final = {}
    for r in reps:
        k = key(r)
        tgt = next((L for L in reps if len(key(L)) > len(k) >= 8 and key(L).startswith(k)), r)
        final[r] = final.get(tgt, tgt)
    return {n: final.get(c, c) for n, c in canon.items()}


def main(db, out):
    con = sqlite3.connect(db)
    lots = con.execute("SELECT l.auction_id, a.auctioneer, a.branch, a.auction_date, l.lot_no, l.seller, l.buyer,"
                       " l.qty_kg, l.rate_rs, l.value_rs, l.ocr_repaired FROM lots l JOIN auctions a USING(auction_id)").fetchall()
    sellers = [tidy(r[5]) for r in lots]; buyers = [tidy(r[6]) for r in lots]
    cs, cb = canon_map(sellers), canon_map(buyers)
    with open(f"{out}/lots.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["auction_id", "auctioneer", "branch", "date", "lot_no", "seller", "buyer", "qty_kg", "rate_rs", "value_rs", "ocr_repaired"])
        for r, s, b in zip(lots, sellers, buyers):
            w.writerow([r[0], r[1], r[2], r[3], r[4] if r[4] is not None else "", cs.get(s, s), cb.get(b, b), r[7], r[8], r[9], r[10]])
    with open(f"{out}/auctions.csv", "w", newline="") as f:
        w = csv.writer(f)
        cols = ["auction_id", "auctioneer", "branch", "date", "auction_no", "arrivals_kg", "sold_kg", "withdrawn_kg",
                "value_rs", "max_rs", "min_rs", "avg_rs", "lots_found", "lots_kg", "coverage_pct"]
        w.writerow(cols)
        for r in con.execute("SELECT auction_id, auctioneer, branch, auction_date, auction_no, arrivals_kg, sold_kg, withdrawn_kg,"
                             " value_rs, max_rs, min_rs, avg_rs, lots_found, lots_kg, coverage_pct FROM auctions ORDER BY auction_date DESC"):
            w.writerow(r)
    print("buyers", len(set(cb.values())), "sellers", len(set(cs.values())), "lots", len(lots))


if __name__ == "__main__":
    main(*sys.argv[1:3])
