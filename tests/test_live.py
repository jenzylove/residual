"""Deterministic end-to-end fixture for the live watcher lifecycle:
new filing -> event record -> PENDING -> gated decision -> paper pair opened -> closed."""
import json
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
            mock.patch.object(live, "analyze", lambda ev, snap: ANALYSIS),
            mock.patch.object(live, "_history_params", lambda ds, before: {"mode": 1, "k": 2.0, "source": "fixture"}),
            mock.patch.object(live, "interpret", lambda ev, a, text: {"status": "ok", "label": "durable", "confidence": 0.8}),
            mock.patch.object(live, "probe", self.book),
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
        self.assertAlmostEqual(pos["legs"][1]["qty"] * pos["legs"][1]["entry_price"], 12_000, places=3)
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

    def test_trade_after_entry_window_is_rejected(self):
        t_obs = market.event_times(RELEASE)["t_obs"]
        r = live.watch(now_ms=t_obs + 2 * HOUR)
        self.assertEqual(r["new_events"][0]["decision"], "NO_TRADE")
        self.assertIn("entry_window_passed", r["new_events"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
