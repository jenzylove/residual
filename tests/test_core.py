import math
import random
import unittest

from residual import extract, factors, paper, strategy
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

    def _one(self, ticker, text):
        return extract.extract_all(ticker, text.encode(), text, "u")

    def test_expansion_extractors_on_real_wording(self):
        cases = [
            ("QCOM", "Revenues | $9,947 | | $10,365 | | (4%) Current Guidance Q4 FY26 Estimates 1 | | Revenues | | $9.7B - $10.5B | |", 9947.0, 10100.0),
            ("KLAC", "For the quarter, total revenues were $3.66 billion, above the midpoint. Total revenues are expected to be in a range of $4.0 billion +/- $200 million", 3660.0, 4000.0),
            ("TXN", "today reported second quarter revenue of $5.46 billion, net income. TI's third quarter outlook is for revenue in the range of $5.65 billion to $6.15 billion", 5460.0, 5900.0),
            ("SMCI", "Net sales of $11.1 billion versus $10.2 billion. Business Outlook The Company expects net sales in the range of $14.5 billion and $15.5 billion", 11100.0, 15000.0),
            ("CRM", "• Subscription and support revenue of $10.8 billion, up 12% Y/Y • Revenue of $11.3 billion, up 11% Y/Y • Initiates third quarter FY27 revenue guidance of $11.42 billion to $11.50 billion", 11300.0, 11460.0),
            ("PANW", "Total revenue for the fiscal fourth quarter 2026 grew 34% year over year to $3.41 billion. • Total revenue in the range of $3.300 billion to $3.310 billion", 3410.0, 3305.0),
            ("CRWD", "Total revenue was $1.47 billion, a 26% increase. Guidance | Total revenue | $1,523.2 - $1,529.2 million |", 1470.0, 1526.2),
            ("MDB", "Total revenue was $771.8 million for the second quarter. Revenues are expected to be in the range of: | $756 million to $761 million |", 771.8, 758.5),
        ]
        for t, text, actual, guide in cases:
            f = self._one(t, text)
            self.assertAlmostEqual(f["revenue_actual"]["value"], actual, places=3, msg=t)
            self.assertAlmostEqual(f["revenue_guidance_next"]["value"], guide, places=3, msg=t)
            self.assertTrue(extract.verify_field(f["revenue_actual"], text, text.encode())[0], t)

    def test_gross_margin_on_real_wording(self):
        cases = [("NVDA", "Gross margin | 73.4 | % | 72.4 | % | 74.6 | %", 73.4),
                 ("AMD", "revenue was $9.2 billion, gross margin was 52%, operating income", 52.0),
                 ("INTC", "GAAP gross margin percentage | | 38.2 | % | | 15.0 | %", 38.2),
                 ("MRVL", "GAAP gross margin | | 51.6 | % | | 50.4 | %", 51.6),
                 ("MDB", "gross profit was $500.2 million, representing a 72% gross margin compared to 71%", 72.0)]
        for t, text, v in cases:
            f = self._one(t, text)["gross_margin"]
            self.assertEqual(f["value"], v, t)
            self.assertTrue(extract.verify_field(f, text, text.encode())[0], t)
        self.assertIsNone(self._one("KLAC", "GAAP gross margin | | 59.62% | | 61.62% |")["gross_margin"])

    def test_hpe_ignores_segment_lines(self):
        text = "• Networking revenue was $2.7 billion, up 148% • Revenue : $10.7 billion, up 40% from the prior-year period"
        self.assertEqual(self._one("HPE", text)["revenue_actual"]["value"], 10700.0)

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


class RiskRatioTests(unittest.TestCase):
    def test_sharpe_sortino(self):
        from residual.pipeline import risk_ratios
        day = 86_400_000
        rows = [{"_release_ms": 0}, {"_release_ms": 9 * day}]
        mk = lambda net, d: {"net": net, "exit_ms": d * day, "legs": [{"role": "company", "notional": 10_000}]}
        traded = [mk(200, 1), mk(-100, 3), mk(300, 5)]
        r = risk_ratios(rows, traded)
        rets = [0.02, -0.01, 0.03]
        import statistics as st
        self.assertAlmostEqual(r["sharpe_per_trade"], round(st.fmean(rets) / st.stdev(rets), 3))
        self.assertAlmostEqual(r["sortino_per_trade"], round(st.fmean(rets) / math.sqrt(0.0001 / 3), 3))
        self.assertEqual(r["days"], 10)
        self.assertGreater(r["sharpe_daily_ann"], 0)
        self.assertIsNone(risk_ratios(rows, [])["sharpe_daily_ann"])


class FundingMergeTests(unittest.TestCase):
    def test_refresh_never_shrinks_coverage(self):
        from residual.market import merge_funding
        old = {"X": {"earliest_available": 100, "settlements": [{"t": 100, "rate": 1e-4}, {"t": 200, "rate": 2e-4}]}}
        new = {"X": {"earliest_available": 200, "settlements": [{"t": 200, "rate": 2e-4}, {"t": 300, "rate": 3e-4}]},
               "Y": {"earliest_available": 250, "settlements": []}}
        m = merge_funding(old, new)
        self.assertEqual(m["X"]["earliest_available"], 100)
        self.assertEqual([x["t"] for x in m["X"]["settlements"]], [100, 200, 300])
        self.assertEqual(m["Y"]["earliest_available"], 250)
        self.assertIs(merge_funding(None, new), new)


class OutputJsonTests(unittest.TestCase):
    def test_non_finite_numbers_become_null(self):
        import json
        from residual.pipeline import _finite
        obj = {"participation": math.inf, "x": [1.0, math.nan, {"y": -math.inf}], "ok": 2.5}
        clean = _finite(obj)
        s = json.dumps(clean, allow_nan=False)  # raises if anything non-finite survived
        self.assertEqual(json.loads(s), {"participation": None, "x": [1.0, None, {"y": None}], "ok": 2.5})


class OfflineDeterminismTests(unittest.TestCase):
    """Offline replay must be reproducible: cached AI answers only, never a live call."""

    def test_offline_never_calls_the_model(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from residual import interpret as I
        ev = {"event_id": "X-1", "release_utc": "2026-01-01T21:00:00Z", "ticker": "X",
              "surprise": {"revenue_actual": 1.0, "revenue_guided_mid": 1.0, "basis": "b",
                           "guidance_surprise_pct": 0.0, "next_quarter_guidance_mid": 1.0,
                           "guidance_direction": "maintained"}}
        an = {"decomposition": {"observed": .01, "market": .002, "sector": .001, "liquidity": 0.0, "residual": .007}}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(I, "CACHE_DIR", Path(d)),              mock.patch.object(I, "_call_anthropic", side_effect=AssertionError("no network in offline mode")):
            out = I.interpret(ev, an, "some press release text", allow_call=False)
        self.assertEqual(out["status"], "unavailable")

    def test_cached_answer_is_reused_without_calling(self):
        import json, tempfile
        from pathlib import Path
        from unittest import mock
        from residual import interpret as I
        ev = {"event_id": "X-2", "release_utc": "2026-01-01T21:00:00Z", "ticker": "X",
              "surprise": {"revenue_actual": 1.0, "revenue_guided_mid": 1.0, "basis": "b",
                           "guidance_surprise_pct": 0.0, "next_quarter_guidance_mid": 1.0,
                           "guidance_direction": "maintained"}}
        an = {"decomposition": {"observed": .01, "market": .002, "sector": .001, "liquidity": 0.0, "residual": .007}}
        text = "some press release text"
        with tempfile.TemporaryDirectory() as d, mock.patch.object(I, "CACHE_DIR", Path(d)):
            import hashlib
            prompt = I.build_prompt(ev, an, text)
            h = hashlib.sha256((I.PROMPT_VERSION + I.SYSTEM + prompt).encode()).hexdigest()
            (Path(d) / "X-2.json").write_text(json.dumps(
                {"status": "ok", "prompt_sha256": h, "label": "durable", "confidence": 0.7,
                 "rationale": "r", "evidence_quotes": ["some press release"], "model": "cached"}), encoding="utf-8")
            with mock.patch.object(I, "_call_anthropic", side_effect=AssertionError("must not call")):
                out = I.interpret(ev, an, text, allow_call=True)
        self.assertEqual((out["status"], out["label"], out["model"]), ("ok", "durable", "cached"))


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


if __name__ == "__main__":
    unittest.main()
