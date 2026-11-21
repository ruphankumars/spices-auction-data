"""Download the reports numbered N1,N2,... in data/index.json into work/pdf; write work/manifest.json."""
import hashlib, json, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from fetch_batch import get, PAUSE

want = {int(x) for x in sys.argv[1].split(",") if x}
rows = json.loads(Path("data/index.json").read_text()) if Path("data/index.json").exists() else []
if Path("data/index_partial.json").exists():
    rows += json.loads(Path("data/index_partial.json").read_text())["rows"]
for e in rows:
    e.setdefault("n", int(hashlib.sha1(e["href"].encode()).hexdigest()[:9], 16))
idx = {e["n"]: e for e in rows}
work = Path("work"); (work / "pdf").mkdir(parents=True, exist_ok=True)
out, missed = [], []
for n in sorted(want):
    e = idx[n]
    code = re.sub(r"[^A-Za-z0-9]+", "_", e["href"].rsplit("/", 1)[1].rsplit(".", 1)[0]).strip("_")
    fn = work / "pdf" / f"n{n}_{code}.pdf"
    try:
        b = get(e["url"]).content
    except Exception as ex:  # noqa: BLE001
        print("fetch failed", n, ex); missed.append({"href": e["href"], "why": f"fetch failed: {ex}"}); continue
    fn.write_bytes(b)
    out.append(dict(e, rank=n, file=fn.name, bytes=len(b), sha256=hashlib.sha256(b).hexdigest()))
    time.sleep(PAUSE)
(work / "manifest.json").write_text(json.dumps(out, indent=1))
(work / "unfetched.json").write_text(json.dumps(missed))
print(len(out), "fetched")
