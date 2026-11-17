#!/bin/bash
# Vercel build: copy the UI front-end from ui/ into this app dir when the repo
# is present (git deploys). The copies are committed so CLI deploys from a
# shallow checkout (or CI machines without ../ui/) still get the assets.
# map.js loads only when the runtime injects a token, so it ships verbatim.
#
# The explorer ships as explorer.html (NOT index.html): the landing page owns
# "/" — a static index.html at the output root would win over the / rewrite.
set -e
cd "$(dirname "$0")"
if [ -f ../ui/explorer.html ]; then
  cp ../ui/explorer.html explorer.html
  # landing.html serves "/" via the vercel.json rewrite. It was missing from
  # this copy list, so the deployed landing page silently drifted from ui/
  # for every content change (it shipped 9,309 moves / 799 kitchens / a
  # pedigree of 73 long after ui/ said otherwise).
  cp ../ui/landing.html landing.html
  cp ../ui/method.html method.html
  cp ../ui/map.js map.js
  cp ../ui/city_venues.json city_venues.json
  cp ../ui/venues_geo.json venues_geo.json
  cp ../ui/city_venues.json api/city_venues.json
  cp ../ui/venues_geo.json api/venues_geo.json
  cp ../ui/map.js api/_map.js
  cp ../ui/score_sample.json api/score_sample.json
  # The shared venue-identity path. stats() and dossier matching must count
  # the same kitchens locally and on Vercel; this file is stdlib-only
  # precisely so it can ship here without the src/ package.
  cp ../src/venue_aliases.py api/venue_aliases.py
  cp ../ui/venue_aliases.json api/venue_aliases.json
  echo "vercel-app build: UI assets copied from ui/"
else
  echo "vercel-app build: using committed copies"
fi
