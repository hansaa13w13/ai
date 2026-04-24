"""predator.indicators — RSI, EMA, MACD, ATR, ADX sayısal kararlılık."""
from __future__ import annotations
import math

import numpy as np
import pytest

from predator import indicators as ind


def _trend_up(n=120, start=100.0, step=0.5):
    return [start + i * step for i in range(n)]


def _trend_flat(n=120, val=100.0):
    return [val] * n


class TestRSI:
    def test_rsi_uptrend_high(self):
        rsi = ind.rsi(_trend_up(), period=14)
        assert rsi > 70  # sürekli artan seri → aşırı alım

    def test_rsi_flat_neutral(self):
        rsi = ind.rsi(_trend_flat(), period=14)
        # Düz seride RS tanımsız → fonksiyon güvenli bir varsayılan döner.
        assert 0 <= rsi <= 100

    def test_rsi_short_input(self):
        # period+1'den az veri → sınırlı/temkinli skor; en azından patlamamalı.
        rsi = ind.rsi([100.0, 101.0, 102.0], period=14)
        assert 0 <= rsi <= 100


class TestEMA:
    def test_ema_length_matches(self):
        e = ind.ema(_trend_up(60), period=9)
        assert len(e) == 60

    def test_ema_tracks_trend(self):
        e = ind.ema(_trend_up(60), period=9)
        # Sürekli artan seri → EMA da artıyor olmalı.
        assert e[-1] > e[10]


class TestMACD:
    def test_macd_keys(self):
        m = ind.macd(_trend_up(120))
        assert {"macd", "signal", "hist"} <= set(m.keys())

    def test_macd_uptrend_positive_hist(self):
        m = ind.macd(_trend_up(120))
        assert m["hist"] > 0


class TestATR_ADX_NumericalStability:
    def test_atr_handles_constant_series(self):
        n = 50
        h = _trend_flat(n, 10.0)
        l = _trend_flat(n, 10.0)
        c = _trend_flat(n, 10.0)
        v = ind.atr(h, l, c, period=14)
        assert math.isfinite(v)
        assert v >= 0

    def test_adx_returns_finite_on_zero_range(self):
        """v38.1: adx() sıfır true-range'de overflow vermemeli."""
        n = 60
        h = _trend_flat(n)
        l = _trend_flat(n)
        c = _trend_flat(n)
        d = ind.adx(h, l, c, period=14)
        # Modülün dış API'si: val/plusDI/minusDI/dir
        assert {"val", "plusDI", "minusDI"} <= set(d.keys())
        for k in ("val", "plusDI", "minusDI"):
            assert math.isfinite(float(d[k])), f"{k} should be finite"

    def test_adx_uptrend_higher_plus_di(self):
        n = 80
        c = np.array(_trend_up(n))
        h = c + 0.5
        l = c - 0.5
        d = ind.adx(h.tolist(), l.tolist(), c.tolist(), period=14)
        assert d["plusDI"] >= d["minusDI"]


class TestSMA:
    def test_sma_average(self):
        out = ind.sma([1, 2, 3, 4, 5], period=5)
        assert out == pytest.approx(3.0)

    def test_sma_short_returns_safe(self):
        # period > len → fonksiyon güvenli bir değer döndürmeli (patlamamalı)
        out = ind.sma([1, 2], period=5)
        assert math.isfinite(out)
