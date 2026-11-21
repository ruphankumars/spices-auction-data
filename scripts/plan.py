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
for m in glob.glob("data/batches/*/manifest.json"):
    done |= {e["href"] for e in json.load(open(m))}
for f in glob.glob("data/batches/*/failed.json") + glob.glob("data/batches/*/unfetched.json"):
    done |= {e["href"] for e in json.load(open(f))}
todo = [e["n"] for e in idx if e["href"] not in done]
chunks = [todo[i:i + per] for i in range(0, min(len(todo), jobs * per), per)]
print(json.dumps({"include": [{"ns": ",".join(map(str, c))} for c in chunks]} if chunks else {"include": []}))
print(f"pending {len(todo)} of {len(idx)}", file=sys.stderr)
