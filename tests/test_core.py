import json
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tbot import backtest, strategies  # noqa: E402
from tbot.data import validate  # noqa: E402
from tbot.live import approved_orders, build_orders, canonical_hash, risk_filter  # noqa: E402


def prices(n=800, seed=0, syms=("SPY", "EFA", "AGG", "BIL")):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    c = pd.DataFrame({s: 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n))) for s in syms}, index=idx)
    o = c.shift(1).fillna(c.iloc[0]) * (1 + rng.normal(0, 0.002, c.shape))
    return o, c


class TestData(unittest.TestCase):
    def frame(self):
        idx = pd.bdate_range("2020-01-01", periods=5)
        return pd.DataFrame({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "adj_close": 10.0, "volume": 1.0}, index=idx)

    def test_clean_passes(self):
        self.assertTrue(validate(self.frame(), "X").ok)

    def test_nan_duplicate_and_ohlc_fail(self):
        f = self.frame(); f.iloc[1, 0] = np.nan
        self.assertFalse(validate(f, "X").ok)
        f = self.frame(); f.index = [f.index[0]] * 5
        self.assertFalse(validate(f, "X").ok)
        f = self.frame(); f.iloc[2, 1] = 5.0
        self.assertFalse(validate(f, "X").ok)


class TestBacktest(unittest.TestCase):
    def test_month_end_never_last_day(self):
        _, c = prices()
        ends = strategies.month_end_dates(c.index)
        self.assertNotIn(c.index[-1], ends)
        self.assertTrue(all((ends[1:].month != ends[:-1].month) | (ends[1:].year != ends[:-1].year)))

    def test_no_lookahead(self):
        o, c = prices()
        p = {"type": "sma_trend", "assets": ["SPY", "EFA"], "cash": "BIL", "sma_months": 10}
        fn = lambda h: strategies.signal(h, p)  # noqa: E731
        base = backtest.run(o, c, fn)
        cut = base.weights.index[len(base.weights) // 2]
        c2, o2 = c.copy(), o.copy()
        c2.loc[c2.index > cut] *= 3.0; o2.loc[o2.index > cut] *= 3.0
        alt = backtest.run(o2, c2, fn)
        pd.testing.assert_frame_equal(base.weights.loc[:cut], alt.weights.loc[:cut])

    def test_buy_and_hold_matches_price_minus_entry_cost(self):
        o, c = prices()
        r = backtest.run(o, c, lambda h: {"SPY": 1.0}, slippage_bps=10)
        first_trade = r.trades["date"].iloc[0]
        expected = 10_000 / (o.at[first_trade, "SPY"] * 1.001) * c["SPY"].iloc[-1]
        self.assertAlmostEqual(r.equity.iloc[-1], expected, places=6)
        self.assertEqual(r.trades["symbol"].nunique(), 1)

    def test_costs_charged_on_switch(self):
        o, c = prices()
        flip = iter(range(10_000))
        r0 = backtest.run(o, c, lambda h: {"SPY": 1.0} if next(flip) % 2 else {"AGG": 1.0}, slippage_bps=0)
        flip = iter(range(10_000))
        r1 = backtest.run(o, c, lambda h: {"SPY": 1.0} if next(flip) % 2 else {"AGG": 1.0}, slippage_bps=20)
        self.assertLess(r1.equity.iloc[-1], r0.equity.iloc[-1])
        self.assertGreater(r1.costs, 0)


class TestLive(unittest.TestCase):
    def proposal(self, orders):
        p = {"date": "2026-10-30", "orders": orders}
        p["sha256"] = canonical_hash(p)
        return p

    def test_build_orders_band_and_month_end(self):
        tgt = {"SPY": 0.6, "AGG": 0.4}
        o, _ = build_orders(tgt, 1000, {"SPY": 620, "AGG": 380}, month_end=False, drift_band=0.05, min_order=5)
        self.assertEqual(o, [])
        o, _ = build_orders(tgt, 1000, {"SPY": 620, "AGG": 380}, month_end=True, drift_band=0.05, min_order=5)
        self.assertEqual([x["side"] for x in o], ["sell", "buy"])
        o, _ = build_orders({"BIL": 1.0}, 1000, {"SPY": 1000}, month_end=False, drift_band=0.05, min_order=5)
        self.assertTrue(o[0]["close_position"])

    def test_review_gating(self):
        orders = [{"id": "SPY-buy", "symbol": "SPY", "side": "buy", "notional": 100.0},
                  {"id": "AGG-buy", "symbol": "AGG", "side": "buy", "notional": 100.0}]
        p = self.proposal(orders)
        self.assertEqual(approved_orders(p, None)[0], [])
        bad = {"proposal_sha256": "x", "decisions": [{"order_id": "SPY-buy", "decision": "approve"}]}
        self.assertEqual(approved_orders(p, bad)[0], [])
        rv = {"proposal_sha256": p["sha256"], "decisions": [{"order_id": "SPY-buy", "decision": "approve"},
                                                             {"order_id": "AGG-buy", "decision": "veto", "reason_code": "data_error"}]}
        self.assertEqual([o["id"] for o in approved_orders(p, rv)[0]], ["SPY-buy"])
        tampered = json.loads(json.dumps(p)); tampered["orders"][0]["notional"] = 9999
        self.assertEqual(approved_orders(tampered, rv)[0], [])

    def test_risk_filter(self):
        orders = [{"id": "SPY-sell", "symbol": "SPY", "side": "sell", "notional": 100.0},
                  {"id": "AGG-buy", "symbol": "AGG", "side": "buy", "notional": 500.0},
                  {"id": "TSLA-buy", "symbol": "TSLA", "side": "buy", "notional": 10.0}]
        kw = dict(universe=["SPY", "AGG"], cash=50.0, max_drawdown=0.25, mode="paper", live_max_equity=None)
        out, _, halt = risk_filter(orders, equity=1000, peak_equity=1000, **kw)
        self.assertFalse(halt)
        self.assertEqual([o["id"] for o in out], ["SPY-sell", "AGG-buy"])
        self.assertLessEqual(out[1]["notional"], 150.0)
        out, _, halt = risk_filter(orders, equity=700, peak_equity=1000, **kw)
        self.assertTrue(halt)
        self.assertEqual([o["side"] for o in out], ["sell"])

    def test_live_requires_confirmation(self):
        import os
        from tbot.broker import BrokerError, mode_from_env
        os.environ["TBOT_MODE"] = "live"; os.environ.pop("TBOT_LIVE_CONFIRM", None)
        try:
            with self.assertRaises(BrokerError):
                mode_from_env()
        finally:
            os.environ["TBOT_MODE"] = "paper"


if __name__ == "__main__":
    unittest.main()
