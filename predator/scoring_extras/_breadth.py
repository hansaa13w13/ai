"""Piyasa genişliği (market breadth) hesaplaması ve cache."""

from __future__ import annotations

from .. import config
from ..utils import load_json


_BREADTH_CACHE: dict | None = None


def get_market_breadth() -> dict:
    """PHP getMarketBreadth birebir."""
    global _BREADTH_CACHE
    if _BREADTH_CACHE is not None:
        return _BREADTH_CACHE
    data = load_json(config.ALLSTOCKS_CACHE, {}) or {}
    stocks = data.get("stocks") or []
    if not stocks:
        return {}
    total = len(stocks)
    rising = falling = above_ema = below_ema = 0
    macd_bull = macd_bear = vol_surge = rsi_oversold = 0
    cmf_pos = sar_up = 0
    net_change = 0.0
    for s in stocks:
        r = float(s.get("gunlukDegisim") or s.get("ret1d") or 0)
        net_change += r
        if r > 0: rising += 1
        elif r < 0: falling += 1
        t = s.get("trend") or ""
        if t == "Yukselis": above_ema += 1
        elif t == "Dusus": below_ema += 1
        mc = s.get("macdCross") or ""
        if mc == "golden": macd_bull += 1
        elif mc == "death": macd_bear += 1
        if float(s.get("volRatio") or 1) >= 2.0: vol_surge += 1
        if float(s.get("rsi") or 50) < 30: rsi_oversold += 1
        if float(s.get("cmf") or 0) > 0.05: cmf_pos += 1
        if (s.get("sarDir") or "") == "yukselis": sar_up += 1
    adv_decline = rising - falling
    breadth_pct = round(rising / total * 100, 1) if total else 50
    ema_breadth = round(above_ema / total * 100, 1) if total else 50
    macd_breadth = round(macd_bull / total * 100, 1) if total else 50
    cmf_breadth = round(cmf_pos / total * 100, 1) if total else 50
    avg_change = round(net_change / total, 2) if total else 0
    health = round(breadth_pct * 0.35 + ema_breadth * 0.25 + macd_breadth * 0.20 + cmf_breadth * 0.20, 1)
    if health >= 70:   label, color, sig = "GÜÇLÜ", "#00ff9d", "AL"
    elif health >= 55: label, color, sig = "ORTA", "#ffea00", "BEKLE"
    elif health >= 40: label, color, sig = "ZAYIF", "#ff9900", "BEKLE"
    else:              label, color, sig = "KRİTİK", "#ff003c", "SAT"
    if health >= 65: sig = "AL"
    elif health >= 45: sig = "BEKLE"
    else: sig = "SAT"
    res = {
        "total": total, "rising": rising, "falling": falling,
        "breadth_pct": breadth_pct, "ema_breadth": ema_breadth,
        "macd_breadth": macd_breadth, "cmf_breadth": cmf_breadth,
        "vol_surge_cnt": vol_surge, "oversold_cnt": rsi_oversold,
        "sar_up_cnt": sar_up, "adv_decline": adv_decline,
        "avg_change": avg_change, "health": health,
        "health_label": label, "health_color": color, "signal": sig,
    }
    _BREADTH_CACHE = res
    return res


def reset_breadth_cache() -> None:
    global _BREADTH_CACHE
    _BREADTH_CACHE = None
