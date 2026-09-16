"""Bitget Demo client against a fake exchange: signing, symbol discovery, sizing, pair open/close, rollback."""
import base64
import hashlib
import hmac
import json
import unittest
import urllib.parse

from residual import demo


class FakeExchange:
    def __init__(self, fail_symbol=None, unfilled_symbol=None, pos_mode="one_way_mode"):
        self.orders, self.calls, self.fail, self.unfilled = {}, [], fail_symbol, unfilled_symbol
        self.pos_mode = pos_mode
        self.px = {"SNVDASUSDT": 200.0, "SQQQSUSDT": 500.0, "SAAPLSUSDT": 330.0}

    def __call__(self, method, url, headers, body):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        self.calls.append((method, u.path, headers, body))
        assert headers["paptrading"] == "1", "every request must carry the demo header"
        ok = lambda data: {"code": "00000", "msg": "success", "data": data}
        if u.path == "/api/v2/mix/market/contracts":
            return ok([{"symbol": s, "symbolStatus": "normal", "volumePlace": "2", "sizeMultiplier": "0.01",
                        "minTradeNum": "0.01"} for s in ("SNVDASUSDT", "SQQQSUSDT", "SAAPLSUSDT", "SBTCSUSDT")])
        if u.path == "/api/v2/mix/market/ticker":
            return ok([{"lastPr": str(self.px[q["symbol"]])}])
        if u.path == "/api/v2/mix/account/set-leverage":
            return ok({})
        if u.path == "/api/v2/mix/account/account":
            return ok({"marginCoin": "USDT", "available": "1000", "posMode": self.pos_mode})
        if u.path == "/api/v2/mix/order/place-order":
            b = json.loads(body)
            if b["symbol"] == self.fail:
                return {"code": "40762", "msg": "insufficient balance", "data": None}
            # the real exchange rejects an order whose format does not match the account's position mode
            if (self.pos_mode == "hedge_mode") != ("tradeSide" in b):
                return {"code": "40774", "msg": "The order type for unilateral position must also be the unilateral position type.", "data": None}
            oid = str(len(self.orders) + 1)
            self.orders[oid] = b
            return ok({"orderId": oid, "clientOid": b["clientOid"]})
        if u.path == "/api/v2/mix/order/detail":
            b = self.orders[q["orderId"]]
            state = "live" if b["symbol"] == self.unfilled else "filled"
            px = self.px[b["symbol"]]
            return ok({"state": state, "priceAvg": str(px), "baseVolume": b["size"], "side": b["side"],
                       "fee": str(-0.0006 * px * float(b["size"])), "clientOid": b["clientOid"], "cTime": "1"})
        return {"code": "404", "msg": "unknown " + u.path}


def client(ex):
    c = demo.BitgetDemo("k", "s", "p", transport=ex)
    return c


class DemoTests(unittest.TestCase):
    def test_signature_matches_bitget_v2_prehash(self):
        exp = base64.b64encode(hmac.new(b"sec", b"1700000000000GET/api/v2/x?a=1&b=2", hashlib.sha256).digest()).decode()
        self.assertEqual(demo.sign("sec", "1700000000000", "get", "/api/v2/x", "a=1&b=2"), exp)
        body = '{"a":1}'
        exp2 = base64.b64encode(hmac.new(b"sec", ("1POST/p" + body).encode(), hashlib.sha256).digest()).decode()
        self.assertEqual(demo.sign("sec", "1", "POST", "/p", "", body), exp2)

    def test_symbol_discovery_and_sizing(self):
        c = client(FakeExchange())
        self.assertEqual(c.demo_symbol("NVDAUSDT"), "SNVDASUSDT")
        self.assertIsNone(c.demo_symbol("PLTRUSDT"))
        self.assertEqual(c.round_size("SNVDASUSDT", 0.2567), 0.25)
        with self.assertRaises(demo.DemoError):
            c.round_size("SNVDASUSDT", 0.004)

    def test_pair_open_close_records_exchange_orders(self):
        ex = FakeExchange()
        c = client(ex)
        legs = c.open_pair([{"live_symbol": "NVDAUSDT", "side": 1, "notional": 100},
                            {"live_symbol": "QQQUSDT", "side": -1, "notional": 120}], "t1")
        self.assertEqual([l["open_order"]["side"] for l in legs], ["buy", "sell"])
        ex.px["SNVDASUSDT"] = 210.0
        closed = c.close_pair(legs, "t1")
        placed = [json.loads(b) for m, p, h, b in ex.calls if p.endswith("place-order")]
        self.assertEqual([p.get("reduceOnly") for p in placed], [None, None, "YES", "YES"])
        r = demo.realized(closed)
        self.assertAlmostEqual(r["gross"], 10.0 * 0.5)  # 0.5 NVDA long gained $10 each; QQQ flat
        self.assertLess(r["fees"], 0)
        self.assertTrue(all(e["code"] == "00000" for e in c.log))

    def test_hedge_mode_orders_use_position_side_and_trade_side(self):
        ex = FakeExchange(pos_mode="hedge_mode")
        c = client(ex)
        legs = c.open_pair([{"live_symbol": "NVDAUSDT", "side": 1, "notional": 100},
                            {"live_symbol": "QQQUSDT", "side": -1, "notional": 120}], "h1")
        c.close_pair(legs, "h1")
        placed = [json.loads(b) for m, p, h, b in ex.calls if p.endswith("place-order")]
        self.assertEqual([(p["symbol"], p["side"], p["tradeSide"], p.get("reduceOnly")) for p in placed],
                         [("SNVDASUSDT", "buy", "open", None), ("SQQQSUSDT", "sell", "open", None),
                          ("SNVDASUSDT", "buy", "close", None), ("SQQQSUSDT", "sell", "close", None)])

    def test_wrong_mode_format_is_rejected_like_the_real_exchange(self):
        ex = FakeExchange(pos_mode="hedge_mode")
        c = client(ex)
        c._pos_mode = "one_way_mode"  # simulate the old bug: one-way format sent to a hedge-mode account
        with self.assertRaises(demo.DemoError) as cm:
            c.open_pair([{"live_symbol": "NVDAUSDT", "side": 1, "notional": 100}], "h2")
        self.assertIn("40774", str(cm.exception))

    def test_failed_second_leg_rolls_back_first(self):
        ex = FakeExchange(fail_symbol="SQQQSUSDT")
        c = client(ex)
        with self.assertRaises(demo.DemoError) as cm:
            c.open_pair([{"live_symbol": "NVDAUSDT", "side": 1, "notional": 100},
                         {"live_symbol": "QQQUSDT", "side": -1, "notional": 120}], "t2")
        self.assertIn("rolled back 1", str(cm.exception))
        placed = [json.loads(b) for m, p, h, b in ex.calls if p.endswith("place-order")]
        self.assertEqual([(p["symbol"], p["side"], p.get("reduceOnly")) for p in placed],
                         [("SNVDASUSDT", "buy", None), ("SQQQSUSDT", "sell", None), ("SNVDASUSDT", "sell", "YES")])

    def test_unlisted_symbol_rejected_before_any_order(self):
        ex = FakeExchange()
        with self.assertRaises(demo.DemoError):
            client(ex).open_pair([{"live_symbol": "PLTRUSDT", "side": 1, "notional": 100}], "t3")
        self.assertFalse(any(p.endswith("place-order") for m, p, h, b in ex.calls))

    def test_credentials_required(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(demo.configured())
            with self.assertRaises(demo.DemoError):
                demo.BitgetDemo()


if __name__ == "__main__":
    unittest.main()
