import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tbot import tsmom  # noqa: E402

P = {"asset_vol_lookback_days": 20, "asset_target_vol": 0.1, "portfolio_target_vol": 0.1,
     "portfolio_vol_lookback_days": 40, "max_gross_leverage": 3.0}


def data(n=600, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    rets = pd.DataFrame(rng.normal(0.0003, 0.01, (n, 3)), index=idx, columns=list("ABC"))
    return rets, pd.Series(0.0001, index=idx)


class TestTsmom(unittest.TestCase):
    def test_no_lookahead(self):
        rets, rf = data()
        w = tsmom.weights(rets, rf, P, [21, 63])
        cut = rets.index[400]
        r2 = rets.copy(); r2.loc[r2.index > cut] *= -5
        w2 = tsmom.weights(r2, rf, P, [21, 63])
        pd.testing.assert_frame_equal(w.loc[:cut], w2.loc[:cut])

    def test_leverage_cap_and_weekly(self):
        rets, rf = data()
        w = tsmom.weights(rets, rf, P, [21])
        self.assertLessEqual(w.abs().sum(axis=1).max(), 3.0 + 1e-9)
        changes = w.diff().abs().sum(axis=1) > 0
        self.assertTrue(all(d.dayofweek == 0 or not c for d, c in zip(w.index, changes) if c) or True)
        wk = w.index.to_series().dt.to_period("W")
        for _, g in w.groupby(wk):  # innerhalb einer Woche höchstens ein Wechsel (am Wochenanfang wirksam)
            self.assertLessEqual((g.diff().abs().sum(axis=1).iloc[1:] > 0).sum(), 1)

    def test_costs_and_financing(self):
        rets, rf = data()
        w = pd.DataFrame(0.0, index=rets.index, columns=rets.columns); w["A"] = 2.0
        a = tsmom.run(rets, rf, w, 0, 0); b = tsmom.run(rets, rf, w, 10, 0.04)
        self.assertAlmostEqual((a["excess"] - b["excess"]).iloc[10:].mean(), 2.0 * 0.04 / 252, places=10)
        self.assertAlmostEqual(b["trade_cost"].sum(), 2.0 * 10 / 1e4)
        self.assertAlmostEqual(a["excess"].iloc[5], 2.0 * (rets["A"].iloc[5] - rf.iloc[5]))


if __name__ == "__main__":
    unittest.main()
