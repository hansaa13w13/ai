"""Smart Money Concepts — order block, FVG, liquidity sweep tespiti."""
from __future__ import annotations
import numpy as np
from typing import Any


def smc_analyze(highs, lows, opens, closes, volumes=None) -> dict:
    """Basit SMC bias hesabı: bullish / bearish / notr."""
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    o = np.asarray(opens, dtype=float)
    c = np.asarray(closes, dtype=float)
    if len(c) < 30:
        return {"bias": "notr", "ob": None, "fvg": None, "sweep": False}

    # Yapısal kırılım tespiti — son 30 barda HH/HL trendi (vectorized)
    n_c = len(c)
    swing_highs = []
    swing_lows = []
    if n_c >= 5:
        idx = np.arange(2, n_c - 2)
        sh_mask = ((h[2:-2] > h[1:-3]) & (h[2:-2] > h[:-4]) &
                   (h[2:-2] > h[3:-1]) & (h[2:-2] > h[4:]))
        sl_mask = ((l[2:-2] < l[1:-3]) & (l[2:-2] < l[:-4]) &
                   (l[2:-2] < l[3:-1]) & (l[2:-2] < l[4:]))
        swing_highs = [(int(i), float(h[i])) for i in idx[sh_mask]]
        swing_lows  = [(int(i), float(l[i])) for i in idx[sl_mask]]

    bias = "notr"
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        last_hh = swing_highs[-1][1] > swing_highs[-2][1]
        last_hl = swing_lows[-1][1] > swing_lows[-2][1]
        if last_hh and last_hl:
            bias = "bullish"
        elif (not last_hh) and (not last_hl):
            bias = "bearish"

    # Fair Value Gap (FVG): üç barlık imbalance
    fvg = None
    for i in range(len(c) - 1, 1, -1):
        if l[i] > h[i - 2]:  # bullish FVG
            fvg = {"type": "bullish", "top": float(l[i]), "bot": float(h[i - 2]), "bar": i}
            break
        if h[i] < l[i - 2]:  # bearish FVG
            fvg = {"type": "bearish", "top": float(l[i - 2]), "bot": float(h[i]), "bar": i}
            break

    # Liquidity sweep: son barın önceki swing high'ı aşıp geri çekilmesi
    sweep = False
    if swing_highs and bias == "bearish":
        last_swing = swing_highs[-1][1]
        if h[-1] > last_swing and c[-1] < last_swing:
            sweep = True

    # Order block (basitleştirilmiş): son güçlü hareket öncesi karşı-yön mum
    ob = None
    for i in range(len(c) - 2, max(0, len(c) - 20), -1):
        move = (c[i + 1] - c[i]) / c[i] * 100 if c[i] else 0
        if move > 3 and c[i] < o[i]:
            ob = {"type": "bullish", "top": float(o[i]), "bot": float(c[i]), "bar": i}
            break
        if move < -3 and c[i] > o[i]:
            ob = {"type": "bearish", "top": float(c[i]), "bot": float(o[i]), "bar": i}
            break

    return {"bias": bias, "ob": ob, "fvg": fvg, "sweep": sweep}


def order_flow_imbalance(closes, volumes, period: int = 14) -> str:
    """OFI sinyali: alış/satış baskısı."""
    c = np.asarray(closes, dtype=float)
    v = np.asarray(volumes, dtype=float)
    n = min(len(c), len(v))
    if n < period + 1:
        return "notr"
    diff = np.diff(c[-(period + 1):])
    vol_window = v[-period:]
    buy_vol = vol_window[diff > 0].sum()
    sell_vol = vol_window[diff < 0].sum()
    total = buy_vol + sell_vol
    if total == 0:
        return "notr"
    ratio = buy_vol / total
    if ratio > 0.70: return "guclu_alis"
    if ratio > 0.58: return "alis"
    if ratio < 0.30: return "guclu_satis"
    if ratio < 0.42: return "satis"
    return "notr"
