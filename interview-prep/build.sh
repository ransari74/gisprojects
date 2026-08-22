#!/bin/sh
# Rebuild index.html from the ordered fragments in src/.
set -e
cd "$(dirname "$0")"
cat src/*.html > index.html
echo "built index.html: $(wc -c < index.html) bytes, $(grep -c '<section id=' index.html) sections"
