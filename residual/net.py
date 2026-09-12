"""HTTP access with a disk cache.

api.bitget.com is DNS-filtered on some networks, so Bitget hosts are resolved
through Cloudflare DNS-over-HTTPS. Every response used by the model is cached
under data/cache so replays are reproducible offline.
"""
import hashlib
import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
SEC_UA = os.environ.get("SEC_USER_AGENT", "RESIDUAL research residual@example.com")

_DOH_HOSTS = {"api.bitget.com"}
_resolved: dict[str, str] = {}
_orig_getaddrinfo = socket.getaddrinfo


def _doh_resolve(host: str) -> str:
    if host not in _resolved:
        req = urllib.request.Request(
            f"https://cloudflare-dns.com/dns-query?name={host}&type=A",
            headers={"accept": "application/dns-json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            answers = json.load(r).get("Answer", [])
        _resolved[host] = next(a["data"] for a in answers if a["type"] == 1)
    return _resolved[host]


_system_dns_failed: set[str] = set()


def _getaddrinfo(host, *args, **kwargs):
    if host in _DOH_HOSTS:
        if host not in _system_dns_failed:
            try:
                return _orig_getaddrinfo(host, *args, **kwargs)
            except socket.gaierror:
                _system_dns_failed.add(host)  # skip the slow failing lookup from now on
        return _orig_getaddrinfo(_doh_resolve(host), *args, **kwargs)
    return _orig_getaddrinfo(host, *args, **kwargs)


socket.getaddrinfo = _getaddrinfo


def _cache_path(url: str, suffix: str) -> Path:
    return CACHE / (hashlib.sha256(url.encode()).hexdigest()[:24] + suffix)


def fetch(url: str, *, cache: bool = True, retries: int = 3) -> bytes:
    """GET a URL. Cached responses are returned without touching the network."""
    path = _cache_path(url, ".bin")
    if cache and path.exists():
        return path.read_bytes()
    headers = {"User-Agent": SEC_UA if "sec.gov" in url else "residual/1.0"}
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=40) as r:
                body = r.read()
            if "sec.gov" in url:
                time.sleep(0.15)  # SEC fair-access: stay well under 10 req/s
            if cache:
                CACHE.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
                index = CACHE / "index.jsonl"
                with index.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"url": url, "file": path.name, "fetched_at": int(time.time())}) + "\n")
            return body
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last}")


def fetch_json(url: str, *, cache: bool = True):
    return json.loads(fetch(url, cache=cache))


def cache_file_for(url: str) -> str:
    return "data/cache/" + _cache_path(url, ".bin").name
