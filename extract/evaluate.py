"""Measure extraction coverage against the reference summary figures."""
import glob, json, os, re, sys
from rows import find_triple

base = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/ocr1/out"
truth = json.load(open(os.path.join(os.path.dirname(__file__), "truth_batch1.json")))


def pages(d):
    fs = glob.glob(f"{base}/{d}/p-*.txt")
    return sorted(fs, key=lambda x: int(re.findall(r"\d+", os.path.basename(x))[0]))


def extract(d):
    rows, seen = [], set()
    for f in pages(d):
        pg = int(re.findall(r"\d+", os.path.basename(f))[0])
        for ln in open(f, errors="ignore"):
            t = find_triple(ln)
            if not t:
                continue
            key = (round(t["q"], 1), round(t["r"]))
            if key in seen:
                continue
            seen.add(key)
            rows.append(dict(page=pg, line=ln.rstrip("\n"), **{k: t[k] for k in ("q", "r", "v", "repaired")}))
    return rows


if __name__ == "__main__":
    tot_t = tot_x = 0
    for d in sorted(truth):
        if d.startswith("_"):
            continue
        rows = extract(d)
        sold = sum(a["sold"] for a in truth[d])
        val = sum(a["value"] for a in truth[d])
        q = sum(r["q"] for r in rows); v = sum(r["v"] for r in rows)
        tot_t += sold; tot_x += min(q, sold)
        rep = sum(r["repaired"] for r in rows)
        print(f"{d[:30]:30s} lots={len(rows):4d} repaired={rep:3d} qty {q:10.1f}/{sold:10.1f} = {100*q/sold:5.1f}%  value {100*v/val:5.1f}%")
    print(f"OVERALL qty coverage {100*tot_x/tot_t:.1f}%")
