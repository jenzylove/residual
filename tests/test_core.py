import json
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from residual import extract, factors, paper, pipeline, strategy
from residual.factors import DAY, HOUR


class ExtractTests(unittest.TestCase):
    TEXT = ("NVIDIA reported record revenue for the third quarter ended October 26, 2025, of $57.0 billion. "
            "Outlook: • Revenue is expected to be $65.0 billion, plus or minus 2%.")

    def _src(self):
        return b"<p>" + self.TEXT.encode() + b"</p>"

    def test_extract_and_verify(self):
        raw = self._src()
        f = extract.extract_all("NVDA", raw, self.TEXT, "https://example/pr.htm")
        self.assertEqual(f["revenue_actual"]["value"], 57000.0)
        g = f["revenue_guidance_next"]
        self.assertAlmostEqual(g["low"], 63700.0)
        self.assertAlmostEqual(g["value"], 65000.0)
        ok, detail = extract.verify_field(f["revenue_actual"], self.TEXT, raw)
        self.assertTrue(ok, detail)

    def test_verify_rejects_tampered_value(self):
        raw = self._src()
        f = extract.extract_all("NVDA", raw, self.TEXT, "u")["revenue_actual"]
        f["value"] = 58000.0
        self.assertFalse(extract.verify_field(f, self.TEXT, raw)[0])

    def test_verify_rejects_changed_document(self):
        raw = self._src()
        f = extract.extract_all("NVDA", raw, self.TEXT, "u")["revenue_actual"]
        self.assertFalse(extract.verify_field(f, self.TEXT, raw + b" ")[0])

    def test_number_does_not_swallow_period(self):
        t = "Diluted EPS was $1.20."
        self.assertEqual(extract.extract_all("AMD", t.encode(), t, "u")["eps_diluted"]["value"], 1.20)


def _synthetic(beta_m=1.3, beta_s=0.6, n=24 * 25, seed=1):
    rnd = random.Random(seed)
    t0 = 1_700_000_000_000 - 1_700_000_000_000 % HOUR
    pc, pm, ps1, ps2 = 100.0, 100.0, 100.0, 100.0
    C, M, S1, S2 = [], [], [], []
    for i in range(n):
        t = t0 + i * HOUR
        rm = rnd.gauss(0, 0.004)
        sx = rnd.gauss(0, 0.003)
        rs = 0.8 * rm + sx
        rc = beta_m * rm + beta_s * sx + rnd.gauss(0, 0.001)
        pm *= math.exp(rm); pc *= math.exp(rc)
        ps1 *= math.exp(rs + rnd.gauss(0, 0.0005)); ps2 *= math.exp(rs + rnd.gauss(0, 0.0005))
        for rows, p in ((C, pc), (M, pm), (S1, ps1), (S2, ps2)):
            rows.append([t, p, p * 1.001, p * 0.999, p, 5e6])
    return t0, C, M, S1, S2


class FactorTests(unittest.TestCase):
    def test_ols_recovers_betas(self):
        t0, C, M, S1, S2 = _synthetic()
        ic, im = factors.index(C), factors.index(M)
        end = t0 + 24 * 25 * HOUR
        rs = factors.basket_returns({"a": factors.index(S1), "b": factors.index(S2)}, t0, end)
        mdl = factors.fit(factors.hourly_returns(ic, t0, end), factors.hourly_returns(im, t0, end), rs)
        # sector shock sx is generated orthogonal to the market, so the market beta is 1.3
        self.assertAlmostEqual(mdl["beta_market"], 1.3, delta=0.08)
        self.assertAlmostEqual(mdl["b_sector_market"], 0.8, delta=0.05)
        self.assertAlmostEqual(mdl["beta_sector"], 0.6, delta=0.08)
        self.assertGreater(mdl["r2"], 0.9)

    def test_decomposition_sums_to_observed(self):
        mdl = {"beta_market": 1.2, "beta_sector": 0.5, "b_sector_market": 0.9}
        d = factors.decompose(mdl, 0.05, 0.01, 0.02, 0.001)
        self.assertAlmostEqual(d["market"] + d["sector"] + d["liquidity"] + d["residual"], d["observed"], places=12)
        self.assertAlmostEqual(d["liquidity"], 0.0005)


class PaperTests(unittest.TestCase):
    def _snap(self):
        t0 = 1_700_000_000_000 - 1_700_000_000_000 % HOUR
        c = [[t0 + i * HOUR, 100 + i, 100 + i, 100 + i, 100 + i + 1, 1e6] for i in range(30)]
        h = [[t0 + i * HOUR, 50.0, 50.0, 50.0, 50.0, 1e6] for i in range(30)]
        return t0, {"candles": {"C": c, "H": h}, "contracts": {"C": {"takerFeeRate": "0.0006"}}, "funding": {}}

    def test_pair_accounting_identity(self):
        t0, snap = self._snap()
        legs = [{"symbol": "C", "side": 1, "notional": 10_000, "slip": 0.0003, "role": "company"},
                {"symbol": "H", "side": -1, "notional": 12_000, "slip": 0.0003, "role": "hedge"}]
        sim = paper.simulate(snap, legs, t0 + 2 * HOUR, t0 + 10 * HOUR, 250, "t")
        self.assertAlmostEqual(sim["gross_mid"] - sim["fees"] - sim["slippage"] + sim["funding"], sim["net"], places=6)
        self.assertEqual(len(sim["orders"]), 4)
        self.assertEqual(sim["funding_data"], "unavailable_for_period")
        self.assertEqual(sim["funding_assumption"], "missing_settlements_treated_as_zero_for_simulation")
        self.assertGreater(sim["legs"][0]["net"], 0)

    def test_stop_loss_triggers(self):
        t0, snap = self._snap()
        legs = [{"symbol": "C", "side": -1, "notional": 10_000, "slip": 0.0, "role": "company"}]
        sim = paper.simulate(snap, legs, t0 + 2 * HOUR, t0 + 20 * HOUR, 250, "t")
        self.assertTrue(sim["stopped"])
        self.assertLess(sim["exit_ms"], t0 + 20 * HOUR)


class WalkForwardTests(unittest.TestCase):
    def _hist(self, n, cont_wins=True):
        out = []
        for i in range(n):
            res = 0.02 if i % 2 else -0.02
            win = 100.0 if cont_wins else -100.0
            out.append({"event_id": f"E{i}", "residual": res, "costs": {"round_trip": 0.002},
                        "counterfactual": {str(int(math.copysign(1, res))): win, str(-int(math.copysign(1, res))): -win},
                        "gates": {k: (True, "") for k in ("event_data", "market_data", "hedge", "liquidity", "robust", "reaction_open")}})
        return out

    def test_prior_until_enough_history(self):
        p = strategy.learn_params(self._hist(3))
        self.assertEqual((p["mode"], p["k"]), (1, 2.0))
        self.assertTrue(p["source"].startswith("prior"))

    def test_learns_reversal(self):
        p = strategy.learn_params(self._hist(8, cont_wins=False))
        self.assertEqual(p["mode"], -1)
        self.assertEqual(p["source"], "walk-forward")

    def test_decide_blocks_without_validated_ai(self):
        a = self._hist(1)[0]
        dec = strategy.decide({}, a, {"mode": 1, "k": 2.0}, {"status": "unavailable", "detail": "no key"})
        self.assertEqual(dec["decision"], "NO_TRADE")
        self.assertIn("ai_interpretation", dec["reasons"])

    def test_decide_trades_with_durable_label(self):
        a = self._hist(1)[0]
        dec = strategy.decide({}, a, {"mode": 1, "k": 2.0}, {"status": "ok", "label": "durable", "confidence": 0.8})
        self.assertEqual(dec["decision"], "TRADE")
        self.assertEqual(dec["direction"], -1)


class InterpretValidationTests(unittest.TestCase):
    SRC = "Revenue grew strongly. We expect demand to remain robust through next year."

    def test_accepts_valid(self):
        from residual.interpret import validate
        out, detail = validate('{"label":"durable","confidence":0.7,"rationale":"r","evidence_quotes":["We expect demand to remain robust"]}', self.SRC)
        self.assertEqual(detail, "ok")
        self.assertEqual(out["label"], "durable")

    def test_accepts_quote_spanning_table_cell(self):
        from residual.interpret import validate
        src = "Revenue | $33.5 billion ± $750 million | next"
        out, detail = validate('{"label":"durable","confidence":0.5,"rationale":"r","evidence_quotes":["Revenue $33.5 billion ± $750 million"]}', src)
        self.assertEqual(detail, "ok")

    def test_rejects_fabricated_quote_and_extra_numbers(self):
        from residual.interpret import validate
        self.assertIsNone(validate('{"label":"durable","confidence":0.7,"rationale":"r","evidence_quotes":["Revenue tripled"]}', self.SRC)[0])
        self.assertIsNone(validate('{"label":"durable","confidence":0.7,"rationale":"r","evidence_quotes":["Revenue grew"],"hedge_ratio":1.4}', self.SRC)[0])
        self.assertIsNone(validate('{"label":"buy","confidence":0.7,"rationale":"r","evidence_quotes":["Revenue grew"]}', self.SRC)[0])

    def test_offline_uses_committed_interpretation_without_source_fetch(self):
        import residual.interpret as interpret_module

        event = {"event_id": "offline-event"}
        with tempfile.TemporaryDirectory() as temp:
            old_cache_dir = interpret_module.CACHE_DIR
            try:
                interpret_module.CACHE_DIR = Path(temp)
                (Path(temp) / "offline-event.json").write_text(json.dumps({
                    "event_id": "offline-event",
                    "prompt_version": interpret_module.PROMPT_VERSION,
                    "status": "ok",
                    "label": "durable",
                    "confidence": 0.8,
                }), encoding="utf-8")
                out = interpret_module.interpret(event, {}, None, allow_call=False, offline=True)
                self.assertEqual(out["status"], "ok")
                self.assertEqual(out["cache_validation"], "committed_offline")
            finally:
                interpret_module.CACHE_DIR = old_cache_dir

    def test_offline_refuses_missing_interpretation(self):
        import residual.interpret as interpret_module

        old_cache_dir = interpret_module.CACHE_DIR
        try:
            with tempfile.TemporaryDirectory() as temp:
                interpret_module.CACHE_DIR = Path(temp)
                out = interpret_module.interpret({"event_id": "missing"}, {}, None,
                                                  allow_call=False, offline=True)
                self.assertEqual(out["status"], "unavailable")
        finally:
            interpret_module.CACHE_DIR = old_cache_dir


class HardeningTests(unittest.TestCase):
    def test_funding_complete_metrics_exclude_unknown_trade(self):
        rows = [
            {"residual": {"net": 10.0, "funding_data": "complete", "holding_hours": 24}},
            {"residual": {"net": 20.0, "funding_data": "unavailable_for_period", "holding_hours": 24}},
            {"residual": None},
        ]
        out = pipeline.metrics(rows, "residual", funding_complete_only=True)
        self.assertEqual(out["trades"], 1)
        self.assertAlmostEqual(out["total_net_pnl"], 10.0)
        self.assertEqual(pipeline.funding_quality(rows, "residual"),
                         {"trades": 2, "complete": 1, "unknown": 1})

    def test_demo_adapter_builds_read_only_request_with_demo_header(self):
        from residual.execution import BitgetDemoExecutionAdapter

        adapter = BitgetDemoExecutionAdapter("key", "secret", "pass", "https://example.test")
        req = adapter.build_account_read_request("1700000000000")
        self.assertEqual(req.method, "GET")
        self.assertEqual(req.url, "https://example.test/api/v2/mix/account/accounts?productType=USDT-FUTURES")
        self.assertEqual(req.headers["paptrading"], "1")
        self.assertEqual(req.headers["ACCESS-KEY"], "key")
        self.assertTrue(req.headers["ACCESS-SIGN"])

    def test_live_mark_requires_quotes_for_each_leg(self):
        from residual import live

        pos = {"legs": [
            {"symbol": "C", "side": 1, "qty": 1.0, "entry_price": 100.0},
            {"symbol": "H", "side": -1, "qty": 2.0, "entry_price": 50.0},
        ]}
        with patch.object(live, "probe", side_effect=[
            {"bid": 89.0, "ask": 91.0},
            {"bid": 54.0, "ask": 56.0},
        ]):
            pnl, quotes = live._mark_position(pos)
        self.assertAlmostEqual(pnl, -20.0)
        self.assertEqual(set(quotes), {"C", "H"})


if __name__ == "__main__":
    unittest.main()
