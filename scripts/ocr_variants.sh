#!/usr/bin/env bash
# Extra RapidOCR reads of the same pages under different renderings, for reports whose books do not close yet.
# Each rendering makes independent mistakes; the checksum decoder merges them. Text only.
set -euo pipefail
cd work
for pdf in pdf/*.pdf; do
  stem=$(basename "$pdf" .pdf)
  mkdir -p "png/hi/$stem" "png/sharp/$stem" "png/level/$stem"
  pdftoppm -r 450 -gray -png "$pdf" "png/hi/$stem/p"
  pdftoppm -r 300 -gray -png "$pdf" "png/sharp/$stem/p"
  for f in png/sharp/$stem/p-*.png; do
    convert "$f" -level 15%,85% "png/level/$stem/$(basename "$f")"
    convert "$f" -unsharp 0x2+1.5+0.02 "$f"
  done
done
i=0
for v in hi sharp level; do
  find "png/$v" -name 'p-*.png' | sort > "list_$v.txt"
  (xargs -a "list_$v.txt" python ../scripts/rapid_ocr.py "out/pass_$v" > "log_$v" 2>&1 || true) &
  i=$((i+1)); if [ $((i % 2)) -eq 0 ]; then wait; fi
done
wait
tail -n 1 log_* || true
rm -rf png list_*.txt log_*
find out -name '*.txt' | wc -l
