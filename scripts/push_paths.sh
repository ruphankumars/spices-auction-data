#!/usr/bin/env bash
# Commit the given paths on top of the latest origin/main and push, retrying when
# another job pushed first. Never rebases (so a regenerated file cannot conflict):
# the paths' current contents are saved, the checkout moved to origin/main, the
# contents put back, committed, pushed.
# Usage: push_paths.sh "<message>" <path>...
set -uo pipefail
MSG="$1"; shift
git config user.name ocr-bot; git config user.email ocr-bot@users.noreply.github.com
TMP=$(mktemp -d); tar -cf "$TMP/p.tar" --ignore-failed-read "$@" 2>/dev/null || true
for i in 1 2 3 4 5 6 7 8 9 10; do
  git fetch -q origin main && git reset -q --hard origin/main
  tar -xf "$TMP/p.tar" 2>/dev/null || true
  for f in "$@"; do if [ -e "$f" ]; then git add -A -- "$f"; elif git ls-files --error-unmatch "$f" >/dev/null 2>&1; then git rm -q --cached -- "$f"; fi; done
  if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
  git commit -qm "$MSG"
  if git push -q origin HEAD:main; then echo "pushed: $MSG"; exit 0; fi
  sleep $((i * 4 + RANDOM % 7))
done
echo "push failed"; exit 1
