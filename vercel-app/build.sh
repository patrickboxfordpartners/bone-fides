#!/bin/bash
# Vercel build: copy the UI front-end from ui/ into this app dir when the repo
# is present (git deploys). The copies are committed so CLI deploys from a
# shallow checkout (or CI machines without ../ui/) still get the assets.
# map.js loads only when the runtime injects a token, so it ships verbatim.
set -e
cd "$(dirname "$0")"
if [ -f ../ui/index.html ]; then
  cp ../ui/index.html index.html
  cp ../ui/map.js map.js
  cp ../ui/city_venues.json city_venues.json
  cp ../ui/venues_geo.json venues_geo.json
  cp ../ui/city_venues.json api/city_venues.json
  cp ../ui/venues_geo.json api/venues_geo.json
  cp ../ui/map.js api/_map.js
  echo "vercel-app build: UI assets copied from ui/"
else
  echo "vercel-app build: using committed copies"
fi
