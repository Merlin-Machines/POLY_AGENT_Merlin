import unittest

from utils.indicators import FEATURE_COLS, build_feature_snapshot, technical_signal
from utils.ml_filter import MLFilter


def _candles(count=60):
    rows = []
    price = 100.0
    for idx in range(count):
        price += 0.4 if idx > count // 2 else -0.05
        rows.append({
            "open": price - 0.2,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": 1000 + idx,
        })
    return rows


class CryptoSignalToolsTest(unittest.TestCase):
    def test_feature_snapshot_contains_model_columns(self):
        features = build_feature_snapshot(_candles())
        for column in FEATURE_COLS:
            self.assertIn(column, features)
            self.assertIsInstance(features[column], float)

    def test_technical_signal_returns_known_shape(self):
        features = build_feature_snapshot(_candles())
        signal, details = technical_signal(features)
        self.assertIn(signal, {"BUY", "SELL", "HOLD"})
        self.assertIn("reason", details)
        self.assertIn("rsi", details)

    def test_ml_filter_missing_model_respects_fail_open(self):
        gate = MLFilter("missing-model.pkl", "missing-scaler.pkl")
        self.assertFalse(gate.load())
        ok, prob, reason = gate.approve({}, FEATURE_COLS, fail_open=True)
        self.assertTrue(ok)
        self.assertIsNone(prob)
        self.assertEqual(reason, "model_files_missing")
        ok, _, _ = gate.approve({}, FEATURE_COLS, fail_open=False)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
