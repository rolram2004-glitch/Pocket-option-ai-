import os
import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models import Direction  # noqa: E402
from parser import parse_signal  # noqa: E402
from risk import check_demo_trade  # noqa: E402
from store import Store  # noqa: E402
from strategy import rsi_series  # noqa: E402


class ParserTests(unittest.TestCase):
    def test_fx_otc_signal(self):
        s = parse_signal("🔥 EUR/USD OTC CALL 1m 87%")
        self.assertIsNotNone(s)
        assert s is not None
        self.assertEqual(s.asset, "EURUSD_OTC")
        self.assertEqual(s.direction, Direction.CALL)
        self.assertEqual(s.expiry_seconds, 60)
        self.assertEqual(s.confidence, 87.0)

    def test_put_seconds(self):
        s = parse_signal("BTCUSD PUT 30s 82%")
        self.assertIsNotNone(s)
        assert s is not None
        self.assertEqual(s.asset, "BTCUSD")
        self.assertEqual(s.direction, Direction.PUT)
        self.assertEqual(s.expiry_seconds, 30)

    def test_no_direction_is_not_invented(self):
        self.assertIsNone(parse_signal("EURUSD 1m 90%"))


class StrategyTests(unittest.TestCase):
    def test_rsi_wilder_extremes(self):
        up = rsi_series([1, 2, 3, 4, 5, 6, 7, 8], 3)
        down = rsi_series([8, 7, 6, 5, 4, 3, 2, 1], 3)
        self.assertEqual(up[-1], 100.0)
        self.assertEqual(down[-1], 0.0)

    def test_rsi_is_bounded(self):
        values = rsi_series([10, 9, 11, 8, 12, 9, 13, 12, 14, 11], 3)
        numeric = [value for value in values if value is not None]
        self.assertTrue(numeric)
        self.assertTrue(all(0 <= value <= 100 for value in numeric))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite3")
        tmp.close()
        self.db = tmp.name
        self.store = Store(self.db, 1000, 1, 60, 80)

    def tearDown(self):
        os.unlink(self.db)

    def test_demo_trade_and_settlement(self):
        s = parse_signal("EURUSD CALL 1m 90%")
        assert s is not None
        trade = self.store.create_demo_trade(123, s)
        self.assertEqual(trade.status, "PENDING")
        self.assertEqual(self.store.get_profile(123).demo_balance, 999)
        trade = self.store.settle_demo_trade(123, trade.trade_id, "WIN", 0.82)
        self.assertEqual(trade.status, "WIN")
        self.assertAlmostEqual(trade.pnl, 0.82)
        self.assertAlmostEqual(self.store.get_profile(123).demo_balance, 1000.82)


if __name__ == "__main__":
    unittest.main()
