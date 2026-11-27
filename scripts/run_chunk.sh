#!/usr/bin/env bash
# Read a few reports end to end: fetch, the three OCR families, checksum build, export.
# Usage: run_chunk.sh N1,N2,...   -> data/batches/<id>/{manifest.json,lots.csv,auctions.csv,recon.txt}
set -uo pipefail
NS="$1"; ID="n$(echo "$NS" | cut -d, -f1)-$(echo "$NS" | awk -F, '{print $NF}')"
# a report read again (an older C-FORM one, 27 Nov 2026) goes in a new batch beside the old empty one
[ -d "data/batches/$ID" ] && ID="${ID}r2"
ROOT=$PWD; OUT="data/batches/$ID"; mkdir -p "$OUT" outs
python scripts/fetch_index.py "$NS"
cp work/manifest.json "$OUT/manifest.json"
# reports that would not download are set aside (failed.json) so the next round does not retry them for ever
python -c "import json;m=json.load(open('work/unfetched.json'));m and json.dump(m,open('$OUT/unfetched.json','w'))"
pass() { name=$1; shift; rm -rf work/out; "$@" > "outs/$name.log" 2>&1 || echo "pass $name failed"; mv work/out "outs/$name" 2>/dev/null || mkdir -p "outs/$name"; }
pass base bash scripts/ocr_batch.sh
pass multi bash scripts/ocr_multi.sh
pass var bash scripts/ocr_variants.sh
D="$ROOT/outs/base,$ROOT/outs/multi/passC,$ROOT/outs/multi/passD,$ROOT/outs/multi/passE,$ROOT/outs/var/pass_hi,$ROOT/outs/var/pass_sharp,$ROOT/outs/var/pass_level"
if python extract/build_db.py "$D" work/manifest.json AUTO chunk.db > outs/build.log 2>&1 && python extract/export.py chunk.db "$OUT" >> outs/build.log 2>&1; then
  python extract/recon.py chunk.db > "$OUT/recon.txt" 2>&1 || true
  touch "$OUT/reader_v2"   # read by the reader that knows the older C-FORM reports (plan.py)
else
  tail -n 30 outs/build.log
  python - "$OUT" <<'PY'
import json, sys
m = json.load(open(f"{sys.argv[1]}/manifest.json"))
json.dump([{"href": e["href"], "why": "build failed"} for e in m], open(f"{sys.argv[1]}/failed.json", "w"))
PY
fi
tail -n 5 outs/build.log
