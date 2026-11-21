"""Pick the next reports to read: newest first, skipping any already in data/batches/.

    python scripts/plan.py <jobs> <per_job>   -> prints a GitHub matrix JSON
"""
import json, sys, glob
from pathlib import Path

jobs, per = int(sys.argv[1]), int(sys.argv[2])
idx = json.loads(Path("data/index.json").read_text())
done = set()
for m in glob.glob("data/batches/*/manifest.json"):
    done |= {e["href"] for e in json.load(open(m))}
for f in glob.glob("data/batches/*/failed.json") + glob.glob("data/batches/*/unfetched.json"):
    done |= {e["href"] for e in json.load(open(f))}
todo = [e["n"] for e in idx if e["href"] not in done]
chunks = [todo[i:i + per] for i in range(0, min(len(todo), jobs * per), per)]
print(json.dumps({"include": [{"ns": ",".join(map(str, c))} for c in chunks]} if chunks else {"include": []}))
print(f"pending {len(todo)} of {len(idx)}", file=sys.stderr)
