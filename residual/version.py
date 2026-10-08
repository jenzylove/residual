"""Deployment stamp: web/version.json ties a deployed site to a commit and to the exact data files it serves."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HASHED = ("data/results.json", "data/events.json", "data/ledger.csv", "web/data.json")
CRLF, LF = bytes([13, 10]), bytes([10])


def _commit(root: Path) -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except Exception:
        return None


def write_version(root: Path) -> dict:
    """`commit` is the commit the data was built from; the stamp itself lands in the commit after it."""
    root = Path(root)
    # hash the bytes as committed and served (LF): a Windows checkout holds CRLF copies of the same files
    files = {rel: hashlib.sha256((root / rel).read_bytes().replace(CRLF, LF)).hexdigest()
             for rel in HASHED if (root / rel).is_file()}
    res = {}
    if (root / "data/results.json").is_file():
        res = json.loads((root / "data/results.json").read_text(encoding="utf-8"))
    out = {"project": "residual", "commit": _commit(root),
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "model_version": res.get("model_version"), "extractor_version": res.get("extractor_version"),
           "sha256": files}
    (root / "web").mkdir(parents=True, exist_ok=True)
    (root / "web/version.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out
