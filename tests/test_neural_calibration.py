"""neural.predict_calibrated — sıcaklık kalibrasyonu davranışı."""
from __future__ import annotations
import math

from predator import neural


def _stub_snap():
    """Tahmin için minimal snapshot — neural.features_from_snap ne tüketiyorsa
    kabul edilebilir defaultlarla doldurur."""
    return {
        "rsi": 50.0, "adxVal": 20.0, "macdHist": 0.0, "cmf": 0.0,
        "mfi": 50.0, "volRatio": 1.0, "pos52wk": 50.0, "atrPct": 2.0,
        "score": 100.0, "aiScore": 100.0, "techScore": 50.0, "finScore": 50.0,
    }


class TestPredictCalibrated:
    def test_empty_net_returns_neutral(self):
        p, c = neural.predict_calibrated({}, _stub_snap())
        assert p == 0.5 and c == 0.0

    def test_returns_prob_and_confidence_in_range(self):
        net = neural.make_net("alpha")
        p, c = neural.predict_calibrated(net, _stub_snap())
        assert 0.0 <= p <= 1.0
        assert 0.0 <= c <= 1.0

    def test_low_training_lowers_confidence(self):
        net = neural.make_net("alpha")
        net["trained_samples"] = 0
        net["recent_accuracy"] = 50.0
        net["avg_loss"] = 0.5
        _, c_low = neural.predict_calibrated(net, _stub_snap())

        net2 = neural.make_net("alpha")
        net2["trained_samples"] = 200
        net2["recent_accuracy"] = 80.0
        net2["avg_loss"] = 0.05
        _, c_high = neural.predict_calibrated(net2, _stub_snap())

        assert c_high > c_low

    def test_high_temperature_pulls_to_neutral(self):
        """avg_loss çok yüksek olduğunda tahmin 0.5'e çekilir (yumuşatma)."""
        net = neural.make_net("alpha")
        # Ham tahmini ekstreme zorlamak için bias'a dokunmaya çalışmaktansa,
        # eğer ham çıktı 0.5'ten farklıysa, T büyüdükçe |p-0.5| küçülmeli.
        net["avg_loss"] = 0.05
        net["recent_accuracy"] = 80.0
        net["trained_samples"] = 100
        p_low_T, _ = neural.predict_calibrated(net, _stub_snap())

        net["avg_loss"] = 1.0
        net["recent_accuracy"] = 30.0
        net["trained_samples"] = 5
        p_high_T, _ = neural.predict_calibrated(net, _stub_snap())

        # Yüksek sıcaklık → 0.5'e daha yakın
        assert abs(p_high_T - 0.5) <= abs(p_low_T - 0.5) + 1e-9


class TestPredictRobustness:
    def test_predict_returns_finite_on_garbage(self):
        net = neural.make_net("alpha")
        out = neural.predict(net, {"rsi": "x", "adxVal": None})
        assert 0.0 <= out <= 1.0
        assert math.isfinite(out)
