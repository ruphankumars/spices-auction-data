"""Keep data/index.json: every report on the Spices Board listing, newest first.

    python scripts/index.py full     # walk every listing page (about 500)
    python scripts/index.py update   # walk from page 1 until a page holds only known reports

A full walk saves data/index_partial.json every 20 pages, so a walk cut short by the
job's time limit carries on from there next run (whatever mode is asked).
Each entry: n (stable number, 1 = oldest; new reports get the next numbers),
date, auctioneer, href, url.
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from fetch_batch import get, parse_rows, abs_url, LIST_URL, PAUSE

IDX = Path("data/index.json")
PART = Path("data/index_partial.json")
BUDGET = float(sys.argv[2]) * 60 if len(sys.argv) > 2 else 95 * 60  # seconds before saving and stopping


def walk(start_page, known, fresh, stop_when_known, t0):
    seen = {e["href"] for e in fresh}
    page = start_page
    while True:
        if time.time() - t0 > BUDGET:
            return page, False
        h = get(LIST_URL if page == 1 else f"{LIST_URL}?page={page}").text
        rows = parse_rows(h)
        if not rows:
            return page, True
        new = [r for r in rows if r["href"] not in known and r["href"] not in seen]
        if not new and all(r["href"] in seen for r in rows):
            return page, True  # the site repeats its last page past the end
        for r in new:
            seen.add(r["href"])
            fresh.append(dict(date=r["date"], auctioneer=r["auctioneer"], href=r["href"], url=abs_url(r["href"])))
        print(f"page {page}: {len(rows)} rows, {len(new)} new", flush=True)
        if stop_when_known and not new:
            return page, True
        page += 1
        if page % 20 == 0 and not stop_when_known:
            PART.write_text(json.dumps(dict(next_page=page, rows=fresh)))
        time.sleep(PAUSE)


def main(mode):
    t0 = time.time()
    old = json.loads(IDX.read_text()) if IDX.exists() else []
    known = {e["href"] for e in old}
    if PART.exists():
        p = json.loads(PART.read_text()); start, fresh, mode = p["next_page"], p["rows"], "full"
        print(f"resuming the full walk at page {start} ({len(fresh)} rows so far)")
    else:
        start, fresh = 1, []
    page, finished = walk(start, known, fresh, mode == "update" and old, t0)
    if not finished:
        PART.parent.mkdir(exist_ok=True)
        PART.write_text(json.dumps(dict(next_page=page, rows=fresh)))
        print(f"time budget used: saved {len(fresh)} rows, next run continues at page {page}")
        return
    top = max((e["n"] for e in old), default=0)
    for i, e in enumerate(reversed(fresh)):
        e["n"] = top + i + 1
    out = fresh + old
    IDX.parent.mkdir(exist_ok=True)
    IDX.write_text(json.dumps(out, indent=0))
    if PART.exists():
        PART.unlink()
    print(f"index: {len(out)} reports ({len(fresh)} new)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "update")
