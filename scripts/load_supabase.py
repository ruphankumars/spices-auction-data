"""Upsert data/batches/* into Supabase (tables in supabase/schema.sql).

Needs SUPABASE_URL and SUPABASE_SERVICE_KEY in the environment (GitHub secrets);
without them it does nothing. Batches already loaded are skipped (reports.batch).
"""
import csv, glob, json, os, sys
import requests

URL, KEY = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
if not URL or not KEY:
    print("Supabase secrets not set: skipping"); sys.exit(0)
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}


def up(table, rows):
    for i in range(0, len(rows), 1000):
        r = requests.post(f"{URL}/rest/v1/{table}", headers=H, data=json.dumps(rows[i:i + 1000]), timeout=120)
        if r.status_code >= 300:
            raise SystemExit(f"{table}: {r.status_code} {r.text[:300]}")


have = {x["batch"] for x in requests.get(f"{URL}/rest/v1/reports?select=batch", headers=H, timeout=60).json() if x.get("batch")}
num = lambda v: None if v in ("", None) else float(v)
for d in sorted(glob.glob("data/batches/*/")):
    b = os.path.basename(d.rstrip("/"))
    if b in have or not os.path.exists(d + "lots.csv"):
        continue
    aucs = [dict(auction_id=a["auction_id"], auctioneer=a["auctioneer"], branch=a["branch"], auction_date=a["date"] or None,
                 auction_no=a["auction_no"], **{k: num(a[k]) for k in ("arrivals_kg", "sold_kg", "withdrawn_kg", "value_rs", "max_rs", "min_rs", "avg_rs", "lots_kg", "coverage_pct")},
                 lots_found=int(float(a["lots_found"] or 0)), batch=b) for a in csv.DictReader(open(d + "auctions.csv"))]
    seq, lots = {}, []
    for r in csv.DictReader(open(d + "lots.csv")):
        seq[r["auction_id"]] = seq.get(r["auction_id"], 0) + 1
        lots.append(dict(auction_id=r["auction_id"], lot_no=r["lot_no"], seller=r["seller"], buyer=r["buyer"], qty_kg=num(r["qty_kg"]),
                         rate_rs=num(r["rate_rs"]), value_rs=num(r["value_rs"]), ocr_repaired=int(float(r["ocr_repaired"] or 0)), seq=seq[r["auction_id"]]))
    reps = [dict(href=m["href"], n=m.get("rank"), report_date=m["date"], auctioneer=m["auctioneer"], url=m["url"], sha256=m.get("sha256"), batch=b)
            for m in json.load(open(d + "manifest.json"))]
    up("auctions", aucs); up("lots", lots); up("reports", reps)
    print(b, len(aucs), "auctions", len(lots), "lots")
