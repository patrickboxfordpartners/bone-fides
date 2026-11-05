"""Set Vercel env vars from local .env without echoing values to the transcript.

Usage: .venv/bin/python src/vercel_env_set.py NAME[:target,...] [NAME2 ...]
Target defaults to all three: production,preview,development.
Values are piped to `vercel env add` via stdin (never argv).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "vercel-app"

with open(ROOT / ".env") as f:
    vals = {}
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip().strip('"').strip("'")

ALL = ("production", "preview", "development")
for spec in sys.argv[1:]:
    name, _, targets = spec.partition(":")
    targets = targets or "production,preview,development"
    if name not in vals:
        print(f"SKIP {name}: not in .env")
        continue
    for target in targets.split(","):
        target = target.strip()
        p = subprocess.run(
            ["vercel", "env", "add", name, target, "--force", "--yes"],
            cwd=APP, input=(vals[name] + "\n").encode(),
            capture_output=True, timeout=60,
        )
        msg = (p.stdout or p.stderr).decode().strip().splitlines()
        tail = msg[-1][:100] if msg else ""
        print(f"{name} {target}: rc={p.returncode} {tail}")
