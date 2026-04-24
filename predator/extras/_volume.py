"""Volume Profile, VWAP, AVWAP stratejileri, Gap Analysis, OFI, Adaptif volatilite."""
from __future__ import annotations

import math


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
    """Çoklu anchor noktalarından AVWAP stratejileri (hh, ll, n20, n50, n200)."""
    n = len(chart_data)
    if n < 10:
        return {"ok": False, "err": "Veri yetersiz", "anchors": {}, "signals": [], "summary": {}}

    last_close = float(chart_data[-1].get("Close", 0))
    win = chart_data[-min(lookback, n):]
    win_start = n - len(win)

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
