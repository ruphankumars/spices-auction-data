#!/usr/bin/env bash
# Render every downloaded PDF page and OCR it. Outputs under work/out/<file-stem>/
set -euo pipefail
cd work
for pdf in pdf/*.pdf; do
  stem=$(basename "$pdf" .pdf); o="out/$stem"; mkdir -p "$o"
  pdfimages -list "$pdf" > "$o/images.txt" || true
  pdftoppm -r 300 -gray -png "$pdf" "$o/p"
  for png in "$o"/p-*.png; do
    b="${png%.png}"
    tesseract "$png" "$b" --psm 6 -l eng tsv txt >/dev/null 2>&1 || echo "ocr fail $png"
    # small preview for visual checking
    convert "$png" -resize 50% -quality 70 "$b.jpg"
    rm "$png"
  done
done
du -sh out
