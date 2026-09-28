#!/usr/bin/env bash
# Usage: web/scripts/measure.sh [base_url]   (default http://127.0.0.1:3000)
# Prints bytes on the wire (gzip requested), raw bytes and TTFB per route.
set -euo pipefail
BASE="${1:-http://127.0.0.1:3000}"
for path in / /deals "/movers?window=7d" "/products?category=gpu" /product/1; do
  wire=$(curl -s -o /dev/null -H 'Accept-Encoding: gzip, br' -w '%{size_download}' "$BASE$path")
  raw=$(curl -s -o /dev/null -w '%{size_download}' "$BASE$path")
  ttfb=$(curl -s -o /dev/null -w '%{time_starttransfer}' "$BASE$path")
  printf '%-26s wire=%8s raw=%8s ttfb=%ss\n' "$path" "$wire" "$raw" "$ttfb"
done
