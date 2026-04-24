"""index.php'deki ek fonksiyonların Python karşılıkları.

Action'ların ihtiyaç duyduğu analitik / brain / backtest fonksiyonları:
- calculate_smc, detect_harmonic_patterns
- calculate_volume_profile, calculate_vwap_bands
- detect_gap_analysis, calculate_ofi_full, calculate_adaptive_volatility
- run_monte_carlo_risk, calculate_kelly_criterion
- get_weekly_signal, mtf_confluence_score
- brain_get_stats, brain_find_similar_history
- get_backtest_stats
- find_similar_movers, find_price_only_movers
- fetch_chart2_candles
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from . import config
from .utils import load_json, save_json, parse_api_num, now_str
from .api_client import fetch_chart2
from .brain import brain_load
from .indicators import rsi as ind_rsi, macd as ind_macd, ema as ind_ema, atr as ind_atr


# ── Yardımcı: CHART2 → mum listesi ─────────────────────────────────────────
def fetch_chart2_candles(code: str, periyot: str = "G", bar: int = 220) -> list[dict]:
    raw = fetch_chart2(code, periyot=periyot, bar=bar)
    if not isinstance(raw, list):
        return []
    out = []
    for b in raw:
        if not isinstance(b, dict):
            continue
        o = parse_api_num(b.get("Open", b.get("Acilis", 0)))
        h = parse_api_num(b.get("High", b.get("Yuksek", 0)))
        l = parse_api_num(b.get("Low",  b.get("Dusuk",  0)))
        c = parse_api_num(b.get("Close", b.get("Kapanis", 0)))
        v = parse_api_num(b.get("Vol", b.get("Volume", b.get("Hacim", 0))))
        t = str(b.get("Date", b.get("Tarih", "")))
        if c <= 0 or h <= 0 or l <= 0:
            continue
        if o <= 0:
            o = c
        out.append({"Open": o, "High": max(h, o, c), "Low": min(l, o, c) if l > 0 else min(o, c),
                    "Close": c, "Vol": v, "Date": t})
    return out


# ── Cache ile dosya yardımcıları ───────────────────────────────────────────
def _read_json_cache(path: Path, ttl: int) -> Any:
    try:
        if path.exists() and (time.time() - path.stat().st_mtime) < ttl:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _write_json_cache(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ── SMC ────────────────────────────────────────────────────────────────────
def calculate_smc(chart_data: list[dict], lookback: int = 100) -> dict:
    n = len(chart_data)
    if n < 20:
        return {"orderBlocks": [], "fvg": [], "liquiditySweep": {"bullish": False, "bearish": False, "strength": 0},
                "bos": "none", "choch": False, "bias": "notr", "bosStrength": 0}

    sl = chart_data[-min(lookback, n):]
    sn = len(sl)
    last_close = float(sl[-1].get("Close", 0))

    obs = []
    for i in range(2, sn - 2):
        cur, nxt = sl[i], sl[i + 1]
        nn = sl[i + 2] if i + 2 < sn else nxt
        cO = float(cur.get("Open", cur.get("Close", 0)))
        cC = float(cur.get("Close", 0))
        cH = float(cur.get("High", cC))
        cL = float(cur.get("Low",  cC))
        nO = float(nxt.get("Open", nxt.get("Close", 0)))
        nC = float(nxt.get("Close", 0))
        nnC = float(nn.get("Close", nC))
        if cC <= 0 or nC <= 0:
            continue
        if (cH - cL) < 0.0001:
            continue
        impulse = abs(nC - nO)
        imp_pct = (impulse / nO * 100) if nO > 0 else 0
        if cC < cO and nC > nO and imp_pct >= 1.5 and nnC > nC:
            obs.append({"type": "bullish", "top": round(cO, 4), "bot": round(cL, 4),
                        "mid": round((cO + cL) / 2, 4), "idx": i,
                        "date": str(cur.get("Date", "")), "strength": round(min(100, imp_pct * 15), 1),
                        "mitigated": False})
        if cC > cO and nC < nO and imp_pct >= 1.5 and nnC < nC:
            obs.append({"type": "bearish", "top": round(cH, 4), "bot": round(cO, 4),
                        "mid": round((cH + cO) / 2, 4), "idx": i,
                        "date": str(cur.get("Date", "")), "strength": round(min(100, imp_pct * 15), 1),
                        "mitigated": False})
    for ob in obs:
        if ob["type"] == "bullish" and last_close < ob["bot"]:
            ob["mitigated"] = True
        elif ob["type"] == "bearish" and last_close > ob["top"]:
            ob["mitigated"] = True
    active_obs = [ob for ob in obs if not ob["mitigated"]][-6:]

    fvgs = []
    for i in range(sn - 2):
        b1, b3 = sl[i], sl[i + 2]
        h1 = float(b1.get("High", b1.get("Close", 0)))
        l1 = float(b1.get("Low",  b1.get("Close", 0)))
        h3 = float(b3.get("High", b3.get("Close", 0)))
        l3 = float(b3.get("Low",  b3.get("Close", 0)))
        if h1 <= 0 or l3 <= 0:
            continue
        if l3 > h1:
            gap_pct = (l3 - h1) / h1 * 100 if h1 > 0 else 0
            if gap_pct >= 0.3:
                fvgs.append({"type": "bullish", "top": round(l3, 4), "bot": round(h1, 4),
                             "mid": round((l3 + h1) / 2, 4), "idx": i, "gapPct": round(gap_pct, 2),
                             "filled": last_close < (l3 + h1) / 2})
        if h3 < l1:
            gap_pct = (l1 - h3) / l1 * 100 if l1 > 0 else 0
            if gap_pct >= 0.3:
                fvgs.append({"type": "bearish", "top": round(l1, 4), "bot": round(h3, 4),
                             "mid": round((l1 + h3) / 2, 4), "idx": i, "gapPct": round(gap_pct, 2),
                             "filled": last_close > (l1 + h3) / 2})
    recent_fvgs = fvgs[-8:]

    sweep = {"bullish": False, "bearish": False, "strength": 0}
    if sn >= 22:
        ref = sl[-21:-1]
        last_bar = sl[-1]
        ref_low  = min(float(b.get("Low", b.get("Close", 9999999))) for b in ref)
        ref_high = max(float(b.get("High", b.get("Close", 0))) for b in ref)
        last_low  = float(last_bar.get("Low", last_close))
        last_high = float(last_bar.get("High", last_close))
        if last_low < ref_low and last_close > ref_low:
            depth = (ref_low - last_low) / max(ref_low, 0.001) * 100
            sweep = {"bullish": True, "bearish": False, "strength": round(min(100, depth * 20), 1)}
        elif last_high > ref_high and last_close < ref_high:
            height = (last_high - ref_high) / max(ref_high, 0.001) * 100
            sweep = {"bullish": False, "bearish": True, "strength": round(min(100, height * 20), 1)}

    swing_highs, swing_lows, sw = [], [], 3
    for i in range(sw, sn - sw):
        h = float(sl[i].get("High", sl[i].get("Close", 0)))
        l = float(sl[i].get("Low",  sl[i].get("Close", 9999999)))
        is_h = is_l = True
        for j in range(i - sw, i + sw + 1):
            if j == i:
                continue
            if float(sl[j].get("High", sl[j].get("Close", 0))) > h:
                is_h = False
            if float(sl[j].get("Low", sl[j].get("Close", 9999999))) < l:
                is_l = False
        if is_h:
            swing_highs.append({"price": h, "idx": i})
        if is_l:
            swing_lows.append({"price": l, "idx": i})

    bos, choch, bos_strength = "none", False, 0
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        sh_last, sh_prev = swing_highs[-1], swing_highs[-2]
        sl_last, sl_prev = swing_lows[-1], swing_lows[-2]
        higher_h = sh_last["price"] > sh_prev["price"]
        higher_l = sl_last["price"] > sl_prev["price"]
        lower_h  = sh_last["price"] < sh_prev["price"]
        lower_l  = sl_last["price"] < sl_prev["price"]
        if higher_h and higher_l:
            bos = "bullish_bos" if last_close > sh_last["price"] else "bullish"
            bos_strength = round((sh_last["price"] - sh_prev["price"]) / sh_prev["price"] * 100, 2) if sh_prev["price"] > 0 else 0
        elif lower_h and lower_l:
            bos = "bearish_bos" if last_close < sl_last["price"] else "bearish"
            bos_strength = round((sl_prev["price"] - sl_last["price"]) / sl_prev["price"] * 100, 2) if sl_prev["price"] > 0 else 0
        choch = (higher_h and lower_l) or (lower_h and higher_l)

    bull = bear = 0
    for ob in active_obs:
        if ob["type"] == "bullish" and abs(last_close - ob["mid"]) / max(ob["mid"], 0.001) < 0.05:
            bull += 1
        if ob["type"] == "bearish" and abs(last_close - ob["mid"]) / max(ob["mid"], 0.001) < 0.05:
            bear += 1
    for f in recent_fvgs:
        if not f["filled"]:
            if f["type"] == "bullish" and last_close > f["bot"]:
                bull += 1
            if f["type"] == "bearish" and last_close < f["top"]:
                bear += 1
    if sweep["bullish"]: bull += 2
    if sweep["bearish"]: bear += 2
    if bos.startswith("bullish"): bull += 2
    if bos.startswith("bearish"): bear += 2
    bias = "bullish" if bull > bear else ("bearish" if bear > bull else "notr")

    return {"orderBlocks": active_obs, "fvg": recent_fvgs, "liquiditySweep": sweep,
            "bos": bos, "choch": choch, "bias": bias, "bosStrength": bos_strength,
            "swingHighs": swing_highs[-3:], "swingLows": swing_lows[-3:]}


# ── Harmonik formasyonlar ──────────────────────────────────────────────────
def detect_harmonic_patterns(chart_data: list[dict], lookback: int = 80) -> list[dict]:
    n = len(chart_data)
    if n < 15:
        return []
    sl = chart_data[-min(lookback, n):]
    highs = [float(b.get("High", b.get("Close", 0))) for b in sl]
    lows  = [float(b.get("Low",  b.get("Close", 0))) for b in sl]
    sn = len(sl)
    pivots = []
    sw2 = 2
    for i in range(sw2, sn - sw2):
        h, l = highs[i], lows[i]
        is_h = is_l = True
        for j in range(i - sw2, i + sw2 + 1):
            if j == i:
                continue
            if highs[j] > h: is_h = False
            if lows[j]  < l: is_l = False
        if is_h: pivots.append({"type": "H", "price": h, "idx": i})
        if is_l: pivots.append({"type": "L", "price": l, "idx": i})
    if len(pivots) < 5:
        return []

    def fib(a: float, b: float, r: float) -> float: return a + (b - a) * r
    def ratio(m1: float, m2: float) -> float: return abs(m2 / m1) if m1 != 0 else 0
    def within(v: float, lo: float, hi: float) -> bool: return lo <= v <= hi

    patterns = []
    recent = pivots[-10:]
    for xi in range(len(recent) - 4):
        X, A, B, C, D = recent[xi:xi + 5]
        if X["type"] == A["type"] or A["type"] == B["type"] or B["type"] == C["type"] or C["type"] == D["type"]:
            continue
        XA = abs(A["price"] - X["price"]); AB = abs(B["price"] - A["price"])
        BC = abs(C["price"] - B["price"]); CD = abs(D["price"] - C["price"])
        if XA < 0.001 or AB < 0.001 or BC < 0.001:
            continue
        AB_XA = ratio(XA, AB); BC_AB = ratio(AB, BC); CD_BC = ratio(BC, CD)
        AD_XA = abs(D["price"] - A["price"]) / XA if XA > 0 else 0
        is_bull = (X["type"] == "H")
        if within(AB_XA, 0.55, 0.68) and within(BC_AB, 0.35, 0.9) and within(CD_BC, 1.2, 1.7) and within(AD_XA, 0.72, 0.83):
            prz = fib(X["price"], A["price"], 0.786)
            patterns.append({"name": "Gartley", "type": "bullish" if is_bull else "bearish",
                             "X": X["price"], "A": A["price"], "B": B["price"], "C": C["price"], "D": D["price"],
                             "prz": round(prz, 4), "confidence": round(80 - abs(AB_XA - 0.618) * 100, 1),
                             "stopBeyond": round(X["price"] * (0.98 if is_bull else 1.02), 4)})
        elif within(AB_XA, 0.35, 0.52) and within(BC_AB, 0.35, 0.9) and within(CD_BC, 1.6, 2.7) and within(AD_XA, 0.82, 0.95):
            prz = fib(X["price"], A["price"], 0.886)
            patterns.append({"name": "Bat", "type": "bullish" if is_bull else "bearish",
                             "X": X["price"], "A": A["price"], "B": B["price"], "C": C["price"], "D": D["price"],
                             "prz": round(prz, 4), "confidence": round(78 - abs(AB_XA - 0.45) * 80, 1),
                             "stopBeyond": round(X["price"] * (0.977 if is_bull else 1.023), 4)})
        elif within(AB_XA, 0.35, 0.63) and within(BC_AB, 0.35, 0.9) and within(CD_BC, 2.5, 3.7) and within(AD_XA, 1.5, 1.74):
            prz = fib(X["price"], A["price"], 1.618)
            patterns.append({"name": "Crab", "type": "bullish" if is_bull else "bearish",
                             "X": X["price"], "A": A["price"], "B": B["price"], "C": C["price"], "D": D["price"],
                             "prz": round(prz, 4), "confidence": round(76 - abs(CD_BC - 3.14) * 15, 1),
                             "stopBeyond": round(X["price"] * (0.975 if is_bull else 1.025), 4)})
        elif within(AB_XA, 0.72, 0.83) and within(BC_AB, 0.35, 0.9) and within(CD_BC, 1.6, 2.7) and within(AD_XA, 1.2, 1.65):
            prz = fib(X["price"], A["price"], 1.272)
            patterns.append({"name": "Butterfly", "type": "bullish" if is_bull else "bearish",
                             "X": X["price"], "A": A["price"], "B": B["price"], "C": C["price"], "D": D["price"],
                             "prz": round(prz, 4), "confidence": round(74 - abs(AB_XA - 0.786) * 80, 1),
                             "stopBeyond": round(X["price"] * (0.98 if is_bull else 1.02), 4)})
        elif within(AB_XA, 0.35, 0.63) and within(BC_AB, 1.2, 1.45):
            XC = abs(C["price"] - X["price"])
            CD_XC = CD / XC if XC > 0 else 0
            if within(CD_XC, 0.72, 0.83):
                prz = fib(X["price"], C["price"], 0.786)
                patterns.append({"name": "Cypher", "type": "bullish" if is_bull else "bearish",
                                 "X": X["price"], "A": A["price"], "B": B["price"], "C": C["price"], "D": D["price"],
                                 "prz": round(prz, 4), "confidence": round(72 - abs(CD_XC - 0.786) * 80, 1),
                                 "stopBeyond": round(X["price"] * (0.975 if is_bull else 1.025), 4)})
    patterns.sort(key=lambda p: p["confidence"], reverse=True)
    return patterns[:3]


# ── Volume Profile ─────────────────────────────────────────────────────────
def calculate_volume_profile(chart_data: list[dict], bins: int = 40) -> dict:
    n = len(chart_data)
    if n < 10:
        return {"poc": 0, "vah": 0, "val": 0, "hvn": [], "lvn": [], "profile": []}
    sl = chart_data[-min(100, n):]
    H = [float(b.get("High", b.get("Close", 0))) for b in sl]
    L = [float(b.get("Low",  b.get("Close", 0))) for b in sl]
    V = [float(b.get("Vol",  b.get("Volume", b.get("Hacim", 0)))) for b in sl]
    pmax, pmin = max(H), min(L)
    rng = pmax - pmin
    if rng < 0.0001:
        return {"poc": 0, "vah": 0, "val": 0, "hvn": [], "lvn": [], "profile": []}
    bin_size = rng / bins
    profile = [0.0] * bins
    for h, l, v in zip(H, L, V):
        if h <= l or v <= 0:
            continue
        lo = max(0, int((l - pmin) / bin_size))
        hi = min(bins - 1, int((h - pmin) / bin_size))
        if hi >= lo:
            share = v / max(1, hi - lo + 1)
            for b in range(lo, hi + 1):
                profile[b] += share
    poc_idx, max_v, tot_v = 0, 0.0, sum(profile)
    for i in range(bins):
        if profile[i] > max_v:
            max_v, poc_idx = profile[i], i
    poc = round(pmin + (poc_idx + 0.5) * bin_size, 4)
    target = tot_v * 0.70
    vah_idx = val_idx = poc_idx
    cum = profile[poc_idx]
    while cum < target:
        up   = profile[vah_idx + 1] if vah_idx + 1 < bins else 0
        down = profile[val_idx - 1] if val_idx - 1 >= 0  else 0
        if up >= down and vah_idx + 1 < bins:
            vah_idx += 1; cum += profile[vah_idx]
        elif val_idx - 1 >= 0:
            val_idx -= 1; cum += profile[val_idx]
        else:
            break
    vah = round(pmin + (vah_idx + 1) * bin_size, 4)
    val = round(pmin + val_idx * bin_size, 4)
    avg_v = tot_v / max(1, bins)
    hvn, lvn = [], []
    for i in range(1, bins - 1):
        p = round(pmin + (i + 0.5) * bin_size, 4)
        if profile[i] > profile[i - 1] and profile[i] > profile[i + 1] and profile[i] > avg_v * 1.5:
            hvn.append(p)
        if profile[i] < profile[i - 1] and profile[i] < profile[i + 1] and profile[i] < avg_v * 0.5:
            lvn.append(p)
    profile_out = [{"price": round(pmin + (i + 0.5) * bin_size, 4), "vol": round(profile[i])} for i in range(bins)]
    return {"poc": poc, "vah": vah, "val": val, "hvn": hvn[:5], "lvn": lvn[:5],
            "profile": profile_out, "totVol": round(tot_v)}


# ── VWAP Bands ─────────────────────────────────────────────────────────────
def calculate_vwap_bands(chart_data: list[dict]) -> dict:
    n = len(chart_data)
    if n < 5:
        return {"vwap": 0, "upper1": 0, "upper2": 0, "lower1": 0, "lower2": 0, "position": "icinde", "dev": 0}
    sl = chart_data[-min(50, n):]
    cum_pv = cum_v = 0.0
    for b in sl:
        h = float(b.get("High", b.get("Close", 0)))
        l = float(b.get("Low",  b.get("Close", 0)))
        c = float(b.get("Close", 0))
        v = float(b.get("Vol", b.get("Volume", b.get("Hacim", 0))))
        if v <= 0 or c <= 0: continue
        tp = (h + l + c) / 3
        cum_pv += tp * v; cum_v += v
    vwap = cum_pv / cum_v if cum_v > 0 else 0
    if vwap <= 0:
        return {"vwap": 0, "upper1": 0, "upper2": 0, "lower1": 0, "lower2": 0, "position": "icinde", "dev": 0}
    var = 0.0
    for b in sl:
        h = float(b.get("High", b.get("Close", 0)))
        l = float(b.get("Low",  b.get("Close", 0)))
        c = float(b.get("Close", 0))
        v = float(b.get("Vol", b.get("Volume", b.get("Hacim", 0))))
        if v <= 0 or c <= 0: continue
        tp = (h + l + c) / 3
        var += v * (tp - vwap) ** 2
    sigma = math.sqrt(var / cum_v) if cum_v > 0 else 0
    u1, u2 = vwap + sigma, vwap + 2 * sigma
    l1, l2 = vwap - sigma, vwap - 2 * sigma
    last_c = float(sl[-1].get("Close", vwap))
    dev = round((last_c - vwap) / sigma, 2) if sigma > 0 else 0
    if   last_c >= u2: pos = "ust2"
    elif last_c >= u1: pos = "ust1"
    elif last_c <= l2: pos = "alt2"
    elif last_c <= l1: pos = "alt1"
    else: pos = "icinde"
    return {"vwap": round(vwap, 4), "upper1": round(u1, 4), "upper2": round(u2, 4),
            "lower1": round(l1, 4), "lower2": round(l2, 4), "sigma": round(sigma, 4),
            "dev": dev, "position": pos}


# ── Anchored VWAP (AVWAP) ──────────────────────────────────────────────────
def _calc_avwap_from(chart_data: list[dict], anchor_idx: int) -> dict:
    """Belirli bir bar indeksinden başlayarak AVWAP + ±1σ/±2σ bantlarını hesaplar."""
    n = len(chart_data)
    if n == 0 or anchor_idx < 0 or anchor_idx >= n:
        return {"avwap": 0, "upper1": 0, "upper2": 0, "lower1": 0, "lower2": 0,
                "sigma": 0, "position": "icinde", "dev": 0, "bars": 0}
    sl = chart_data[anchor_idx:]
    cum_pv = cum_v = 0.0
    for b in sl:
        h = float(b.get("High", b.get("Close", 0)))
        l = float(b.get("Low",  b.get("Close", 0)))
        c = float(b.get("Close", 0))
        v = float(b.get("Vol", b.get("Volume", b.get("Hacim", 0))))
        if v <= 0 or c <= 0:
            continue
        tp = (h + l + c) / 3
        cum_pv += tp * v
        cum_v += v
    if cum_v <= 0:
        return {"avwap": 0, "upper1": 0, "upper2": 0, "lower1": 0, "lower2": 0,
                "sigma": 0, "position": "icinde", "dev": 0, "bars": len(sl)}
    avwap = cum_pv / cum_v
    var = 0.0
    for b in sl:
        h = float(b.get("High", b.get("Close", 0)))
        l = float(b.get("Low",  b.get("Close", 0)))
        c = float(b.get("Close", 0))
        v = float(b.get("Vol", b.get("Volume", b.get("Hacim", 0))))
        if v <= 0 or c <= 0:
            continue
        tp = (h + l + c) / 3
        var += v * (tp - avwap) ** 2
    sigma = math.sqrt(var / cum_v) if cum_v > 0 else 0
    u1, u2 = avwap + sigma, avwap + 2 * sigma
    l1, l2 = avwap - sigma, avwap - 2 * sigma
    last_c = float(sl[-1].get("Close", avwap))
    dev = round((last_c - avwap) / sigma, 2) if sigma > 0 else 0
    if   last_c >= u2: pos = "ust2"
    elif last_c >= u1: pos = "ust1"
    elif last_c <= l2: pos = "alt2"
    elif last_c <= l1: pos = "alt1"
    else: pos = "icinde"
    return {"avwap": round(avwap, 4), "upper1": round(u1, 4), "upper2": round(u2, 4),
            "lower1": round(l1, 4), "lower2": round(l2, 4), "sigma": round(sigma, 4),
            "dev": dev, "position": pos, "bars": len(sl)}


def calculate_avwap_strategies(chart_data: list[dict], lookback: int = 120) -> dict:
    """
    Çoklu anchor noktalarından AVWAP stratejileri:
      - hh:  son `lookback` bardaki en yüksek tepe (direnç AVWAP)
      - ll:  son `lookback` bardaki en düşük dip (destek AVWAP)
      - n20 / n50 / n200: N bar önceki anchor (momentum / trend)
    Her anchor için fiyatın AVWAP'a göre konumu, sapması ve sinyal üretilir.
    """
    n = len(chart_data)
    if n < 10:
        return {"ok": False, "err": "Veri yetersiz", "anchors": {}, "signals": [], "summary": {}}

    last_close = float(chart_data[-1].get("Close", 0))
    win = chart_data[-min(lookback, n):]
    win_start = n - len(win)

    # Anchor noktaları
    hh_idx = win_start + max(range(len(win)),
                             key=lambda i: float(win[i].get("High", win[i].get("Close", 0))))
    ll_idx = win_start + min(range(len(win)),
                             key=lambda i: float(win[i].get("Low",  win[i].get("Close", 0))))

    anchors_def = {
        "hh":   ("Highest High", hh_idx, "resistance"),
        "ll":   ("Lowest Low",   ll_idx, "support"),
        "n20":  ("20 Bar Önce",  max(0, n - 20), "trend_short"),
        "n50":  ("50 Bar Önce",  max(0, n - 50), "trend_mid"),
        "n200": ("200 Bar Önce", max(0, n - 200), "trend_long"),
    }

    anchors_out: dict = {}
    signals: list[dict] = []
    bull_pts = bear_pts = 0

    for key, (label, idx, role) in anchors_def.items():
        a = _calc_avwap_from(chart_data, idx)
        a["label"] = label
        a["role"] = role
        a["anchorIdx"] = idx
        a["anchorDate"] = str(chart_data[idx].get("Date", "")) if 0 <= idx < n else ""
        anchors_out[key] = a

        if a["avwap"] <= 0 or last_close <= 0:
            continue

        diff_pct = (last_close - a["avwap"]) / a["avwap"] * 100
        a["diffPct"] = round(diff_pct, 2)
        pos = a["position"]

        # Strateji sinyalleri
        if role in ("trend_short", "trend_mid", "trend_long"):
            if last_close > a["avwap"]:
                signals.append({"anchor": key, "type": "long_bias",
                                "msg": f"Fiyat {label} AVWAP üstünde (+%{diff_pct:.2f}) → trend yukarı"})
                bull_pts += 1 if role == "trend_short" else (2 if role == "trend_mid" else 3)
            else:
                signals.append({"anchor": key, "type": "short_bias",
                                "msg": f"Fiyat {label} AVWAP altında (%{diff_pct:.2f}) → trend aşağı"})
                bear_pts += 1 if role == "trend_short" else (2 if role == "trend_mid" else 3)

        if role == "resistance":
            if pos in ("ust1", "ust2"):
                signals.append({"anchor": key, "type": "breakout",
                                "msg": f"Tepe AVWAP üstünde kırılım ({pos}) → güçlü alım"})
                bull_pts += 4
            elif pos == "icinde" and diff_pct < 1:
                signals.append({"anchor": key, "type": "rejection_risk",
                                "msg": "Tepe AVWAP'a yakın → reddedilme riski"})
                bear_pts += 1

        if role == "support":
            if pos in ("alt1", "alt2"):
                signals.append({"anchor": key, "type": "support_break",
                                "msg": f"Dip AVWAP altında ({pos}) → trend kırıldı"})
                bear_pts += 4
            elif pos == "icinde" and diff_pct > -1:
                signals.append({"anchor": key, "type": "bounce_zone",
                                "msg": "Dip AVWAP yakınında → tepki alımı bölgesi"})
                bull_pts += 1

    # Genel bias
    if bull_pts - bear_pts >= 4:   bias = "guclu_alis"
    elif bull_pts - bear_pts >= 2: bias = "alis"
    elif bear_pts - bull_pts >= 4: bias = "guclu_satis"
    elif bear_pts - bull_pts >= 2: bias = "satis"
    else:                          bias = "notr"

    summary = {
        "lastClose": round(last_close, 4),
        "bullPts": bull_pts,
        "bearPts": bear_pts,
        "bias": bias,
        "lookback": len(win),
    }
    return {"ok": True, "anchors": anchors_out, "signals": signals, "summary": summary}


# ── Gap Analysis ───────────────────────────────────────────────────────────
def detect_gap_analysis(chart_data: list[dict]) -> dict:
    n = len(chart_data)
    if n < 5:
        return {"gaps": [], "openGap": None, "gapFillProb": 0}
    sl = chart_data[-min(60, n):]
    sn = len(sl); gaps = []
    for i in range(1, sn):
        prev, curr = sl[i - 1], sl[i]
        prevH = float(prev.get("High", prev.get("Close", 0)))
        prevL = float(prev.get("Low",  prev.get("Close", 0)))
        currO = float(curr.get("Open", curr.get("Close", 0)))
        currH = float(curr.get("High", curr.get("Close", 0)))
        currL = float(curr.get("Low",  curr.get("Close", 0)))
        if prevH <= 0 or currO <= 0:
            continue
        gap_size, gap_type = 0.0, ""
        if currO > prevH:
            gap_size = (currO - prevH) / prevH * 100; gap_type = "up"
        elif currO < prevL and prevL > 0:
            gap_size = (prevL - currO) / prevL * 100; gap_type = "down"
        if gap_size < 0.3 or not gap_type:
            continue
        filled = (gap_type == "up" and currL <= prevH) or (gap_type == "down" and currH >= prevL)
        gaps.append({"idx": i, "type": gap_type, "size": round(gap_size, 2),
                     "top": round(currO, 4) if gap_type == "up" else round(prevL, 4),
                     "bot": round(prevH, 4) if gap_type == "up" else round(currO, 4),
                     "filled": filled, "date": str(curr.get("Date", ""))})
    open_gap = next((g for g in reversed(gaps) if not g["filled"]), None)
    total = len(gaps); filled_n = sum(1 for g in gaps if g["filled"])
    prob = round(filled_n / total * 100, 1) if total > 0 else 72.0
    return {"gaps": gaps[-5:], "openGap": open_gap, "gapFillProb": prob,
            "totalGaps": total, "filledGaps": filled_n}


# ── OFI tam ────────────────────────────────────────────────────────────────
def calculate_ofi_full(chart_data: list[dict], period: int = 20) -> dict:
    n = len(chart_data)
    if n < period + 2:
        return {"ofi": 0, "signal": "notr", "cumulative": 0, "trend": "notr"}
    sl = chart_data[-min(100, n):]
    ofis = []
    for b in sl:
        h = float(b.get("High", b.get("Close", 0)))
        l = float(b.get("Low",  b.get("Close", 0)))
        c = float(b.get("Close", 0))
        v = float(b.get("Vol", b.get("Volume", b.get("Hacim", 0))))
        rng = h - l
        if rng < 0.0001 or v <= 0:
            ofis.append(0); continue
        buy_ratio = (c - l) / rng
        ofis.append((buy_ratio * 2 - 1) * v)
    recent = ofis[-period:]
    ofi_sum = sum(recent)
    max_abs = max(1, max(abs(x) for x in recent))
    ofi_norm = round(ofi_sum / max_abs / period * 100, 2)
    r5 = ofis[-5:]; p5 = ofis[-10:-5] if len(ofis) >= 10 else [0] * 5
    r5s, p5s = sum(r5), sum(p5)
    trend = "artis" if r5s > p5s * 1.1 else ("dusus" if r5s < p5s * 0.9 else "yatay")
    cum = sum(ofis[-50:])
    if   ofi_norm >  20: sig = "guclu_alis"
    elif ofi_norm >   5: sig = "alis"
    elif ofi_norm < -20: sig = "guclu_satis"
    elif ofi_norm <  -5: sig = "satis"
    else: sig = "notr"
    return {"ofi": ofi_norm, "signal": sig, "cumulative": round(cum), "trend": trend}


# ── Adaptif volatilite ─────────────────────────────────────────────────────
def calculate_adaptive_volatility(chart_data: list[dict], period: int = 20) -> dict:
    n = len(chart_data)
    if n < period + 5:
        return {"realized": 0, "ewma": 0, "regime": "normal", "zScore": 0, "percentile": 50, "forecastPct": 0}
    closes = [float(b.get("Close", 0)) for b in chart_data]
    rets = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            rets.append(math.log(closes[i] / closes[i - 1]))
    if len(rets) < period:
        return {"realized": 0, "ewma": 0, "regime": "normal", "zScore": 0, "percentile": 50, "forecastPct": 0}
    r_recent = rets[-period:]
    mean = sum(r_recent) / len(r_recent)
    rv = math.sqrt(sum((r - mean) ** 2 for r in r_recent) / len(r_recent)) * math.sqrt(252) * 100
    lam = 0.94
    ewma_var = rets[0] ** 2
    for r in rets:
        ewma_var = lam * ewma_var + (1 - lam) * r * r
    ewma = math.sqrt(ewma_var) * math.sqrt(252) * 100
    am = sum(rets) / len(rets)
    long_vol = math.sqrt(sum((r - am) ** 2 for r in rets) / len(rets)) * math.sqrt(252) * 100
    long_std = long_vol * 0.3 if long_vol > 0 else 1
    z = round((rv - long_vol) / max(long_std, 0.1), 2) if long_vol > 0 else 0
    vols = []
    for i in range(period, len(rets)):
        rr = rets[i - period:i]
        mu = sum(rr) / len(rr)
        vols.append(math.sqrt(sum((r - mu) ** 2 for r in rr) / len(rr)) * math.sqrt(252) * 100)
    if vols:
        vols_sorted = sorted(vols)
        closest = min(range(len(vols_sorted)), key=lambda i: abs(vols_sorted[i] - rv))
        pct = max(0, min(100, round(closest / len(vols_sorted) * 100)))
    else:
        pct = 50
    if rv > long_vol * 2.0: regime = "ekstrem"
    elif rv > long_vol * 1.4: regime = "yuksek"
    elif rv < long_vol * 0.7: regime = "dusuk"
    else: regime = "normal"
    return {"realized": round(rv, 2), "ewma": round(ewma, 2), "longTerm": round(long_vol, 2),
            "regime": regime, "zScore": z, "percentile": pct,
            "forecastPct": round(ewma / math.sqrt(252), 2)}


# ── Monte Carlo Risk ───────────────────────────────────────────────────────
def run_monte_carlo_risk(entry: float, stop: float, h1: float, h2: float,
                         daily_vol_pct: float, days: int = 10, iters: int = 500) -> dict:
    if entry <= 0 or daily_vol_pct <= 0:
        return {"var95": 0, "var99": 0, "expectedReturn": 0, "probH1": 0, "probStop": 0, "paths": []}
    sigma = daily_vol_pct / 100
    rng = np.random.default_rng()
    finals = []
    hit_h1 = hit_stop = 0
    paths_sample = []
    for it in range(iters):
        price = entry; h1_hit = stop_hit = False
        path = [round(price, 4)]
        for _ in range(days):
            z = rng.standard_normal()
            price = price * math.exp(-0.5 * sigma * sigma + sigma * z)
            if stop > 0 and price <= stop and not h1_hit:
                stop_hit = True; price = stop; break
            if h1   > 0 and price >= h1   and not stop_hit:
                h1_hit   = True; price = h1; break
            if it < 10:
                path.append(round(price, 4))
        if it < 10:
            paths_sample.append(path)
        if h1_hit:   hit_h1 += 1
        if stop_hit: hit_stop += 1
        finals.append(price)
    arr = np.array(finals)
    rets = (arr - entry) / entry * 100
    return {"var95":  round(float(np.percentile(rets, 5)), 2),
            "var99":  round(float(np.percentile(rets, 1)), 2),
            "expectedReturn": round(float(rets.mean()), 2),
            "probH1":  round(hit_h1 / iters * 100, 1),
            "probStop": round(hit_stop / iters * 100, 1),
            "paths":   paths_sample, "iters": iters, "days": days}


# ── Kelly Criterion ────────────────────────────────────────────────────────
def calculate_kelly_criterion(win_rate: float, avg_win_pct: float, avg_loss_pct: float,
                              portfolio_value: float = 100000.0, max_risk_pct: float = 0.02) -> dict:
    if win_rate <= 0 or win_rate >= 1 or avg_win_pct <= 0 or avg_loss_pct <= 0:
        return {"fullKelly": 0, "halfKelly": 0, "positionTL": 0, "positionPct": 0,
                "riskTL": 0, "verdict": "veri_yetersiz", "bRatio": 0}
    p = max(0.01, min(0.99, win_rate)); q = 1 - p
    b = avg_win_pct / avg_loss_pct
    full = (p * b - q) / b
    half = max(0, min(0.25, full / 2))
    risk_frac = max_risk_pct / (avg_loss_pct / 100) if avg_loss_pct > 0 else 0.02
    final = min(half, risk_frac)
    pos_tl = round(portfolio_value * final)
    pos_pct = round(final * 100, 2)
    risk_tl = round(pos_tl * avg_loss_pct / 100)
    if   full <= 0:    verdict = "pozisyon_alma"
    elif half < 0.05:  verdict = "kucuk_pozisyon"
    elif half < 0.15:  verdict = "normal_pozisyon"
    else:              verdict = "buyuk_pozisyon"
    return {"fullKelly": round(full, 4), "halfKelly": round(half, 4),
            "positionTL": pos_tl, "positionPct": pos_pct, "riskTL": risk_tl,
            "verdict": verdict, "bRatio": round(b, 2)}


# ── Haftalık sinyal ────────────────────────────────────────────────────────
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


# ── Brain stats ────────────────────────────────────────────────────────────
def brain_get_stats() -> dict:
    brain = brain_load()
    total_snaps = total_outcomes = 0
    for snaps in (brain.get("snapshots") or {}).values():
        for s in snaps:
            total_snaps += 1
            if s.get("outcome5") is not None:
                total_outcomes += 1
    form_stats = []
    for name, d in (brain.get("learned_weights", {}).get("formation") or {}).items():
        if d.get("count", 0) < 2: continue
        form_stats.append({"ad": name, "count": d["count"],
                           "win_rate": d.get("win_rate", 0), "avg_ret": d.get("avg_ret", 0),
                           "weight": d.get("weight", 1.0)})
    form_stats.sort(key=lambda x: x["count"], reverse=True)
    ind_stats = []
    for key, d in (brain.get("learned_weights", {}).get("indicator") or {}).items():
        if d.get("count", 0) < 3: continue
        avg = round(d.get("total_ret", 0) / d["count"], 2) if d["count"] > 0 else 0
        ind_stats.append({"key": key, "weight": d.get("weight", 1.0),
                          "count": d["count"], "avg_ret": avg})
    ind_stats.sort(key=lambda x: x["weight"], reverse=True)
    acc = brain.get("prediction_accuracy") or {"toplam": 0, "dogru": 0, "oran": 0.0}
    conf_stats = []
    for key, d in (brain.get("confluence_patterns") or {}).items():
        if d.get("count", 0) < 6: continue
        conf_stats.append({"key": key, "win_rate": d.get("win_rate", 0),
                           "count": d["count"], "avg_ret": d.get("avg_ret", 0),
                           "weight": d.get("weight", 1.0)})
    conf_stats.sort(key=lambda x: x["count"], reverse=True)
    sm_matrix = []
    for key, d in (brain.get("sector_mode_matrix") or {}).items():
        if d.get("count", 0) < 5: continue
        sm_matrix.append({"key": key, "win_rate": d.get("win_rate", 0),
                          "count": d["count"], "avg_ret": d.get("avg_ret", 0)})
    sm_matrix.sort(key=lambda x: x["win_rate"], reverse=True)
    nn = brain.get("neural_net") or {}
    nnb = brain.get("neural_net_beta") or {}
    return {
        "takip_edilen_hisse": len(brain.get("snapshots") or {}),
        "toplam_snapshot": total_snaps,
        "degerlendirilmis": total_outcomes,
        "total_scans": brain.get("total_scans", 0),
        "son_guncelleme": brain.get("last_updated", "Henüz yok"),
        "formasyon_istatistik": form_stats[:10],
        "indikatör_istatistik": ind_stats[:15],
        "sektor_perf": brain.get("sector_perf") or {},
        "version": brain.get("version", 1),
        "pred_toplam": int(acc.get("toplam", 0) or 0),
        "pred_dogru":  int(acc.get("dogru",  0) or 0),
        "pred_oran":   float(acc.get("oran",  0.0) or 0.0),
        "confluence_stats": conf_stats[:5],
        "mode_performance": brain.get("mode_perf_detail") or {},
        "time_patterns":    brain.get("time_patterns")    or {},
        "volatility_learning": brain.get("volatility_learning") or {},
        "sector_mode_matrix":  sm_matrix[:10],
        "alpha_trained":  int(nn.get("trained_samples", 0) or 0),
        "alpha_accuracy": float(nn.get("recent_accuracy", 0.0) or 0.0),
        "alpha_avg_loss": float(nn.get("avg_loss", 1.0) or 1.0),
        "beta_trained":   int(nnb.get("trained_samples", 0) or 0),
        "beta_accuracy":  float(nnb.get("recent_accuracy", 0.0) or 0.0),
        "beta_avg_loss":  float(nnb.get("avg_loss", 1.0) or 1.0),
        "dual_stats":     brain.get("dual_brain_stats") or {},
    }


# ── Brain similar history ──────────────────────────────────────────────────
def brain_find_similar_history(code: str, stock: dict) -> dict | list:
    brain = brain_load()
    snaps = (brain.get("snapshots") or {}).get(code, [])
    if not snaps:
        return []
    rsi_v   = float(stock.get("rsi", 50))
    mode    = stock.get("marketMode", "bull")
    form_names = [f.get("ad") for f in (stock.get("formations") or [])]
    vol_r   = float(stock.get("volRatio", 1))
    trend   = stock.get("trend", "Notr")
    cmf     = float(stock.get("cmf", 0))
    cmf_dir = "pos" if cmf > 0.05 else ("neg" if cmf < -0.05 else "notr")
    sektor  = stock.get("sektor", "")
    similar = []
    for s in snaps:
        if s.get("outcome5") is None: continue
        s_rsi = float(s.get("rsi", 50))
        s_mode = s.get("marketMode", "bull")
        s_forms = s.get("formations", []) or []
        s_vol = float(s.get("volRatio", 1))
        s_trend = s.get("trend", "Notr")
        s_cmf = float(s.get("cmf", 0))
        s_cmf_dir = "pos" if s_cmf > 0.05 else ("neg" if s_cmf < -0.05 else "notr")
        s_sektor = s.get("sektor", "")
        score = 0
        diff = abs(rsi_v - s_rsi)
        if diff < 5: score += 3
        elif diff < 10: score += 2
        elif diff < 18: score += 1
        if s_mode == mode: score += 2
        common = len(set(form_names) & set(s_forms))
        score += min(6, common * 3)
        vd = abs(vol_r - s_vol)
        if vd < 0.3: score += 2
        elif vd < 0.7: score += 1
        if s_trend == trend: score += 2
        if s_cmf_dir == cmf_dir: score += 1
        if sektor and s_sektor == sektor: score += 1
        st_d = stock.get("supertrendDir", "notr")
        hu_d = stock.get("hullDir", "notr")
        smc_b = stock.get("smcBias", "notr")
        if s.get("supertrendDir", "notr") == st_d and st_d != "notr": score += 2
        if s.get("hullDir", "notr") == hu_d and hu_d != "notr": score += 2
        if s.get("smcBias", "notr") == smc_b and smc_b != "notr": score += 2
        if "ofiSig" in s and s["ofiSig"] == stock.get("ofiSig", "notr") and stock.get("ofiSig", "notr") != "notr":
            score += 1
        if "vwapPos" in s and s["vwapPos"] == stock.get("vwapPos", "icinde") and stock.get("vwapPos", "icinde") != "icinde":
            score += 1
        if score >= 5:
            similar.append({"ret": float(s["outcome5"]), "date": s.get("date", ""), "score": score})
    if not similar:
        return []
    similar.sort(key=lambda x: x["score"], reverse=True)
    top = similar[:7]
    rets = [t["ret"] for t in top]
    return {
        "count": len(top),
        "avg_ret": round(sum(rets) / len(rets), 2),
        "win_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 0),
        "samples": top,
    }


# ── Backtest stats ─────────────────────────────────────────────────────────
def get_backtest_stats() -> dict:
    if not config.SIGNAL_HISTORY_FILE.exists():
        return {"toplam_sinyal": 0}
    hist = load_json(config.SIGNAL_HISTORY_FILE, []) or []
    if not hist:
        return {"toplam_sinyal": 0}
    live_prices = {}
    cache = load_json(config.ALLSTOCKS_CACHE, {}) or {}
    for s in cache.get("stocks", []) or []:
        c = s.get("code"); p = float(s.get("guncel", 0) or 0)
        if c and p > 0: live_prices[c] = p
    temp_results = {}
    for h in hist:
        if h.get("result5") is not None: continue
        code = h.get("code", "")
        if not code or code not in live_prices: continue
        ep = float(h.get("price", 0) or 0)
        if ep <= 0: continue
        temp_results[h.get("date", "") + "|" + code] = round((live_prices[code] - ep) / ep * 100, 2)

    def empty_t(): return {"count": 0, "win": 0, "total_ret": 0.0, "max_ret": -9999, "min_ret": 9999}
    out = {
        "toplam_sinyal": len(hist), "bekleyen": 0,
        "t5": empty_t(), "t10": empty_t(), "t20": empty_t(),
        "by_formation": [], "by_mode": {}, "by_score_tier": {}, "by_sektor": [],
        "best": [], "worst": [], "equity": [], "equity_final": 100.0,
        "equity_gain": 0.0, "sharpe_approx": 0.0,
    }
    by_form, by_mode, by_tier, by_sektor = {}, {}, {}, {}
    t5list, rets5 = [], []
    for h in hist:
        code = h.get("code", "")
        date = (h.get("date") or "")[:10]
        score = int(h.get("aiScore", 0) or 0)
        mode  = h.get("marketMode", "bull")
        tier  = "160+" if score >= 160 else ("120-159" if score >= 120 else ("80-119" if score >= 80 else "<80"))
        sektor = h.get("sektor", "genel")
        live_key = (h.get("date") or "") + "|" + code
        r5 = h.get("result5")
        r5_use = r5 if r5 is not None else temp_results.get(live_key)
        if r5_use is None and h.get("result10") is None and h.get("result20") is None:
            out["bekleyen"] += 1
        for k, field in (("t10", "result10"), ("t20", "result20")):
            v = h.get(field)
            if v is None: continue
            r = float(v)
            o = out[k]; o["count"] += 1
            if r > 0: o["win"] += 1
            o["total_ret"] += r
            if r > o["max_ret"]: o["max_ret"] = r
            if r < o["min_ret"]: o["min_ret"] = r
        if r5_use is not None:
            r = float(r5_use); o = out["t5"]; o["count"] += 1
            if r > 0: o["win"] += 1
            o["total_ret"] += r
            if r > o["max_ret"]: o["max_ret"] = r
            if r < o["min_ret"]: o["min_ret"] = r
            rets5.append(r)
            for form in (h.get("formations") or []):
                if not form: continue
                d = by_form.setdefault(form, {"count": 0, "win": 0, "ret": 0.0})
                d["count"] += 1
                if r > 0: d["win"] += 1
                d["ret"] += r
            d = by_mode.setdefault(mode, {"count": 0, "win": 0, "ret": 0.0})
            d["count"] += 1
            if r > 0: d["win"] += 1
            d["ret"] += r
            d = by_tier.setdefault(tier, {"count": 0, "win": 0, "ret": 0.0})
            d["count"] += 1
            if r > 0: d["win"] += 1
            d["ret"] += r
            d = by_sektor.setdefault(sektor, {"count": 0, "win": 0, "ret": 0.0})
            d["count"] += 1
            if r > 0: d["win"] += 1
            d["ret"] += r
            t5list.append({"code": code, "date": date, "ret": r, "score": score, "mode": mode})
    for k in ("t5", "t10", "t20"):
        c = out[k]["count"]
        out[k]["win_rate"] = round(out[k]["win"] / c * 100, 1) if c > 0 else 0
        out[k]["avg_ret"]  = round(out[k]["total_ret"] / c, 2) if c > 0 else 0
        if out[k]["max_ret"] == -9999: out[k]["max_ret"] = 0
        if out[k]["min_ret"] ==  9999: out[k]["min_ret"] = 0
    if len(rets5) >= 5:
        avg5 = sum(rets5) / len(rets5)
        std = math.sqrt(sum((r - avg5) ** 2 for r in rets5) / len(rets5))
        out["sharpe_approx"] = round(avg5 / std, 2) if std > 0 else 0
    flist = []
    for name, d in by_form.items():
        c = d["count"]
        flist.append({"ad": name, "count": c,
                      "win_rate": round(d["win"] / c * 100, 1) if c > 0 else 0,
                      "avg_ret":  round(d["ret"] / c, 2)        if c > 0 else 0})
    flist.sort(key=lambda x: x["count"], reverse=True)
    out["by_formation"] = flist[:12]
    for m, d in by_mode.items():
        c = d["count"]
        out["by_mode"][m] = {"count": c,
                             "win_rate": round(d["win"] / c * 100, 1) if c > 0 else 0,
                             "avg_ret":  round(d["ret"] / c, 2)        if c > 0 else 0}
    for tier, d in by_tier.items():
        c = d["count"]
        out["by_score_tier"][tier] = {"count": c,
                                      "win_rate": round(d["win"] / c * 100, 1) if c > 0 else 0,
                                      "avg_ret":  round(d["ret"] / c, 2)        if c > 0 else 0}
    seklist = []
    for sek, d in by_sektor.items():
        c = d["count"]
        if c < 2: continue
        seklist.append({"sektor": sek, "count": c,
                        "win_rate": round(d["win"] / c * 100, 1),
                        "avg_ret":  round(d["ret"] / c, 2)})
    seklist.sort(key=lambda x: x["win_rate"], reverse=True)
    out["by_sektor"] = seklist
    if t5list:
        ranked = sorted(t5list, key=lambda x: x["ret"], reverse=True)
        out["best"]  = ranked[:5]
        out["worst"] = sorted(t5list, key=lambda x: x["ret"])[:5]
        chrono = sorted(t5list, key=lambda x: x["date"])
        eq = 100.0; curve = []
        for sig in chrono[-40:]:
            eq = round(eq * (1 + sig["ret"] / 100), 2)
            curve.append({"date": sig["date"], "val": eq, "code": sig["code"], "ret": sig["ret"]})
        out["equity"] = curve
        out["equity_final"] = eq
        out["equity_gain"] = round(eq - 100, 2)
    return out


# ── Benzer hareket motoru (teknik) ─────────────────────────────────────────
def _stock_fingerprint(s: dict) -> dict:
    forms = sorted([f.get("ad") for f in (s.get("formations") or []) if f.get("ad")])
    return {
        "ret1m": float(s.get("ret1m", 0) or 0),
        "ret3m": float(s.get("ret3m", 0) or 0),
        "retYil": float(s.get("retYil", 0) or 0),
        "rsi": float(s.get("rsi", 50) or 50),
        "aiScore": int(s.get("aiScore", 0) or 0),
        "macd": str(s.get("macdCross", "") or ""),
        "sar":  str(s.get("sarDir", "")    or ""),
        "bb":   bool(s.get("bbSqueeze")),
        "adx":  float(s.get("adxVal", 0) or 0),
        "pos52wk": float(s.get("pos52wk", 50) or 50),
        "vol":  float(s.get("volRatio", 1) or 1),
        "forms": forms,
        "sektor": str(s.get("sektor", "") or ""),
        "cap": float(s.get("marketCap", 0) or 0),
    }


def _movement_similarity(a: dict, b: dict) -> int:
    score = 0
    rd = abs(a["rsi"] - b["rsi"])
    if rd < 5: score += 20
    elif rd < 10: score += 12
    elif rd < 20: score += 5
    if a["macd"] and a["macd"] == b["macd"]: score += 15
    if a["sar"]  and a["sar"]  == b["sar"]:  score += 10
    if a["bb"] and b["bb"]: score += 8
    if a["adx"] >= 20 and b["adx"] >= 20:
        ad = abs(a["adx"] - b["adx"])
        if ad < 5: score += 10
        elif ad < 15: score += 5
    wd = abs(a["pos52wk"] - b["pos52wk"])
    if wd < 10: score += 12
    elif wd < 20: score += 6
    if a["forms"] and b["forms"]:
        common = len(set(a["forms"]) & set(b["forms"]))
        score += min(20, common * 7)
    if a["sektor"] and a["sektor"] == b["sektor"]: score += 5
    return min(100, score)


def find_similar_movers(all_stocks: list[dict]) -> dict:
    cache = config.CACHE_DIR / "predator_compare_cache.json"
    cached = _read_json_cache(cache, 900)
    if cached and cached.get("groups"):
        return cached
    leaders, candidates = {}, {}
    for s in all_stocks:
        code = s.get("code")
        if not code: continue
        fp = _stock_fingerprint(s)
        price = float(s.get("guncel", 0) or 0)
        kat = bool(s.get("katlamis"))
        if kat or fp["ret3m"] > 40 or fp["retYil"] > 80:
            leaders[code] = {"stock": s, "fp": fp, "price": price}
        elif price > 0 and price < 150 and int(s.get("aiScore", 0) or 0) >= 30 and not kat:
            candidates[code] = {"stock": s, "fp": fp, "price": price}
    groups = []
    for cc, cd in candidates.items():
        cfp = cd["fp"]; matched = []
        for lc, ld in leaders.items():
            sim = _movement_similarity(cfp, ld["fp"])
            if sim >= 30:
                matched.append({"code": lc, "sim": sim, "ret3m": ld["fp"]["ret3m"],
                                "retYil": ld["fp"]["retYil"], "price": ld["price"],
                                "sektor": ld["fp"]["sektor"], "katlamis": bool(ld["stock"].get("katlamis"))})
        if not matched: continue
        matched.sort(key=lambda x: x["sim"], reverse=True)
        top = matched[:3]
        avg = round(sum(t["sim"] for t in top) / len(top))
        if avg < 30: continue
        s = cd["stock"]
        groups.append({
            "code": cc, "name": s.get("name", cc), "price": cd["price"],
            "aiScore": int(s.get("aiScore", 0) or 0), "rsi": round(cfp["rsi"], 1),
            "ret1m": cfp["ret1m"], "ret3m": cfp["ret3m"], "retYil": cfp["retYil"],
            "cap": cfp["cap"], "sektor": cfp["sektor"], "macd": cfp["macd"],
            "sar": cfp["sar"], "pos52wk": cfp["pos52wk"], "forms": cfp["forms"][:3],
            "leaders": top, "avgSim": avg,
            "formations": (s.get("formations") or [])[:3],
            "signalTipi": s.get("signalTipi", {"tip": "NOTR", "renk": "#888", "emoji": "→"}),
            "h1": float((s.get("targets") or {}).get("sell1", s.get("h1", 0)) or 0),
            "stop": float((s.get("targets") or {}).get("stop", s.get("stop", 0)) or 0),
            "rr": float(s.get("rr1", 0) or 0),
            "signalQuality": int(s.get("signalQuality", 0) or 0),
        })
    groups.sort(key=lambda g: g["avgSim"] * 0.5 + min(100, g["aiScore"] / 3.5) * 0.3 + max(0, 40 - g["pos52wk"]) * 0.5,
                reverse=True)
    result = {"ts": int(time.time()), "leader_count": len(leaders),
              "candidate_count": len(candidates), "groups": groups[:25]}
    _write_json_cache(cache, result)
    return result


# ── Saf fiyat hareketi karşılaştırma ───────────────────────────────────────
def _price_mov_vec(s: dict) -> dict:
    def norm(v: float, cap: float) -> float:
        if cap <= 0: return 0.0
        return max(-1.0, min(1.0, v / cap))
    roc5  = float(s.get("roc5", 0) or 0); roc20 = float(s.get("roc20", 0) or 0)
    ret1m = float(s.get("ret1m", 0) or 0); ret3m = float(s.get("ret3m", 0) or 0)
    retY  = float(s.get("retYil", 0) or 0); fark = float(s.get("farkYuzde", 0) or 0)
    volR  = min(5.0, float(s.get("volRatio", 1) or 1))
    volM  = float(s.get("volMomentum", 100) or 100)
    pos52 = float(s.get("pos52wk", 50) or 50)
    atr14 = float(s.get("atr14", 0) or 0)
    g = max(0.001, float(s.get("guncel", 1) or 1))
    return {"roc5": norm(roc5, 20.0), "roc20": norm(roc20, 40.0),
            "ret1m": norm(ret1m, 60.0), "ret3m": norm(ret3m, 120.0),
            "retYil": norm(retY, 200.0), "fark": norm(fark, 8.0),
            "volR": norm(volR - 1, 4.0), "volM": norm(volM - 100, 100.0),
            "pos52": norm(pos52 - 50, 50.0), "atrRel": norm(atr14 / g * 100, 5.0)}


def _cosine_sim_pm(a: dict, b: dict) -> float:
    keys = a.keys()
    dot = magA = magB = 0.0
    for k in keys:
        av = float(a.get(k, 0)); bv = float(b.get(k, 0))
        dot += av * bv; magA += av * av; magB += bv * bv
    magA = math.sqrt(magA); magB = math.sqrt(magB)
    if magA < 1e-9 or magB < 1e-9: return 50.0
    return round((dot / (magA * magB) + 1.0) / 2.0 * 100.0, 1)


def find_price_only_movers(all_stocks: list[dict]) -> dict:
    cache = config.CACHE_DIR / "predator_price_compare_cache.json"
    cached = _read_json_cache(cache, 900)
    if cached and cached.get("groups"):
        return cached
    leaders, candidates = {}, {}
    for s in all_stocks:
        code = s.get("code")
        if not code: continue
        price = float(s.get("guncel", 0) or 0)
        ret3m = float(s.get("ret3m", 0) or 0)
        retY  = float(s.get("retYil", 0) or 0)
        kat = bool(s.get("katlamis"))
        roc5  = float(s.get("roc5", 0) or 0)
        roc20 = float(s.get("roc20", 0) or 0)
        cap = float(s.get("marketCap", 0) or 0)
        vec = _price_mov_vec(s)
        if kat or ret3m > 35 or retY > 70:
            leaders[code] = {"vec": vec, "ret3m": ret3m, "retYil": retY, "price": price,
                             "katlamis": kat, "code": code, "name": s.get("name", code),
                             "sektor": s.get("sektor", ""), "cap": cap, "roc5": roc5, "roc20": roc20}
        elif price > 0 and price < 120 and not kat and (roc5 > -5 or roc20 > 0):
            candidates[code] = {"vec": vec, "ret3m": ret3m, "retYil": retY, "price": price,
                                "code": code, "name": s.get("name", code),
                                "sektor": s.get("sektor", ""), "cap": cap,
                                "roc5": roc5, "roc20": roc20,
                                "aiScore": int(s.get("aiScore", 0) or 0),
                                "rsi": float(s.get("rsi", 50) or 50),
                                "pos52wk": float(s.get("pos52wk", 50) or 50),
                                "farkYuzde": float(s.get("farkYuzde", 0) or 0),
                                "volRatio": float(s.get("volRatio", 1) or 1),
                                "formations": (s.get("formations") or [])[:3],
                                "signalTipi": s.get("signalTipi", {"tip": "NOTR", "renk": "#888", "emoji": ""}),
                                "targets": s.get("targets", {}),
                                "rr": float(s.get("rr1", 0) or 0),
                                "signalQuality": int(s.get("signalQuality", 0) or 0)}
    groups = []
    for cc, cd in candidates.items():
        matched = []
        for lc, ld in leaders.items():
            sim = _cosine_sim_pm(cd["vec"], ld["vec"])
            if sim >= 72:
                ldr_mov = abs(ld["ret3m"]) + abs(ld["retYil"]) * 0.3
                cnd_mov = abs(cd["ret3m"]) + abs(cd["retYil"]) * 0.3
                ratio = cnd_mov / ldr_mov if ldr_mov > 0 else 1
                if ratio < 0.65:
                    matched.append({"code": lc, "sim": sim, "ret3m": ld["ret3m"], "retYil": ld["retYil"],
                                    "roc5": ld["roc5"], "roc20": ld["roc20"], "katlamis": ld["katlamis"],
                                    "price": ld["price"], "sektor": ld["sektor"], "name": ld["name"],
                                    "lagRatio": round((1 - ratio) * 100)})
        if not matched: continue
        matched.sort(key=lambda x: x["sim"], reverse=True)
        top = matched[:3]
        avg_sim = round(sum(t["sim"] for t in top) / len(top), 1)
        max_lag = max(t["lagRatio"] for t in top)
        opp = avg_sim * 0.4 + max_lag * 0.3 + min(100, cd["aiScore"] / 3.5) * 0.2 + max(0, 50 - cd["pos52wk"]) * 0.5
        groups.append({**{k: cd[k] for k in ("code", "name", "price", "aiScore", "rsi", "roc5", "roc20",
                                              "ret3m", "retYil", "farkYuzde", "volRatio", "pos52wk",
                                              "cap", "sektor", "formations", "signalTipi", "rr",
                                              "signalQuality", "targets")},
                       "leaders": top, "avgSim": avg_sim, "maxLag": max_lag,
                       "oppScore": round(opp, 1)})
    groups.sort(key=lambda g: g["oppScore"], reverse=True)
    result = {"ts": int(time.time()), "leader_count": len(leaders),
              "candidate_count": len(candidates), "groups": groups[:30],
              "method": "price_cosine"}
    _write_json_cache(cache, result)
    return result


# ── ATR (chart_data formatında) ────────────────────────────────────────────
def calculate_atr_chart(chart_data: list[dict], period: int = 14) -> float:
    if len(chart_data) < period + 1: return 0.0
    H = [b.get("High", b.get("Close", 0)) for b in chart_data]
    L = [b.get("Low",  b.get("Close", 0)) for b in chart_data]
    C = [b.get("Close", 0) for b in chart_data]
    return float(ind_atr(H, L, C, period))


# ── Haber / Gündem / Bilanço basit dış API yardımcıları ────────────────────
def fetch_news(code: str, adet: int = 5) -> dict:
    cache = config.CACHE_DIR / f"haber_{code.upper()}.json"
    cached = _read_json_cache(cache, 1800)
    if cached: return cached
    raw = _ideal_text(f"HaberFirmaBasliklar?adet=10?symbol={code.upper()}", timeout=8)
    haberler = []
    if raw:
        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        if lines:
            lines = lines[1:]  # başlık satırını atla
        for line in lines:
            p = line.split("|", 5)
            if len(p) < 5: continue
            haberler.append({
                "id": p[0].strip(), "tarih": p[1].strip(),
                "kategori": p[2].strip(), "link": p[3].strip(),
                "sembol": p[4].strip(),
                "baslik": p[5].strip() if len(p) > 5 else ""
            })
    out = {"ok": True, "code": code.upper(), "haberler": haberler[:max(3, min(30, adet))]}
    _write_json_cache(cache, out)
    return out


def fetch_gundem() -> dict:
    cache = config.CACHE_DIR / "predator_gundem.json"
    cached = _read_json_cache(cache, 3600)
    if cached: return cached
    raw = _ideal_text("Gundem", timeout=10)
    events = []
    if raw:
        try:
            from xml.etree import ElementTree as ET
            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                raw2 = raw.encode("latin1", errors="ignore").decode("iso-8859-9", errors="ignore")
                root = ET.fromstring(raw2)
            for d in root.iter("data"):
                events.append({
                    "tarih": (d.findtext("tarih") or "").strip(),
                    "saat":  (d.findtext("saat")  or "").strip(),
                    "ulke":  (d.findtext("ulke")  or "").strip(),
                    "onem":  (d.findtext("onem")  or "").strip(),
                    "veri":  (d.findtext("veri")  or "").strip(),
                    "beklenti": (d.findtext("beklenti") or "").strip(),
                    "onceki": (d.findtext("onceki") or "").strip(),
                })
        except Exception:
            pass
    out = {"ok": True, "events": events, "ts": int(time.time())}
    _write_json_cache(cache, out)
    return out


def fetch_bilanco(code: str) -> dict:
    cache = config.CACHE_DIR / f"bilanco_{code.upper()}.json"
    cached = _read_json_cache(cache, 86400)
    if cached: return cached
    raw = _ideal_text(f"BilancoDetay?symbol={code.upper()}?konsolide=0", timeout=10)
    rows = []
    if raw:
        lines = [ln for ln in raw.split("\n") if ln.strip()]
        if lines:
            header = [h.strip() for h in lines[0].split(";")]
            for ln in lines[1:]:
                cols = ln.split(";")
                rows.append({header[i]: (cols[i].strip() if i < len(cols) else "")
                             for i in range(len(header))})
    out = {"ok": True, "code": code.upper(), "rows": rows}
    _write_json_cache(cache, out)
    return out


def _ideal_text(suffix: str, timeout: int = 10) -> str:
    """idealdata API'den ham metin yanıt al (PHP'deki garip ?ayraç biçimi)."""
    import requests
    url = f"{config.API_BASE_URL}/cmd={suffix}?lang=tr"
    try:
        r = requests.get(url, headers={"Referer": config.API_REFERER, "User-Agent": "Mozilla/5.0"},
                         timeout=timeout, verify=False)
        if r.status_code == 200 and r.content:
            try:
                return r.content.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    return r.content.decode("iso-8859-9")
                except UnicodeDecodeError:
                    return r.text
    except requests.RequestException:
        pass
    return ""


# ── PREDICTIVE WARM CACHE ─────────────────────────────────────────────────
# Tarama bittikten sonra her top pick için SMC/MC/Kelly/Weekly/Gap/Harmonik
# paketini önceden hesaplayıp diske yazar; UI tıklamasında sıfır gecikme.

def compute_smc_pack(code: str, stock_entry: dict | None = None) -> dict:
    """act_smclevels ile aynı çıktı şemasını üretir; UI'dan bağımsız çağrılabilir."""
    code = (code or "").upper()
    if not code:
        return {"ok": False, "err": "Geçersiz sembol"}
    candles = fetch_chart2_candles(code, periyot="G", bar=150)
    if len(candles) < 20:
        return {"ok": False, "err": "Veri yetersiz"}
    smc_r   = calculate_smc(candles, 100)
    vp_r    = calculate_volume_profile(candles, 40)
    vwap_r  = calculate_vwap_bands(candles)
    avwap_r = calculate_avwap_strategies(candles, 120)
    gap_r   = detect_gap_analysis(candles)
    ofi_r   = calculate_ofi_full(candles, 20)
    harm_r  = detect_harmonic_patterns(candles, 80)
    av_r    = calculate_adaptive_volatility(candles, 20)
    last    = candles[-1]
    entry   = float(last.get("Close", 0))
    atr_v   = calculate_atr_chart(candles)
    daily_vol = (atr_v / entry * 100) if entry > 0 else 1.5

    if stock_entry is None:
        all_cache = load_json(config.ALLSTOCKS_CACHE, {}) or {}
        for key in ("topPicks", "stocks", "allStocks"):
            for s in (all_cache.get(key) or []):
                if (s.get("code") or "").upper() == code:
                    stock_entry = s; break
            if stock_entry: break
    stock_entry = stock_entry or {}
    tgts = stock_entry.get("targets", {}) or {}
    stop = float(tgts.get("stop",  entry * 0.95) or (entry * 0.95))
    h1   = float(tgts.get("sell1", entry * 1.08) or (entry * 1.08))
    h2   = float(tgts.get("sell2", entry * 1.15) or (entry * 1.15))

    mc_raw = run_monte_carlo_risk(entry, stop, h1, h2, daily_vol, 10, 500)
    _exp = float(mc_raw.get("expectedReturn", 0) or 0)
    _p95 = float(mc_raw.get("var95", 0) or 0)
    _ph1 = float(mc_raw.get("probH1", 0) or 0)
    _pst = float(mc_raw.get("probStop", 0) or 0)
    _std = max(0.01, abs(_exp - _p95) / 1.65) if _p95 != 0 else max(0.01, daily_vol)
    mc_r = dict(mc_raw); mc_r.update({
        "win_prob": _ph1,
        "h2_prob":  round(max(0.0, _ph1 * 0.55), 1),
        "stop_prob": _pst,
        "median_ret": _exp,
        "ev":        round(_exp, 2),
        "p95":       round(_exp + 1.65 * _std, 2),
        "p5":        _p95,
        "sharpe":    round(_exp / _std, 2) if _std > 0 else 0,
    })

    bt = get_backtest_stats(); bt10 = bt.get("t10", {}) if isinstance(bt, dict) else {}
    win   = float(bt10.get("win_rate", 55) or 55) / 100
    avg_w = abs(float(bt10.get("avg_gain", 7) or 7))
    avg_l = abs(float(bt10.get("avg_loss", -3.5) or -3.5))
    kelly = calculate_kelly_criterion(win, max(0.1, avg_w), max(0.1, avg_l),
                                      config.OTO_PORTFOLIO_VALUE, config.OTO_MAX_RISK_PCT)
    if isinstance(kelly, dict):
        kelly.setdefault("kelly_frac",   kelly.get("halfKelly", 0))
        kelly.setdefault("position_size", kelly.get("positionTL", 0))
        kelly.setdefault("max_risk_tl",  kelly.get("riskTL", 0))
        _pos = float(kelly.get("position_size") or 0)
        kelly.setdefault("lots_100", round(_pos / 100) if _pos else 0)

    weekly = get_weekly_signal(code)
    out = {
        "ok": True, "code": code, "smc": smc_r, "volProfile": vp_r,
        "vwapBands": vwap_r, "avwap": avwap_r, "gapAnalysis": gap_r, "ofi": ofi_r,
        "harmonics": harm_r, "adaptiveVol": av_r, "monteCarlo": mc_r,
        "kelly": kelly, "weeklySignal": weekly, "atr": round(atr_v, 4),
        "dailyVol": round(daily_vol, 2), "timestamp": now_str(),
    }
    cache_file = config.CACHE_DIR / f"predator_smc_{code}.json"
    _write_json_cache(cache_file, out)
    return out


def warm_smc_cache(picks: list[dict], max_workers: int = 6,
                   on_progress=None) -> dict:
    """Top pick listesindeki her hisse için tam analiz paketini önceden hesapla.

    Daemon tarama bittikten sonra çağırır → kullanıcı modal açtığında her şey hazır.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if not isinstance(picks, list) or not picks:
        return {"ok": 0, "err": 0, "total": 0}
    items = [(p.get("code") or "").upper() for p in picks if p.get("code")]
    items = [c for c in items if c]
    by_code = {(p.get("code") or "").upper(): p for p in picks if p.get("code")}
    ok = err = 0
    total = len(items)

    def _one(c: str) -> tuple[str, bool]:
        try:
            res = compute_smc_pack(c, by_code.get(c))
            ok_flag = bool(res and res.get("ok"))
            # v37.1: harmonik & tam SMC'yi pick dict'ine geri yaz → yeniden skorlamada
            # harmonic bonus + zengin SMC bonusu devreye girer.
            if ok_flag:
                pk = by_code.get(c)
                if isinstance(pk, dict):
                    if isinstance(res.get("harmonics"), list):
                        pk["harmonics"] = res["harmonics"]
                    if isinstance(res.get("smc"), dict):
                        pk["smcFull"] = res["smc"]
            return c, ok_flag
        except Exception:
            return c, False

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_one, c): c for c in items}
        done = 0
        for f in as_completed(futs):
            done += 1
            try:
                _, success = f.result()
                if success: ok += 1
                else:       err += 1
            except Exception:
                err += 1
            if on_progress:
                try: on_progress(done, total)
                except Exception: pass
    return {"ok": ok, "err": err, "total": total}
