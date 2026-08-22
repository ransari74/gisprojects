#!/bin/sh
# Assemble each standalone book from the shared head + its body fragment,
# substituting cross-book links from links.json.
set -e
cd "$(dirname "$0")"
for body in src/[0-9]*.html; do
  base=$(basename "$body" .html)
  title=$(sed -n 's/.*<!--TITLE:\(.*\)-->.*/\1/p' "$body" | head -1)
  out="${base#*-}.html"
  sed "s|__TITLE__|$title|" src/_head.html > "$out"
  cat "$body" >> "$out"
  python3 - "$out" <<'PY'
import json,sys
p=sys.argv[1]; s=open(p,encoding='utf-8').read()
for k,v in json.load(open('links.json')).items(): s=s.replace(k,v)
open(p,'w',encoding='utf-8').write(s)
PY
  echo "built $out  ($(wc -c < "$out") bytes)  — $title"
done
