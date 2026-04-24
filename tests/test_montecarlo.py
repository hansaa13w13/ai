"""predator.montecarlo — vektörize GBM ve Kelly fraksiyonu."""
from __future__ import annotations
import math

import numpy as np
import pytest

from predator import montecarlo as mc


class TestMonteCarlo:
    def test_insufficient_history_low_confidence(self):
        out = mc.monte_carlo_forecast([100.0, 101.0, 102.0], days=10, simulations=50)
        assert out["low_confidence"] is True
        assert out["confidence"] == 0.0
        assert out["reason"] == "insufficient_history"
        assert out["mean"] == 102.0  # son fiyatı döner

    def test_zero_volatility_low_confidence(self):
        flat = [100.0] * 60
        out = mc.monte_carlo_forecast(flat, days=10, simulations=50)
        assert out["low_confidence"] is True
        assert out["reason"] == "zero_volatility"

    def test_gbm_keys_and_ranges(self):
        rng = np.random.default_rng(42)
        rets = rng.normal(0.0005, 0.015, 200)
        prices = 100.0 * np.cumprod(1 + rets)
        out = mc.monte_carlo_forecast(prices.tolist(), days=20, simulations=300)
        assert {"mean", "p25", "p75", "p_up", "exp_ret",
                "confidence", "low_confidence", "n_obs", "sigma_ann"} <= set(out.keys())
        assert 0.0 <= out["p_up"] <= 1.0
        assert out["p25"] <= out["mean"] <= out["p75"] or abs(out["p25"] - out["p75"]) < 1e-9
        assert out["n_obs"] == 200
        assert out["sigma_ann"] > 0

    def test_gbm_mean_finite(self):
        rng = np.random.default_rng(7)
        prices = 50.0 + np.cumsum(rng.normal(0.05, 0.5, 250))
        prices = np.clip(prices, 1.0, None)
        out = mc.monte_carlo_forecast(prices.tolist(), days=30, simulations=500)
        assert math.isfinite(out["mean"])
        assert math.isfinite(out["exp_ret"])


class TestKelly:
    def test_kelly_zero_when_no_edge(self):
        # win_rate=0.5, avg_win=avg_loss → b=1, k=0
        assert mc.kelly_fraction(0.5, 1.0, 1.0) == 0.0

    def test_kelly_positive_edge(self):
        # win_rate=0.6, win:loss=2:1 → kazançlı
        k = mc.kelly_fraction(0.6, 2.0, 1.0)
        assert 0.0 < k <= 0.25  # half-Kelly + cap

    def test_kelly_capped_at_quarter(self):
        # Aşırı uçlar → 0.25 cap
        k = mc.kelly_fraction(0.95, 5.0, 1.0)
        assert k == 0.25

    def test_kelly_zero_loss_returns_zero(self):
        assert mc.kelly_fraction(0.7, 1.0, 0.0) == 0.0

    def test_kelly_zero_winrate_returns_zero(self):
        assert mc.kelly_fraction(0.0, 2.0, 1.0) == 0.0
