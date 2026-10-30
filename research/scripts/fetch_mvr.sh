#!/usr/bin/env bash
# Download the messivsronaldo.app page data used by the pipeline into research/mvr/.
# These files are third-party data and are not stored in this repository.
# Usage: bash research/scripts/fetch_mvr.sh   (run from the repository root)
set -euo pipefail
out="$(dirname "$0")/../mvr"
mkdir -p "$out"
pages=(
  all-time-stats/stats-by-age all-time-stats/vs-top-sides all-time-stats/uefa-club-rankings
  club-stats/champions-league club-stats/el-clasico
  international-stats/world-cup-stats international-stats/copa-euros-stats international-stats/fifa-rankings
  detailed-stats/record-in-finals honours-and-achievements individual-awards
  match-histories/ronaldo-match-history match-histories/messi-match-history index
)
for p in "${pages[@]}"; do
  if [ "$p" = "index" ]; then f="page-data_index_page-data.json"; else f="$(echo "$p" | tr '/' '_').json"; fi
  curl -sSf -A "Mozilla/5.0" "https://www.messivsronaldo.app/page-data/$p/page-data.json" -o "$out/$f"
  echo "fetched $p"
  sleep 1
done
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$out/fetched_at.txt"
