#!/usr/bin/env bash
# Render every downloaded PDF page and OCR it, 4 pages in parallel.
# Outputs under work/out/<file-stem>/ : p-N.tsv (word boxes), p-N.txt, p-N.jpg (preview)
set -euo pipefail
cd work
for pdf in pdf/*.pdf; do
  stem=$(basename "$pdf" .pdf); o="out/$stem"; mkdir -p "$o"
  pdfimages -list "$pdf" > "$o/images.txt" || true
  pdftoppm -r 300 -gray -png "$pdf" "$o/p"
done
ocr_one() {
  png="$1"; b="${png%.png}"
  python3 "$GITHUB_WORKSPACE/scripts/preprocess.py" "$png" "$b.clean.png"
  OMP_THREAD_LIMIT=1 tesseract "$b.clean.png" "$b" --psm 6 -l eng -c preserve_interword_spaces=1 tsv txt >/dev/null 2>&1 || echo "ocr fail $png"
  convert "$png" -resize 50% -quality 70 "$b.jpg"
  rm -f "$b.clean.png"
  rm "$png"
}
export -f ocr_one
find out -name 'p-*.png' | sort | xargs -P 4 -I{} bash -c 'ocr_one "$@"' _ {}
du -sh out
