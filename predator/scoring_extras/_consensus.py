"""8-sistem konsensüs skorlaması (calculate_consensus_score)."""

from __future__ import annotations

from ..utils import parse_api_num
from ._safe import _safe_num, _safe_str
from ._brain_bonus import brain_get_confluence_bonus, brain_get_time_bonus
from ._breadth import get_market_breadth


def calculate_consensus_score(stock: dict, fin: dict | None = None) -> dict:
    """PHP calculateConsensusScore birebir (v32 ULTRA — 8 sistem)."""
    fin = fin or {}
    rsi    = _safe_num(stock.get("rsi"), 50)
    stoch_k= _safe_num(stock.get("stochK"), 50)
    mfi    = _safe_num(stock.get("mfi"), 50)
    will_r = _safe_num(stock.get("williamsR"), -50)
    cci    = _safe_num(stock.get("cci"), 0)
    macd   = _safe_str(stock.get("macdCross"), "none")
    sar_d  = _safe_str(stock.get("sarDir"), "notr")
    adx_v  = _safe_num(stock.get("adxVal"), 0)
    adx_d  = _safe_str(stock.get("adxDir"), "notr")
    trix   = _safe_num(stock.get("trix"), 0)
    ema_x  = _safe_str(stock.get("emaCross"), "notr")
    trend  = _safe_str(stock.get("trend"), "Notr")
    vol_r  = _safe_num(stock.get("volRatio"), 1)
    cmf    = _safe_num(stock.get("cmf"), 0)
    obv    = _safe_str(stock.get("obvTrend"), "notr")
    vol_m  = _safe_num(stock.get("volumeMomentum"), 0)
    pos52  = _safe_num(stock.get("pos52wk"), 50)
    bb_pct = _safe_num(stock.get("bbPct"), 50)
    fib    = _safe_num(stock.get("fibPos"), 50)
    piv    = _safe_str(stock.get("pivotAction"), "none")
    forms  = stock.get("formations") or []
    if not isinstance(forms, list):
        forms = []
    pred_b = int(_safe_num(stock.get("predBonus"), 0))
    sig_q  = int(_safe_num(stock.get("signalQuality"), 0))
    adil   = _safe_num(stock.get("adil"), 0)
    guncel = _safe_num(stock.get("guncel"), 1) or 1.0

    # System 1: Oscillator
    s1 = 50.0
    if   rsi < 20: s1 += 30
    elif rsi < 30: s1 += 20
    elif rsi < 40: s1 += 10
    elif rsi > 80: s1 -= 25
    elif rsi > 70: s1 -= 15
    if   stoch_k < 15 and stoch_k > 5: s1 += 15
    elif stoch_k < 25: s1 += 8
    elif stoch_k > 85: s1 -= 15
    if   mfi < 20: s1 += 12
    elif mfi < 30: s1 += 7
    elif mfi > 80: s1 -= 12
    if   will_r > -10: s1 -= 10
    elif will_r > -20: s1 -= 5
    elif will_r < -85: s1 += 12
    elif will_r < -75: s1 += 7
    if   cci < -150: s1 += 10
    elif cci < -100: s1 += 6
    elif cci > 150:  s1 -= 10
    s1 = max(0, min(100, s1))

    # System 2: Trend
    s2 = 50.0
    if   macd == "golden": s2 += 20
    elif macd == "death":  s2 -= 20
    if   sar_d == "yukselis": s2 += 15
    elif sar_d == "dusus":    s2 -= 15
    if   adx_v >= 30 and adx_d == "yukselis": s2 += 15
    elif adx_v >= 20 and adx_d == "yukselis": s2 += 8
    elif adx_v >= 25 and adx_d == "dusus":    s2 -= 12
    if   trix > 0.1:  s2 += 8
    elif trix < -0.1: s2 -= 8
    if   ema_x == "golden": s2 += 10
    elif ema_x == "death":  s2 -= 10
    if   trend == "Yukselis": s2 += 8
    elif trend == "Dusus":    s2 -= 8
    s2 = max(0, min(100, s2))

    # System 3: Volume Flow
    s3 = 50.0
    if   cmf > 0.20:  s3 += 20
    elif cmf > 0.10:  s3 += 12
    elif cmf > 0.02:  s3 += 5
    elif cmf < -0.20: s3 -= 18
    elif cmf < -0.10: s3 -= 10
    if   obv == "yukselis": s3 += 15
    elif obv == "dusus":    s3 -= 12
    if   vol_r >= 3.0: s3 += 18
    elif vol_r >= 2.0: s3 += 12
    elif vol_r >= 1.5: s3 += 7
    elif vol_r < 0.6:  s3 -= 8
    if   vol_m > 50:  s3 += 8
    elif vol_m < -30: s3 -= 8
    s3 = max(0, min(100, s3))

    # System 4: Price Structure
    s4 = 50.0
    if   pos52 < 5:   s4 += 25
    elif pos52 < 15:  s4 += 18
    elif pos52 < 25:  s4 += 10
    elif pos52 > 90:  s4 -= 15
    elif pos52 > 80:  s4 -= 8
    if   bb_pct < 5:  s4 += 18
    elif bb_pct < 15: s4 += 10
    elif bb_pct < 25: s4 += 5
    elif bb_pct > 90: s4 -= 15
    elif bb_pct > 80: s4 -= 8
    if   0 < fib <= 38: s4 += 12
    elif 0 < fib <= 62: s4 += 5
    elif fib > 85:      s4 -= 10
    if   piv == "destek": s4 += 10
    elif piv == "direnc": s4 -= 8
    s4 = max(0, min(100, s4))

    # System 5: Formation
    s5 = 50.0
    bull_forms = bear_forms = 0
    for f in forms:
        guc = float(f.get("guc") or 65)
        if (f.get("tip") or "") == "bearish":
            bear_forms += 1
            s5 -= (guc - 60) * 0.6
        else:
            bull_forms += 1
            s5 += (guc - 60) * 0.5 + 5
    if bull_forms >= 3: s5 += 10
    if bear_forms >= 2: s5 -= 15
    s5 = max(0, min(100, s5))

    # System 6: Brain AI
    s6 = 50.0
    s6 += min(30, max(-30, pred_b))
    if   sig_q >= 8: s6 += 15
    elif sig_q >= 6: s6 += 8
    elif sig_q >= 4: s6 += 3
    elif sig_q < 2:  s6 -= 10
    conf_b = brain_get_confluence_bonus(stock)
    s6 += conf_b
    time_b = brain_get_time_bonus()
    s6 += time_b
    # Similar history (lazy import to avoid circular)
    from ..extras import brain_find_similar_history
    sim_h = brain_find_similar_history(stock.get("code") or "", stock)
    if isinstance(sim_h, dict) and (sim_h.get("count") or 0) >= 3:
        sim_wr = float(sim_h.get("win_rate") or 50)
        sim_avg = float(sim_h.get("avg_ret") or 0)
        if   sim_wr >= 70 and sim_avg > 3: s6 += 15
        elif sim_wr >= 60:                  s6 += 8
        elif sim_wr <= 35:                  s6 -= 12
    s6 = max(0, min(100, s6))

    # System 7: Fundamental
    s7 = 50.0
    if adil > 0 and guncel > 0:
        pot = (adil - guncel) / guncel
        if   pot > 1.0:  s7 += 30
        elif pot > 0.5:  s7 += 22
        elif pot > 0.2:  s7 += 14
        elif pot > 0.0:  s7 += 7
        elif pot < -0.5: s7 -= 20
        elif pot < -0.2: s7 -= 12
    fk = parse_api_num(fin.get("FK") or stock.get("fk") or 0)
    pddd = parse_api_num(fin.get("PiyDegDefterDeg") or stock.get("pddd") or 0)
    roe = parse_api_num(fin.get("ROE") or stock.get("roe") or 0)
    if   0 < fk < 8:  s7 += 18
    elif 0 < fk < 12: s7 += 10
    elif fk > 30:     s7 -= 12
    if   0 < pddd < 0.5: s7 += 20
    elif 0 < pddd < 1:   s7 += 10
    elif pddd > 5:        s7 -= 12
    if   roe > 20: s7 += 12
    elif roe > 10: s7 += 6
    elif roe < 0:  s7 -= 10
    s7 = max(0, min(100, s7))

    # System 8: Market Breadth
    s8 = 50.0
    try:
        b = get_market_breadth()
        if b:
            h = float(b.get("health") or 50)
            br = float(b.get("breadth_pct") or 50)
            ad = int(b.get("adv_decline") or 0)
            mb = float(b.get("macd_breadth") or 50)
            if   h >= 70: s8 += 20
            elif h >= 60: s8 += 12
            elif h >= 50: s8 += 5
            elif h <= 30: s8 -= 20
            elif h <= 40: s8 -= 10
            if   br >= 60: s8 += 10
            elif br <= 35: s8 -= 10
            if   ad > 50:  s8 += 5
            elif ad < -50: s8 -= 5
            if   mb >= 55: s8 += 5
            elif mb <= 35: s8 -= 5
    except Exception:
        pass
    s8 = max(0, min(100, s8))

    scores = [s1, s2, s3, s4, s5, s6, s7, s8]
    agree_bull = sum(1 for s in scores if s >= 60)
    agree_bear = sum(1 for s in scores if s <= 40)
    total_w = 1.0 + 1.2 + 1.1 + 0.9 + 1.0 + 1.2 + 0.6 + 0.8
    w_avg = (s1*1.0 + s2*1.2 + s3*1.1 + s4*0.9 + s5*1.0 + s6*1.2 + s7*0.6 + s8*0.8) / total_w
    if   agree_bull >= 7: agree_bonus = 20
    elif agree_bull >= 6: agree_bonus = 15
    elif agree_bull >= 5: agree_bonus = 8
    elif agree_bull >= 4: agree_bonus = 3
    elif agree_bear >= 6: agree_bonus = -18
    elif agree_bear >= 5: agree_bonus = -12
    elif agree_bear >= 4: agree_bonus = -6
    else: agree_bonus = 0
    consensus = max(0, min(100, w_avg + agree_bonus))
    return {
        "scores": [round(s) for s in scores],
        "names": ["Osilatör","Trend","Hacim","Yapı","Formasyon","Beyin AI","Temel","Genişlik"],
        "avg": round(w_avg, 1),
        "agree_bull": agree_bull,
        "agree_bear": agree_bear,
        "consensus": round(consensus, 1),
        "ai_score_bonus": int(round((consensus - 50) * 0.8)),
        "sim_history": sim_h if isinstance(sim_h, dict) else {},
        "conf_bonus": conf_b,
        "time_bonus": time_b,
        "breadth_score": round(s8, 1),
    }
