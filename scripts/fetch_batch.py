"""Fetch Spices Board auction report PDFs for listing rows START..END (1 = newest).

Writes work/manifest.json and work/pdf/<rank>_<code>.pdf. Polite: one request at a time,
pause between requests, retries with backoff.
"""
import hashlib, json, re, sys, time, html
from pathlib import Path
from urllib.parse import quote
import requests

BASE = "https://www.indianspices.com"
LIST_URL = BASE + "/dailyprice-auctiondetails.html"
UA = {"User-Agent": "Mozilla/5.0 (spices-auction-data research; contact: Emperor Spices)"}
PAUSE = 3

S = requests.Session(); S.headers.update(UA)

def get(url, **kw):
    for t in range(4):
        try:
            r = S.get(url, timeout=120, **kw)
            if r.status_code == 200:
                return r
            print(f"HTTP {r.status_code} {url}")
        except requests.RequestException as e:
            print(f"retry {t+1}: {e}")
        time.sleep(PAUSE * (t + 2))
    raise RuntimeError(f"failed: {url}")

ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
HREF = re.compile(r'href="([^"]+\.pdf)"', re.I)
TAG = re.compile(r"<[^>]+>")

def parse_rows(page_html):
    rows = []
    for tr in ROW.findall(page_html):
        cells = CELL.findall(tr)
        m = HREF.search(tr)
        if len(cells) < 3 or not m:
            continue
        text = [html.unescape(TAG.sub("", c)).strip() for c in cells]
        rows.append({"sl": text[0], "date": text[1], "auctioneer": text[2],
                     "href": html.unescape(m.group(1))})
    return rows

def listing(n_needed, work):
    rows, page = [], 0
    while len(rows) < n_needed:
        url = LIST_URL if page == 0 else f"{LIST_URL}?page={page}"
        h = get(url).text
        (work / f"listing_p{page}.html").write_text(h)
        got = parse_rows(h)
        print(f"listing page {page}: {len(got)} rows")
        if not got:
            break
        rows += got
        page += 1
        time.sleep(PAUSE)
    return rows

def abs_url(href):
    if href.startswith("http"):
        u = href
    else:
        u = BASE + "/" + href.lstrip("./").lstrip("/")
    head, name = u.rsplit("/", 1)
    return head + "/" + quote(name)  # literal spaces in names

def main(start, end):
    work = Path("work"); (work / "pdf").mkdir(parents=True, exist_ok=True)
    rows = listing(end, work)
    out = []
    for rank in range(start, end + 1):
        if rank > len(rows):
            break
        r = rows[rank - 1]
        url = abs_url(r["href"])
        code = re.sub(r"[^A-Za-z0-9]+", "_", r["href"].rsplit("/", 1)[1].rsplit(".", 1)[0]).strip("_")
        fn = work / "pdf" / f"{rank:04d}_{code}.pdf"
        b = get(url).content
        fn.write_bytes(b)
        rec = dict(r, rank=rank, url=url, file=fn.name, bytes=len(b),
                   sha256=hashlib.sha256(b).hexdigest())
        out.append(rec); print(json.dumps(rec))
        time.sleep(PAUSE)
    (work / "manifest.json").write_text(json.dumps(out, indent=1))

if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]))
