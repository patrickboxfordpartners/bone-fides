#!/bin/bash
# Vercel build step (vercel.json "buildCommand"). Assembles this deploy dir
# from the sources of truth; none of the copied files are committed.
#
#   ui/*.html                      -> public/, the only static output (so no
#                                     source file in this dir is ever served)
#   src/{dossier,es_query,roles,venue_aliases}.py
#                                  -> api/_lib/, the code api/search.py imports
#   ui/{map.js,*.json data}        -> api/_lib/, the files dossier.data_path() reads
#
# The Vercel project needs "Include source files outside of the Root
# Directory" enabled (it is), so ../ui and ../src exist during the build.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f ../ui/explorer.html ] || [ ! -f ../src/dossier.py ]; then
  echo "vercel-app build: ../ui or ../src is missing; deploy from the repo root" >&2
  exit 1
fi

# The explorer ships as explorer.html, not index.html: a static index.html at
# the output root would win over the "/" -> landing.html rewrite.
rm -rf public
mkdir -p public
cp ../ui/explorer.html ../ui/landing.html ../ui/method.html public/

rm -rf api/_lib
mkdir -p api/_lib
touch api/_lib/__init__.py
cp ../src/dossier.py ../src/es_query.py ../src/roles.py ../src/venue_aliases.py api/_lib/
cp ../ui/map.js ../ui/city_venues.json ../ui/venues_geo.json ../ui/score_sample.json \
   ../ui/venue_aliases.json api/_lib/

echo "vercel-app build: pages and api/_lib assembled from ui/ and src/"
