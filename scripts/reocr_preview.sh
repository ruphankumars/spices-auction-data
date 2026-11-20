#!/bin/bash
# re-OCR one preview jpg: 2x upscale + light denoise, psm 6
f="$1"; rel="${f#/home/claude/ocr1/out/}"; o="/home/claude/ocr2/out/${rel%.jpg}"
mkdir -p "$(dirname "$o")"
convert "$f" -colorspace Gray -resize 200% -median 1 "$o.png"
OMP_THREAD_LIMIT=1 tesseract "$o.png" "$o" --psm 6 -c preserve_interword_spaces=1 >/dev/null 2>&1
rm -f "$o.png"
