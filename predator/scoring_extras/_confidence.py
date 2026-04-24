"""Güven aralığı (confidence) skorlama."""

from __future__ import annotations

from ..market import get_market_mode, get_volatility_regime
from ._breadth import get_market_breadth


def calculate_confidence_score(signal_quality: int, ai_score: int,
                                market_mode: str = "", extra: dict | None = None) -> int:
    """PHP calculateConfidenceScore birebir (v36)."""
    extra = extra or {}
    base = round(signal_quality / 10 * 68)
    if   ai_score >= 280: base += 30
    elif ai_score >= 220: base += 25
    elif ai_score >= 170: base += 18
    elif ai_score >= 120: base += 12
    elif ai_score >=  80: base +=  6
    if not market_mode:
        market_mode = get_market_mode()
    if   market_mode == "ayi":      base = round(base * 0.72)
    elif market_mode == "temkinli": base = round(base * 0.86)
    elif market_mode == "bull":     base = round(base * 1.08)
    cons = float(extra.get("consensus") or 0)
    if   cons >= 85: base += 15
    elif cons >= 75: base += 10
    elif cons >= 65: base +=  6
    elif cons >= 55: base +=  3
    elif cons <= 30: base -= 12
    elif cons <= 40: base -=  7
    elif cons <= 50: base -=  3
    tbc = int(extra.get("triple_brain_cons") or 0)
    if   tbc == 3: base += 12
    elif tbc == 2: base +=  5
    elif tbc == 1: base -=  4
    try:
        breadth = get_market_breadth()
        if breadth:
            h = float(breadth.get("health") or 50)
            if   h >= 80: base += 10
            elif h >= 65: base +=  5
            elif h <= 25: base -= 12
            elif h <= 38: base -=  6
    except Exception:
        pass
    vol_lvl = get_volatility_regime()
    if   vol_lvl == "extreme": base = round(base * 0.80)
    elif vol_lvl == "high":    base = round(base * 0.90)
    pred = int(extra.get("predBonus") or 0)
    if   pred >=  25: base += 8
    elif pred >=  15: base += 5
    elif pred >=   5: base += 2
    elif pred <= -25: base -= 8
    elif pred <= -15: base -= 5
    elif pred <=  -5: base -= 2
    return max(10, min(97, int(base)))
