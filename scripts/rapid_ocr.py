"""OCR page images with RapidOCR (PP-OCR models) and write line-reconstructed text.
usage: python rapid_ocr.py <out_dir> <img> [<img> ...]   -> <out_dir>/<parent>/<stem>.txt
"""
import os, sys
from rapidocr_onnxruntime import RapidOCR

def lines_from(result):
    items = []
    for box, text, score in result or []:
        ys = [p[1] for p in box]; xs = [p[0] for p in box]
        items.append(((min(ys) + max(ys)) / 2, min(xs), max(ys) - min(ys), text))
    items.sort()
    lines, cur, cy = [], [], None
    for y, x, h, t in items:
        if cy is None or abs(y - cy) <= max(6, 0.55 * h):
            cur.append((x, t)); cy = y if cy is None else (cy * (len(cur) - 1) + y) / len(cur)
        else:
            lines.append(cur); cur = [(x, t)]; cy = y
    if cur: lines.append(cur)
    return ["   ".join(t for _, t in sorted(l)) for l in lines]

if __name__ == "__main__":
    out = sys.argv[1]; eng = RapidOCR()
    for f in sys.argv[2:]:
        res, _ = eng(f)
        d = os.path.join(out, os.path.basename(os.path.dirname(f))); os.makedirs(d, exist_ok=True)
        stem = os.path.splitext(os.path.basename(f))[0]
        open(os.path.join(d, stem + ".txt"), "w").write("\n".join(lines_from(res)) + "\n")
        print(f, len(res or []), flush=True)
