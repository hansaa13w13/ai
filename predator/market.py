"""Piyasa modu (bull / temkinli / ayi) ve volatilite rejimi.

PHP cache şemasıyla birebir uyumlu:
  MARKET_MODE_FILE  → mode, code, sma20/50/200, rsi, bearScore, bullScore, ai_bias, ts, date
  VOLATILITY_FILE   → atr, atrPct, ts, code, level (extreme/high/normal)
"""
from __future__ import annotations
import time
from . import config
from .utils import load_json, save_json, now_str


# ── Okuma fonksiyonları ─────────────────────────────────────────────────────
def get_market_mode() -> str:
    """Cache'lenmiş piyasa modunu döndürür (2 saatten eskiyse 'bull')."""
    data = load_json(config.MARKET_MODE_FILE, {})
    if isinstance(data, dict) and "mode" in data:
        ts = int(data.get("ts", 0) or 0)
        if ts and (time.time() - ts) < 7200:
            return str(data["mode"])
        return str(data["mode"])  # eski cache de kabul (PHP gibi)
    return "bull"


def get_volatility_regime() -> str:
    """PHP getVolatilityLevel — extreme/high/normal."""
    data = load_json(config.VOLATILITY_FILE, {})
    if not isinstance(data, dict):
        return "normal"
    ts = int(data.get("ts", 0) or 0)
    if ts and (time.time() - ts) > 86400:
        return "normal"
    return str(data.get("level", data.get("regime", "normal")))


# ── Yazma fonksiyonları ─────────────────────────────────────────────────────
def set_market_mode(mode: str, reason: str = "", **extra) -> None:
    """Sade ayar — geriye dönük uyumluluk için."""
    payload = {
        "mode": mode,
        "code": extra.get("code", ""),
        "ts":   int(time.time()),
        "date": now_str(),
        "reason": reason,
    }
    payload.update({k: v for k, v in extra.items() if k != "code"})
    save_json(config.MARKET_MODE_FILE, payload)


def set_volatility_regime(level: str, atr_pct: float = 0.0,
                          atr: float = 0.0, code: str = "XU100") -> None:
    """PHP volatility cache şeması."""
    save_json(config.VOLATILITY_FILE, {
        "atr":    round(float(atr), 4),
        "atrPct": round(float(atr_pct), 2),
        "ts":     int(time.time()),
        "code":   code,
        "level":  level,
    })


# ── PHP saveMarketMode birebir port ─────────────────────────────────────────
def save_market_mode(tech: dict, code: str = "XU100", ai_bias: str = "notr") -> str:
    """PHP saveMarketMode($tech, $code) birebir.

    5 faktörlü skorlama: SMA dizilimi, RSI, MACD hist, ADX yönü, CMF.
    Sonra AI bias bir kademe nüansla. Volatilite ATR/SMA50%'den hesaplanır.
    """
    sma20  = float(tech.get("sma20", 0)  or 0)
    sma50  = float(tech.get("sma50", 0)  or 0)
    sma200 = float(tech.get("sma200", 0) or 0)
    rsi    = float(tech.get("rsi", 50)   or 50)

    # MACD hist alabiliriz: nested macd dict ya da flat macdHist
    macd_hist = float(tech.get("macdHist",
                     (tech.get("macd") or {}).get("hist", 0)) or 0)
    adx_dir = (tech.get("adxDir") or
               (tech.get("adx") or {}).get("dir", "notr") or "notr")
    adx_val = float(tech.get("adxVal",
                    (tech.get("adx") or {}).get("adx", 0)) or 0)
    cmf_val = float(tech.get("cmf", 0) or 0)

    bull_score = 0
    bear_score = 0

    # SMA dizilimi
    if sma20 > 0 and sma50 > 0 and sma200 > 0:
        if sma50 < sma200 and sma20 < sma50:
            bear_score += 3
        elif sma20 < sma50:
            bear_score += 1
        elif sma20 > sma50 and sma50 > sma200:
            bull_score += 3
        elif sma20 > sma50:
            bull_score += 1

    # RSI
    if   rsi < 35: bear_score += 2
    elif rsi < 45: bear_score += 1
    elif rsi > 70: bull_score += 2
    elif rsi > 60: bull_score += 1

    # MACD histogram
    if   macd_hist < -0.5: bear_score += 1
    elif macd_hist >  0.5: bull_score += 1

    # ADX yönü
    if adx_dir == "dusus"    and adx_val >= 20: bear_score += 1
    if adx_dir == "yukselis" and adx_val >= 20: bull_score += 1

    # CMF
    if   cmf_val < -0.10: bear_score += 1
    elif cmf_val >  0.10: bull_score += 1

    # v42: Piyasa genişliği faktörü — breadth sağlık skoru piyasa modunu etkiler
    try:
        from .scoring_extras._breadth import get_market_breadth
        _b = get_market_breadth()
        if _b:
            _bh = float(_b.get("health") or 50)
            _adv = int(_b.get("adv_decline") or 0)
            _smc_br = float(_b.get("smc_breadth") or 50)
            if   _bh >= 72: bull_score += 2
            elif _bh >= 60: bull_score += 1
            elif _bh <= 28: bear_score += 2
            elif _bh <= 38: bear_score += 1
            if _adv > 150: bull_score += 1
            elif _adv < -150: bear_score += 1
            if _smc_br >= 60: bull_score += 1
            elif _smc_br <= 30: bear_score += 1
    except Exception:
        pass

    # Kural tabanlı mod
    if   bear_score >= 6:               mode = "ayi"
    elif bear_score >= 4:               mode = "temkinli"
    elif bull_score >= 5:               mode = "bull"
    elif bear_score >= 3:               mode = "temkinli"
    elif bull_score >= 4:               mode = "bull"
    elif bear_score > bull_score:       mode = "temkinli"
    else:                                mode = "bull"

    # AI bias nüanslama
    if ai_bias == "bull_bias":
        if mode == "ayi": mode = "temkinli"
    elif ai_bias == "bear_bias":
        if mode == "bull": mode = "temkinli"

    save_json(config.MARKET_MODE_FILE, {
        "mode":      mode,
        "code":      code,
        "sma20":     round(sma20, 2),
        "sma50":     round(sma50, 2),
        "sma200":    round(sma200, 2),
        "rsi":       round(rsi, 1),
        "bearScore": bear_score,
        "bullScore": bull_score,
        "ai_bias":   ai_bias,
        "ts":        int(time.time()),
        "date":      now_str(),
    })

    # Volatilite kaydı
    atr_raw   = float(tech.get("atr", tech.get("atr14", 0)) or 0)
    ref_price = sma50 if sma50 > 0 else (sma20 if sma20 > 0 else 0)
    if ref_price > 0 and atr_raw > 0:
        atr_pct = round(atr_raw / ref_price * 100, 2)
        if atr_pct > 0:
            level = "extreme" if atr_pct >= 4.0 else ("high" if atr_pct >= 2.5 else "normal")
            set_volatility_regime(level, atr_pct=atr_pct, atr=atr_raw, code=code)

    return mode


# ── Eski API: tepe seçimlerden mod tahmini (geriye dönük uyumluluk) ─────────
def detect_market_mode(top_picks: list[dict]) -> str:
    if not top_picks:
        return get_market_mode()
    bull = bear = 0
    for s in top_picks[:30]:
        score = float(s.get("aiScore", 0) or 0)
        rsi   = float(s.get("rsi", 50) or 50)
        if score >= 100: bull += 1
        if score <= 40:  bear += 1
        if rsi >= 65 and score < 80: bear += 1
        if rsi <= 35 and score > 60: bull += 1
    if   bull >= bear * 1.8:  mode = "bull"
    elif bear >= bull * 1.5:  mode = "ayi"
    else:                     mode = "temkinli"
    set_market_mode(mode, reason=f"bull={bull} bear={bear}")
    return mode


def market_mode_label(mode: str) -> str:
    """PHP marketModeLabel."""
    return {
        "bull":     "🟢 BOĞA MODU",
        "temkinli": "🟡 TEMKİNLİ MOD",
        "ayi":      "🔴 AYI MODU",
    }.get(mode, "⚪ NORMAL MOD")


# Eskinin alias'ı
get_volatility_level = get_volatility_regime
