"""Bitget Demo Trading execution (paper orders on Bitget's demo environment).

Enabled only when all three credentials are present:
  BITGET_DEMO_API_KEY, BITGET_DEMO_API_SECRET, BITGET_DEMO_API_PASSPHRASE
Requests are signed per Bitget API v2 and carry the `paptrading: 1` header, which
routes them to Demo Trading. Nothing here can reach a live (real-money) account:
every request is sent with the demo header and the demo product type.

Demo symbols/product type differ from live; `discover()` reads the demo contract
list at runtime and maps each universe symbol, so no mapping is guessed.
"""
import base64
import hashlib
import hmac
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import net  # noqa: F401  (installs the resolver policy)

BASE = "https://api.bitget.com"
PRODUCT_TYPE = os.environ.get("BITGET_DEMO_PRODUCT_TYPE", "SUSDT-FUTURES")
MARGIN_COIN = os.environ.get("BITGET_DEMO_MARGIN_COIN", "SUSDT")


class DemoError(RuntimeError):
    pass


def configured() -> bool:
    return all(os.environ.get(k) for k in ("BITGET_DEMO_API_KEY", "BITGET_DEMO_API_SECRET", "BITGET_DEMO_API_PASSPHRASE"))


def sign(secret: str, timestamp: str, method: str, path: str, query: str = "", body: str = "") -> str:
    prehash = timestamp + method.upper() + path + (("?" + query) if query else "") + body
    return base64.b64encode(hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()


class BitgetDemo:
    def __init__(self, key=None, secret=None, passphrase=None, transport=None):
        self.key = key or os.environ.get("BITGET_DEMO_API_KEY", "")
        self.secret = secret or os.environ.get("BITGET_DEMO_API_SECRET", "")
        self.passphrase = passphrase or os.environ.get("BITGET_DEMO_API_PASSPHRASE", "")
        if not (self.key and self.secret and self.passphrase):
            raise DemoError("Bitget Demo credentials missing (BITGET_DEMO_API_KEY/SECRET/PASSPHRASE)")
        self._transport = transport or self._http
        self._contracts = None
        self.log: list[dict] = []  # every request/response, for the evidence trail

    # -- transport -------------------------------------------------------
    def _http(self, method, url, headers, body):
        req = urllib.request.Request(url, data=body.encode() if body else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read())
            except Exception:
                return {"code": str(e.code), "msg": str(e)}

    def request(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        query = urllib.parse.urlencode(params or {})
        body_s = json.dumps(body, separators=(",", ":")) if body else ""
        ts = str(int(time.time() * 1000))
        headers = {
            "ACCESS-KEY": self.key, "ACCESS-SIGN": sign(self.secret, ts, method, path, query, body_s),
            "ACCESS-TIMESTAMP": ts, "ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json", "locale": "en-US", "paptrading": "1",
        }
        url = BASE + path + (("?" + query) if query else "")
        resp = self._transport(method, url, headers, body_s)
        self.log.append({"ts": ts, "method": method, "path": path, "params": params, "body": body,
                         "code": resp.get("code"), "msg": resp.get("msg"), "data": resp.get("data")})
        if resp.get("code") != "00000":
            raise DemoError(f"{method} {path}: {resp.get('code')} {resp.get('msg')}")
        return resp.get("data")

    # -- market / account ------------------------------------------------
    def contracts(self) -> dict[str, dict]:
        if self._contracts is None:
            rows = self.request("GET", "/api/v2/mix/market/contracts", {"productType": PRODUCT_TYPE})
            self._contracts = {c["symbol"]: c for c in rows}
        return self._contracts

    def demo_symbol(self, live_symbol: str) -> str | None:
        """Map a live symbol (e.g. NVDAUSDT) to its demo contract, if Bitget lists one."""
        c = self.contracts()
        base = live_symbol[:-4] if live_symbol.endswith("USDT") else live_symbol
        for cand in (live_symbol, f"S{base}SUSDT", f"{base}SUSDT", f"S{live_symbol}"):
            if cand in c and c[cand].get("symbolStatus", "normal") == "normal":
                return cand
        return None

    def accounts(self):
        return self.request("GET", "/api/v2/mix/account/accounts", {"productType": PRODUCT_TYPE})

    def ticker(self, symbol):
        return self.request("GET", "/api/v2/mix/market/ticker", {"symbol": symbol, "productType": PRODUCT_TYPE})[0]

    def round_size(self, symbol: str, qty: float) -> float:
        c = self.contracts()[symbol]
        step = float(c.get("sizeMultiplier") or 10 ** -int(c.get("volumePlace", 3)))
        size = math.floor(qty / step) * step
        places = int(c.get("volumePlace", 3))
        size = round(size, places)
        if size < float(c.get("minTradeNum") or 0):
            raise DemoError(f"{symbol}: size {qty:.6f} below minimum {c.get('minTradeNum')}")
        return size

    # -- orders ------------------------------------------------------------
    def set_leverage(self, symbol: str, leverage: int = 2):
        return self.request("POST", "/api/v2/mix/account/set-leverage", body={
            "symbol": symbol, "productType": PRODUCT_TYPE, "marginCoin": MARGIN_COIN, "leverage": str(leverage)})

    def market_order(self, symbol: str, side: str, size: float, reduce_only: bool, client_oid: str) -> dict:
        body = {"symbol": symbol, "productType": PRODUCT_TYPE, "marginMode": "crossed", "marginCoin": MARGIN_COIN,
                "size": f"{size}", "side": side, "orderType": "market", "clientOid": client_oid}
        if reduce_only:
            body["reduceOnly"] = "YES"
        placed = self.request("POST", "/api/v2/mix/order/place-order", body=body)
        return self.order_detail(symbol, placed["orderId"])

    def order_detail(self, symbol: str, order_id: str, tries: int = 6) -> dict:
        d = {}
        for _ in range(tries):
            d = self.request("GET", "/api/v2/mix/order/detail",
                             {"symbol": symbol, "productType": PRODUCT_TYPE, "orderId": order_id})
            if d.get("state") in ("filled", "canceled", "cancelled"):
                break
            time.sleep(0.5)
        return {"orderId": order_id, "clientOid": d.get("clientOid"), "state": d.get("state"),
                "priceAvg": float(d.get("priceAvg") or 0), "baseVolume": float(d.get("baseVolume") or 0),
                "fee": float(d.get("fee") or 0), "cTime": d.get("cTime"), "symbol": symbol,
                "side": d.get("side"), "raw": d}

    # -- paired execution --------------------------------------------------
    def open_pair(self, legs: list[dict], tag: str) -> list[dict]:
        """legs: [{live_symbol, side (+1/-1), notional}]. All-or-nothing: if any leg fails, filled legs are flattened."""
        filled = []
        try:
            for i, leg in enumerate(legs):
                sym = self.demo_symbol(leg["live_symbol"])
                if not sym:
                    raise DemoError(f"{leg['live_symbol']} is not listed on Bitget Demo Trading")
                px = float(self.ticker(sym)["lastPr"])
                size = self.round_size(sym, leg["notional"] / px)
                self.set_leverage(sym)
                o = self.market_order(sym, "buy" if leg["side"] > 0 else "sell", size, False, f"{tag}-o{i}")
                if o["state"] != "filled":
                    raise DemoError(f"{sym} open order {o['orderId']} not filled (state {o['state']})")
                filled.append({**leg, "demo_symbol": sym, "size": size, "open_order": o})
        except Exception as e:
            rollback = self.close_pair(filled, tag + "-rollback") if filled else []
            raise DemoError(f"pair not opened: {e}; rolled back {len(rollback)} leg(s)") from e
        return filled

    def close_pair(self, legs: list[dict], tag: str) -> list[dict]:
        out = []
        for i, leg in enumerate(legs):
            o = self.market_order(leg["demo_symbol"], "sell" if leg["side"] > 0 else "buy", leg["size"], True, f"{tag}-c{i}")
            out.append({**leg, "close_order": o})
        return out


def realized(legs: list[dict]) -> dict:
    """P&L from exchange fills (fees as reported by Bitget, negative = cost)."""
    total, fees = 0.0, 0.0
    for l in legs:
        o, c = l["open_order"], l.get("close_order")
        if not c:
            continue
        total += l["side"] * (c["priceAvg"] - o["priceAvg"]) * min(o["baseVolume"], c["baseVolume"])
        fees += o["fee"] + c["fee"]
    return {"gross": total, "fees": fees, "net": total + fees}
