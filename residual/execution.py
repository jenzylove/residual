"""Isolated Bitget Demo Trading request boundary.

The paper and live-watcher paths never import this module. It builds signed
requests for the future authenticated integration, but deliberately performs
no network call and exposes no order method. The first private step is the
read-only Demo account verification requested by the operator.
"""
import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass


BASE = "https://api.bitget.com"


class DemoCredentialsRequired(RuntimeError):
    """Raised when the private Demo adapter is used without all three keys."""


@dataclass(frozen=True)
class SignedRequest:
    method: str
    path: str
    query: str
    body: str
    url: str
    headers: dict[str, str]


class BitgetDemoExecutionAdapter:
    """Build, but do not send, authenticated Demo Trading requests."""

    def __init__(self, api_key: str, secret_key: str, passphrase: str, base_url: str = BASE):
        if not api_key or not secret_key or not passphrase:
            raise DemoCredentialsRequired("BITGET_API_KEY, BITGET_SECRET_KEY and BITGET_PASSPHRASE are required")
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.base_url = base_url.rstrip("/")

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("BITGET_API_KEY", ""),
                   os.environ.get("BITGET_SECRET_KEY", ""),
                   os.environ.get("BITGET_PASSPHRASE", ""))

    def build_request(self, method: str, path: str, query: str = "", body: str = "",
                      timestamp: str | None = None) -> SignedRequest:
        method = method.upper()
        query = query.lstrip("?")
        query_part = f"?{query}" if query else ""
        timestamp = timestamp or str(int(time.time() * 1000))
        prehash = timestamp + method + path + query_part + body
        signature = base64.b64encode(
            hmac.new(self.secret_key.encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        return SignedRequest(
            method=method, path=path, query=query, body=body,
            url=f"{self.base_url}{path}{query_part}",
            headers={
                "ACCESS-KEY": self.api_key,
                "ACCESS-SIGN": signature,
                "ACCESS-TIMESTAMP": timestamp,
                "ACCESS-PASSPHRASE": self.passphrase,
                "Content-Type": "application/json",
                "locale": "en-US",
                "paptrading": "1",
            },
        )

    def build_account_read_request(self, timestamp: str | None = None) -> SignedRequest:
        """Prepare the first safe private call; no request is sent."""
        return self.build_request(
            "GET", "/api/v2/mix/account/accounts", "productType=USDT-FUTURES", timestamp=timestamp
        )
