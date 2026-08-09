import os
import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models import Candle, Direction, StrategyMode  # noqa: E402
from market import KrakenPublicMarket  # noqa: E402
from parser import parse_signal  # noqa: E402
from risk import check_demo_trade  # noqa: E402
from store import Store  # noqa: E402
from strategy import (  # noqa: E402
    RsiLevel,
    direction_for_rsi_level,
    rsi_level_cross_signal,
    rsi_series,
)


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

    def test_normal_and_inverse_mapping(self):
        self.assertEqual(
            direction_for_rsi_level(RsiLevel.UPPER), Direction.CALL
        )
        self.assertEqual(
            direction_for_rsi_level(RsiLevel.LOWER), Direction.PUT
        )
        self.assertEqual(
            direction_for_rsi_level(RsiLevel.UPPER, inverse=True), Direction.PUT
        )
        self.assertEqual(
            direction_for_rsi_level(RsiLevel.LOWER, inverse=True), Direction.CALL
        )

    def test_threshold_cross_emits_only_on_entry(self):
        closes = [1, 1, 1, 1, 1, 1, 2]
        candles = [
            Candle(str(i), close, close, close, close)
            for i, close in enumerate(closes)
        ]
        decision = rsi_level_cross_signal(candles, 3, 14, 86)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.level, RsiLevel.UPPER)


class PublicMarketTests(unittest.TestCase):
    def test_keyless_feed_supports_crypto_only(self):
        self.assertTrue(KrakenPublicMarket.supports("BTC/USD"))
        self.assertTrue(KrakenPublicMarket.supports("ethusd"))
        self.assertFalse(KrakenPublicMarket.supports("EUR/USD"))
        self.assertEqual(KrakenPublicMarket.pair_for("BTC/USD"), "XBTUSD")

    def test_kraken_payload_excludes_open_candle_for_signals(self):
        payload = {
            "error": [],
            "result": {
                "BTC/USD": [
                    [100, "1", "2", "0.5", "1.5", "1.2", "3", 4],
                    [160, "1.5", "3", "1", "2.5", "2", "4", 5],
                ],
                "last": 160,
            },
        }
        candles = KrakenPublicMarket._parse_payload(
            "BTC/USD", payload, 20, include_current=False
        )
        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[-1].close, 1.5)

    def test_kraken_live_price_includes_open_candle(self):
        payload = {
            "error": [],
            "result": {
                "BTC/USD": [
                    [100, "1", "2", "0.5", "1.5", "1.2", "3", 4],
                    [160, "1.5", "3", "1", "2.5", "2", "4", 5],
                ],
                "last": 160,
            },
        }
        candles = KrakenPublicMarket._parse_payload(
            "BTC/USD", payload, 20, include_current=True
        )
        self.assertEqual(candles[-1].close, 2.5)


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

    def test_dual_demo_is_active_by_default_and_can_be_reactivated(self):
        profile = self.store.get_profile(123)
        self.assertTrue(profile.strategy_on)
        self.assertEqual(profile.strategy_mode, StrategyMode.COMPARE)
        self.store.set_value(123, "strategy_on", False)
        self.store.set_value(123, "strategy_mode", StrategyMode.NORMAL.value)
        profile = self.store.activate_dual_demo(123)
        self.assertTrue(profile.strategy_on)
        self.assertEqual(profile.strategy_mode, StrategyMode.COMPARE)

    def test_strategy_mode_and_variant_are_persisted(self):
        profile = self.store.set_value(123, "strategy_mode", StrategyMode.INVERSE.value)
        self.assertEqual(profile.strategy_mode, StrategyMode.INVERSE)
        signal = parse_signal("EURUSD PUT 1m 90%")
        assert signal is not None
        trade = self.store.create_demo_trade(
            123, signal, strategy_variant=StrategyMode.INVERSE.value
        )
        self.assertEqual(trade.strategy_variant, StrategyMode.INVERSE.value)
        self.assertEqual(self.store.get_profile(123).demo_balance, 1000)
        self.assertEqual(
            self.store.strategy_ledger_balance(123, StrategyMode.INVERSE.value),
            999,
        )

    def test_strategy_comparison_splits_results(self):
        normal_signal = parse_signal("EURUSD CALL 1m 90%")
        inverse_signal = parse_signal("EURUSD PUT 1m 90%")
        assert normal_signal is not None and inverse_signal is not None
        normal = self.store.create_demo_trade(
            123, normal_signal, strategy_variant=StrategyMode.NORMAL.value
        )
        inverse = self.store.create_demo_trade(
            123, inverse_signal, strategy_variant=StrategyMode.INVERSE.value
        )
        self.store.settle_demo_trade(123, normal.trade_id, "WIN", 0.82)
        self.store.settle_demo_trade(123, inverse.trade_id, "LOSS", 0.82)

        stats = self.store.strategy_comparison(123)
        self.assertEqual(stats[StrategyMode.NORMAL.value]["wins"], 1)
        self.assertEqual(stats[StrategyMode.INVERSE.value]["losses"], 1)
        self.assertAlmostEqual(stats[StrategyMode.NORMAL.value]["pnl"], 0.82)
        self.assertAlmostEqual(stats[StrategyMode.INVERSE.value]["pnl"], -1.0)
        self.assertAlmostEqual(
            stats[StrategyMode.NORMAL.value]["balance"], 1000.82
        )
        self.assertAlmostEqual(stats[StrategyMode.INVERSE.value]["balance"], 999.0)
        self.assertEqual(self.store.get_profile(123).demo_balance, 1000)


if __name__ == "__main__":
    unittest.main()
