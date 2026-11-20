"""Build the auction database from OCR text.

usage: python build_db.py <ocr_out_dir> <manifest.json> <truth.json> <db.sqlite>

Tables
  reports   one row per PDF (source link, checksum)
  auctions  one row per auction (a PDF can hold 2 branches); summary figures
  lots      one row per sold lot found and arithmetic-verified (qty x rate = value)
"""
import glob, json, os, re, sqlite3, sys
from rows import find_triple, num_tokens, variants

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


def extract_report(d):
    rows, aux, byqr = {}, {}, {}
    for f in page_files(d):
        pg = int(re.findall(r"\d+", os.path.basename(f))[0])
        for ln in open(f, errors="ignore"):
            ln = ln.rstrip("\n")
            t = find_triple(ln)
            if t:
                toks = t["toks"]
                prefix = ln[: toks[t["i"]][0]]
                suffix = ln[toks[t["k"]][1]:]
                key = round(t["v"])
                qr = (round(t["q"], 2), round(t["r"]))
                if key not in rows:  # same lot read in another pass/page: match by value or by qty+rate
                    key = next((k for k in (key - 1, key + 1) if k in rows), None) or byqr.get(qr, key)
                byqr.setdefault(qr, key)
                rec = dict(page=pg, lot=lot_from_prefix(prefix), seller=seller_from_prefix(prefix),
                           buyer=buyer_from_suffix(suffix), q=t["q"], r=t["r"], v=t["v"],
                           repaired=int(t["repaired"]), line=ln.strip())
                old = rows.get(key)
                if old:  # same lot on another page type: fill gaps
                    for fld in ("seller", "buyer", "lot"):
                        if not old[fld] and rec[fld]:
                            old[fld] = rec[fld]
                else:
                    rows[key] = rec
                continue
            m = LOTLINE.match(ln.replace("—", " "))
            if m:  # lot list without value column (KCPMC/CPMCS style): buyer code only
                vq = variants(m.group(3)); vr = variants(m.group(4))
                if vq and vr:
                    aux[(round(vq[0], 1), round(vr[0]))] = dict(lot=int(m.group(1)), code=m.group(5))
    for key, rec in rows.items():
        a = aux.get((round(rec["q"], 1), round(rec["r"])))
        if a:
            rec["lot"] = rec["lot"] or a["lot"]
            if not rec["buyer"]:
                rec["buyer"] = a["code"]
    return list(rows.values())


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
    truth = json.load(open(truth_path))
    con = sqlite3.connect(db); con.executescript(SCHEMA)
    for t in ("reports", "auctions", "lots"):
        con.execute(f"DELETE FROM {t}")
    for rid, m in sorted(man.items()):
        con.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?)",
                    (rid, m["rank"], m["auctioneer"], m["date"], m["url"], m["sha256"], m["bytes"]))
        lots = extract_report(",".join(os.path.join(o, rid) for o in ocr_dir.split(",")))
        summ = truth.get(rid, [{}])
        aucs = []
        for s in summ:
            aid = f"{rid}{('_' + s['branch']) if s.get('branch') else ''}"
            aucs.append((aid, s))
        # multi-branch PDFs: assign lots by page order (branch pages are contiguous);
        # CPA: Bodinayakanur branch starts at its own Form D page (p-11)
        bounds = {"0007_CPA_13_11_2026_001": [(1, 10), (11, 999)]}.get(rid, [(1, 999)] * len(aucs))
        for (aid, s), (lo, hi) in zip(aucs, bounds):
            mine = [l for l in lots if lo <= l["page"] <= hi]
            kg = sum(l["q"] for l in mine)
            con.execute("INSERT INTO auctions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (aid, rid, m["auctioneer"], s.get("branch", ""), s.get("date"), s.get("auction_no"),
                         s.get("arrivals"), s.get("sold"), s.get("withdrawn"), s.get("value"),
                         s.get("max"), s.get("min"), s.get("avg"), "claude-read", len(mine), round(kg, 3),
                         round(100 * kg / s["sold"], 1) if s.get("sold") else None))
            for l in mine:
                con.execute("INSERT INTO lots VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (aid, l["lot"], l["seller"], l["buyer"], l["q"], l["r"], l["v"], l["page"],
                             l["repaired"], 1, l["line"][:300]))
    con.commit()
    for r in con.execute("SELECT auction_id, lots_found, lots_kg, sold_kg, coverage_pct FROM auctions"):
        print(r)


if __name__ == "__main__":
    main(*sys.argv[1:5])
