"""Pick the next reports to read: newest first, skipping any already in data/batches/.

    python scripts/plan.py <jobs> <per_job>   -> prints a GitHub matrix JSON
"""
import json, sys, glob
from pathlib import Path

jobs, per = int(sys.argv[1]), int(sys.argv[2])
import hashlib
idx = json.loads(Path("data/index.json").read_text()) if Path("data/index.json").exists() else []
if Path("data/index_partial.json").exists():  # start reading while the listing walk is still going
    known = {e["href"] for e in idx}
    idx += [e for e in json.loads(Path("data/index_partial.json").read_text())["rows"] if e["href"] not in known]
for e in idx:
    e.setdefault("n", int(hashlib.sha1(e["href"].encode()).hexdigest()[:9], 16))
done = set()
# A report counts as read when its batch has an auction from it, or when the batch was read by the
# reader that knows the older C-FORM reports (27 Nov 2026): before that, 2016-2022 reports came out
# with no summary and no lots, and are read again once.
for m in glob.glob("data/batches/*/manifest.json"):
    b = Path(m).parent
    ents = json.load(open(m))
    if (b / "reader_v2").exists():
        done |= {e["href"] for e in ents}
        continue
    aids = (b / "auctions.csv").read_text(errors="ignore") if (b / "auctions.csv").exists() else ""
    done |= {e["href"] for e in ents if Path(e.get("file", "")).stem and Path(e["file"]).stem in aids}
for f in glob.glob("data/batches/*/failed.json") + glob.glob("data/batches/*/unfetched.json"):
    done |= {e["href"] for e in json.load(open(f))}
todo = [e["n"] for e in idx if e["href"] not in done]
if __import__("os").environ.get("PLAN_ORDER") == "oldest":  # the Mac helper reads from the other end
    todo.reverse()
chunks = [todo[i:i + per] for i in range(0, min(len(todo), jobs * per), per)]
print(json.dumps({"include": [{"ns": ",".join(map(str, c))} for c in chunks]} if chunks else {"include": []}))
print(f"pending {len(todo)} of {len(idx)}", file=sys.stderr)
