"""Publish downloaded venue photos to Vercel Blob and point the cache at them.

src/venue_images.py downloads photos into ui/venue-images/ (gitignored) and
records each as a relative "venue-images/<file>" url in crawl/venue_images.json.
This script uploads every referenced file once per distinct content (exact
duplicates share one blob) and rewrites those urls to the public Blob URLs.
Files no record references are skipped and listed.

Needs VENUE_IMAGES_READ_WRITE_TOKEN (the bone-fides-venue-images Blob store,
connected to the Vercel project). Safe to re-run: published urls are skipped.

Usage: .venv/bin/python scripts/publish_venue_images.py [--dry-run]
"""
import argparse
import hashlib
import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
from src.cli import load_env  # noqa: E402

CACHE = os.path.join(BASE, "crawl", "venue_images.json")
IMG_DIR = os.path.join(BASE, "ui", "venue-images")
LOCAL_PREFIX = "venue-images/"


def upload(token, pathname, path):
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(
        "https://blob.vercel-storage.com/" + urllib.parse.quote(pathname),
        data=data, method="PUT",
        headers={
            "Authorization": "Bearer " + token,
            "x-api-version": "7",
            "x-content-type": mimetypes.guess_type(path)[0] or "application/octet-stream",
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
            "x-cache-control-max-age": "31536000",
        })
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["url"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    load_env(os.path.join(BASE, ".env"))

    cache = json.load(open(CACHE))
    pending = {k: v for k, v in cache.items()
               if isinstance(v, dict) and (v.get("url") or "").startswith(LOCAL_PREFIX)}
    by_hash, missing = {}, []
    for key, rec in pending.items():
        path = os.path.join(IMG_DIR, rec["url"][len(LOCAL_PREFIX):])
        if not os.path.exists(path):
            missing.append(rec["url"])
            continue
        digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
        by_hash.setdefault(digest, {"path": path, "keys": []})["keys"].append(key)

    referenced = {rec["url"][len(LOCAL_PREFIX):] for rec in pending.values()}
    orphans = sorted(set(os.listdir(IMG_DIR)) - referenced) if os.path.isdir(IMG_DIR) else []
    print(f"{len(pending)} local urls, {len(by_hash)} distinct files, "
          f"{len(missing)} missing on disk, {len(orphans)} unreferenced files")
    if args.dry_run:
        return 0

    token = os.environ.get("VENUE_IMAGES_READ_WRITE_TOKEN")
    if not token:
        print("VENUE_IMAGES_READ_WRITE_TOKEN is not set", file=sys.stderr)
        return 1

    def publish(group):
        return group, upload(token, LOCAL_PREFIX + os.path.basename(group["path"]), group["path"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        for n, (group, url) in enumerate(pool.map(publish, by_hash.values()), 1):
            for key in group["keys"]:
                cache[key]["url"] = url
            if n % 100 == 0:
                print(f"  {n}/{len(by_hash)} uploaded")

    with open(CACHE, "w") as f:
        json.dump(cache, f, indent=1, sort_keys=True)  # same format src/venue_images.py writes
    print(f"published {len(by_hash)} files; missing: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
