"""Formasyon tespiti — PHP detectChartFormations (9364) + detectCandleFormations
(9791) birebir port + hacim doğrulama (9774-9782) + top 4 / top 3 dönüş.

Her formasyon dict: {'ad': str, 'guc': int, 'renk': str, 'emoji': str, 'tip': str}
  tip ∈ {'reversal','breakout','momentum','bearish','neutral'}
"""
from __future__ import annotations
import numpy as np
from typing import Sequence


# ─────────────────────────────────────────────────────────────────────────────
# Yardımcı: chart_data → numpy diziler
# ─────────────────────────────────────────────────────────────────────────────
def _to_arrays(chart_data: Sequence[dict]) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    closes = []; highs = []; lows = []; opens = []; vols = []
    for b in chart_data:
        c = float(b.get("Close", 0) or 0)
        closes.append(c)
        highs.append(float(b.get("High",  c) or c))
        lows.append( float(b.get("Low",   c) or c))
        opens.append(float(b.get("Open",  c) or c))
        vols.append( float(b.get("Vol", b.get("Volume", b.get("Hacim", 0))) or 0))
    return (np.asarray(highs, dtype=float), np.asarray(lows, dtype=float),
            np.asarray(opens, dtype=float), np.asarray(closes, dtype=float),
            np.asarray(vols,  dtype=float))


# ─────────────────────────────────────────────────────────────────────────────
# detectChartFormations — PHP index.php:9364 birebir
# ─────────────────────────────────────────────────────────────────────────────
def detect_chart_formations(chart_data: Sequence[dict], tech: dict | None = None) -> list[dict]:
    formations: list[dict] = []
    n = len(chart_data)
    if n < 30:
        return formations
    H, L, O, C, V = _to_arrays(chart_data)
    tech = tech or {}

    curr   = float(C[-1])
    lb     = min(80, n)
    rH     = H[-lb:]; rL = L[-lb:]; rC = C[-lb:]; rV = V[-lb:]
    rn     = len(rC)

    rsi       = float(tech.get("rsi", 50) or 50)
    pos52     = float(tech.get("pos52wk", 50) or 50)
    roc20     = float(tech.get("roc20", 0) or 0)
    roc60     = float(tech.get("roc60", 0) or 0)
    v_ratio   = float(tech.get("volRatio", 1.0) or 1.0)
    macd_d    = tech.get("macd") or {}
    macd_cross = (macd_d.get("cross") if isinstance(macd_d, dict) else None) or tech.get("macdCross", "none")
    sar_d     = tech.get("sar") or {}
    sar_dir   = (sar_d.get("direction") if isinstance(sar_d, dict) else None) or tech.get("sarDir", "notr")
    ichi_d    = tech.get("ichimoku") or {}
    ichi_tk   = (ichi_d.get("tkCross") if isinstance(ichi_d, dict) else None) or tech.get("ichiTkCross", "none")
    don_d     = tech.get("donchian") or {}
    don_break = (don_d.get("breakout") if isinstance(don_d, dict) else None) or "none"
    bb_d      = tech.get("bb") or {}
    bb_squeeze = bool((bb_d.get("squeeze") if isinstance(bb_d, dict) else None) or tech.get("bbSqueeze", False))
    div_d     = tech.get("divergence") or {}
    div_rsi   = (div_d.get("rsi") if isinstance(div_d, dict) else None) or tech.get("divRsi", "yok")
    div_macd  = (div_d.get("macd") if isinstance(div_d, dict) else None) or tech.get("divMacd", "yok")
    adx_d     = tech.get("adx") or {}
    adx_dir   = (adx_d.get("dir") if isinstance(adx_d, dict) else None) or tech.get("adxDir", "notr")
    adx_val   = float((adx_d.get("adx") if isinstance(adx_d, dict) else None) or tech.get("adxVal", 0) or 0)
    cmf       = float(tech.get("cmf", 0) or 0)
    sma50     = float(tech.get("sma50", 0) or 0)
    sma200    = float(tech.get("sma200", 0) or 0)
    ema_cross_d = tech.get("emaCross") or {}
    ema_cross_v = (ema_cross_d.get("cross") if isinstance(ema_cross_d, dict) else None) or tech.get("emaCrossDir", "none")
    st_d      = tech.get("supertrend") or {}
    st_dir    = (st_d.get("direction") if isinstance(st_d, dict) else None) or tech.get("supertrendDir", "notr")

    avg_vol = float(rV[:-1].mean()) if rn > 5 else 0.0
    last_vol = float(rV[-1]) if rn else 0.0
    prev_close = float(rC[-2]) if rn >= 2 else curr

    # Pivot dipler ve tepeler (±3) — vectorized via sliding_window_view
    W = 7  # window = 2*3+1
    if rn >= W:
        win_L = np.lib.stride_tricks.sliding_window_view(rL, W)
        win_H = np.lib.stride_tricks.sliding_window_view(rH, W)
        center = 3  # index within each window
        is_dip  = (win_L[:, center] == win_L.min(axis=1)) & (rL[3:rn-3] > 0)
        is_peak = (win_H[:, center] == win_H.max(axis=1)) & (rH[3:rn-3] > 0)
        idxs = np.arange(3, rn - 3)
        dips  = [{"idx": int(i), "price": float(rL[i]), "close": float(rC[i])} for i in idxs[is_dip]]
        peaks = [{"idx": int(i), "price": float(rH[i])} for i in idxs[is_peak]]
    else:
        dips = []; peaks = []

    # ── ÇİFT DİP ──────────────────────────────────────────────────────────
    if len(dips) >= 2:
        d1 = dips[-2]; d2 = dips[-1]
        p_diff = abs(d1["price"] - d2["price"]) / max(d1["price"], 0.001)
        i_diff = d2["idx"] - d1["idx"]
        if p_diff < 0.07 and 5 <= i_diff <= 45:
            peak_b = float(rH[d1["idx"]:d2["idx"] + 1].max())
            if peak_b > d1["price"] * 1.04 and curr > min(d1["price"], d2["price"]) * 1.01 and pos52 < 75:
                formations.append({"ad":"ÇİFT DİP","guc":92,"renk":"#00ff9d","emoji":"W","tip":"reversal"})

    # ── TERS H&S ──────────────────────────────────────────────────────────
    if len(dips) >= 3:
        d1 = dips[-3]; d2 = dips[-2]; d3 = dips[-1]
        sh_avg = (d1["price"] + d3["price"]) / 2
        if (d2["price"] < d1["price"] * 0.96 and d2["price"] < d3["price"] * 0.96
                and abs(d1["price"] - d3["price"]) / sh_avg < 0.08
                and curr > sh_avg * 0.99):
            formations.append({"ad":"TERS H&S","guc":90,"renk":"#00ff9d","emoji":"⚖️","tip":"reversal"})

    # ── BULL FLAG ─────────────────────────────────────────────────────────
    if rn >= 25:
        pole = rC[-25:-15]; flag = rC[-15:-5]; flag_last = rC[-5:]
        pole_up   = (pole[-1]-pole[0])/pole[0]*100 if len(pole) and pole[0] > 0 else 0
        flag_corr = (flag[-1]-flag[0])/flag[0]*100 if len(flag) and flag[0] > 0 else 0
        last_brk  = (flag_last[-1]-flag_last[0])/flag_last[0]*100 if len(flag_last) and flag_last[0] > 0 else 0
        if pole_up > 8 and -7 < flag_corr < 1.5 and last_brk > 1:
            formations.append({"ad":"BULL FLAG","guc":85,"renk":"#00f3ff","emoji":"🚩","tip":"momentum"})

    # ── KUPA & KULP ───────────────────────────────────────────────────────
    if rn >= 50:
        cup = rC[-50:-10]; handle = rC[-10:]
        if len(cup) and len(handle):
            cl = float(cup[0]); cr = float(cup[-1]); cb = float(cup.min())
            hb = float(handle.min()); hr = float(handle[-1])
            cup_d = (cl - cb) / max(cl, 0.001) * 100
            han_d = (cr - hb) / max(cr, 0.001) * 100
            if (10 < cup_d < 45 and 2 < han_d < 15 and hr > hb * 1.01
                    and abs(cl - cr) / max(cl, 0.001) < 0.06):
                formations.append({"ad":"KUPA&KULP","guc":88,"renk":"#ffea00","emoji":"☕","tip":"reversal"})

    # ── SIKIŞMA KIRILIMI (BB squeeze + SAR up + ROC5>1.5%) ─────────────────
    if bb_squeeze and sar_dir == "yukselis":
        roc5_ = (curr - float(rC[-5])) / max(float(rC[-5]), 0.001) * 100 if rn >= 5 else 0
        if roc5_ > 1.5:
            formations.append({"ad":"SIKIŞMA KIRIL.","guc":87,"renk":"#bc13fe","emoji":"⚡","tip":"breakout"})

    # ── DONCHIAN KIRILIM ──────────────────────────────────────────────────
    if don_break == "yukari":
        vol_boost = avg_vol > 0 and last_vol > avg_vol * 1.5
        formations.append({"ad":"KIRILIM" + ("+VOL" if vol_boost else ""),
                           "guc":88 if vol_boost else 76,
                           "renk":"#00f3ff","emoji":"🔥","tip":"breakout"})

    # ── 52H DİP ───────────────────────────────────────────────────────────
    if pos52 < 18 and rsi < 35 and roc20 > -3:
        formations.append({"ad":"52H DİP","guc":78,"renk":"#00ff9d","emoji":"📍","tip":"reversal"})

    # ── GOLDEN COMBO (MACD golden + RSI<48) ───────────────────────────────
    if macd_cross == "golden" and rsi < 48:
        formations.append({"ad":"GOLDEN COMBO","guc":86,"renk":"#ffea00","emoji":"✨","tip":"momentum"})

    # ── RSI DİVERJANS (boğa) ──────────────────────────────────────────────
    if div_rsi == "boga" and pos52 < 45:
        formations.append({"ad":"RSI DİVERJANS","guc":84,"renk":"#00ff9d","emoji":"📈","tip":"reversal"})

    # ── HACİM PATLAMA ─────────────────────────────────────────────────────
    if avg_vol > 0 and last_vol > avg_vol * 2.8 and curr > prev_close * 1.015:
        formations.append({"ad":"HACİM PATL.","guc":82,"renk":"#ff9900","emoji":"💥","tip":"momentum"})

    # ── İCHİ + SAR ────────────────────────────────────────────────────────
    if ichi_tk == "golden" and sar_dir == "yukselis" and rsi < 55:
        formations.append({"ad":"İCHİ+SAR","guc":83,"renk":"#00f3ff","emoji":"🌸","tip":"momentum"})

    # ── ADX GÜÇLÜ ─────────────────────────────────────────────────────────
    if adx_dir == "yukselis" and adx_val >= 30 and cmf > 0.1:
        formations.append({"ad":"ADX GÜÇLÜ","guc":80,"renk":"#00f3ff","emoji":"💪","tip":"momentum"})

    # ── ÜÇGEN KIRILIM (basic) ─────────────────────────────────────────────
    if rn >= 20:
        rh20 = rH[-20:]; rl20 = rL[-20:]
        h_first, h_last = float(rh20[0]), float(rh20[-1])
        l_first, l_last = float(rl20[0]), float(rl20[-1])
        if h_first > 0 and l_first > 0 and h_last < h_first * 0.97 and l_last > l_first * 1.03:
            if curr > h_last * 1.02:
                formations.append({"ad":"ÜÇGEN KIRIL.","guc":82,"renk":"#00ff9d","emoji":"△","tip":"breakout"})

    # ── ÇANAK DİP (Rounding Bottom) ───────────────────────────────────────
    if rn >= 50:
        cup50 = rC[-50:]
        left_rim  = float((cup50[0] + cup50[1] + cup50[2]) / 3)
        right_rim = float((cup50[47] + cup50[48] + cup50[49]) / 3)
        mid_slice = cup50[15:25]
        mid_bot = float(mid_slice.min()) if len(mid_slice) else 0
        if left_rim > 0 and mid_bot > 0:
            cup_depth = (left_rim - mid_bot) / left_rim * 100
            rim_sym = abs(left_rim - right_rim) / left_rim * 100
            if 8 < cup_depth < 40 and rim_sym < 10 and right_rim * 0.98 <= curr <= right_rim * 1.08:
                formations.append({"ad":"ÇANAK DİP","guc":86,"renk":"#00ff9d","emoji":"🥣","tip":"reversal"})

    # ── DÜŞEN KAMA (Falling Wedge) ────────────────────────────────────────
    if rn >= 30:
        n30 = min(35, rn)
        wH = rH[-n30:]; wL = rL[-n30:]
        h_first = (wH[0] + wH[1]) / 2;  h_last = (wH[-1] + wH[-2]) / 2
        l_first = (wL[0] + wL[1]) / 2;  l_last = (wL[-1] + wL[-2]) / 2
        if h_first > 0 and l_first > 0:
            h_decl = (h_first - h_last) / h_first * 100
            l_decl = (l_first - l_last) / l_first * 100
            converging = h_decl > l_decl + 1.5
            if h_decl > 5 and l_decl > 0 and converging:
                recent_h5 = float(wH[-5:].max())
                if curr > recent_h5 * 1.005 and v_ratio >= 1.15:
                    formations.append({"ad":"DÜŞEN KAMA","guc":87,"renk":"#00ff9d","emoji":"📐","tip":"breakout"})

    # ── ÇİFT TEPE (Double Top) ────────────────────────────────────────────
    if len(peaks) >= 2:
        p1 = peaks[-2]; p2 = peaks[-1]
        p_diff = abs(p1["price"] - p2["price"]) / max(p1["price"], 0.001)
        i_diff = p2["idx"] - p1["idx"]
        if p_diff < 0.05 and 5 <= i_diff <= 50:
            neck_bot = float(rL[p1["idx"]:p2["idx"] + 1].min())
            if neck_bot < float("inf") and neck_bot * 0.90 < curr < neck_bot * 1.01:
                formations.append({"ad":"ÇİFT TEPE","guc":85,"renk":"#ff003c","emoji":"M","tip":"bearish"})

    # ── BAŞ & OMUZ (H&S) — bearish ────────────────────────────────────────
    if len(peaks) >= 3:
        p1 = peaks[-3]; p2 = peaks[-2]; p3 = peaks[-1]
        sh_avg = (p1["price"] + p3["price"]) / 2
        if (p2["price"] > p1["price"] * 1.03 and p2["price"] > p3["price"] * 1.03
                and abs(p1["price"] - p3["price"]) / sh_avg < 0.08
                and curr < sh_avg * 1.01):
            formations.append({"ad":"BAŞ&OMUZ","guc":88,"renk":"#ff003c","emoji":"⚠️","tip":"bearish"})

    # ── YÜKSELEN ÜÇGEN (Asc. Triangle) ────────────────────────────────────
    if rn >= 25:
        rH25 = rH[-25:]; rL25 = rL[-25:]
        hVals = rH25[-10:]; max_h = float(hVals.max()); min_h = float(hVals.min())
        l_first3 = (float(rL25[0]) + float(rL25[1]) + float(rL25[2])) / 3
        l_last3  = (float(rL25[22]) + float(rL25[23]) + float(rL25[24])) / 3
        horiz_res = (max_h - min_h) / max(max_h, 0.001) < 0.04
        rising_floor = l_last3 > l_first3 * 1.03
        if horiz_res and rising_floor and curr >= max_h * 0.99:
            formations.append({"ad":"YÜKS. ÜÇGEN","guc":83,"renk":"#00f3ff","emoji":"△","tip":"breakout"})

    # ── DÜŞEN ÜÇGEN (Desc. Triangle) ──────────────────────────────────────
    if rn >= 25:
        rH25 = rH[-25:]; rL25 = rL[-25:]
        lVals = rL25[-10:]; max_l = float(lVals.max()); min_l = float(lVals.min())
        h_first3 = (float(rH25[0]) + float(rH25[1]) + float(rH25[2])) / 3
        h_last3  = (float(rH25[22]) + float(rH25[23]) + float(rH25[24])) / 3
        horiz_sup = (max_l - min_l) / max(max_l, 0.001) < 0.04
        falling_ceil = h_last3 < h_first3 * 0.97
        if horiz_sup and falling_ceil and curr <= min_l * 1.01:
            formations.append({"ad":"DÜŞEN ÜÇGEN","guc":78,"renk":"#ff003c","emoji":"▽","tip":"bearish"})

    # ── YÜKSELEN KAMA (Rising Wedge) — bearish reversal ───────────────────
    if rn >= 30:
        n30r = min(35, rn)
        wH = rH[-n30r:]; wL = rL[-n30r:]
        h_first = (wH[0] + wH[1]) / 2;  h_last = (wH[-1] + wH[-2]) / 2
        l_first = (wL[0] + wL[1]) / 2;  l_last = (wL[-1] + wL[-2]) / 2
        if h_first > 0 and l_first > 0:
            h_rise = (h_last - h_first) / h_first * 100
            l_rise = (l_last - l_first) / l_first * 100
            if l_rise > h_rise + 1.5 and h_rise > 3 and l_rise > 5 and rsi > 58:
                formations.append({"ad":"YÜKS. KAMA","guc":84,"renk":"#ff003c","emoji":"📐","tip":"bearish"})

    # ── ÖLÜM KESİŞİMİ (SMA50<SMA200) ──────────────────────────────────────
    if sma50 > 0 and sma200 > 0 and sma50 < sma200 and rsi < 55:
        gap = (sma200 - sma50) / sma200 * 100
        if gap < 8:
            formations.append({"ad":"ÖLÜM KESİŞ.","guc":80,"renk":"#ff003c","emoji":"💀","tip":"bearish"})

    # ── GAP DOWN ──────────────────────────────────────────────────────────
    if rn >= 3:
        prev_c2 = float(rC[-2]); prev_l2 = float(rL[-2])
        curr_o2 = float(chart_data[-1].get("Open", 0) or 0) or curr
        gap_dn = (curr_o2 - prev_l2) / prev_l2 * 100 if prev_l2 > 0 else 0
        if gap_dn < -2.5 and curr < prev_c2 * 0.97 and avg_vol > 0 and last_vol > avg_vol * 1.8:
            formations.append({"ad":"GAP DOWN","guc":82,"renk":"#ff003c","emoji":"🕳️","tip":"bearish"})

    # ── RSI TEPE + MACD death ─────────────────────────────────────────────
    if rsi > 72 and macd_cross == "death":
        formations.append({"ad":"RSI TEPE+MACD","guc":85,"renk":"#ff003c","emoji":"🚨","tip":"bearish"})

    # ── RSI AYI DİVERJANS ─────────────────────────────────────────────────
    if div_rsi == "ayi" and pos52 > 55:
        formations.append({"ad":"RSI AYI DIV.","guc":83,"renk":"#ff003c","emoji":"📉","tip":"bearish"})

    # ── FLAMA (Pennant) ───────────────────────────────────────────────────
    if rn >= 20:
        pole = rC[-20:-12]; pennant = rC[-12:]
        pole_move = (pole[-1] - pole[0]) / pole[0] * 100 if len(pole) and pole[0] > 0 else 0
        ph = float(pennant.max()); pl = float(pennant.min())
        prange = (ph - pl) / pl * 100 if pl > 0 else 0
        if pole_move > 8 and 0.5 < prange < 5 and curr > pl * 1.01:
            formations.append({"ad":"FLAMA","guc":81,"renk":"#00f3ff","emoji":"🔺","tip":"momentum"})

    # ── GAP UP ────────────────────────────────────────────────────────────
    if rn >= 3:
        prev_h = float(rH[-2])
        curr_o = float(chart_data[-1].get("Open", 0) or 0) or curr
        gap = (curr_o - prev_h) / prev_h * 100 if prev_h > 0 else 0
        if gap > 2.5 and curr > prev_h * 1.02 and avg_vol > 0 and last_vol > avg_vol * 1.8:
            formations.append({"ad":"GAP UP","guc":84,"renk":"#ff9900","emoji":"🚀","tip":"momentum"})

    # ── DAR BANT SIKIŞMA (NR4/NR7) ────────────────────────────────────────
    if rn >= 8:
        ranges = list(rH[-8:] - rL[-8:])
        today = ranges[-1]; prev = ranges[:-1]
        if today > 0 and prev and today < min(prev) * 0.6:
            formations.append({"ad":"SIKIŞ. BANT","guc":76,"renk":"#bc13fe","emoji":"🎯","tip":"breakout"})

    # ── 3 BOĞA MUMU (Three White Soldiers — chart side) ───────────────────
    if rn >= 3 and len(chart_data) >= 3:
        c0 = float(rC[-3]); c1 = float(rC[-2]); c2 = float(rC[-1])
        o0 = float(chart_data[-3].get("Open", c0) or c0)
        o1 = float(chart_data[-2].get("Open", c1) or c1)
        o2 = float(chart_data[-1].get("Open", c2) or c2)
        if (c2 > c1 > c0 and c0 > o0 and c1 > o1 and c2 > o2
                and c1 > c0 * 1.005 and c2 > c1 * 1.005):
            formations.append({"ad":"3 BOĞA MUMU","guc":85,"renk":"#00ff9d","emoji":"🕯️","tip":"momentum"})

    # ── YATAY KIRILIM (Rectangle Breakout) ────────────────────────────────
    if rn >= 20:
        rH20 = rH[-20:]; rL20 = rL[-20:]
        ch = float(rH20[:15].max()); cl = float(rL20[:15].min())
        crange = (ch - cl) / ch * 100 if ch > 0 else 0
        if 3 < crange < 18 and curr > ch * 1.015 and avg_vol > 0 and last_vol > avg_vol * 1.5:
            formations.append({"ad":"YATAY KIRILIM","guc":83,"renk":"#00f3ff","emoji":"📦","tip":"breakout"})
        if 3 < crange < 18 and curr < cl * 0.985 and avg_vol > 0 and last_vol > avg_vol * 1.3:
            formations.append({"ad":"KANAL ASAGI KIR.","guc":80,"renk":"#ff003c","emoji":"📦","tip":"bearish"})

    # ── GENİŞLEYEN FRM (Broadening) ───────────────────────────────────────
    if rn >= 20:
        bH = rH[-20:]; bL = rL[-20:]
        h_first = (float(bH[0]) + float(bH[1])) / 2
        h_last  = (float(bH[19]) + float(bH[18])) / 2
        l_first = (float(bL[0]) + float(bL[1])) / 2
        l_last  = (float(bL[19]) + float(bL[18])) / 2
        if h_first > 0 and l_first > 0 and h_last > h_first * 1.05 and l_last < l_first * 0.95:
            formations.append({"ad":"GENİŞLEYEN FRM.","guc":76,"renk":"#ff003c","emoji":"🔊","tip":"bearish"})

    # ── SİMETRİK ÜÇGEN (sym wedge breakout) ───────────────────────────────
    if rn >= 30:
        sH = rH[-30:]; sL = rL[-30:]
        sh_first = (float(sH[0]) + float(sH[1])) / 2
        sh_last  = (float(sH[28]) + float(sH[29])) / 2
        sl_first = (float(sL[0]) + float(sL[1])) / 2
        sl_last  = (float(sL[28]) + float(sL[29])) / 2
        h_decl = (sh_first - sh_last) / sh_first * 100 if sh_first > 0 else 0
        l_rise = (sl_last - sl_first) / sl_first * 100 if sl_first > 0 else 0
        if h_decl > 3 and l_rise > 3 and abs(h_decl - l_rise) < 4:
            if curr > sh_last * 1.015 and roc20 > 1 and avg_vol > 0 and last_vol > avg_vol:
                formations.append({"ad":"SİMETRİK ÜÇGEN+","guc":84,"renk":"#00ff9d","emoji":"△","tip":"breakout"})
            elif curr < sl_last * 0.985 and roc20 < -1:
                formations.append({"ad":"SİMETRİK ÜÇGEN-","guc":79,"renk":"#ff003c","emoji":"▽","tip":"bearish"})

    # ── YÜK. ÜÇGEN KIR. (Ascending Tri breakout — strong) ─────────────────
    if rn >= 20:
        aH = rH[-20:]; aL = rL[-20:]
        a_high = float(aH.max())
        h_top1 = float(aH[:10].max()); h_top2 = float(aH[10:].max())
        l_bot1 = float(aL[:10].min()); l_bot2 = float(aL[10:].min())
        is_flat = a_high > 0 and abs(h_top1 - h_top2) / a_high < 0.03
        rising = l_bot2 > l_bot1 * 1.02
        if is_flat and rising and curr > a_high * 1.01 and avg_vol > 0 and last_vol > avg_vol * 1.4:
            formations.append({"ad":"YÜK. ÜÇGEN KIR.","guc":85,"renk":"#00ff9d","emoji":"📐","tip":"breakout"})

    # ── DUSME 3 YOL (Falling Three Methods) ───────────────────────────────
    if rn >= 6:
        f0, f1, f2, f3, f4, f5 = (float(rC[i]) for i in (-6, -5, -4, -3, -2, -1))
        bear_candle = f0 > f5
        small_bulls = (f1 > f0 * 0.97 and f2 > f0 * 0.97 and f3 > f0 * 0.97 and f4 > f0 * 0.97)
        if bear_candle and small_bulls and f5 < f0:
            formations.append({"ad":"DUSME 3 YOL","guc":78,"renk":"#ff003c","emoji":"🎌","tip":"bearish"})

    # ── AYI BAYRAĞI (Bear Flag) ───────────────────────────────────────────
    if rn >= 25:
        bf_pole = rC[-25:-15]; bf_flag = rC[-15:-5]; bf_last = rC[-5:]
        pole_dn = (bf_pole[0] - bf_pole[-1]) / bf_pole[0] * 100 if len(bf_pole) and bf_pole[0] > 0 else 0
        flag_corr = (bf_flag[-1] - bf_flag[0]) / bf_flag[0] * 100 if len(bf_flag) and bf_flag[0] > 0 else 0
        last_brk = (bf_last[0] - bf_last[-1]) / bf_last[0] * 100 if len(bf_last) and bf_last[0] > 0 else 0
        if pole_dn > 8 and -1.5 < flag_corr < 7 and last_brk > 1:
            formations.append({"ad":"AYI BAYRAĞI","guc":84,"renk":"#ff003c","emoji":"🏴","tip":"bearish"})

    # ── ALTIN KESİŞİM (SMA50>SMA200, gap<6%) ──────────────────────────────
    if sma50 > 0 and sma200 > 0 and sma50 > sma200 and rsi < 65:
        gap = (sma50 - sma200) / sma200 * 100
        if gap < 6:
            formations.append({"ad":"ALTIN KESİŞİM","guc":87,"renk":"#ffea00","emoji":"⭐","tip":"momentum"})

    # ── İÇ BAR KIRILIM (Inside Bar Breakout) ──────────────────────────────
    if rn >= 4:
        ibH1 = float(rH[-2]); ibL1 = float(rL[-2])
        ibH0 = float(rH[-1])
        ibHM = float(rH[-3]); ibLM = float(rL[-3])
        is_inside = (rH[-2] < ibHM) and (rL[-2] > ibLM)
        if is_inside and ibH0 > ibH1 * 1.01 and avg_vol > 0 and last_vol > avg_vol * 1.3:
            formations.append({"ad":"İÇ BAR KIRIL.","guc":79,"renk":"#00f3ff","emoji":"📌","tip":"breakout"})

    # ── DIŞ BAR (Outside Bar) ─────────────────────────────────────────────
    if rn >= 3:
        obH1 = float(rH[-2]); obL1 = float(rL[-2])
        obH0 = float(rH[-1]); obL0 = float(rL[-1])
        mid = (obH1 + obL1) / 2
        if obH0 > obH1 * 1.005 and obL0 < obL1 * 0.995 and avg_vol > 0 and last_vol > avg_vol * 1.5:
            if curr > mid:
                formations.append({"ad":"DIŞ BAR YÜKS.","guc":78,"renk":"#00ff9d","emoji":"🔱","tip":"breakout"})
            else:
                formations.append({"ad":"DIŞ BAR DÜŞÜŞ","guc":77,"renk":"#ff003c","emoji":"🔻","tip":"bearish"})

    # ── MACD DİVERJANS ────────────────────────────────────────────────────
    if div_macd == "boga" and pos52 < 50:
        formations.append({"ad":"MACD DIV BOĞA","guc":82,"renk":"#00ff9d","emoji":"📈","tip":"reversal"})
    if div_macd == "ayi" and pos52 > 50:
        formations.append({"ad":"MACD DIV AYI","guc":81,"renk":"#ff003c","emoji":"📉","tip":"bearish"})

    # ── HACİM KURUMA ──────────────────────────────────────────────────────
    if rn >= 10 and avg_vol > 0:
        last_avg = float(rV[-5:].mean())
        prev_avg = float(rV[-10:-5].mean())
        if prev_avg > 0 and last_avg < prev_avg * 0.55 and curr >= float(rC[-5]) * 0.98:
            formations.append({"ad":"HACİM KURUMA","guc":75,"renk":"#bc13fe","emoji":"🔇","tip":"breakout"})

    # ── EMA 9/21 KESİŞİM (chart formation) ────────────────────────────────
    if ema_cross_v == "golden" and rsi < 60 and adx_val >= 20:
        formations.append({"ad":"EMA ALTIN KES.","guc":83,"renk":"#ffea00","emoji":"✨","tip":"momentum"})
    if ema_cross_v == "death" and rsi > 40:
        formations.append({"ad":"EMA ÖLÜM KES.","guc":80,"renk":"#ff003c","emoji":"💀","tip":"bearish"})

    # ── SÜPER TREND (Supertrend + SAR aynı yön) ──────────────────────────
    if st_dir == "yukselis" and sar_dir == "yukselis" and rsi < 55:
        formations.append({"ad":"SÜPER TREND↑","guc":84,"renk":"#00ff9d","emoji":"🚀","tip":"momentum"})
    if st_dir == "dusus" and sar_dir == "dusus" and rsi > 45:
        formations.append({"ad":"SÜPER TREND↓","guc":82,"renk":"#ff003c","emoji":"🔻","tip":"bearish"})

    # ── YÜKS. 3 YOL (Rising Three Methods) ────────────────────────────────
    if rn >= 6:
        r0, r1, r2, r3, r4, r5 = (float(rC[i]) for i in (-6, -5, -4, -3, -2, -1))
        bull_mother = r0 < r5
        small_bears = (r1 < r0 * 1.02 and r2 < r0 * 1.02 and r3 < r0 * 1.02 and r4 < r0 * 1.02
                       and r1 > r0 * 0.97 and r4 > r0 * 0.97)
        if bull_mother and small_bears and r5 > r0 * 1.005:
            formations.append({"ad":"YÜKS. 3 YOL","guc":80,"renk":"#00ff9d","emoji":"🕯️","tip":"momentum"})

    # ── Hacim doğrulama & dinamik güç (PHP 9774-9782) ─────────────────────
    formations = _apply_volume_strength(formations, v_ratio, avg_vol)

    formations.sort(key=lambda f: f.get("guc", 0), reverse=True)
    return formations[:4]


# ─────────────────────────────────────────────────────────────────────────────
# detectCandleFormations — PHP index.php:9791 birebir
# ─────────────────────────────────────────────────────────────────────────────
def detect_candle_formations(chart_data: Sequence[dict]) -> list[dict]:
    n = len(chart_data); 
    if n < 5: return []
    found: list[dict] = []
    bars = list(chart_data[-5:]); nb = len(bars)

    def O(i): return float(bars[i].get("Open",  bars[i].get("Close", 0)) or 0)
    def H(i): return float(bars[i].get("High",  bars[i].get("Close", 0)) or 0)
    def L(i): return float(bars[i].get("Low",   bars[i].get("Close", 0)) or 0)
    def C(i): return float(bars[i].get("Close", 0) or 0)

    last = nb - 1; prev = nb - 2; prev2 = nb - 3
    o1, h1, l1, c1 = O(last),  H(last),  L(last),  C(last)
    o2, h2, l2, c2 = O(prev),  H(prev),  L(prev),  C(prev)
    o3, c3         = O(prev2), C(prev2)
    body1 = abs(c1 - o1); body2 = abs(c2 - o2)
    rng1 = h1 - l1;       rng2 = h2 - l2
    bull1 = c1 > o1;      bull2 = c2 > o2

    # Çekiç (Hammer)
    if rng1 > 0:
        lower = (o1 if bull1 else c1) - l1
        upper = h1 - (c1 if bull1 else o1)
        if lower >= body1 * 2.2 and upper < body1 * 0.4 and body1 > 0 and not bull2:
            found.append({"ad":"ÇEKİÇ","guc":83,"renk":"#00ff9d","emoji":"🔨","tip":"reversal"})

    # Yutan Boğa
    if not bull2 and bull1 and body1 > 0 and body2 > 0:
        if o1 <= c2 and c1 >= o2 and body1 > body2 * 1.1:
            found.append({"ad":"YUTAN BOĞA","guc":89,"renk":"#00ff9d","emoji":"🐂","tip":"reversal"})

    # Sabah Yıldızı
    if nb >= 3:
        body_mid = abs(C(prev) - O(prev))
        bear3 = not (C(prev2) > O(prev2)); bull3 = c1 > o1
        if (bear3 and bull3 and body_mid < abs(c3 - o3) * 0.5
                and c1 > (o3 + c3) / 2 and c2 < min(o3, c3)):
            found.append({"ad":"SABAH YILDIZI","guc":91,"renk":"#00ff9d","emoji":"⭐","tip":"reversal"})

    # Doji Dip
    if rng1 > 0:
        body_pct = body1 / rng1
        low_pct  = ((o1 if bull1 else c1) - l1) / rng1
        if body_pct < 0.12 and low_pct > 0.65 and not bull2:
            found.append({"ad":"DOJİ DİP","guc":81,"renk":"#00ff9d","emoji":"🐉","tip":"reversal"})

    # Ters Çekiç
    if rng1 > 0 and not bull2:
        upper = h1 - (c1 if bull1 else o1)
        lower = (o1 if bull1 else c1) - l1
        if upper >= body1 * 2.0 and lower < body1 * 0.3 and body1 > 0:
            found.append({"ad":"TERS ÇEKİÇ","guc":77,"renk":"#ffea00","emoji":"🔃","tip":"reversal"})

    # Akşam Yıldızı
    if nb >= 3:
        body_mid2 = abs(C(prev) - O(prev))
        bull3e = C(prev2) > O(prev2); bear3e = not bull1
        if (bull3e and bear3e and body_mid2 < abs(c3 - o3) * 0.5
                and c1 < (o3 + c3) / 2 and c2 > max(o3, c3)):
            found.append({"ad":"AKŞAM YILDIZI","guc":88,"renk":"#ff003c","emoji":"🌙","tip":"bearish"})

    # Karanlık Bulut
    if bull2 and not bull1 and body2 > 0 and body1 > 0:
        if o1 > h2 and c1 < (o2 + c2) / 2 and c1 > o2:
            found.append({"ad":"KARANLIK BULUT","guc":82,"renk":"#ff003c","emoji":"☁️","tip":"bearish"})

    # Yutan Ayı
    if bull2 and not bull1 and body2 > 0 and body1 > 0:
        if o1 >= c2 and c1 <= o2 and body1 > body2 * 1.1:
            found.append({"ad":"YUTAN AYI","guc":86,"renk":"#ff003c","emoji":"🐻","tip":"bearish"})

    # Harami Boğa
    if not bull2 and bull1 and body2 > 0 and body1 > 0:
        if o1 >= c2 and c1 <= o2 and body1 < body2 * 0.6:
            found.append({"ad":"HARAMİ BOĞA","guc":74,"renk":"#00ff9d","emoji":"🕯️","tip":"reversal"})

    # Dragonfly Doji
    if rng1 > 0 and not bull2:
        body_pct2 = body1 / rng1
        upper_sh = h1 - max(o1, c1)
        lower_sh = min(o1, c1) - l1
        if body_pct2 < 0.1 and lower_sh > rng1 * 0.6 and upper_sh < rng1 * 0.1:
            found.append({"ad":"DRAGONFLİ DOJİ","guc":79,"renk":"#00ff9d","emoji":"🐉","tip":"reversal"})

    # Asılı Adam
    if rng1 > 0 and bull2:
        lower_hm = (o1 if bull1 else c1) - l1
        upper_hm = h1 - (c1 if bull1 else o1)
        if lower_hm >= body1 * 2.2 and upper_hm < body1 * 0.4 and body1 > 0:
            found.append({"ad":"ASILI ADAM","guc":80,"renk":"#ff003c","emoji":"🪝","tip":"bearish"})

    # Harami Ayı
    if bull2 and not bull1 and body2 > 0 and body1 > 0:
        if o1 <= c2 and c1 >= o2 and body1 < body2 * 0.6:
            found.append({"ad":"HARAMİ AYI","guc":76,"renk":"#ff003c","emoji":"🐻","tip":"bearish"})

    # Mezar Taşı Doji
    if rng1 > 0 and bull2:
        upper_gd = h1 - max(o1, c1)
        lower_gd = min(o1, c1) - l1
        body_pct_gd = body1 / rng1
        if body_pct_gd < 0.1 and upper_gd > rng1 * 0.6 and lower_gd < rng1 * 0.1:
            found.append({"ad":"MEZAR TAŞI DOJİ","guc":78,"renk":"#ff003c","emoji":"🪦","tip":"bearish"})

    # 3 Kara Karga
    if nb >= 3:
        o3b, c3b = O(prev2), C(prev2); o2b, c2b = O(prev), C(prev); o1b, c1b = O(last), C(last)
        bear1b = c3b < o3b; bear2b = c2b < o2b; bear3b = c1b < o1b
        b1 = abs(c3b-o3b); b2 = abs(c2b-o2b); b3 = abs(c1b-o1b)
        if (bear1b and bear2b and bear3b and b1 > 0 and b2 > b1 * 0.7 and b3 > b2 * 0.7
                and c2b < c3b and c1b < c2b):
            found.append({"ad":"3 KARA KARGA","guc":90,"renk":"#ff003c","emoji":"🐦","tip":"bearish"})

    # Fışkıran Yıldız
    if rng1 > 0 and bull2:
        upper_ss = h1 - max(o1, c1)
        lower_ss = min(o1, c1) - l1
        if upper_ss >= body1 * 2.0 and lower_ss < body1 * 0.5 and body1 > 0:
            found.append({"ad":"FIŞKİRAN YILDIZ","guc":81,"renk":"#ff003c","emoji":"💫","tip":"bearish"})

    # Delici Hat
    if nb >= 2 and not bull2 and bull1 and body2 > 0 and body1 > 0:
        bear_mid = (o2 + c2) / 2
        if o1 < l2 and c1 > bear_mid and c1 < o2 and body1 > body2 * 0.5:
            found.append({"ad":"DELİCİ HAT","guc":80,"renk":"#00ff9d","emoji":"🗡️","tip":"reversal"})

    # Cımbız Dip
    if nb >= 2 and not bull2 and rng1 > 0 and rng2 > 0:
        if abs(l1 - l2) / max(l1, 0.001) < 0.005 and bull1:
            found.append({"ad":"CIMBIZ DİP","guc":77,"renk":"#00ff9d","emoji":"🔧","tip":"reversal"})

    # Cımbız Tepe
    if nb >= 2 and bull2 and rng1 > 0 and rng2 > 0:
        if abs(h1 - h2) / max(h1, 0.001) < 0.005 and not bull1:
            found.append({"ad":"CIMBIZ TEPE","guc":75,"renk":"#ff003c","emoji":"🔧","tip":"bearish"})

    # 3 İçeriden Yukarı
    if nb >= 3:
        c3i, o3i = C(prev2), O(prev2); c2i, o2i = C(prev), O(prev)
        if c3i < o3i and c2i > o2i and bull1 and o2i > c3i and c2i < o3i and c1 > o3i:
            found.append({"ad":"3 İÇERİDEN YUKA.","guc":82,"renk":"#00ff9d","emoji":"⬆️","tip":"reversal"})

    # 3 İçeriden Aşağı
    if nb >= 3:
        c3d, o3d = C(prev2), O(prev2); c2d, o2d = C(prev), O(prev)
        if c3d > o3d and c2d < o2d and not bull1 and o2d < c3d and c2d > o3d and c1 < o3d:
            found.append({"ad":"3 İÇERİDEN AŞA.","guc":80,"renk":"#ff003c","emoji":"⬇️","tip":"bearish"})

    # Boğa Tepme
    if nb >= 2 and bull1 and not bull2 and body1 > 0 and body2 > 0:
        if o1 >= o2 and c1 > o2 and body1 > body2 * 0.8:
            found.append({"ad":"BOĞA TEPME","guc":91,"renk":"#00ff9d","emoji":"🦵","tip":"reversal"})

    # Ayı Tepme
    if nb >= 2 and not bull1 and bull2 and body1 > 0 and body2 > 0:
        if o1 <= o2 and c1 < o2 and body1 > body2 * 0.8:
            found.append({"ad":"AYI TEPME","guc":88,"renk":"#ff003c","emoji":"🦵","tip":"bearish"})

    # Marubozu Boğa
    if rng1 > 0 and bull1 and body1 > 0:
        upper_m = h1 - c1; lower_m = o1 - l1
        if upper_m < body1 * 0.05 and lower_m < body1 * 0.05 and body1 / rng1 > 0.92:
            found.append({"ad":"MARUBOZU BOĞA","guc":86,"renk":"#00ff9d","emoji":"🟢","tip":"reversal"})

    # Marubozu Ayı
    if rng1 > 0 and not bull1 and body1 > 0:
        upper_mb = h1 - o1; lower_mb = c1 - l1
        if upper_mb < body1 * 0.05 and lower_mb < body1 * 0.05 and body1 / rng1 > 0.92:
            found.append({"ad":"MARUBOZU AYI","guc":85,"renk":"#ff003c","emoji":"🔴","tip":"bearish"})

    # Kemer Tutma Boğa
    if nb >= 2 and bull1 and not bull2 and body1 > 0:
        lower_bh = o1 - l1
        if lower_bh < body1 * 0.05 and body1 > body2 * 0.8 and o1 < l2:
            found.append({"ad":"KEMER TUTMA↑","guc":79,"renk":"#00ff9d","emoji":"🎗️","tip":"reversal"})

    # Kemer Tutma Ayı
    if nb >= 2 and not bull1 and bull2 and body1 > 0:
        upper_bhb = h1 - o1
        if upper_bhb < body1 * 0.05 and body1 > body2 * 0.8 and o1 > h2:
            found.append({"ad":"KEMER TUTMA↓","guc":78,"renk":"#ff003c","emoji":"🎗️","tip":"bearish"})

    # Doji Yıldız
    if nb >= 2 and rng1 > 0 and rng2 > 0:
        is_doji_star = (body1 / rng1) < 0.08
        gap_up = o1 > h2 * 0.995
        gap_dn = o1 < l2 * 1.005
        if is_doji_star and gap_up and bull2:
            found.append({"ad":"DOJİ YILDIZ TEPE","guc":78,"renk":"#ff003c","emoji":"💫","tip":"bearish"})
        if is_doji_star and gap_dn and not bull2:
            found.append({"ad":"DOJİ YILDIZ DİP","guc":77,"renk":"#00ff9d","emoji":"💫","tip":"reversal"})

    # Uzun Alt Gölge
    if rng1 > 0 and body1 > 0:
        lower_sh = (o1 if bull1 else c1) - l1
        upper_sh = h1 - (c1 if bull1 else o1)
        if lower_sh >= body1 * 3.0 and upper_sh < body1 * 0.5 and not bull2:
            found.append({"ad":"UZUN ALT GÖLGE","guc":76,"renk":"#00ff9d","emoji":"📏","tip":"reversal"})

    # Sabah Doji Yıldızı
    if nb >= 3:
        o3mds, c3mds = O(prev2), C(prev2); o2mds, c2mds = O(prev), C(prev)
        body2mds = abs(c2mds - o2mds); rng2mds = H(prev) - L(prev)
        is_doji_mid = rng2mds > 0 and body2mds / rng2mds < 0.1
        bear3mds = c3mds < o3mds
        if bear3mds and is_doji_mid and bull1 and c2mds < o3mds and c1 > (o3mds + c3mds) / 2:
            found.append({"ad":"SABAH DOJİ","guc":90,"renk":"#00ff9d","emoji":"🌟","tip":"reversal"})

    # Akşam Doji Yıldızı
    if nb >= 3:
        o3eds, c3eds = O(prev2), C(prev2); o2eds, c2eds = O(prev), C(prev)
        body2eds = abs(c2eds - o2eds); rng2eds = H(prev) - L(prev)
        is_doji_mid_e = rng2eds > 0 and body2eds / rng2eds < 0.1
        bull3eds = c3eds > o3eds
        if bull3eds and is_doji_mid_e and not bull1 and c2eds > o3eds and c1 < (o3eds + c3eds) / 2:
            found.append({"ad":"AKŞAM DOJİ","guc":89,"renk":"#ff003c","emoji":"🌚","tip":"bearish"})

    # Uzun Üst Gölge
    if rng1 > 0 and body1 > 0:
        upper_u = h1 - (c1 if bull1 else o1)
        lower_u = (o1 if bull1 else c1) - l1
        if upper_u >= body1 * 3.0 and lower_u < body1 * 0.5 and bull2:
            found.append({"ad":"UZUN ÜST GÖLGE","guc":75,"renk":"#ff003c","emoji":"📏","tip":"bearish"})

    found.sort(key=lambda f: f.get("guc", 0), reverse=True)
    return found[:3]


# ─────────────────────────────────────────────────────────────────────────────
# Hacim doğrulama (PHP 9774-9782): vRatio>=2 → +4, vRatio<0.7 → -6 (60-99)
# ─────────────────────────────────────────────────────────────────────────────
def _apply_volume_strength(formations: list[dict], v_ratio: float, avg_vol: float) -> list[dict]:
    out = []
    for f in formations:
        f = dict(f)
        tip = f.get("tip", "")
        if v_ratio >= 2.0 and tip in ("reversal", "breakout", "momentum"):
            f["guc"] = min(99, int(f.get("guc", 60)) + 4)
        elif avg_vol > 0 and v_ratio < 0.7:
            f["guc"] = max(60, int(f.get("guc", 60)) - 6)
        out.append(f)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Birleşik API — scan.py geriye dönük uyumlu
# ─────────────────────────────────────────────────────────────────────────────
def detect_all(highs, lows, opens, closes, volumes=None, tech: dict | None = None) -> list[dict]:
    """Hem mum hem grafik formasyonlarını birleştirip döndürür.
    `tech` verilirse grafik formasyonları (chart) da hesaplanır.
    """
    n = len(closes) if closes is not None else 0
    if n < 5:
        return []
    # Build chart_data list-comprehension (faster than loop+append)
    _c = [float(x) for x in closes]
    _h = [float(highs[i])   if highs   is not None and i < len(highs)   else _c[i] for i in range(n)]
    _l = [float(lows[i])    if lows    is not None and i < len(lows)    else _c[i] for i in range(n)]
    _o = [float(opens[i])   if opens   is not None and i < len(opens)   else _c[i] for i in range(n)]
    _v = [float(volumes[i]) if volumes is not None and i < len(volumes) else 0.0   for i in range(n)]
    chart_data: list[dict] = [
        {"Open": _o[i], "High": _h[i], "Low": _l[i], "Close": _c[i], "Vol": _v[i]}
        for i in range(n)
    ]
    found: list[dict] = []
    try:
        found.extend(detect_candle_formations(chart_data))
    except Exception:
        pass
    if tech is not None:
        try:
            found.extend(detect_chart_formations(chart_data, tech))
        except Exception:
            pass
    return found
