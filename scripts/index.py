"""Keep data/index.json: every report on the Spices Board listing, newest first.

    python scripts/index.py full     # walk every listing page (about 500)
    python scripts/index.py update   # walk from page 1 until a page holds only known reports

Each entry: n (stable number, 1 = oldest ever seen; new reports get the next numbers),
date, auctioneer, href, url.
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from fetch_batch import get, parse_rows, abs_url, LIST_URL, PAUSE

IDX = Path("data/index.json")


def main(mode):
    old = json.loads(IDX.read_text()) if IDX.exists() else []
    known = {e["href"] for e in old}
    fresh, seen, page = [], set(), 1
    while True:
        h = get(LIST_URL if page == 1 else f"{LIST_URL}?page={page}").text
        rows = parse_rows(h)
        if not rows:
            break
        new = [r for r in rows if r["href"] not in known and r["href"] not in seen]
        for r in new:
            seen.add(r["href"])
            fresh.append(dict(date=r["date"], auctioneer=r["auctioneer"], href=r["href"], url=abs_url(r["href"])))
        print(f"page {page}: {len(rows)} rows, {len(new)} new", flush=True)
        if mode == "update" and not new:
            break
        page += 1
        time.sleep(PAUSE)
    top = max((e["n"] for e in old), default=0)
    if mode == "full" and not old:
        for i, e in enumerate(reversed(fresh)):
            e["n"] = i + 1
        out = fresh
    else:
        # Newly listed reports are newer than everything known (the listing is newest first),
        # except stragglers found deep in a full walk: they still get fresh numbers.
        for i, e in enumerate(reversed(fresh)):
            e["n"] = top + i + 1
        out = fresh + old
    IDX.parent.mkdir(exist_ok=True)
    IDX.write_text(json.dumps(out, indent=0))
    print(f"index: {len(out)} reports ({len(fresh)} new)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "update")
