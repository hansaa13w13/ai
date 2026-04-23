"""PHP'den birebir portlanan ek skorlama / radar / güven / kalibrasyon fonksiyonları.

Buradaki tüm fonksiyonlar ``index.php`` içindeki muadilleriyle birebir uyumludur:
- getAIPerformanceStats          → ai_performance_stats
- updateSignalOutcomes           → update_signal_outcomes
- calculateConfidenceScore       → calculate_confidence_score
- getCalibrationSuggestions      → get_calibration_suggestions
- brainGetConfluenceBonus        → brain_get_confluence_bonus
- brainGetTimeBonus              → brain_get_time_bonus
- getConfluenceKey               → get_confluence_key
- getMarketBreadth               → get_market_breadth
- getAIReasoning                 → get_ai_reasoning
- calculateConsensusScore        → calculate_consensus_score
- getRadarMembership             → get_radar_membership
- getUnifiedPositionConfidence   → get_unified_position_confidence
- getBrainBacktestFusion         → get_brain_backtest_fusion
- buildAIBreakdown               → build_ai_breakdown
- dualBrainKnowledgeTransfer     → dual_brain_knowledge_transfer
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config
from .utils import load_json, save_json, parse_api_num, now_tr
from .market import get_market_mode, get_volatility_regime
from .brain import brain_load, brain_save


# ───────────────────── 1) AI PERFORMANS İSTATİSTİKLERİ ──────────────────────
def ai_performance_stats() -> dict:
    """PHP getAIPerformanceStats birebir."""
    hist = load_json(config.SIGNAL_HISTORY_FILE, []) or []
    if not hist:
        return {}
    toplam = 0
    kazanan = 0
    total_ret = 0.0
    by_score: dict[int, dict] = {}
    by_form: dict[str, dict] = {}
    for h in hist:
        if h.get("result5") is None:
            continue
        toplam += 1
        ret5 = float(h.get("result5") or 0)
        total_ret += ret5
        if ret5 > 0:
            kazanan += 1
        score = int(h.get("aiScore") or 0)
        bucket = (score // 20) * 20
        d = by_score.setdefault(bucket, {"toplam": 0, "kazanan": 0, "ret": 0.0})
        d["toplam"] += 1
        if ret5 > 0:
            d["kazanan"] += 1
        d["ret"] += ret5
        for f in h.get("formations") or []:
            if not f:
                continue
            df = by_form.setdefault(f, {"toplam": 0, "kazanan": 0})
            df["toplam"] += 1
            if ret5 > 0:
                df["kazanan"] += 1
    if toplam == 0:
        return {"toplam_sinyal": len(hist), "degerlendirilmis": 0}
    form_list = []
    for k, v in by_form.items():
        form_list.append({
            "ad": k,
            "basari": round(v["kazanan"] / v["toplam"] * 100, 1) if v["toplam"] else 0,
            "toplam": v["toplam"],
        })
    form_list.sort(key=lambda x: x["basari"], reverse=True)
    return {
        "toplam_sinyal": len(hist),
        "degerlendirilmis": toplam,
        "kazanma_orani": round(kazanan / toplam * 100, 1),
        "ort_getiri": round(total_ret / toplam, 2),
        "by_score": dict(sorted(by_score.items(), key=lambda x: -x[0])),
        "by_formation": form_list[:5],
    }


# ───────────────────── 2) SİNYAL SONUÇLARINI GÜNCELLE ───────────────────────
def update_signal_outcomes(current_stocks: list[dict]) -> bool:
    """PHP updateSignalOutcomes birebir. result5/10/20 doldurur."""
    hist = load_json(config.SIGNAL_HISTORY_FILE, []) or []
    if not hist:
        return False
    price_map: dict[str, float] = {}
    for s in current_stocks:
        c = s.get("code") or ""
        p = float(s.get("guncel") or 0)
        if c and p > 0:
            price_map[c] = p
    changed = False
    now = time.time()
    for h in hist:
        code = h.get("code") or ""
        if not code or code not in price_map or price_map[code] <= 0:
            continue
        entry_p = float(h.get("price") or 0)
        if entry_p <= 0:
            continue
        try:
            entry_time = datetime.fromisoformat((h.get("date") or "").replace("Z", "+00:00")).timestamp()
        except Exception:
            try:
                entry_time = datetime.strptime((h.get("date") or "")[:19], "%Y-%m-%d %H:%M:%S").timestamp()
            except Exception:
                continue
        days = int((now - entry_time) / 86400)
        cur_p = price_map[code]
        ret = round((cur_p - entry_p) / entry_p * 100, 2)
        if h.get("result5") is None and days >= 5:
            h["result5"] = ret
            changed = True
        if h.get("result10") is None and days >= 10:
            h["result10"] = ret
            changed = True
        if h.get("result20") is None and days >= 20:
            h["result20"] = ret
            changed = True
    if changed:
        save_json(config.SIGNAL_HISTORY_FILE, hist)
    return changed


# ───────────────────── 3) GÜVEN ARALIĞI (CONFIDENCE) ────────────────────────
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


# ───────────────────── 4) KALİBRASYON ÖNERİLERİ ─────────────────────────────
def get_calibration_suggestions() -> list[dict]:
    """PHP getCalibrationSuggestions birebir."""
    hist = load_json(config.SIGNAL_HISTORY_FILE, []) or []
    if not hist:
        return []
    by_score: dict[str, dict] = {}
    total_eval = 0
    for h in hist:
        if h.get("result5") is None:
            continue
        total_eval += 1
        score = int(h.get("aiScore") or 0)
        bucket = (score // 20) * 20
        key = f"{bucket}-{bucket + 20}"
        d = by_score.setdefault(key, {"toplam": 0, "kazanan": 0, "bucket": bucket, "totalRet": 0.0})
        d["toplam"] += 1
        ret5 = float(h.get("result5") or 0)
        d["totalRet"] += ret5
        if ret5 > 0:
            d["kazanan"] += 1
    if total_eval < 10:
        return [{"tip": "info", "mesaj": "Yeterli sinyal geçmişi yok (en az 10 değerlendirme gerekli)", "renk": "#555"}]
    out = []
    for rng, d in by_score.items():
        if d["toplam"] < 3:
            continue
        basari = round(d["kazanan"] / d["toplam"] * 100)
        ort = round(d["totalRet"] / d["toplam"], 1)
        b = d["bucket"]
        if basari < 38 and b <= 100:
            out.append({"tip": "uyari", "mesaj": f"AI {rng} aralığı — başarı %{basari}, ort. %{ort} → Eşiği yükseltmeyi düşün", "renk": "#ff9900", "basari": basari, "aralik": rng})
        elif basari < 45 and b <= 80:
            out.append({"tip": "dikkat", "mesaj": f"AI {rng} aralığı — başarı %{basari} (düşük) → Bu sinyallere dikkatli ol", "renk": "#ffea00", "basari": basari, "aralik": rng})
        elif basari >= 68:
            out.append({"tip": "basarili", "mesaj": f"AI {rng} aralığı — başarı %{basari} ✅ Bu aralık güçlü performans gösteriyor", "renk": "#00ff9d", "basari": basari, "aralik": rng})
    return out


# ───────────────────── 5) CONFLUENCE KEY & BONUSES ──────────────────────────
def get_confluence_key(stock: dict) -> str:
    """PHP getConfluenceKey (v33 — 11 boyutlu)."""
    rsi = float(stock.get("rsi") or 50)
    rsi_b = "RSI_EXT" if rsi < 20 else ("RSI_LOW" if rsi < 30 else ("RSI_MID" if rsi < 40 else "RSI_HIGH"))
    macd = stock.get("macdCross") or "none"
    macd_b = "MACD_G" if macd == "golden" else ("MACD_D" if macd == "death" else "MACD_N")
    sar = stock.get("sarDir") or "notr"
    sar_b = "SAR_UP" if sar == "yukselis" else ("SAR_DN" if sar == "dusus" else "SAR_NO")
    vol = float(stock.get("volRatio") or 1)
    vol_b = "VOL_XX" if vol >= 3.0 else ("VOL_X" if vol >= 2.0 else ("VOL_H" if vol >= 1.5 else "VOL_N"))
    bb_b = "BB_SQ" if stock.get("bbSqueeze") else "BB_NO"
    ad = stock.get("adxDir") or "notr"
    ad_b = "ADX_UP" if ad == "yukselis" else ("ADX_DN" if ad == "dusus" else "ADX_NO")
    tr = stock.get("trend") or "Notr"
    tr_b = "TR_UP" if tr == "Yukselis" else ("TR_DN" if tr == "Dusus" else "TR_NO")
    cmf = float(stock.get("cmf") or 0)
    cmf_b = "CMF_P" if cmf > 0.10 else ("CMF_N" if cmf < -0.10 else "CMF_NO")
    st = stock.get("supertrendDir") or "notr"
    st_b = "ST_UP" if st == "yukselis" else ("ST_DN" if st == "dusus" else "ST_NO")
    hu = stock.get("hullDir") or "notr"
    hu_b = "HU_UP" if hu == "yukselis" else ("HU_DN" if hu == "dusus" else "HU_NO")
    smc = stock.get("smcBias") or "notr"
    smc_b = "SMC_B" if smc == "bullish" else ("SMC_S" if smc == "bearish" else "SMC_N")
    return "|".join([rsi_b, macd_b, sar_b, vol_b, bb_b, ad_b, tr_b, cmf_b, st_b, hu_b, smc_b])


def brain_get_confluence_bonus(stock: dict) -> int:
    """PHP brainGetConfluenceBonus birebir (v35 min 4 örnek)."""
    brain = brain_load()
    cp = brain.get("confluence_patterns") or {}
    if not cp:
        return 0
    key = get_confluence_key(stock)
    data = cp.get(key)
    if not data or int(data.get("count") or 0) < 4:
        return 0
    wr = float(data.get("win_rate") or 50)
    avg = float(data.get("avg_ret") or 0)
    w = float(data.get("weight") or 1.0)
    if   wr >= 75 and avg > 5: return min(25, round(w * 20))
    elif wr >= 65 and avg > 0: return min(18, round(w * 14))
    elif wr >= 55:             return min(10, round(w * 7))
    elif wr <= 30 and avg < 0: return max(-20, round(-w * 16))
    elif wr <= 40:             return max(-10, round(-w * 8))
    return 0


def brain_get_time_bonus() -> int:
    """PHP brainGetTimeBonus birebir."""
    brain = brain_load()
    tp = brain.get("time_patterns") or {}
    dow = now_tr().isoweekday()  # 1=Mon..7=Sun
    key = f"dow_{dow}"
    d = tp.get(key)
    if not d or int(d.get("count") or 0) < 3:
        return 0
    wr = float(d.get("win_rate") or 50)
    avg = float(d.get("avg_ret") or 0)
    if   wr >= 70 and avg > 3: return  8
    elif wr >= 60:             return  5
    elif wr <= 35 and avg < 0: return -8
    elif wr <= 45:             return -4
    return 0


# ───────────────────── 6) MARKET BREADTH (PIYASA GENİŞLİĞİ) ──────────────────
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


# ───────────────────── 7) AI REASONING (TR METİN) ───────────────────────────
def get_ai_reasoning(stock: dict, consensus: dict) -> str:
    """PHP getAIReasoning birebir."""
    rsi = float(stock.get("rsi") or 50)
    macd = stock.get("macdCross") or "none"
    sar = stock.get("sarDir") or "notr"
    vol = float(stock.get("volRatio") or 1)
    pos52 = float(stock.get("pos52wk") or 50)
    cmf = float(stock.get("cmf") or 0)
    adx_v = float(stock.get("adxVal") or 0)
    forms = stock.get("formations") or []
    adil = float(stock.get("adil") or 0)
    guncel = float(stock.get("guncel") or 0)
    cap = float(stock.get("marketCap") or 0)
    agree_bull = consensus.get("agree_bull") or 0
    sim = consensus.get("sim_history") or {}
    reasons: list[str] = []
    if rsi < 20:    reasons.append(f"RSI aşırı satım bölgesinde ({round(rsi,1)}) — güçlü toparlanma potansiyeli")
    elif rsi < 30:  reasons.append(f"RSI satım bölgesinde ({round(rsi,1)}) — dip oluşumu sinyali")
    if macd == "golden": reasons.append("MACD altın kesişimi gerçekleşti — yükseliş trendi onaylandı")
    if sar == "yukselis": reasons.append("Parabolik SAR yükseliş yönüne döndü — fiyat üstünde destek var")
    if vol >= 2.5:  reasons.append(f"Olağanüstü hacim artışı ({round(vol,1)}x) — akıllı para girişi")
    elif vol >= 1.5: reasons.append(f"Ortalamanın üzerinde hacim ({round(vol,1)}x) — alıcı ilgisi var")
    if pos52 < 10:  reasons.append(f"52 haftalık dibin yakınında ({round(pos52,1)}%) — çift dip fırsatı")
    elif pos52 < 20: reasons.append(f"52 haftalık dibe yakın ({round(pos52,1)}%) — değer alımı bölgesi")
    if cmf > 0.15:  reasons.append(f"Para akışı endeksi pozitif (CMF: +{round(cmf,2)}) — kurumsal alım")
    if adx_v >= 25: reasons.append(f"ADX {round(adx_v,1)} — trend güçlü, yön yukarı")
    bull_form_names = []
    for f in forms:
        if (f.get("tip") or "") != "bearish":
            bull_form_names.append(f"{f.get('emoji','')} {f.get('ad','')}")
    if bull_form_names:
        reasons.append("Formasyon(lar): " + ", ".join(bull_form_names[:3]))
    if adil > 0 and guncel > 0 and adil > guncel * 1.2:
        pot = round((adil - guncel) / guncel * 100, 1)
        reasons.append(f"Graham adil değeri mevcut fiyatın %{pot} üzerinde — temel potansiyel güçlü")
    if agree_bull >= 6:
        reasons.append(f"7 bağımsız sistemden {agree_bull} tanesi AL oyu verdi — güçlü uyum")
    elif agree_bull >= 5:
        reasons.append(f"7 sistemden {agree_bull} tanesi AL tarafında — iyi konsensüs")
    if isinstance(sim, dict) and (sim.get("count") or 0) >= 3:
        reasons.append(f"Benzer geçmiş durumlarda {sim.get('win_rate')}% başarı oranı, ort. %{sim.get('avg_ret')} getiri ({sim.get('count')} örnek)")
    if cap and cap < 500:
        reasons.append(f"Mikro-cap ({round(cap)}M₺) — yüksek hareket potansiyeli")
    elif cap and cap < 2000:
        reasons.append(f"Küçük-cap ({round(cap)}M₺) — kurumsal hareket öncesi fırsat")
    if (consensus.get("conf_bonus") or 0) >= 10:
        reasons.append("Bu sinyal kombinasyonu geçmişte yüksek başarı gösterdi")
    if (consensus.get("time_bonus") or 0) >= 5:
        reasons.append("Haftanın bu günü tarihsel olarak olumlu")
    if not reasons:
        reasons.append("Teknik göstergeler alım bölgesine işaret ediyor · AI skor eşiğini aştı")
    return " · ".join(reasons[:5])


# ───────────────────── 8) 8-SİSTEM KONSENSÜS SKORU ──────────────────────────
def _safe_num(v, default: float = 0.0) -> float:
    """Dict/None/str gelse bile güvenli sayı döndürür (dict ise value/k/score arar)."""
    if v is None:
        return float(default)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        for key in ("value", "val", "k", "score", "v"):
            if key in v:
                try:
                    return float(v[key])
                except (TypeError, ValueError):
                    pass
        return float(default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _safe_str(v, default: str) -> str:
    if v is None:
        return default
    if isinstance(v, dict):
        for key in ("dir", "cross", "trend", "signal", "value"):
            if key in v and isinstance(v[key], str):
                return v[key]
        return default
    return str(v) if not isinstance(v, str) else v


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
    from .extras import brain_find_similar_history
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


# ───────────────────── 9) RADAR ÜYELİĞİ ─────────────────────────────────────
_CMP_MAP_CACHE: dict | None = None
_PRC_MAP_CACHE: dict | None = None


def _load_radar_maps():
    global _CMP_MAP_CACHE, _PRC_MAP_CACHE
    if _CMP_MAP_CACHE is None:
        _CMP_MAP_CACHE = {}
        d = load_json(config.CACHE_DIR / "predator_compare_cache.json", {}) or {}
        for g in (d.get("groups") or []):
            if g.get("code"):
                _CMP_MAP_CACHE[g["code"]] = int(g.get("avgSim") or 0)
    if _PRC_MAP_CACHE is None:
        _PRC_MAP_CACHE = {}
        d = load_json(config.CACHE_DIR / "predator_price_compare_cache.json", {}) or {}
        for g in (d.get("groups") or []):
            if g.get("code"):
                _PRC_MAP_CACHE[g["code"]] = float(g.get("oppScore") or 0)


def get_radar_membership(code: str) -> dict:
    """PHP getRadarMembership birebir."""
    _load_radar_maps()
    cmp_sim = (_CMP_MAP_CACHE or {}).get(code, 0)
    prc_opp = (_PRC_MAP_CACHE or {}).get(code, 0.0)
    return {
        "inCmp":  cmp_sim >= 60,
        "cmpSim": cmp_sim,
        "inPrc":  prc_opp >= 45,
        "prcOpp": prc_opp,
    }


def reset_radar_caches() -> None:
    global _CMP_MAP_CACHE, _PRC_MAP_CACHE
    _CMP_MAP_CACHE = None
    _PRC_MAP_CACHE = None


# ───────────────────── 10) UNIFIED POSITION CONFIDENCE ───────────────────────
def get_unified_position_confidence(code: str, pos: dict, brain_data: dict, bt_stats: dict) -> dict:
    """PHP getUnifiedPositionConfidence birebir."""
    signals = []
    total = max_s = 0
    bt_wr5 = float(((bt_stats.get("t5") or {}).get("win_rate")) or 0)
    bt_cnt = int(((bt_stats.get("t5") or {}).get("count")) or 0)
    if bt_cnt >= 3:
        max_s += 30
        contrib = round(bt_wr5 / 100 * 30)
        total += contrib
        signals.append({"label": "Backtest WR(5g)", "val": f"%{bt_wr5}",
                        "color": "#00ff9d" if bt_wr5 >= 60 else ("#ffea00" if bt_wr5 >= 50 else "#ff003c")})
    acc = brain_data.get("prediction_accuracy") or {}
    pred_oran = float(acc.get("oran") or 0)
    pred_top = int(acc.get("toplam") or 0)
    if pred_top >= 5:
        max_s += 25
        contrib = round(pred_oran / 100 * 25)
        total += contrib
        signals.append({"label": "Brain Doğruluk", "val": f"%{pred_oran}",
                        "color": "#bc13fe" if pred_oran >= 60 else ("#ffea00" if pred_oran >= 50 else "#ff003c")})
    pnl = float(pos.get("pnl_pct") or 0)
    max_s += 20
    if pnl > 3:
        total += 20
        signals.append({"label": "K/Z Trend", "val": f"+{round(pnl,1)}%", "color": "#00ff9d"})
    elif pnl > 0:
        total += 12
        signals.append({"label": "K/Z Trend", "val": f"+{round(pnl,1)}%", "color": "#ffea00"})
    elif pnl > -3:
        total += 6
        signals.append({"label": "K/Z Trend", "val": f"{round(pnl,1)}%", "color": "#ff9900"})
    else:
        signals.append({"label": "K/Z Trend", "val": f"{round(pnl,1)}%", "color": "#ff003c"})
    sc_entry = int(pos.get("score") or 0)
    max_s += 15
    if sc_entry >= 200:
        total += 15
        signals.append({"label": "Giriş Skoru", "val": sc_entry, "color": "#00ff9d"})
    elif sc_entry >= 130:
        total += 10
        signals.append({"label": "Giriş Skoru", "val": sc_entry, "color": "#ffea00"})
    else:
        total += 5
        signals.append({"label": "Giriş Skoru", "val": sc_entry, "color": "#ff9900"})
    snaps = ((brain_data.get("snapshots") or {}).get(code)) or []
    eligible = [s for s in snaps if s.get("outcome5") is not None]
    wins = [s for s in eligible if float(s.get("outcome5") or 0) > 0]
    if eligible:
        snap_wr = round(len(wins) / len(eligible) * 100)
        max_s += 10
        total += round(snap_wr / 100 * 10)
        signals.append({"label": "Hisse Geçmişi", "val": f"%{snap_wr}({len(eligible)})",
                        "color": "#00ff9d" if snap_wr >= 60 else ("#ffea00" if snap_wr >= 50 else "#ff003c")})
    pct = min(100, round(total / max_s * 100)) if max_s > 0 else 0
    return {"pct": pct, "signals": signals}


# ───────────────────── 11) BRAIN × BACKTEST FUSION (PREDATOR IQ) ─────────────
def get_brain_backtest_fusion(brain_stats: dict, bt_stats: dict) -> dict:
    """PHP getBrainBacktestFusion birebir."""
    bt_wr5  = float(((bt_stats.get("t5") or {}).get("win_rate")) or 0)
    bt_avg5 = float(((bt_stats.get("t5") or {}).get("avg_ret")) or 0)
    bt_cnt5 = int(((bt_stats.get("t5") or {}).get("count")) or 0)
    pred_oran = float(brain_stats.get("pred_oran") or 0)
    pred_total = int(brain_stats.get("pred_toplam") or 0)
    iq = 0
    iq_parts = []
    if bt_cnt5 >= 3:
        bt_score = min(40, round(bt_wr5 * 0.4))
        iq += bt_score
        iq_parts.append(["Backtest", bt_score, 40, "#00f3ff"])
    if pred_total >= 5:
        brain_score = min(35, round(pred_oran * 0.35))
        iq += brain_score
        iq_parts.append(["Brain Doğruluk", brain_score, 35, "#bc13fe"])
    form_count = len(brain_stats.get("formasyon_istatistik") or [])
    form_score = min(15, form_count * 2)
    iq += form_score
    iq_parts.append(["Formasyon", form_score, 15, "#ffea00"])
    sekt_count = len(brain_stats.get("sektor_perf") or [])
    sekt_score = min(15, sekt_count)
    iq += sekt_score
    iq_parts.append(["Sektör", sekt_score, 15, "#00ff9d"])
    iq_color = "#00ff9d" if iq >= 70 else ("#ffea00" if iq >= 50 else ("#ff9900" if iq >= 30 else "#555"))
    return {
        "iq": iq, "iq_color": iq_color, "iq_parts": iq_parts,
        "bt_wr5": bt_wr5, "bt_avg5": bt_avg5, "bt_cnt5": bt_cnt5,
        "pred_oran": pred_oran, "pred_total": pred_total,
    }


# ───────────────────── 12) AI BREAKDOWN (PUAN KIRILIMI) ──────────────────────
def build_ai_breakdown(fiyat: float, adil: float, tech: dict, fin: dict,
                       formations: list[dict], market_cap_m: float,
                       ai_score: int, al_puani: int,
                       sektor: str = "", signal_quality: int = 0) -> dict:
    """PHP buildAIBreakdown birebir — radar/açıklama için puan kırılımı."""
    items: list[list] = []
    mode = get_market_mode()

    if adil > 0:
        pot = (adil - fiyat) / max(fiyat, 0.001)
        if   pot > 1.0: items.append(["✅", f"Adil değerin {round(pot*100)}% altında (çok ucuz)", "+50"])
        elif pot > 0.3: items.append(["✅", f"Adil değerin {round(pot*100)}% altında", "+30"])
        elif pot > 0.1: items.append(["✅", f"Adil değer altında (%{round(pot*100)})", "+18"])
        elif pot < -0.4: items.append(["⛔", f"Adil değerin %{round(abs(pot)*100)} üzerinde (pahalı)", "-25"])
        elif pot < -0.2: items.append(["⚠️", f"Adil değerin %{round(abs(pot)*100)} üzerinde", "-15"])

    rsi = float(tech.get("rsi") or 50)
    if   rsi < 20: items.append(["✅", f"RSI aşırı aşırı satım ({round(rsi,1)})", "+28"])
    elif rsi < 30: items.append(["✅", f"RSI aşırı satım bölgesinde ({round(rsi,1)})", "+17"])
    elif rsi < 40: items.append(["✅", f"RSI hafif aşırı satım ({round(rsi,1)})", "+10"])
    elif rsi > 85: items.append(["⛔", f"RSI aşırı alım — yüksek risk ({round(rsi,1)})", "-22"])
    elif rsi > 75: items.append(["⚠️", f"RSI aşırı alım bölgesine yakın ({round(rsi,1)})", "-14"])

    macd = tech.get("macd") or {}
    if (macd.get("cross") or "") == "golden":   items.append(["✅", "MACD Golden Cross (yükseliş teyidi)", "+22"])
    elif (macd.get("cross") or "") == "death":  items.append(["⛔", "MACD Death Cross (düşüş sinyali)", "-20"])
    elif (macd.get("hist") or 0) > 0:           items.append(["✅", "MACD histogramı pozitif", "+5"])

    div = tech.get("divergence") or {}
    if (div.get("rsi") or "") == "boga":  items.append(["⚡", "Yükseliş RSI Diverjansı (güçlü sinyal)", "+25"])
    if (div.get("macd") or "") == "boga": items.append(["⚡", "Yükseliş MACD Diverjansı", "+20"])
    if (div.get("rsi") or "") == "ayi":   items.append(["⛔", "Düşüş RSI Diverjansı (dikkat!)", "-20"])

    srsi = tech.get("stochRsi") or {"k": 50, "d": 50}
    sk = float(srsi.get("k") or 50)
    sd = float(srsi.get("d") or 50)
    if sk < 10 and sk > sd: items.append(["✅", "StochRSI dipte yükseliş kesişimi", "+20"])
    elif sk < 20:           items.append(["✅", "StochRSI aşırı satım", "+8"])
    elif sk > 90:           items.append(["⚠️", "StochRSI aşırı alım", "-11"])

    ichi = tech.get("ichimoku") or {}
    if (ichi.get("signal") or "") == "ustunde":  items.append(["✅", "Ichimoku bulutunun üzerinde", "+12"])
    elif (ichi.get("signal") or "") == "altinda": items.append(["⛔", "Ichimoku bulutunun altında", "-14"])
    if (ichi.get("tkCross") or "") == "golden":  items.append(["✅", "Ichimoku TK Golden Cross", "+10"])

    sar = tech.get("sar") or {"direction": "notr"}
    if sar.get("direction") == "yukselis": items.append(["✅", "Parabolic SAR yükseliş modunda", "+12"])
    elif sar.get("direction") == "dusus":  items.append(["⛔", "Parabolic SAR düşüş modunda", "-10"])

    bb = tech.get("bb") or {"pct": 50}
    bb_pct = float(bb.get("pct") or 50)
    if   bb_pct < 5:  items.append(["✅", "BB alt bantında (aşırı satım)", "+17"])
    elif bb_pct < 15: items.append(["✅", "BB alt bölgesinde", "+11"])
    elif bb_pct > 95: items.append(["⛔", "BB üst bantında (aşırı alım)", "-17"])
    if bb.get("squeeze"): items.append(["⚡", "Bollinger Sıkışması (kırılım bekleniyor)", "+10"])

    wr = float(tech.get("williamsR") or -50)
    if   wr <= -90: items.append(["✅", f"Williams %R aşırı satım ({round(wr)})", "+16"])
    elif wr <= -80: items.append(["✅", f"Williams %R dip bölgesinde ({round(wr)})", "+12"])
    elif wr >= -10: items.append(["⛔", f"Williams %R aşırı alım ({round(wr)})", "-14"])

    cmf_v = float(tech.get("cmf") or 0)
    if   cmf_v > 0.25:  items.append(["✅", f"CMF güçlü para girişi ({round(cmf_v,2)})", "+12"])
    elif cmf_v > 0.10:  items.append(["✅", f"CMF pozitif para akışı ({round(cmf_v,2)})", "+8"])
    elif cmf_v < -0.25: items.append(["⛔", f"CMF kurumsal çıkış sinyali ({round(cmf_v,2)})", "-12"])
    elif cmf_v < -0.10: items.append(["⚠️", f"CMF negatif para akışı ({round(cmf_v,2)})", "-7"])

    mfi_v = float(tech.get("mfi") or 50)
    if   mfi_v < 10: items.append(["✅", f"MFI aşırı satım ({round(mfi_v)})", "+17"])
    elif mfi_v < 20: items.append(["✅", f"MFI dip bölgesinde ({round(mfi_v)})", "+11"])
    elif mfi_v > 90: items.append(["⛔", f"MFI aşırı alım ({round(mfi_v)})", "-14"])
    elif mfi_v > 80: items.append(["⚠️", f"MFI alım doygunluğuna yakın ({round(mfi_v)})", "-8"])

    adx = tech.get("adx") or {}
    adx_v = float(adx.get("adx") or 0)
    adx_d = adx.get("dir") or "notr"
    if adx_d == "yukselis" and adx_v >= 40:   items.append(["✅", f"ADX çok güçlü yükseliş trendi ({round(adx_v)})", "+20"])
    elif adx_d == "yukselis" and adx_v >= 25: items.append(["✅", f"ADX güçlü yükseliş trendi ({round(adx_v)})", "+13"])
    elif adx_d == "dusus" and adx_v >= 30:    items.append(["⛔", f"ADX güçlü düşüş trendi ({round(adx_v)})", "-18"])

    st = tech.get("supertrend") or {}
    if (st.get("direction") or "") == "yukselis": items.append(["✅", f"Supertrend yükseliş modunda (destek: {round(float(st.get('value') or 0),2)})", "+12"])
    elif (st.get("direction") or "") == "dusus":  items.append(["⛔", f"Supertrend düşüş modunda (direnç: {round(float(st.get('value') or 0),2)})", "-12"])

    ema_c = tech.get("emaCross") or {}
    if (ema_c.get("cross") or "") == "golden":   items.append(["✅", "EMA 9/21 Golden Cross (yükseliş)", "+14"])
    elif (ema_c.get("cross") or "") == "death":  items.append(["⛔", "EMA 9/21 Death Cross (düşüş)", "-13"])
    elif ema_c.get("fastAboveSlow"):             items.append(["✅", "EMA 9 > EMA 21 (yükselen ivme)", "+5"])

    trix = tech.get("trix") or {}
    if (trix.get("cross") or "") == "bullish":     items.append(["⚡", "TRIX sıfır yukarı kesiyor (güçlü ivme)", "+10"])
    elif (trix.get("cross") or "") == "bearish":   items.append(["⛔", "TRIX sıfır aşağı kesiyor", "-9"])
    elif (trix.get("signal") or "") == "yukselis": items.append(["✅", "TRIX pozitif bölgede", "+4"])

    cmo = float(tech.get("cmo") or 0)
    if   cmo < -50: items.append(["✅", f"CMO aşırı satım bölgesinde ({round(cmo)})", "+10"])
    elif cmo < -30: items.append(["✅", f"CMO satım aşırılığı ({round(cmo)})", "+5"])
    elif cmo >  50: items.append(["⛔", f"CMO aşırı alım bölgesinde ({round(cmo)})", "-10"])
    elif cmo >  30: items.append(["⚠️", f"CMO alım doygunluğu ({round(cmo)})", "-5"])

    ao = tech.get("awesomeOsc") or {}
    if (ao.get("cross") or "") == "bullish":      items.append(["⚡", "Awesome Osc. sıfır üstüne geçiyor (güçlü)", "+10"])
    elif (ao.get("cross") or "") == "bearish":    items.append(["⛔", "Awesome Osc. sıfır altına iniyor", "-10"])
    elif (ao.get("signal") or "") == "yukselis":  items.append(["✅", "Awesome Oscillator pozitif", "+4"])
    elif (ao.get("signal") or "") == "dusus":     items.append(["⚠️", "Awesome Oscillator negatif", "-4"])

    hull = tech.get("hullDir") or "notr"
    if   hull == "yukselis": items.append(["✅", "Hull MA yükselen yönde", "+7"])
    elif hull == "dusus":    items.append(["⛔", "Hull MA düşen yönde", "-6"])

    elder = tech.get("elder") or {}
    if   (elder.get("signal") or "") == "guclu_boga": items.append(["✅", "Elder Ray güçlü boğa (Bull Power pozitif)", "+9"])
    elif (elder.get("signal") or "") == "guclu_ayi":  items.append(["⛔", "Elder Ray güçlü ayı (Bear Power negatif)", "-8"])

    uo = float(tech.get("ultimateOsc") or 50)
    if   uo < 30: items.append(["✅", f"Ultimate Oscillator aşırı satım ({round(uo)})", "+9"])
    elif uo < 40: items.append(["✅", f"Ultimate Oscillator dip bölgesi ({round(uo)})", "+5"])
    elif uo > 70: items.append(["⛔", f"Ultimate Oscillator aşırı alım ({round(uo)})", "-9"])

    pvt = tech.get("pvt") or "notr"
    if   pvt == "artis": items.append(["✅", "PVT yükselen hacim/fiyat trendi", "+5"])
    elif pvt == "dusus": items.append(["⚠️", "PVT düşen hacim/fiyat trendi", "-4"])

    pos52 = float(tech.get("pos52wk") or 50)
    if   pos52 < 10: items.append(["💎", f"52 hafta dibine yakın (%{round(pos52)})", "+12"])
    elif pos52 < 20: items.append(["✅", f"52 hafta alt bölgesinde (%{round(pos52)})", "+8"])
    elif pos52 > 90: items.append(["⚠️", f"52 hafta zirvesine yakın (%{round(pos52)})", "-10"])

    vol_r = float(tech.get("volRatio") or 1)
    if   vol_r > 3.0: items.append(["🔊", f"Çok yüksek hacim ({round(vol_r,1)}x ortalamanın)", "+14"])
    elif vol_r > 2.0: items.append(["🔊", f"Yüksek hacim ({round(vol_r,1)}x)", "+9"])
    elif vol_r < 0.7: items.append(["⚠️", f"Düşük hacim ({round(vol_r,1)}x) — dikkat", "-10"])

    for f in formations:
        tip = f.get("tip") or ""
        tip_tr = {
            "reversal": "dönüş formasyonu",
            "breakout": "kırılım formasyonu",
            "momentum": "momentum formasyonu",
            "bearish":  "düşüş formasyonu ⚠️",
        }.get(tip, "formasyon")
        guc = float(f.get("guc") or 60)
        if tip == "bearish":
            penalty = int((guc - 60) * 1.8 + 22)
            items.append(["🔻", f"{f.get('emoji','')} {f.get('ad','')} {tip_tr} (güç: {int(guc)})", f"-{penalty}"])
        else:
            extra = 6 if tip == "reversal" else (5 if tip == "breakout" else 3)
            bonus = int((guc - 60) * 0.9 + extra)
            items.append(["🔷", f"{f.get('emoji','')} {f.get('ad','')} {tip_tr} (güç: {int(guc)})", f"+{bonus}"])

    if market_cap_m > 0:
        if   market_cap_m < 500:    items.append(["🏷️", f"Mikro Cap — yüksek büyüme potansiyeli ({round(market_cap_m)}M₺)", "+40"])
        elif market_cap_m < 1000:   items.append(["🏷️", f"Küçük Cap ({round(market_cap_m/1000,1)}B₺)", "+32"])
        elif market_cap_m > 50000:  items.append(["⚠️", "Büyük Cap — yavaş büyüme beklentisi", "-10"])

    net_kar  = parse_api_num(fin.get("NetKar") or 0)
    fk       = parse_api_num(fin.get("FK") or 0)
    pddd     = parse_api_num(fin.get("PiyDegDefterDeg") or 0)
    roe_d    = float(fin.get("roe") or 0)
    nkm      = float(fin.get("netKarMarj") or 0)
    fkm      = float(fin.get("faalKarMarj") or 0)
    cari     = float(fin.get("cariOran") or 0)
    borc     = float(fin.get("borcOz") or 0)
    tmt      = float(fin.get("lastTemettu") or 0)
    bdl      = bool(fin.get("recentBedelsiz") or False)

    if   net_kar > 0: items.append(["✅", "Net kâr pozitif", "+20"])
    elif net_kar < 0: items.append(["⛔", "Net zarar — şirket zarar ediyor", "-20"])
    if   0 < fk < 8:  items.append(["✅", f"Düşük F/K oranı ({round(fk,1)}) — ucuz", "+15"])
    elif fk > 30:     items.append(["⚠️", f"Yüksek F/K oranı ({round(fk,1)}) — pahalı", "-10"])
    if 0 < pddd < 1.0: items.append(["✅", "PD/DD < 1 — defter değerinin altında", "+12"])

    if   roe_d > 25: items.append(["✅", f"ROE çok yüksek (%{round(roe_d,1)}) — özsermaye getirisi güçlü", "+14"])
    elif roe_d > 15: items.append(["✅", f"ROE iyi (%{round(roe_d,1)})", "+10"])
    elif roe_d < 0:  items.append(["⛔", f"ROE negatif (%{round(roe_d,1)})", "-8"])

    if   nkm > 20: items.append(["✅", f"Net kâr marjı güçlü (%{round(nkm,1)})", "+10"])
    elif nkm > 8:  items.append(["✅", f"Net kâr marjı pozitif (%{round(nkm,1)})", "+6"])
    elif nkm < 0:  items.append(["⛔", f"Net kâr marjı negatif (%{round(nkm,1)})", "-10"])

    if   fkm > 20: items.append(["✅", f"Faaliyet kâr marjı güçlü (%{round(fkm,1)})", "+8"])
    elif fkm < 0:  items.append(["⛔", f"Faaliyet zararı (%{round(fkm,1)})", "-8"])

    if   cari > 2.0: items.append(["✅", f"Cari oran sağlam ({round(cari,2)}) — likidite güçlü", "+8"])
    elif 0 < cari < 0.8: items.append(["⛔", f"Cari oran kritik düşük ({round(cari,2)})", "-10"])

    if   0 < borc < 0.3: items.append(["✅", f"Çok düşük borçluluk (B/Ö: {round(borc,2)})", "+8"])
    elif borc > 4.0:     items.append(["⛔", f"Çok yüksek borçluluk (B/Ö: {round(borc,2)})", "-14"])

    if   tmt > 5: items.append(["💰", f"Yüksek temettü verimi (%{round(tmt,1)})", "+10"])
    elif tmt > 2: items.append(["💰", f"Temettü verimi pozitif (%{round(tmt,1)})", "+5"])
    elif tmt > 0: items.append(["💰", f"Temettü var (%{round(tmt,1)})", "+2"])
    if bdl:       items.append(["🎁", "Son dönemde bedelsiz sermaye artışı", "+8"])

    # ── PHP v31 ek finansal kalemler (index.php satır 7148-7212 birebir) ──────
    brut_kar  = float(fin.get("brutKarMarj") or 0)
    roa_v     = float(fin.get("roa") or 0)
    ret3m     = float(fin.get("ret3m") or 0)
    nakit_o   = float(fin.get("nakitOran") or 0)
    likit_o   = float(fin.get("likitOran") or 0)
    kaldirac  = float(fin.get("kaldiraci") or 0)
    stok_dev  = float(fin.get("stokDevirH") or 0)
    alacak_dev= float(fin.get("alacakDevirH") or 0)
    aktif_dev = float(fin.get("aktifDevir") or 0)
    kvsa_borc = float(fin.get("kvsaBorcOran") or 0)
    net_para  = float(fin.get("netParaAkis") or 0)
    para_gir  = float(fin.get("paraGiris") or 0)
    halkak    = float(fin.get("halkakAciklik") or 0)
    son4c     = float(fin.get("sonDortCeyrek") or 0)
    taban_f   = float(fin.get("tabanFark") or 0)

    # Brüt Kar Marjı
    if   brut_kar > 50: items.append(["✅", f"Brüt kar marjı çok yüksek (%{round(brut_kar,1)})", "+4"])
    elif brut_kar > 30: items.append(["✅", f"Brüt kar marjı iyi (%{round(brut_kar,1)})", "+2"])
    elif 0 < brut_kar < 5: items.append(["⚠️", f"Brüt kar marjı çok düşük (%{round(brut_kar,1)})", "-3"])

    # ROA
    if   roa_v > 15: items.append(["✅", f"ROA çok yüksek — varlık verimliliği güçlü (%{round(roa_v,1)})", "+4"])
    elif roa_v > 8:  items.append(["✅", f"ROA iyi (%{round(roa_v,1)})", "+2"])
    elif roa_v < 0:  items.append(["⛔", f"ROA negatif — varlık verimsizliği (%{round(roa_v,1)})", "-4"])

    # 3 Aylık Gerçek Getiri
    if   ret3m > 40:  items.append(["🚀", f"3A gerçek getiri çok yüksek (+%{round(ret3m,1)})", "+15"])
    elif ret3m > 20:  items.append(["✅", f"3A gerçek getiri güçlü (+%{round(ret3m,1)})", "+8"])
    elif ret3m > 10:  items.append(["✅", f"3A getiri pozitif (+%{round(ret3m,1)})", "+4"])
    elif ret3m < -40: items.append(["⛔", f"3A getiri çok negatif (%{round(ret3m,1)})", "-18"])
    elif ret3m < -20: items.append(["⛔", f"3A getiri negatif (%{round(ret3m,1)})", "-10"])

    # Nakit Oran
    if   nakit_o > 1.0: items.append(["✅", f"Nakit oran güçlü ({round(nakit_o,2)}) — yüksek likidite", "+4"])
    elif 0 < nakit_o < 0.1: items.append(["⚠️", f"Nakit oran çok düşük ({round(nakit_o,2)})", "-3"])

    # Likit Oran
    if   likit_o > 1.5: items.append(["✅", f"Likit oran güçlü ({round(likit_o,2)})", "+3"])
    elif 0 < likit_o < 0.5: items.append(["⚠️", f"Likit oran zayıf ({round(likit_o,2)})", "-4"])

    # Kaldıraç
    if   0 < kaldirac < 0.3: items.append(["✅", f"Düşük kaldıraç ({round(kaldirac,2)}) — sağlam bilanço", "+3"])
    elif kaldirac > 0.7:     items.append(["⚠️", f"Yüksek kaldıraç ({round(kaldirac,2)})", "-4"])

    # Stok + Alacak Devir Hızı
    if stok_dev > 15:
        items.append(["✅", f"Stok devir hızı yüksek ({round(stok_dev,1)}x) — hızlı satış", "+2"])
    if alacak_dev > 15:
        items.append(["✅", f"Alacak devir hızı yüksek ({round(alacak_dev,1)}x) — hızlı tahsilat", "+3"])
    elif 0 < alacak_dev < 3:
        items.append(["⚠️", f"Alacak devir hızı düşük ({round(alacak_dev,1)}x) — tahsilat sorunu", "-3"])

    # Aktif Devir Hızı
    if aktif_dev > 2.0:
        items.append(["✅", f"Aktif devir hızı güçlü ({round(aktif_dev,2)}x) — varlık verimliliği", "+3"])

    # Kısa Vade Borç Oranı
    if kvsa_borc > 0.7:
        items.append(["⚠️", f"Kısa vade borç oranı yüksek ({round(kvsa_borc,2)}) — vade riski", "-3"])

    # Net Para Akışı
    if net_para > 0 and para_gir > 0:
        akis = net_para / max(para_gir * 2, 1)
        if   akis > 0.20: items.append(["💹", f"Güçlü net para girişi — kurumsal alım ({round(net_para/1e6,1)}M₺)", "+7"])
        elif akis > 0.08: items.append(["💹", f"Net para girişi var ({round(net_para/1e6,1)}M₺)", "+3"])
    elif net_para < 0 and para_gir > 0:
        cikis = abs(net_para) / max(para_gir * 2, 1)
        if cikis > 0.20: items.append(["📉", f"Güçlü net para çıkışı — kurumsal satım ({round(net_para/1e6,1)}M₺)", "-6"])

    # Halka Açıklık
    if   halkak > 60: items.append(["✅", f"Yüksek halka açıklık (%{round(halkak)}) — likidite güçlü", "+4"])
    elif 0 < halkak < 10: items.append(["⚠️", f"Düşük halka açıklık (%{round(halkak)}) — düşük likidite", "-4"])

    # Son 4 Çeyrek Kümülatif Kâr/Zarar
    if   son4c > 0: items.append(["✅", "Son 4 çeyrek kümülatif kâr pozitif", "+2"])
    elif son4c < 0: items.append(["⛔", "Son 4 çeyrek kümülatif zarar", "-4"])

    # Taban Fiyatına Yakınlık
    if 0 < taban_f < 3:
        items.append(["💎", f"Taban fiyatına çok yakın (%{round(taban_f,1)})", "+5"])

    if signal_quality > 0:
        items.append(["⚡", "Zamanlama & sinyal konsensüsü Al Puanına dahil", f"+{signal_quality * 5}"])

    if   mode == "temkinli": items.append(["⚠️", "Genel piyasa temkinli modda (eşik yükseltildi)", "-15%"])
    elif mode == "ayi":      items.append(["⛔", "Genel piyasa ayı modunda (çok seçici)", "-35%"])
    elif mode == "bull":     items.append(["✅", "Genel piyasa boğa modunda", "+5"])

    return {
        "items":   items,
        "aiScore": ai_score,
        "alPuani": al_puani,
        "mode":    mode,
        "toplam":  len(items),
    }


# ───────────────────── 13) DUAL/TRIPLE BRAIN KNOWLEDGE TRANSFER ──────────────
def dual_brain_knowledge_transfer(brain: dict, snap: dict, ret: float, loser: str) -> None:
    """PHP dualBrainKnowledgeTransfer — kayıp ağa ek eğitim adımları + duel istatistikleri.

    Triple Brain (alpha/beta/gamma) için PHP birebir; Python neural modülü tek-ağ olduğundan
    'gamma' ve dual-stat takibi tutulur, kayıp ağa lr_mult=2.2 ile ekstra adım atılır.
    """
    extra_steps = 3
    lr_mult = 2.2

    # Hangi ağlar kaybetti — neural train'e ek adım uygula
    try:
        from .neural import train_on_outcome
        net = brain.get("neural_net")
        if net and loser in ("alpha", "alpha_beta", "alpha_gamma", "both", "all"):
            for _ in range(extra_steps):
                train_on_outcome(net, snap, ret)
        # beta/gamma ağları PHP-spesifik; mevcut neural mimarisinde tek bir net var.
        # İleride çoklu ağ eklenirse buradan dağıtılabilir.
    except Exception:
        pass

    # Triple Brain rekabet istatistikleri
    if "dual_brain_stats" not in brain:
        brain["dual_brain_stats"] = {
            "alpha_wins": 0, "beta_wins": 0, "gamma_wins": 0,
            "ties": 0, "total_duels": 0,
            "alpha_streak": 0, "beta_streak": 0, "gamma_streak": 0,
            "current_champion": "tie", "last_duel": "", "duel_log": [],
        }
    ds = brain["dual_brain_stats"]
    ds["total_duels"] = int(ds.get("total_duels") or 0) + 1
    ds["last_duel"] = now_tr().strftime("%Y-%m-%d %H:%M:%S")
    if loser in ("beta", "beta_gamma"):
        ds["alpha_wins"] = int(ds.get("alpha_wins") or 0) + 1
        ds["alpha_streak"] = int(ds.get("alpha_streak") or 0) + 1
        ds["beta_streak"] = 0
        ds["current_champion"] = "alpha"
    elif loser in ("alpha", "alpha_gamma"):
        ds["beta_wins"] = int(ds.get("beta_wins") or 0) + 1
        ds["beta_streak"] = int(ds.get("beta_streak") or 0) + 1
        ds["alpha_streak"] = 0
        ds["current_champion"] = "beta"
    elif loser == "alpha_beta":
        ds["gamma_wins"] = int(ds.get("gamma_wins") or 0) + 1
        ds["gamma_streak"] = int(ds.get("gamma_streak") or 0) + 1
        ds["alpha_streak"] = 0
        ds["beta_streak"] = 0
        ds["current_champion"] = "gamma"
    else:
        ds["ties"] = int(ds.get("ties") or 0) + 1
        ds["alpha_streak"] = 0
        ds["beta_streak"] = 0
    code = snap.get("code") or "?"
    log = ds.get("duel_log") or []
    log.insert(0, {
        "code": code, "loser": loser,
        "ret": round(ret, 2),
        "at": now_tr().strftime("%d.%m %H:%M"),
    })
    ds["duel_log"] = log[:20]
