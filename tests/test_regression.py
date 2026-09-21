"""Regression and invariant tests over the committed dataset and results.

These run against the real artefacts, so they catch drift that unit tests on synthetic data cannot:
provenance completeness, walk-forward leakage, gate/decision consistency, ledger integrity and
the arithmetic identities behind every published number.
"""
import json
import math
import unittest
from pathlib import Path

from residual.strategy import SELECTOR_VARIANTS

ROOT = Path(__file__).resolve().parent.parent
EVENTS = json.loads((ROOT / "data" / "events.json").read_text(encoding="utf-8"))
RESULTS = json.loads((ROOT / "data" / "results.json").read_text(encoding="utf-8"))
ROWS = RESULTS["rows"]
BY_ID = {e["event_id"]: e for e in EVENTS}
REQUIRED = ("revenue_actual", "revenue_guidance_prior", "revenue_guidance_next", "revenue_prior_actual")


class DatasetInvariants(unittest.TestCase):
    def test_every_scored_event_is_a_verified_earnings_release(self):
        for r in ROWS:
            e = BY_ID[r["event_id"]]
            self.assertNotEqual(e["status"], "not_an_earnings_release", r["event_id"])
            if e["status"] == "complete":
                for name in REQUIRED:
                    self.assertTrue(e["earnings"][name]["verified"], r["event_id"] + " " + name)

    def test_every_number_carries_its_source(self):
        for e in EVENTS:
            for name, f in e["earnings"].items():
                if not f:
                    continue
                where = e["event_id"] + " " + name
                self.assertTrue(f["snippet"].strip(), where)
                self.assertEqual(len(f["source_sha256"]), 64, where)
                self.assertTrue(f["source_url"].startswith("https://www.sec.gov/"), where)
                archived = ROOT / "data" / "sources" / (f["source_sha256"] + ".htm")
                self.assertTrue(archived.exists(), where + ": archived source missing")

    def test_guidance_baseline_is_a_different_release(self):
        for e in EVENTS:
            if e["status"] != "complete":
                continue
            self.assertNotEqual(e["source"]["press_release_url"],
                                e["prior_source"]["press_release_url"], e["event_id"])

    def test_consensus_values_are_flagged_not_silently_used(self):
        for e in EVENTS:
            c = e.get("consensus")
            if not c:
                continue
            self.assertIn(c["quality"], ("ok", "basis_mismatch_suspected"), e["event_id"])
            if abs(c["consensus_surprise_pct"]) > 30:
                self.assertEqual(c["quality"], "basis_mismatch_suspected", e["event_id"])


class WalkForwardInvariants(unittest.TestCase):
    def test_parameters_never_use_the_event_they_score(self):
        for r in ROWS:
            self.assertNotIn(r["event_id"], r["params"].get("train_events") or [],
                             r["event_id"] + " trained on itself")

    def test_training_events_all_exited_before_the_release(self):
        release = {r["event_id"]: r["_release_ms"] for r in ROWS}
        exits = {}
        for r in ROWS:
            t = r.get("residual") or r.get("v_residual")
            if t:
                exits[r["event_id"]] = t["exit_ms"]
        for r in ROWS:
            for e in (r["params"].get("train_events") or []):
                if e in exits:
                    self.assertLessEqual(exits[e], release[r["event_id"]], r["event_id"] + " <- " + e)

    def test_post_hoc_consensus_rule_cannot_drive_strategy(self):
        self.assertNotIn("consensus", SELECTOR_VARIANTS)
        for r in ROWS:
            self.assertIn(r["variant"]["variant"], SELECTOR_VARIANTS, r["event_id"])


class DecisionInvariants(unittest.TestCase):
    def test_trade_requires_every_gate_to_pass(self):
        for r in ROWS:
            gates = r["decision"]["gates"]
            if r["decision"]["decision"] == "TRADE":
                self.assertTrue(all(g["pass"] for g in gates.values()), r["event_id"])
                self.assertEqual(r["decision"]["reasons"], [], r["event_id"])
            else:
                self.assertTrue(r["decision"]["reasons"], r["event_id"])
                for k in r["decision"]["reasons"]:
                    if k in gates:
                        self.assertFalse(gates[k]["pass"], r["event_id"] + " " + k)

    def test_no_trade_events_have_no_orders(self):
        traded = {r["event_id"] for r in ROWS if r["decision"]["decision"] == "TRADE"}
        for r in ROWS:
            if r["event_id"] not in traded:
                self.assertIsNone(r.get("residual"), r["event_id"])

    def test_ai_label_and_book_only_scale_size(self):
        """Size is the AI label's fraction times what the book can carry. Neither can create a
        trade, and neither can push size above the base notional."""
        from residual.strategy import MIN_SIZE_FRACTION
        for r in ROWS:
            size = r["decision"]["size"]
            self.assertGreaterEqual(size, 0.0, r["event_id"])
            self.assertLessEqual(size, 1.0, r["event_id"])
            if r["decision"]["decision"] != "TRADE":
                self.assertEqual(size, 0.0, r["event_id"])
                continue
            liq = r["analysis"]["costs"]["liquidity_size"]
            self.assertGreaterEqual(liq, MIN_SIZE_FRACTION, r["event_id"])
            self.assertIn(round(size / liq, 4), (0.5, 1.0), r["event_id"])
            it = r.get("interpretation")
            if it and it.get("status") == "ok":
                self.assertIn(it["label"], ("durable", "temporary", "already_priced",
                                            "contradicted_by_guidance", "too_uncertain"), r["event_id"])


class ExecutionInvariants(unittest.TestCase):
    def test_every_trade_is_a_hedged_pair_with_both_legs(self):
        for r in ROWS:
            t = r.get("residual")
            if not t:
                continue
            self.assertEqual(sorted(l["role"] for l in t["legs"]), ["company", "hedge"], r["event_id"])
            sides = {l["role"]: l["side"] for l in t["legs"]}
            self.assertNotEqual(sides["company"], sides["hedge"], r["event_id"] + " legs same direction")

    def test_pnl_identity_holds_for_every_trade(self):
        for r in ROWS:
            t = r.get("residual")
            if not t:
                continue
            self.assertAlmostEqual(t["gross_mid"] - t["fees"] - t["slippage"] + t["funding"],
                                   t["net"], places=6, msg=r["event_id"])
            a = t["attribution"]
            self.assertAlmostEqual(a["residual"] + a["factor_error"] + a["slippage"] + a["fees"] + a["funding"],
                                   a["net"], places=6, msg=r["event_id"])

    def test_costs_are_always_charged(self):
        for r in ROWS:
            t = r.get("residual")
            if not t:
                continue
            self.assertGreater(t["fees"], 0, r["event_id"])
            self.assertGreater(t["slippage"], 0, r["event_id"])

    def test_ledger_matches_the_trades(self):
        traded = [r for r in ROWS if r.get("residual")]
        expected_orders = sum(len(r["residual"]["legs"]) * 2 for r in traded)
        self.assertEqual(len(RESULTS["orders"]), expected_orders)
        for o in RESULTS["orders"]:
            self.assertIn(o["type"], ("entry", "exit"))
            self.assertGreater(o["price"], 0)
            self.assertGreaterEqual(o["fee"], 0)


class PublishedNumberInvariants(unittest.TestCase):
    def test_headline_summary_matches_the_rows(self):
        S = RESULTS["summary_conservative_funding"]["residual"]
        total = sum((r["residual"] or {}).get("net_conservative", 0.0) for r in ROWS)
        self.assertAlmostEqual(S["total_net_pnl"], round(total, 2), places=2)
        self.assertEqual(S["trades"], sum(1 for r in ROWS if r.get("residual")))

    def test_every_published_number_is_finite(self):
        def walk(o, path):
            if isinstance(o, float):
                self.assertTrue(math.isfinite(o), "non-finite at " + path)
            elif isinstance(o, dict):
                for k, v in o.items():
                    walk(v, path + "." + str(k))
            elif isinstance(o, list):
                for i, v in enumerate(o):
                    walk(v, path + "[" + str(i) + "]")
        walk(RESULTS, "results")

    def test_demo_mode_pairs_are_all_demo_listed(self):
        listed = set(RESULTS["demo_mode"]["hedge_pool"])
        for r in RESULTS["demo_mode"]["rows"]:
            if r["decision"]["decision"] != "TRADE":
                continue
            self.assertIn(r["hedge"]["symbol"], listed, r["event_id"])
            self.assertIn(BY_ID[r["event_id"]]["company_symbol"], listed, r["event_id"])

    def test_fresh_snapshots_request_every_demo_hedge_candidate(self):
        from residual import universe
        for ticker in universe.demo_companies():
            self.assertTrue(set(universe.demo_hedge_pool(ticker)).issubset(universe.snapshot_symbols(ticker)))


if __name__ == "__main__":
    unittest.main()
