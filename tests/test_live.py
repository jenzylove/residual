"""Deterministic end-to-end fixture for the live watcher lifecycle:
new filing -> event record -> PENDING -> gated decision -> paper pair opened -> closed."""
import json
import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from residual import events, live, market

HOUR = 3_600_000
RELEASE = 1_790_000_000_000 - 1_790_000_000_000 % HOUR + 20 * 60_000  # 20 min past an hour


def _filing(acc, day):
    return {"ticker": "NVDA", "cik": 1045810, "accession": acc, "filing_date": day,
            "accepted_et": f"{day}T20:20:00", "index_url": "https://example/idx/"}


def _fake_exchange():
    try:
        from test_demo import FakeExchange  # discover -s tests
    except ImportError:
        from tests.test_demo import FakeExchange  # python -m unittest tests.test_live
    return FakeExchange


PREV = _filing("0001-26-000001", "2026-08-26")
NEW = _filing("0001-26-000099", "2026-09-22")


def _event(filing, release_ms):
    return {"event_id": f"NVDA-{filing['filing_date']}", "ticker": "NVDA", "company_symbol": "NVDAUSDT",
            "accession": filing["accession"], "release_ms": release_ms,
            "release_utc": filing["accepted_et"] + "Z", "status": "complete",
            "surprise": {"guidance_surprise_pct": 3.0},
            "source": {"press_release_url": "https://example/pr.htm", "sha256": "0" * 64}}


class Book:
    """Order book whose prices rise over time so the long leg makes money."""
    def __init__(self):
        self.px = {"NVDAUSDT": 200.0, "QQQUSDT": 500.0}

    def __call__(self, symbol):
        p = self.px.get(symbol, 100.0)
        return {"symbol": symbol, "bid": p - 0.01, "ask": p + 0.01, "last": p, "spread_bps": 1.0,
                "bid_depth_10bps_usdt": 1e6, "ask_depth_10bps_usdt": 1e6, "funding_rate": 0.0, "ts": 0}


GATES = {k: (True, "fixture") for k in ("event_data", "market_data", "hedge", "liquidity", "robust", "reaction_open")}
ANALYSIS = {"gates": GATES, "residual": 0.03, "costs": {"round_trip": 0.002},
            "hedge": {"symbol": "QQQUSDT", "beta": 1.2}}


def _analysis(ev, snap, pool=None):
    out = copy.deepcopy(ANALYSIS)
    if pool is not None:
        # A Demo-mode analysis must use the declared Demo hedge universe,
        # never the main-mode ETF from the fixture.
        out["hedge"] = {"symbol": "AAPLUSDT", "beta": 0.8}
    return out


class LiveLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.book = Book()
        prev_ev = _event(PREV, RELEASE - 27 * 24 * HOUR)
        patches = [
            mock.patch.object(events, "EVENTS_FILE", self.tmp / "events.json"),
            mock.patch.object(live, "LIVE_LOG", self.tmp / "live_log.jsonl"),
            mock.patch.object(live, "POSITIONS", self.tmp / "positions.json"),
            mock.patch.object(live, "PENDING", self.tmp / "pending.json"),
            mock.patch.object(live.edgar, "earnings_filings",
                              lambda t, cache=False: [PREV, NEW] if t == "NVDA" else []),
            mock.patch.object(live.events, "build_event", lambda f, prev: _event(f, RELEASE)),
            mock.patch.object(live.events, "source_raw", lambda *a, **k: b"<p>fixture</p>"),
            mock.patch.object(live.market, "build_snapshot", lambda ev, c, now_ms=None: {"event_id": ev["event_id"]}),
            mock.patch.object(live.market, "save_snapshot", lambda snap: None),
            mock.patch.object(live.bitget, "contracts", lambda cache=False: {}),
            mock.patch.object(live, "analyze", _analysis),
            mock.patch.object(live, "_history_params", lambda ds, before: {"mode": 1, "k": 2.0, "source": "fixture"}),
            mock.patch.object(live, "interpret", lambda ev, a, text: {"status": "ok", "label": "durable", "confidence": 0.8}),
            mock.patch.object(live, "probe", self.book),
            # never touch a real exchange from tests, even if demo keys are in .env.local
            mock.patch.object(live.demo, "configured", lambda: False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        events.save_events([prev_ev])

    def test_full_lifecycle(self):
        t_obs = market.event_times(RELEASE)["t_obs"]

        # 1) new filing appears before the reaction window closes -> event record + PENDING
        r1 = live.watch(now_ms=RELEASE + 10 * 60_000)
        self.assertEqual(r1["decision"], "PENDING")
        ids = [e["event_id"] for e in events.load_events()]
        self.assertIn("NVDA-2026-09-22", ids)
        self.assertEqual(json.loads(live.PENDING.read_text()), ["NVDA-2026-09-22"])

        # 2) next run inside the entry window -> gated TRADE, both legs opened at live bid/ask
        r2 = live.watch(now_ms=t_obs + 10 * 60_000)
        self.assertEqual(r2["decision"], "TRADE")
        pos = r2["new_events"][0]["position"]
        self.assertEqual([l["symbol"] for l in pos["legs"]], ["NVDAUSDT", "QQQUSDT"])
        self.assertEqual([l["side"] for l in pos["legs"]], [1, -1])
        self.assertAlmostEqual(pos["legs"][0]["entry_price"], 200.01)   # long pays the ask
        self.assertAlmostEqual(pos["legs"][1]["qty"] * pos["legs"][1]["entry_price"], 1.2 * live.BASE_NOTIONAL, places=3)
        self.assertEqual(json.loads(live.PENDING.read_text()), [])
        self.assertEqual(len(events.load_events()), 2)  # the filing is not re-added

        # 3) after the horizon -> position closed at the live bid/ask, run records NO_TRADE
        self.book.px["NVDAUSDT"] = 210.0
        r3 = live.watch(now_ms=pos["exit_due_ms"] + 1)
        self.assertEqual(r3["decision"], "NO_TRADE")
        closed = r3["closed_positions"][0]
        self.assertEqual(closed["status"], "closed")
        expected = (209.99 - 200.01) * pos["legs"][0]["qty"] - (500.01 - 499.99) * pos["legs"][1]["qty"] \
            - sum(l["entry_fee"] + l["exit_fee"] for l in closed["legs"])
        self.assertAlmostEqual(closed["net_pnl"], expected, places=6)
        self.assertEqual(len(live.load_live_log()), 3)

    def test_lifecycle_through_bitget_demo(self):
        FakeExchange = _fake_exchange()
        ex = FakeExchange()
        real_client = live.demo.BitgetDemo  # capture before patching, or the factory calls itself
        make = lambda: real_client("k", "s", "p", transport=ex)
        with mock.patch.object(live.demo, "configured", lambda: True), \
             mock.patch.object(live.demo, "BitgetDemo", make):
            t_obs = market.event_times(RELEASE)["t_obs"]
            live.watch(now_ms=RELEASE + 10 * 60_000)                      # PENDING
            r2 = live.watch(now_ms=t_obs + 10 * 60_000)                  # demo orders placed
            pos = r2["new_events"][0]["position"]
            self.assertEqual(pos["execution"], "bitget_demo")
            self.assertEqual(pos["strategy_mode"], "demo_executable")
            self.assertEqual([l["demo_symbol"] for l in pos["demo_legs"]], ["SNVDASUSDT", "SAAPLSUSDT"])
            self.assertTrue(all(l["open_order"]["state"] == "filled" for l in pos["demo_legs"]))
            ex.px["SNVDASUSDT"] = 205.0
            r3 = live.watch(now_ms=pos["exit_due_ms"] + 1)               # closed with reduce-only orders
            closed = r3["closed_positions"][0]
            self.assertEqual(closed["status"], "closed")
            self.assertGreater(closed["realized"]["gross"], 0)
            self.assertTrue(any(e["path"].endswith("place-order") and e["body"].get("reduceOnly") == "YES"
                                for e in closed["exchange_log"]))

    def test_demo_refuses_unlisted_hedge_before_any_order(self):
        FakeExchange = _fake_exchange()
        ex = FakeExchange()
        ex.px["SAAPLSUSDT"] = 330.0
        real_contracts = ex.__call__
        def no_qqq(method, url, headers, body):
            r = real_contracts(method, url, headers, body)
            if url.split("?")[0].endswith("/market/contracts"):
                r["data"] = [c for c in r["data"] if c["symbol"] != "SQQQSUSDT"] + [
                    {"symbol": "SAAPLSUSDT", "symbolStatus": "normal", "volumePlace": "2", "sizeMultiplier": "0.01", "minTradeNum": "0.01"}]
            return r
        real_client = live.demo.BitgetDemo
        with mock.patch.object(live.demo, "configured", lambda: True), \
             mock.patch.object(live.demo, "BitgetDemo", lambda: real_client("k", "s", "p", transport=no_qqq)), \
             mock.patch.object(live, "analyze", lambda ev, snap, pool=None: ANALYSIS):
            t_obs = market.event_times(RELEASE)["t_obs"]
            live.watch(now_ms=RELEASE + 10 * 60_000)
            r = live.watch(now_ms=t_obs + 10 * 60_000)
            rec = r["new_events"][0]
            self.assertEqual(rec["decision"], "NO_TRADE")
            self.assertIn("strict Demo mode refuses substitution", rec["reason"])
            self.assertFalse(any(p.endswith("/place-order") for m, p, h, b in ex.calls))

    def test_demo_rejects_company_outside_demo_universe_before_market_or_orders(self):
        ev = {**_event(NEW, RELEASE), "ticker": "AMD", "company_symbol": "AMDUSDT", "event_id": "AMD-x"}
        with mock.patch.object(live.demo, "configured", lambda: True), \
             mock.patch.object(live.market, "build_snapshot") as build:
            out = live.evaluate(ev, [ev], market.event_times(RELEASE)["t_obs"] + 1, {})
        self.assertEqual(out["decision"], "NO_TRADE")
        self.assertEqual(out["strategy_mode"], "demo_executable")
        self.assertIn("not listed on Bitget Demo", out["reason"])
        build.assert_not_called()

    def test_live_applies_walk_forward_variant_before_opening(self):
        t_obs = market.event_times(RELEASE)["t_obs"]
        with mock.patch.object(live, "learn_variant", return_value={
                "variant": "headline", "source": "fixture", "scores": {},
                "eligible_variants": ["residual", "headline", "agreement"]}), \
             mock.patch.object(live, "variant_direction", return_value=-1):
            live.watch(now_ms=RELEASE + 10 * 60_000)
            out = live.watch(now_ms=t_obs + 10 * 60_000)
        self.assertEqual(out["new_events"][0]["variant"]["variant"], "headline")
        self.assertEqual([l["side"] for l in out["new_events"][0]["position"]["legs"]], [-1, 1])

    def test_mature_live_snapshot_is_completed_for_future_learning(self):
        ev = _event(NEW, RELEASE)
        t_exit = market.event_times(RELEASE)["t_exit"]
        state = {"event_id": ev["event_id"], "candles": {"NVDAUSDT": [[t_exit - HOUR]]}}
        completed = {"event_id": ev["event_id"], "candles": {"NVDAUSDT": [[t_exit]]}}

        def save(snap):
            state.clear()
            state.update(snap)

        with mock.patch.object(live.market, "load_snapshot", lambda eid: state), \
             mock.patch.object(live.market, "build_snapshot", return_value=completed) as build, \
             mock.patch.object(live.market, "save_snapshot", save):
            refreshed = live._refresh_mature_snapshots([ev], t_exit + 1, {})
        self.assertEqual(refreshed, [ev["event_id"]])
        self.assertTrue(live._snapshot_complete(ev, state))
        build.assert_called_once()

    def test_trade_after_entry_window_is_rejected(self):
        t_obs = market.event_times(RELEASE)["t_obs"]
        r = live.watch(now_ms=t_obs + 2 * HOUR)
        self.assertEqual(r["new_events"][0]["decision"], "NO_TRADE")
        self.assertIn("entry_window_passed", r["new_events"][0]["reason"])


class PartialCloseTest(unittest.TestCase):
    """Bitget Demo close is restart safe: partial closes persist, retries touch only open legs."""
    def setUp(self):
        FakeExchange = _fake_exchange()
        self.ex = FakeExchange()
        self.tmp = Path(tempfile.mkdtemp())
        real = live.demo.BitgetDemo
        self.make = lambda: real("k", "s", "p", transport=self.ex)
        for p in (mock.patch.object(live, "POSITIONS", self.tmp / "positions.json"),
                  mock.patch.object(live.demo, "BitgetDemo", self.make)):
            p.start()
            self.addCleanup(p.stop)
        legs = self.make().open_pair([{"live_symbol": "NVDAUSDT", "side": 1, "notional": 100.0},
                                      {"live_symbol": "AAPLUSDT", "side": -1, "notional": 80.0}], "NVDA2026")
        self.pos = {"event_id": "NVDA-2026-09-22", "status": "open", "execution": "bitget_demo",
                    "exit_due_ms": 1000, "demo_legs": legs, "exchange_log": []}
        live._write(live.POSITIONS, [self.pos])

    def closes(self, symbol=None):
        return [o for o in self.ex.orders.values() if o.get("reduceOnly") == "YES"
                and (symbol is None or o["symbol"] == symbol)]

    def test_partial_close_then_retry_sends_only_remaining_leg(self):
        self.ex.fail = "SAAPLSUSDT"  # second leg's close is rejected
        self.assertEqual(live._close_due_positions(2000), [])
        pos = live._read(live.POSITIONS, [])[0]
        self.assertEqual((pos["status"], pos["close_state"]), ("open", "partial"))
        self.assertIn("SAAPLSUSDT", pos["close_error"])
        self.assertEqual(pos["demo_legs"][0]["close_order"]["state"], "filled")
        self.assertNotIn("close_order", pos["demo_legs"][1])
        self.ex.fail = None
        closed = live._close_due_positions(3000)
        self.assertEqual(closed[0]["status"], "closed")
        self.assertNotIn("close_state", closed[0])
        self.assertEqual(len(self.closes("SNVDASUSDT")), 1)  # leg 0 closed exactly once
        self.assertEqual(len(self.closes("SAAPLSUSDT")), 1)
        self.assertIn("net", closed[0]["realized"])

    def test_crash_after_send_does_not_resend_leg(self):
        # leg 0's close reached the exchange but the local file never recorded it
        self.make().market_order("SNVDASUSDT", 1, self.pos["demo_legs"][0]["size"], True, "NVDA-2026-09-22-close-c0")
        closed = live._close_due_positions(2000)
        self.assertEqual(closed[0]["status"], "closed")
        self.assertEqual(len(self.closes("SNVDASUSDT")), 1)
        self.assertEqual(len(self.closes("SAAPLSUSDT")), 1)

    def test_duplicate_invocation_sends_nothing_more(self):
        self.assertEqual(len(live._close_due_positions(2000)), 1)
        n = len(self.ex.orders)
        self.assertEqual(live._close_due_positions(2001), [])
        self.assertEqual(len(self.ex.orders), n)

    def test_new_exposure_blocked_while_partial_close_unresolved(self):
        self.ex.fail = "SAAPLSUSDT"
        live._close_due_positions(2000)
        n = len(self.ex.orders)
        ev = _event(NEW, RELEASE)
        pos, err = live._open_position(ev, ANALYSIS, {"size": 1.0, "direction": 1}, 5000)
        self.assertIsNone(pos)
        self.assertIn("unresolved partial close on NVDA-2026-09-22; no new exposure", err)
        self.assertEqual(len(self.ex.orders), n)


class VersionStampTest(unittest.TestCase):
    def test_write_version_hashes_files(self):
        import hashlib
        from residual.version import write_version
        root = Path(tempfile.mkdtemp())
        (root / "data").mkdir(); (root / "web").mkdir()
        CSV = b"a,b\n1,2\n"
        res = b'{"model_version": "m1", "extractor_version": "e2"}'
        (root / "data/results.json").write_bytes(res)
        (root / "data/ledger.csv").write_bytes(CSV)
        out = write_version(root)
        self.assertEqual(out["project"], "residual")
        self.assertEqual(out["sha256"], {"data/results.json": hashlib.sha256(res).hexdigest(),
                                         "data/ledger.csv": hashlib.sha256(CSV).hexdigest()})
        self.assertEqual((out["model_version"], out["extractor_version"]), ("m1", "e2"))
        self.assertIsNone(out["commit"])  # temp dir is not a git repo
        self.assertEqual(json.loads((root / "web/version.json").read_text()), out)


if __name__ == "__main__":
    unittest.main()
