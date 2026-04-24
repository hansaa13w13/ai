"""Multi-timeframe sinyaller: haftalık sinyal ve günlük↔haftalık konfluence skoru."""
from __future__ import annotations

from .. import config
from ..indicators import ema as ind_ema, macd as ind_macd, rsi as ind_rsi
from ..utils import now_str
from ._chart_io import _read_json_cache, _write_json_cache, fetch_chart2_candles


def get_weekly_signal(code: str) -> dict:
    cache = config.CACHE_DIR / f"predator_wtf_{code.upper()}.json"
    cached = _read_json_cache(cache, 7200)
    if cached and cached.get("trend"):
        return cached
    empty = {"trend": "notr", "rsi": 50, "macdCross": "none", "emaCross": "none",
             "signal": "notr", "confluence": False}
    candles = fetch_chart2_candles(code, periyot="H", bar=100)
    if len(candles) < 10:
        _write_json_cache(cache, empty)
        return empty
    closes = [c["Close"] for c in candles]
    n = len(closes)
    sma20 = sum(closes[-20:]) / 20 if n >= 20 else closes[-1]
    sma50 = sum(closes[-50:]) / 50 if n >= 50 else sma20
    rsi_v = ind_rsi(closes)
    macd_d = ind_macd(closes)
    macd_cross = "none"
    if macd_d.get("hist", 0) > 0 and macd_d.get("prev_hist", 0) <= 0: macd_cross = "golden"
    elif macd_d.get("hist", 0) < 0 and macd_d.get("prev_hist", 0) >= 0: macd_cross = "death"
    ema9 = ind_ema(closes, 9); ema21 = ind_ema(closes, 21)
    ema_cross = "none"
    if len(ema9) >= 2 and len(ema21) >= 2:
        if ema9[-1] > ema21[-1] and ema9[-2] <= ema21[-2]: ema_cross = "golden"
        elif ema9[-1] < ema21[-1] and ema9[-2] >= ema21[-2]: ema_cross = "death"

    trend = "yukselis" if sma20 > sma50 else ("dusus" if sma20 < sma50 else "notr")
    bull = bear = 0
    if rsi_v < 40: bull += 1
    if rsi_v > 60: bear += 1
    if trend == "yukselis": bull += 1
    if trend == "dusus":    bear += 1
    if macd_cross == "golden": bull += 1
    if macd_cross == "death":  bear += 1
    if ema_cross == "golden": bull += 1
    if ema_cross == "death":  bear += 1
    if   bull >= 3: signal = "guclu_boga"
    elif bull >= 2: signal = "boga"
    elif bear >= 3: signal = "guclu_ayi"
    elif bear >= 2: signal = "ayi"
    else: signal = "notr"
    out = {"trend": trend, "rsi": round(rsi_v, 1), "macdCross": macd_cross, "emaCross": ema_cross,
           "signal": signal, "sma20": round(sma20, 4), "sma50": round(sma50, 4),
           "bullScore": bull, "bearScore": bear,
           "confluence": (bull >= 2 or bear >= 2), "cached_at": now_str()}
    _write_json_cache(cache, out)
    return out


def mtf_confluence_score(daily_tech: dict, weekly_signal: dict) -> int:
    bonus = 0
    daily_bull = int(daily_tech.get("techScore", 50)) >= 60
    daily_bear = int(daily_tech.get("techScore", 50)) <= 40
    ws = weekly_signal.get("signal", "notr"); wt = weekly_signal.get("trend", "notr")
    if daily_bull and ws in ("boga", "guclu_boga") and wt == "yukselis": bonus += 20
    elif daily_bull and wt == "yukselis": bonus += 12
    elif daily_bull and ws in ("boga", "guclu_boga"): bonus += 10
    if daily_bear and ws in ("ayi", "guclu_ayi") and wt == "dusus": bonus -= 18
    elif daily_bear and wt == "dusus": bonus -= 10
    if daily_bull and ws in ("ayi", "guclu_ayi"): bonus -= 12
    if daily_bear and ws in ("boga", "guclu_boga"): bonus -= 8
    return max(-25, min(25, bonus))
