"""Güven aralığı (confidence) skorlama — v43: SMA200, fear/greed, trend gücü, neural konsensüs."""

from __future__ import annotations

from ..market import get_market_mode, get_volatility_regime
from ._breadth import get_market_breadth


def calculate_confidence_score(signal_quality: int, ai_score: int,
                                market_mode: str = "", extra: dict | None = None) -> int:
    """PHP calculateConfidenceScore (v43 elite genişleme).

    v43 yenilikleri:
    - sma200Pos: SMA200 konumu (uzun vadeli trend filtresi)
    - trendStrength: 6 trend indikatörünün kaçı bullish
    - neural_consensus: 4 ağın uyum oranı (0-1)
    - oscDepth: kaç osilatör aşırı satımda
    - fear/greed: kontraryan sinyal güçlendirici
    """
    extra = extra or {}
    base = round(signal_quality / 10 * 68)

    # AI skor katkısı
    if   ai_score >= 280: base += 30
    elif ai_score >= 220: base += 25
    elif ai_score >= 170: base += 18
    elif ai_score >= 120: base += 12
    elif ai_score >=  80: base +=  6

    # Piyasa modu çarpanı
    if not market_mode:
        market_mode = get_market_mode()
    if   market_mode == "ayi":      base = round(base * 0.72)
    elif market_mode == "temkinli": base = round(base * 0.86)
    elif market_mode == "bull":     base = round(base * 1.08)

    # Konsensüs skoru katkısı
    cons = float(extra.get("consensus") or 0)
    if   cons >= 85: base += 15
    elif cons >= 75: base += 10
    elif cons >= 65: base +=  6
    elif cons >= 55: base +=  3
    elif cons <= 30: base -= 12
    elif cons <= 40: base -=  7
    elif cons <= 50: base -=  3

    # Triple brain konsensüsü
    tbc = int(extra.get("triple_brain_cons") or 0)
    if   tbc == 3: base += 12
    elif tbc == 2: base +=  5
    elif tbc == 1: base -=  4

    # Piyasa genişliği + korku/açgözlülük endeksi
    try:
        breadth = get_market_breadth()
        if breadth:
            h  = float(breadth.get("health")     or 50)
            fg = float(breadth.get("fear_greed")  or 50)
            if   h >= 80: base += 10
            elif h >= 65: base +=  5
            elif h <= 25: base -= 12
            elif h <= 38: base -=  6
            # v43: Kontraryan booster — aşırı korku + güçlü sinyal = yüksek beklenti
            if   fg <= 15 and ai_score >= 170: base += 10
            elif fg <= 25 and ai_score >= 140: base +=  6
            # v43: Aşırı açgözlülük = piyasa riski artar
            elif fg >= 82: base -=  8
            elif fg >= 72: base -=  4
    except Exception:
        pass

    # Volatilite rejimi çarpanı
    vol_lvl = get_volatility_regime()
    if   vol_lvl == "extreme": base = round(base * 0.80)
    elif vol_lvl == "high":    base = round(base * 0.90)

    # predBonus katkısı
    pred = int(extra.get("predBonus") or 0)
    if   pred >=  25: base +=  8
    elif pred >=  15: base +=  5
    elif pred >=   5: base +=  2
    elif pred <= -25: base -=  8
    elif pred <= -15: base -=  5
    elif pred <=  -5: base -=  2

    # v43: SMA200 konumu — uzun vadeli trend filtresi
    sma200_pos = float(extra.get("sma200Pos") or 0)
    if   sma200_pos > 15: base += 10
    elif sma200_pos >  5: base +=  6
    elif sma200_pos >  0: base +=  3
    elif sma200_pos < -20: base -= 12
    elif sma200_pos < -10: base -=  7
    elif sma200_pos <   0: base -=  3

    # v43: Trend gücü sayısı (0-6 trend indikatörü bullish)
    trend_str = int(extra.get("trendStrength") or 0)
    if   trend_str >= 6: base += 14
    elif trend_str >= 5: base += 10
    elif trend_str >= 4: base +=  6
    elif trend_str >= 3: base +=  2
    elif trend_str <= 1: base -=  8
    elif trend_str == 0: base -= 14

    # v43: Neural ensemble konsensüsü (4 ağın tahmin yakınlığı, 0-1)
    neural_cons = float(extra.get("neural_consensus") or 0)
    if   neural_cons >= 0.90: base += 14
    elif neural_cons >= 0.75: base +=  8
    elif neural_cons >= 0.60: base +=  4

    # v43: Osilatör derinliği (kaç osilatör aşırı satımda)
    osc_depth = int(extra.get("oscDepth") or 0)
    if   osc_depth >= 4: base += 12
    elif osc_depth >= 3: base +=  8
    elif osc_depth >= 2: base +=  4

    return max(10, min(97, int(base)))
