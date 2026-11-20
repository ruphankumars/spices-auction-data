#!/usr/bin/env bash
# Extra OCR passes on full-resolution pages. Output text only: work/out/<pass>/<stem>/p-N.txt
set -euo pipefail
cd work
mkdir -p png
for pdf in pdf/*.pdf; do
  stem=$(basename "$pdf" .pdf); mkdir -p "png/$stem"
  pdftoppm -r 300 -gray -png "$pdf" "png/$stem/p"
done
# pass C: RapidOCR (PP-OCR) on 300 dpi pages, 2 processes
find png -name 'p-*.png' | sort > all.txt
split -n l/2 all.txt chunk_
for c in chunk_*; do (xargs -a "$c" python ../scripts/rapid_ocr.py out/passC > "log_$c" 2>&1 || true) & done
# pass D/E: Tesseract on denoised 1.5x pages, two layouts
tess() { png="$1"; rel="${png#png/}"; b="${rel%.png}"
  mkdir -p "out/passD/$(dirname "$b")" "out/passE/$(dirname "$b")"
  convert "$png" -resize 150% -median 1 "/tmp/$(echo "$b" | tr / _).png"
  t="/tmp/$(echo "$b" | tr / _).png"
  OMP_THREAD_LIMIT=1 tesseract "$t" "out/passD/$b" --psm 4 -c preserve_interword_spaces=1 >/dev/null 2>&1 || true
  OMP_THREAD_LIMIT=1 tesseract "$t" "out/passE/$b" --psm 11 >/dev/null 2>&1 || true
  rm -f "$t"; }
export -f tess
[ -n "${ONLY_RAPID:-}" ] || xargs -a all.txt -P 2 -I{} bash -c 'tess "$@"' _ {}
wait
tail -n 2 log_chunk_* || true
rm -rf png all.txt chunk_* log_chunk_*
find out -name '*.txt' | wc -l
