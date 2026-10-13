import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tbot.ibt import Signal, _nights, simulate  # noqa: E402

INST = {"tz": "America/New_York", "session": ["09:30", "16:00"], "spread_session": 1.0, "spread_off": 2.0}
COSTS = {"slippage_points_market": 0.0, "slippage_points_stop_extra": 0.0, "financing_long_pa": 0.036,
         "financing_short_pa": 0.0, "financing_cutoff_local": "23:00", "financing_cutoff_tz": "Europe/Berlin",
         "financing_day_count": 360}
RISK = {"risk_per_trade": 0.01, "max_leverage": 100.0, "initial_equity": 10_000}


def bars(rows, start="2024-03-05 14:30"):  # 09:30 New York (Sitzung)
    idx = pd.date_range(start, periods=len(rows), freq="30min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


class TestIBT(unittest.TestCase):
    def test_time_exit_pays_full_spread(self):
        b = bars([(100, 100, 100, 100)] * 3)
        t = simulate(b, [Signal(i=1, direction=1, stop=90, exit_at=2)], INST, COSTS, RISK)
        self.assertAlmostEqual(t["entry"][0], 100.5)
        self.assertAlmostEqual(t["exit"][0], 99.5)
        self.assertLess(t["pnl"][0], 0)

    def test_gap_through_stop_fills_at_open(self):
        b = bars([(100, 100, 100, 100), (100, 101, 99, 100), (95, 96, 94, 95)])
        t = simulate(b, [Signal(i=1, direction=1, stop=98, exit_at=2)], INST, COSTS, RISK)
        self.assertEqual(t["reason"][0], "stop")
        self.assertAlmostEqual(t["exit"][0], 94.5)  # Gap-Open 95 minus halber Spread, nicht Stop 98

    def test_stop_checked_before_time_exit_same_bar(self):
        b = bars([(100, 100, 100, 100), (100, 103, 97, 102)])
        t = simulate(b, [Signal(i=1, direction=1, stop=98, exit_at=1)], INST, COSTS, RISK)
        self.assertEqual(t["reason"][0], "stop")

    def test_short_mirrors(self):
        b = bars([(100, 100, 100, 100), (100, 100, 100, 100), (90, 90, 90, 90)])
        t = simulate(b, [Signal(i=1, direction=-1, stop=110, exit_at=2)], INST, COSTS, RISK)
        self.assertAlmostEqual(t["entry"][0], 99.5)
        self.assertAlmostEqual(t["exit"][0], 90.5)
        self.assertGreater(t["pnl"][0], 0)

    def test_overlapping_signals_skipped_and_sizing(self):
        b = bars([(100, 100, 100, 100)] * 5)
        t = simulate(b, [Signal(1, 1, 90, exit_at=3), Signal(2, 1, 90, exit_at=4)], INST, COSTS, RISK)
        self.assertEqual(len(t), 1)
        self.assertAlmostEqual(t["units"][0], 100 / (100.5 - 90))  # 1 % Risiko / Stopabstand

    def test_financing_nights(self):
        u = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731
        self.assertEqual(_nights(u("2024-03-05 20:00"), u("2024-03-05 21:00"), "23:00", "Europe/Berlin"), 0)
        self.assertEqual(_nights(u("2024-03-05 20:00"), u("2024-03-06 14:00"), "23:00", "Europe/Berlin"), 1)
        self.assertEqual(_nights(u("2024-03-08 20:00"), u("2024-03-11 14:00"), "23:00", "Europe/Berlin"), 3)  # Freitag


if __name__ == "__main__":
    unittest.main()
