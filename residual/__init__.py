"""RESIDUAL: event-neutral earnings agent for Bitget stock perpetuals."""
import os
from pathlib import Path

MODEL_VERSION = "residual-factor-v1"


def _load_env():
    """Load KEY=VALUE lines from .env / .env.local (any case) without overriding the environment."""
    root = Path(__file__).resolve().parent.parent
    for p in sorted(root.iterdir()):
        if p.is_file() and p.name.lower() in (".env", ".env.local"):
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()
