"""Teknik indikatörler — numpy tabanlı (RSI, MACD, ADX, Bollinger, vs.).

Tüm fonksiyonlar OHLCV verisini bekler. Veri yoksa 0/varsayılan döner.
"""
from __future__ import annotations
import numpy as np
from typing import Any


def _to_arr(x: Any) -> np.ndarray:
    if x is None:
        return np.array([], dtype=float)
    arr = np.asarray(x, dtype=float)
    return arr[~np.isnan(arr)]


def rsi(closes: Any, period: int = 14) -> float:
    c = _to_arr(closes)
    if len(c) < period + 1:
        return 50.0
    diff = np.diff(c)
    gain = np.where(diff > 0, diff, 0.0)
    loss = np.where(diff < 0, -diff, 0.0)
    # Wilder smoothing
    avg_g = gain[:period].mean()
    avg_l = loss[:period].mean()
    for i in range(period, len(diff)):
        avg_g = (avg_g * (period - 1) + gain[i]) / period
        avg_l = (avg_l * (period - 1) + loss[i]) / period
    if avg_l == 0:
        return 100.0
    rs = avg_g / avg_l
    return float(100.0 - (100.0 / (1.0 + rs)))


def ema(closes: Any, period: int) -> np.ndarray:
    c = _to_arr(closes)
    if len(c) == 0:
        return c
    alpha = 2.0 / (period + 1)
    out = np.empty_like(c)
    out[0] = c[0]
    for i in range(1, len(c)):
        out[i] = alpha * c[i] + (1 - alpha) * out[i - 1]
    return out


def sma(closes: Any, period: int) -> float:
    c = _to_arr(closes)
    if len(c) < period:
        return float(c.mean()) if len(c) else 0.0
    return float(c[-period:].mean())


def macd(closes: Any, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    c = _to_arr(closes)
    if len(c) < slow + signal:
        return {"macd": 0.0, "signal": 0.0, "hist": 0.0, "cross": "none"}
    ema_f = ema(c, fast)
    ema_s = ema(c, slow)
    line = ema_f - ema_s
    sig = ema(line, signal)
    hist = line - sig
    cross = "none"
    if len(line) >= 2 and len(sig) >= 2:
        if line[-2] <= sig[-2] and line[-1] > sig[-1]:
            cross = "golden"
        elif line[-2] >= sig[-2] and line[-1] < sig[-1]:
            cross = "death"
    return {
        "macd": float(line[-1]),
        "signal": float(sig[-1]),
        "hist": float(hist[-1]),
        "cross": cross,
    }


def bollinger(closes: Any, period: int = 20, mult: float = 2.0) -> dict:
    c = _to_arr(closes)
    if len(c) < period:
        return {"upper": 0.0, "mid": 0.0, "lower": 0.0, "squeeze": False}
    window = c[-period:]
    mid = float(window.mean())
    sd = float(window.std(ddof=0))
    upper = mid + mult * sd
    lower = mid - mult * sd
    width = (upper - lower) / mid if mid > 0 else 1.0
    # Sıkışma: bant genişliği son 60 günün ortalamasının %85'i altında
    squeeze = False
    if len(c) >= period + 40:
        widths = []
        for i in range(period, len(c) + 1):
            w = c[i - period:i]
            m = w.mean()
            s = w.std(ddof=0)
            widths.append((4 * s) / m if m > 0 else 0)
        if widths:
            avg = np.mean(widths[-60:]) if len(widths) >= 60 else np.mean(widths)
            squeeze = width < avg * 0.85
    return {"upper": upper, "mid": mid, "lower": lower, "squeeze": squeeze, "width": width}


def calculate_bb_position(closes: Any, period: int = 20, mult: float = 2.0) -> dict:
    """PHP calculateBBPosition birebir.
    Returns: {pct, bandwidth, squeeze, lower, upper}
    pct = (curr - lower) / (upper - lower) * 100
    squeeze = bandwidth < 0.2 quantile of historical bandwidths.
    """
    c = _to_arr(closes)
    n = len(c)
    if n < period:
        return {"pct": 50.0, "bandwidth": 0.0, "squeeze": False, "lower": 0.0, "upper": 0.0}
    window = c[-period:]
    avg = float(window.mean())
    sd  = float(np.sqrt(((window - avg) ** 2).mean()))
    upper = avg + mult * sd
    lower = avg - mult * sd
    curr  = float(c[-1])
    pct = (curr - lower) / (upper - lower) * 100 if upper > lower else 50.0
    bw  = (upper - lower) / max(avg, 1e-4) * 100
    bw_arr = []
    for i in range(period, n):
        s2 = c[i - period:i]
        a2 = float(s2.mean())
        v2 = float(((s2 - a2) ** 2).mean())
        sd2 = float(np.sqrt(v2))
        bw_arr.append(2 * mult * sd2 / max(a2, 1e-4) * 100)
    if len(bw_arr) >= 10:
        srt = sorted(bw_arr)
        idx = 0.2 * (len(srt) - 1)
        lo = int(idx); hi = min(lo + 1, len(srt) - 1)
        thresh = srt[lo] + (idx - lo) * (srt[hi] - srt[lo])
    else:
        thresh = bw + 1
    return {
        "pct":       round(pct, 1),
        "bandwidth": round(bw, 2),
        "squeeze":   bool(bw < thresh),
        "lower":     round(lower, 2),
        "upper":     round(upper, 2),
    }


def calculate_ema_crossover(closes: Any, fast_p: int = 9, slow_p: int = 21) -> dict:
    """PHP calculateEMACrossover birebir.
    Returns: {cross: 'none'|'golden'|'death', fastAboveSlow, fastEMA, slowEMA}
    """
    c = _to_arr(closes)
    if len(c) < slow_p + 2:
        return {"cross": "none", "fastAboveSlow": False, "fastEMA": 0.0, "slowEMA": 0.0}
    fast_ema = float(ema(c, fast_p)[-1])
    slow_ema = float(ema(c, slow_p)[-1])
    prev_fast = float(ema(c[:-1], fast_p)[-1])
    prev_slow = float(ema(c[:-1], slow_p)[-1])
    cross = "none"
    if prev_fast <= prev_slow and fast_ema > slow_ema:
        cross = "golden"
    elif prev_fast >= prev_slow and fast_ema < slow_ema:
        cross = "death"
    return {
        "cross":         cross,
        "fastAboveSlow": fast_ema > slow_ema,
        "fastEMA":       round(fast_ema, 2),
        "slowEMA":       round(slow_ema, 2),
    }


def detect_divergence(chart_data: list, lookback: int = 60) -> dict:
    """PHP detectDivergence birebir — RSI ve MACD divergence (boga/ayi/ayi_gizli/yok).
    chart_data: [{Close, High, Low, Vol}, ...]
    """
    n = len(chart_data) if chart_data else 0
    if n < lookback + 20:
        return {"rsi": "yok", "macd": "yok"}
    sl = chart_data[-lookback:]
    closes = [float(b.get("Close", 0) or 0) for b in sl]
    ln = len(closes)

    # Dipler (5-bar pivot low)
    dips = []
    for i in range(3, ln - 3):
        if (closes[i] <= closes[i-1] and closes[i] <= closes[i-2]
                and closes[i] <= closes[i+1] and closes[i] <= closes[i+2]):
            dips.append({"idx": i, "price": closes[i]})

    # RSI dizisi
    rsi_arr = {}
    for i in range(14, ln):
        s = closes[max(0, i - 28):i + 1]
        rsi_arr[i] = float(rsi(s, 14))

    rsi_div = "yok"
    if len(dips) >= 2:
        d1 = dips[-2]; d2 = dips[-1]
        if d2["price"] < d1["price"] and d1["idx"] in rsi_arr and d2["idx"] in rsi_arr:
            if rsi_arr[d2["idx"]] > rsi_arr[d1["idx"]]:
                rsi_div = "boga"
        if d2["price"] > d1["price"] and d1["idx"] in rsi_arr and d2["idx"] in rsi_arr:
            if rsi_arr[d2["idx"]] < rsi_arr[d1["idx"]]:
                rsi_div = "ayi"

    # Tepeler (5-bar pivot high)
    peaks = []
    for i in range(3, ln - 3):
        if (closes[i] >= closes[i-1] and closes[i] >= closes[i-2]
                and closes[i] >= closes[i+1] and closes[i] >= closes[i+2]):
            peaks.append({"idx": i, "price": closes[i]})

    macd_div = "yok"
    if len(dips) >= 2:
        d1 = dips[-2]; d2 = dips[-1]
        m1 = macd(closes[:d1["idx"] + 1])
        m2 = macd(closes[:d2["idx"] + 1])
        if d2["price"] < d1["price"] and m2["hist"] > m1["hist"]:
            macd_div = "boga"
    if macd_div == "yok" and len(peaks) >= 2:
        p1 = peaks[-2]; p2 = peaks[-1]
        pm1 = macd(closes[:p1["idx"] + 1])
        pm2 = macd(closes[:p2["idx"] + 1])
        if p2["price"] > p1["price"] and pm2["hist"] < pm1["hist"]:
            macd_div = "ayi_gizli"

    return {"rsi": rsi_div, "macd": macd_div}


def atr(highs: Any, lows: Any, closes: Any, period: int = 14) -> float:
    h, l, c = _to_arr(highs), _to_arr(lows), _to_arr(closes)
    n = min(len(h), len(l), len(c))
    if n < period + 1:
        return 0.0
    h, l, c = h[-n:], l[-n:], c[-n:]
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    if len(tr) < period:
        return float(tr.mean()) if len(tr) else 0.0
    a = tr[:period].mean()
    for i in range(period, len(tr)):
        a = (a * (period - 1) + tr[i]) / period
    return float(a)


def adx(highs: Any, lows: Any, closes: Any, period: int = 14) -> dict:
    h, l, c = _to_arr(highs), _to_arr(lows), _to_arr(closes)
    n = min(len(h), len(l), len(c))
    if n < period * 2:
        return {"val": 0.0, "dir": "notr", "plusDI": 0.0, "minusDI": 0.0}
    h, l, c = h[-n:], l[-n:], c[-n:]
    up = h[1:] - h[:-1]
    dn = l[:-1] - l[1:]
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    # Wilder smoothing
    def _smooth(arr):
        s = np.empty(len(arr))
        s[period - 1] = arr[:period].sum()
        for i in range(period, len(arr)):
            s[i] = s[i - 1] - s[i - 1] / period + arr[i]
        return s
    if len(tr) < period:
        return {"val": 0.0, "dir": "notr", "plusDI": 0.0, "minusDI": 0.0}
    str_ = _smooth(tr)
    spdm = _smooth(plus_dm)
    smdm = _smooth(minus_dm)
    # v38.1: Güvenli bölme — np.errstate ile overflow/invalid uyarıları
    # tamamen baskılanır; np.divide(out=, where=) sonucu sıfır yazar ama
    # numpy yine de tüm öğeleri hesapladığından uyarı üretebiliyor.
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        pdi = np.divide(100.0 * spdm, str_, out=np.zeros_like(str_, dtype=float), where=(str_ != 0))
        mdi = np.divide(100.0 * smdm, str_, out=np.zeros_like(str_, dtype=float), where=(str_ != 0))
        pmi_sum = pdi + mdi
        dx = np.divide(100.0 * np.abs(pdi - mdi), pmi_sum, out=np.zeros_like(pmi_sum, dtype=float), where=(pmi_sum != 0))
    # NaN/Inf temizliği — savunmacı (yukarıdan emin olsak da)
    dx = np.nan_to_num(dx, nan=0.0, posinf=0.0, neginf=0.0)
    pdi = np.nan_to_num(pdi, nan=0.0, posinf=0.0, neginf=0.0)
    mdi = np.nan_to_num(mdi, nan=0.0, posinf=0.0, neginf=0.0)
    if dx.size > period:
        adx_val = float(dx[-period:].mean())
    elif dx.size:
        adx_val = float(dx.mean())
    else:
        adx_val = 0.0
    direction = "yukselis" if pdi[-1] > mdi[-1] else "dusus"
    if abs(pdi[-1] - mdi[-1]) < 1.0:
        direction = "notr"
    return {"val": adx_val, "dir": direction, "plusDI": float(pdi[-1]), "minusDI": float(mdi[-1])}


def stoch_rsi(closes: Any, period: int = 14, k_period: int = 3, d_period: int = 3) -> dict:
    """Stoch RSI — PHP $tech['stochRsi'] uyumlu."""
    c = _to_arr(closes)
    if len(c) < period * 2:
        return {"k": 50.0, "d": 50.0}
    rsi_arr = []
    for i in range(period, len(c) + 1):
        rsi_arr.append(rsi(c[:i], period))
    rsi_arr = np.asarray(rsi_arr, dtype=float)
    if len(rsi_arr) < period:
        return {"k": 50.0, "d": 50.0}
    ks = []
    for i in range(period - 1, len(rsi_arr)):
        win = rsi_arr[i - period + 1:i + 1]
        hi = float(win.max()); lo = float(win.min())
        ks.append(100 * (rsi_arr[i] - lo) / (hi - lo) if (hi - lo) > 0 else 50)
    if not ks:
        return {"k": 50.0, "d": 50.0}
    k_smooth = float(np.mean(ks[-k_period:])) if len(ks) >= k_period else float(ks[-1])
    d_smooth = float(np.mean(ks[-d_period:])) if len(ks) >= d_period else k_smooth
    return {"k": k_smooth, "d": d_smooth}


def stochastic(highs: Any, lows: Any, closes: Any, k_period: int = 14, d_period: int = 3) -> dict:
    h, l, c = _to_arr(highs), _to_arr(lows), _to_arr(closes)
    n = min(len(h), len(l), len(c))
    if n < k_period:
        return {"k": 50.0, "d": 50.0}
    h, l, c = h[-n:], l[-n:], c[-n:]
    ks = []
    for i in range(k_period - 1, n):
        hh = h[i - k_period + 1:i + 1].max()
        ll = l[i - k_period + 1:i + 1].min()
        ks.append(100 * (c[i] - ll) / (hh - ll) if (hh - ll) > 0 else 50)
    k = ks[-1]
    d = float(np.mean(ks[-d_period:])) if len(ks) >= d_period else k
    return {"k": float(k), "d": float(d)}


def williams_r(highs: Any, lows: Any, closes: Any, period: int = 14) -> float:
    h, l, c = _to_arr(highs), _to_arr(lows), _to_arr(closes)
    n = min(len(h), len(l), len(c))
    if n < period:
        return -50.0
    h, l, c = h[-period:], l[-period:], c[-period:]
    hh, ll = h.max(), l.min()
    if hh - ll == 0:
        return -50.0
    return float(-100 * (hh - c[-1]) / (hh - ll))


def cci(highs: Any, lows: Any, closes: Any, period: int = 20) -> float:
    h, l, c = _to_arr(highs), _to_arr(lows), _to_arr(closes)
    n = min(len(h), len(l), len(c))
    if n < period:
        return 0.0
    tp = (h[-period:] + l[-period:] + c[-period:]) / 3
    sma_v = tp.mean()
    md = np.abs(tp - sma_v).mean()
    if md == 0:
        return 0.0
    return float((tp[-1] - sma_v) / (0.015 * md))


def mfi(highs: Any, lows: Any, closes: Any, volumes: Any, period: int = 14) -> float:
    h, l, c, v = _to_arr(highs), _to_arr(lows), _to_arr(closes), _to_arr(volumes)
    n = min(len(h), len(l), len(c), len(v))
    if n < period + 1:
        return 50.0
    h, l, c, v = h[-n:], l[-n:], c[-n:], v[-n:]
    tp = (h + l + c) / 3
    mf = tp * v
    pos = neg = 0.0
    for i in range(n - period, n):
        if i == 0:
            continue
        if tp[i] > tp[i - 1]:
            pos += mf[i]
        elif tp[i] < tp[i - 1]:
            neg += mf[i]
    if neg == 0:
        return 100.0
    mr = pos / neg
    return float(100 - 100 / (1 + mr))


def cmf(highs: Any, lows: Any, closes: Any, volumes: Any, period: int = 20) -> float:
    h, l, c, v = _to_arr(highs), _to_arr(lows), _to_arr(closes), _to_arr(volumes)
    n = min(len(h), len(l), len(c), len(v))
    if n < period:
        return 0.0
    h, l, c, v = h[-period:], l[-period:], c[-period:], v[-period:]
    rng = h - l
    rng[rng == 0] = 1
    mfm = ((c - l) - (h - c)) / rng
    mfv = mfm * v
    if v.sum() == 0:
        return 0.0
    return float(mfv.sum() / v.sum())


def vwap(highs: Any, lows: Any, closes: Any, volumes: Any) -> dict:
    h, l, c, v = _to_arr(highs), _to_arr(lows), _to_arr(closes), _to_arr(volumes)
    n = min(len(h), len(l), len(c), len(v))
    if n == 0:
        return {"vwap": 0.0, "pos": "icinde"}
    h, l, c, v = h[-n:], l[-n:], c[-n:], v[-n:]
    tp = (h + l + c) / 3
    if v.sum() == 0:
        return {"vwap": float(tp[-1]), "pos": "icinde"}
    vw = float((tp * v).sum() / v.sum())
    sd = float(np.std(tp - vw))
    last = c[-1]
    if last < vw - 2 * sd: pos = "alt2"
    elif last < vw - sd:   pos = "alt1"
    elif last > vw + 2 * sd: pos = "ust2"
    elif last > vw + sd:     pos = "ust1"
    else:                    pos = "icinde"
    return {"vwap": vw, "pos": pos, "sd": sd}


def parabolic_sar(highs: Any, lows: Any, accel: float = 0.02, max_a: float = 0.2) -> dict:
    h, l = _to_arr(highs), _to_arr(lows)
    n = min(len(h), len(l))
    if n < 5:
        return {"sar": 0.0, "dir": "notr"}
    h, l = h[-n:], l[-n:]
    bull = True
    af = accel
    ep = h[0]
    sar = l[0]
    sars = [sar]
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if bull:
            if l[i] < sar:
                bull = False
                sar = ep
                ep = l[i]
                af = accel
            else:
                if h[i] > ep:
                    ep = h[i]
                    af = min(af + accel, max_a)
        else:
            if h[i] > sar:
                bull = True
                sar = ep
                ep = h[i]
                af = accel
            else:
                if l[i] < ep:
                    ep = l[i]
                    af = min(af + accel, max_a)
        sars.append(sar)
    direction = "yukselis" if bull else "dusus"
    return {"sar": float(sars[-1]), "dir": direction}


def supertrend(highs: Any, lows: Any, closes: Any, period: int = 10, mult: float = 3.0) -> dict:
    h, l, c = _to_arr(highs), _to_arr(lows), _to_arr(closes)
    a = atr(h, l, c, period)
    if a == 0 or len(c) == 0:
        return {"val": 0.0, "dir": "notr"}
    hl2 = (h[-1] + l[-1]) / 2
    upper = hl2 + mult * a
    lower = hl2 - mult * a
    last = c[-1]
    if last > lower and last > hl2:
        return {"val": float(lower), "dir": "yukselis"}
    if last < upper and last < hl2:
        return {"val": float(upper), "dir": "dusus"}
    return {"val": float(hl2), "dir": "notr"}


def hull_ma(closes: Any, period: int = 20) -> dict:
    c = _to_arr(closes)
    if len(c) < period * 2:
        return {"val": 0.0, "dir": "notr"}
    half = period // 2
    sqp = max(2, int(np.sqrt(period)))
    def _wma(arr, p):
        if len(arr) < p:
            return float(arr.mean()) if len(arr) else 0.0
        w = np.arange(1, p + 1)
        return float(np.dot(arr[-p:], w) / w.sum())
    wma_h = _wma(c, half)
    wma_p = _wma(c, period)
    raw = 2 * wma_h - wma_p
    raw_arr = np.full(sqp, raw)
    hma = float(raw_arr.mean())
    direction = "yukselis" if c[-1] > hma else "dusus"
    return {"val": hma, "dir": direction}


def obv(closes: Any, volumes: Any) -> dict:
    c, v = _to_arr(closes), _to_arr(volumes)
    n = min(len(c), len(v))
    if n < 5:
        return {"val": 0.0, "trend": "notr"}
    c, v = c[-n:], v[-n:]
    o = np.zeros(n)
    for i in range(1, n):
        if c[i] > c[i - 1]: o[i] = o[i - 1] + v[i]
        elif c[i] < c[i - 1]: o[i] = o[i - 1] - v[i]
        else: o[i] = o[i - 1]
    if len(o) >= 10:
        trend = "yukselis" if o[-1] > o[-10] else "dusus"
    else:
        trend = "notr"
    return {"val": float(o[-1]), "trend": trend}


def ichimoku(highs: Any, lows: Any, closes: Any) -> dict:
    h, l, c = _to_arr(highs), _to_arr(lows), _to_arr(closes)
    n = min(len(h), len(l), len(c))
    if n < 52:
        return {"sig": "notr", "tenkan": 0.0, "kijun": 0.0}
    h, l, c = h[-n:], l[-n:], c[-n:]
    tenkan = (h[-9:].max() + l[-9:].min()) / 2
    kijun = (h[-26:].max() + l[-26:].min()) / 2
    span_a = (tenkan + kijun) / 2
    span_b = (h[-52:].max() + l[-52:].min()) / 2
    cloud_top = max(span_a, span_b)
    cloud_bot = min(span_a, span_b)
    last = c[-1]
    if last > cloud_top: sig = "ustunde"
    elif last < cloud_bot: sig = "altinda"
    else: sig = "icinde"
    return {"sig": sig, "tenkan": float(tenkan), "kijun": float(kijun),
            "spanA": float(span_a), "spanB": float(span_b)}


def keltner(highs: Any, lows: Any, closes: Any, period: int = 20, mult: float = 2.0) -> dict:
    c = _to_arr(closes)
    if len(c) < period:
        return {"pos": "notr", "upper": 0.0, "lower": 0.0}
    e = float(np.mean(c[-period:]))
    a = atr(highs, lows, closes, period)
    upper = e + mult * a
    lower = e - mult * a
    last = c[-1]
    if last > upper: pos = "ust_bant"
    elif last < lower: pos = "alt_bant"
    else: pos = "icinde"
    return {"pos": pos, "upper": upper, "lower": lower}


def trix(closes: Any, period: int = 15) -> dict:
    c = _to_arr(closes)
    if len(c) < period * 3:
        return {"val": 0.0, "cross": "none"}
    e1 = ema(c, period)
    e2 = ema(e1, period)
    e3 = ema(e2, period)
    if len(e3) < 3 or e3[-2] == 0:
        return {"val": 0.0, "cross": "none"}
    val = (e3[-1] - e3[-2]) / e3[-2] * 100
    prev = (e3[-2] - e3[-3]) / e3[-3] * 100 if e3[-3] != 0 else 0
    cross = "bullish" if prev <= 0 < val else ("bearish" if prev >= 0 > val else "none")
    return {"val": float(val), "cross": cross}


def chande_mo(closes: Any, period: int = 14) -> float:
    c = _to_arr(closes)
    if len(c) < period + 1:
        return 0.0
    diff = np.diff(c[-(period + 1):])
    s_up = diff[diff > 0].sum()
    s_dn = -diff[diff < 0].sum()
    if (s_up + s_dn) == 0:
        return 0.0
    return float(100 * (s_up - s_dn) / (s_up + s_dn))


def awesome_osc(highs: Any, lows: Any) -> dict:
    h, l = _to_arr(highs), _to_arr(lows)
    n = min(len(h), len(l))
    if n < 35:
        return {"val": 0.0, "sig": "notr", "cross": "none"}
    mp = (h[-n:] + l[-n:]) / 2
    sma5  = mp[-5:].mean()
    sma34 = mp[-34:].mean()
    val   = sma5 - sma34
    sma5p  = mp[-6:-1].mean()
    sma34p = mp[-35:-1].mean()
    prev   = sma5p - sma34p
    sig = "yukselis" if val > 0 else "dusus"
    if prev <= 0 < val: cross = "bullish"
    elif prev >= 0 > val: cross = "bearish"
    else: cross = "none"
    return {"val": float(val), "sig": sig, "cross": cross}


def aroon(highs: Any, lows: Any, period: int = 25) -> dict:
    h, l = _to_arr(highs), _to_arr(lows)
    n = min(len(h), len(l))
    if n < period + 1:
        return {"osc": 0.0, "up": 50.0, "down": 50.0}
    h, l = h[-(period + 1):], l[-(period + 1):]
    high_idx = int(np.argmax(h))
    low_idx = int(np.argmin(l))
    up = 100 * high_idx / period
    dn = 100 * low_idx / period
    return {"osc": float(up - dn), "up": float(up), "down": float(dn)}


def ultimate_osc(highs: Any, lows: Any, closes: Any) -> float:
    h, l, c = _to_arr(highs), _to_arr(lows), _to_arr(closes)
    n = min(len(h), len(l), len(c))
    if n < 28:
        return 50.0
    h, l, c = h[-n:], l[-n:], c[-n:]
    bp = c[1:] - np.minimum(l[1:], c[:-1])
    tr = np.maximum(h[1:], c[:-1]) - np.minimum(l[1:], c[:-1])
    def _avg(p):
        if len(bp) < p or tr[-p:].sum() == 0:
            return 50.0
        return bp[-p:].sum() / tr[-p:].sum()
    a7 = _avg(7); a14 = _avg(14); a28 = _avg(28)
    return float(100 * (4 * a7 + 2 * a14 + a28) / 7)


def elder_ray(highs: Any, closes: Any, period: int = 13) -> dict:
    h, c = _to_arr(highs), _to_arr(closes)
    if len(c) < period:
        return {"bull": 0.0, "bear": 0.0}
    e = float(np.mean(c[-period:]))
    return {"bull": float(h[-1] - e), "bear": float((c[-1] if len(c) else 0) - e)}


def detect_rsi_divergence(closes: Any, rsi_vals: Any) -> str:
    c = _to_arr(closes); r = _to_arr(rsi_vals)
    n = min(len(c), len(r))
    if n < 20:
        return "yok"
    c, r = c[-20:], r[-20:]
    p_low = int(np.argmin(c[:10]))
    p_low2 = 10 + int(np.argmin(c[10:]))
    if c[p_low2] < c[p_low] and r[p_low2] > r[p_low]:
        return "boga"
    p_high = int(np.argmax(c[:10]))
    p_high2 = 10 + int(np.argmax(c[10:]))
    if c[p_high2] > c[p_high] and r[p_high2] < r[p_high]:
        return "ayi"
    return "yok"


def vol_ratio(volumes: Any, period: int = 20) -> float:
    v = _to_arr(volumes)
    if len(v) < period + 1:
        return 1.0
    avg = v[-(period + 1):-1].mean()
    if avg == 0:
        return 1.0
    return float(v[-1] / avg)


def pos_52wk(closes: Any) -> float:
    c = _to_arr(closes)
    if len(c) == 0:
        return 50.0
    window = c[-min(252, len(c)):]
    hh, ll = window.max(), window.min()
    if hh - ll == 0:
        return 50.0
    return float(100 * (c[-1] - ll) / (hh - ll))


def fib_pos(closes: Any) -> float:
    """52 hafta arasındaki fib pozisyon (basitleştirilmiş)."""
    return pos_52wk(closes)


def roc(closes: Any, period: int = 5) -> float:
    """Rate of Change — PHP calculateROC karşılığı. Yüzde değişim."""
    c = _to_arr(closes)
    if len(c) < period + 1:
        return 0.0
    prev = c[-(period + 1)]
    if prev == 0:
        return 0.0
    return float((c[-1] - prev) / prev * 100)


def vol_momentum(volumes: Any, fast: int = 5, slow: int = 20) -> float:
    """Hacim momentum — son dönem hacmi geçmiş döneme kıyasla değişim oranı.
    PHP calculateVolumeMomentum karşılığı. > 0 yükseliş, < 0 düşüş.
    """
    v = _to_arr(volumes)
    if len(v) < slow + 1:
        return 0.0
    fast_avg = v[-fast:].mean() if v[-fast:].size else 0.0
    slow_avg = v[-slow:-fast].mean() if v[-slow:-fast].size else 0.0
    if slow_avg == 0:
        return 0.0
    return float((fast_avg - slow_avg) / slow_avg)


def elder_signal(highs: Any, closes: Any, period: int = 13) -> str:
    """Elder Ray sinyali: guclu_boga / guclu_ayi / boga / ayi / notr.
    PHP elderData['signal'] karşılığı.
    """
    h, c = _to_arr(highs), _to_arr(closes)
    if len(c) < period:
        return "notr"
    ema = float(np.mean(c[-period:]))
    bull = float(h[-1] - ema)
    bear = float(c[-1] - ema)
    if bull > 0 and bear > 0:
        return "guclu_boga"
    if bull > 0 and bear <= 0:
        return "boga"
    if bull <= 0 and bear < 0:
        return "guclu_ayi"
    if bull <= 0 and bear >= 0:
        return "ayi"
    return "notr"


def detect_macd_divergence(closes: Any, period: int = 25) -> str:
    """Basit MACD Diverjansı tespiti — boga/ayi/yok.
    PHP divergence['macd'] karşılığı.
    """
    c = _to_arr(closes)
    if len(c) < period + 26:
        return "yok"
    # MACD histogram son 25 mumu
    def _ema(arr, n):
        k = 2 / (n + 1)
        e = arr[0]
        for x in arr[1:]:
            e = x * k + e * (1 - k)
        return e
    hist = []
    for i in range(period):
        sl = c[-(period - i + 26):-(period - i) if (period - i) > 0 else None]
        if len(sl) < 26:
            hist.append(0.0)
            continue
        fast = _ema(sl, 12)
        slow = _ema(sl, 26)
        sig_arr = [fast - slow]
        hist.append(fast - slow - _ema(sig_arr, 9))
    prices = list(c[-period:])
    mid = period // 2
    p1_low = int(np.argmin(prices[:mid]))
    p2_low = mid + int(np.argmin(prices[mid:]))
    if prices[p2_low] < prices[p1_low] and hist[p2_low] > hist[p1_low] + 0.00001:
        return "boga"
    p1_high = int(np.argmax(prices[:mid]))
    p2_high = mid + int(np.argmax(prices[mid:]))
    if prices[p2_high] > prices[p1_high] and hist[p2_high] < hist[p1_high] - 0.00001:
        return "ayi"
    return "yok"


# ===========================================================================
# PHP v35 birebir port: Donchian, Pivot, Fibonacci, PVT
# ===========================================================================
def calculate_donchian_breakout(highs: Any, lows: Any, closes: Any,
                                period: int = 20) -> dict:
    """PHP calculateDonchianBreakout (index.php:7941) birebir."""
    h = list(map(float, highs)); l = list(map(float, lows)); c = list(map(float, closes))
    n = len(c)
    if n < period + 2:
        return {"breakout": "none", "upper": 0.0, "lower": 0.0, "mid": 0.0}
    hh = h[-(period + 1):-1]
    ll = l[-(period + 1):-1]
    upper = max(hh); lower = min(ll); cur = c[-1]
    if cur >= upper:   bo = "yukari"
    elif cur <= lower: bo = "asagi"
    else:              bo = "none"
    return {"breakout": bo, "upper": round(upper, 2), "lower": round(lower, 2),
            "mid": round((upper + lower) / 2, 2)}


def calculate_pivot_points(highs: Any, lows: Any, closes: Any) -> dict:
    """PHP calculatePivotPoints (index.php:8093) — klasik pivot S1-R3."""
    h = list(map(float, highs)); l = list(map(float, lows)); c = list(map(float, closes))
    n = len(c)
    z = {"pp": 0, "r1": 0, "r2": 0, "r3": 0, "s1": 0, "s2": 0, "s3": 0}
    if n < 2: return z
    ph, pl, pc = h[-2], l[-2], c[-2]
    if ph <= 0 or pl <= 0 or pc <= 0: return z
    pp = (ph + pl + pc) / 3
    r1 = 2 * pp - pl
    r2 = pp + (ph - pl)
    r3 = ph + 2 * (pp - pl)
    s1 = 2 * pp - ph
    s2 = pp - (ph - pl)
    s3 = pl - 2 * (ph - pp)
    return {"pp": round(pp, 4), "r1": round(r1, 4), "r2": round(r2, 4),
            "r3": round(r3, 4), "s1": round(s1, 4), "s2": round(s2, 4),
            "s3": round(s3, 4)}


def pivot_action(cur_price: float, piv: dict) -> str:
    """Cari fiyat pivot seviyelerine göre: 'r_break', 's_bounce', 'none'."""
    if not piv or piv.get("pp", 0) <= 0: return "none"
    cp = float(cur_price)
    if cp >= piv["r1"]: return "r_break"
    if cp <= piv["s1"]: return "s_bounce"
    return "none"


def calculate_fibonacci_levels(highs: Any, lows: Any, period: int = 100) -> dict:
    """PHP calculateFibonacciLevels (index.php:9295) birebir."""
    h = list(map(float, highs)); l = list(map(float, lows))
    n = len(h)
    if n < 10: return {}
    sh = h[-min(period, n):]; sl = l[-min(period, n):]
    hi = max(sh); lo = min(sl); diff = hi - lo
    if diff <= 0: return {}
    return {
        "high": round(hi, 2), "low": round(lo, 2),
        "fib236": round(hi - 0.236 * diff, 2),
        "fib382": round(hi - 0.382 * diff, 2),
        "fib500": round(hi - 0.500 * diff, 2),
        "fib618": round(hi - 0.618 * diff, 2),
        "fib786": round(hi - 0.786 * diff, 2),
    }


def fib_position(cur_price: float, fib: dict) -> float:
    """Cari fiyatın hi-lo aralığındaki yüzdesi (0-100)."""
    if not fib: return 50.0
    hi = float(fib.get("high", 0)); lo = float(fib.get("low", 0))
    if hi <= lo: return 50.0
    cp = float(cur_price)
    return round(max(0.0, min(100.0, (cp - lo) / (hi - lo) * 100)), 1)


def calculate_pvt(closes: Any, volumes: Any, lookback: int = 20) -> str:
    """PHP calculatePVT (index.php:9318) — Price Volume Trend artis/dusus/notr."""
    c = list(map(float, closes)); v = list(map(float, volumes))
    n = len(c)
    if n < lookback + 1: return "notr"
    pvt = 0.0; arr = []
    for i in range(1, n):
        pc = c[i - 1]
        if pc > 0:
            pvt += ((c[i] - pc) / pc) * v[i] if i < len(v) else 0.0
        arr.append(pvt)
    if len(arr) < lookback * 2: return "notr"
    recent = arr[-lookback:]
    older  = arr[-lookback * 2:-lookback]
    if not older: return "notr"
    avg_r = sum(recent) / len(recent)
    avg_o = sum(older) / len(older)
    return "artis" if avg_r > avg_o else "dusus"


def volume_momentum(highs: Any = None, lows: Any = None, closes: Any = None,
                    volumes: Any = None, period: int = 5) -> float:
    """PHP calculateVolumeMomentum birebir — son N bar hacmi vs önceki N bar."""
    v = _to_arr(volumes if volumes is not None else closes)
    n = len(v)
    if n < period * 2: return 0.0
    rV = float(v[-period:].sum())
    pV = float(v[-period * 2:-period].sum())
    return round((rV - pV) / pV * 100, 1) if pV > 0 else 0.0


def obv_trend(closes: Any, volumes: Any, lookback: int = 20) -> str:
    """PHP calculateOBVTrend — son lookback'in toplamı ile bir önceki lookback toplamı."""
    c, v = _to_arr(closes), _to_arr(volumes)
    n = min(len(c), len(v))
    if n < lookback + 1: return "notr"
    c, v = c[-n:], v[-n:]
    o = np.zeros(n)
    for i in range(1, n):
        if c[i] > c[i - 1]: o[i] = o[i - 1] + v[i]
        elif c[i] < c[i - 1]: o[i] = o[i - 1] - v[i]
        else: o[i] = o[i - 1]
    obv_arr = o[1:]  # PHP $obvArr[i-1]'den başlar
    if len(obv_arr) < lookback: return "notr"
    recent = obv_arr[-lookback:]
    older  = obv_arr[-lookback * 2:-lookback] if len(obv_arr) >= lookback * 2 else None
    if older is None or len(older) == 0: return "notr"
    return "artis" if recent.sum() > older.sum() else "dusus"


# ─────────────────────────────────────────────────────────────────────────────
# PHP-uyumlu isim aliasları — index.php'deki camelCase isimleri Python tarafında
# da aynı şekilde erişilebilir kılar. Hepsi mevcut snake_case fonksiyonlara
# referans verir; ek logic veya kopya yoktur.
# ─────────────────────────────────────────────────────────────────────────────

def calculate_ema(closes: list[float], period: int) -> float:
    """PHP calculateEMA — son EMA değerini float olarak döner."""
    a = ema(closes, period)
    return float(a[-1]) if len(a) else 0.0

calc_ema                       = calculate_ema
calculate_rsi                  = rsi
calculate_macd                 = macd
calculate_atr                  = atr
calculate_adx                  = adx
calculate_stoch_rsi            = stoch_rsi
calculate_williams_r           = williams_r
calculate_cci                  = cci
calculate_mfi                  = mfi
calculate_cmf                  = cmf
calculate_vwap                 = vwap
calculate_parabolic_sar        = parabolic_sar
calculate_supertrend           = supertrend
calculate_hull_ma              = hull_ma
calculate_ichimoku             = ichimoku
calculate_keltner              = keltner
calculate_trix                 = trix
calculate_cmo                  = chande_mo
calculate_awesome_oscillator   = awesome_osc
calculate_aroon                = aroon
calculate_ultimate_oscillator  = ultimate_osc
calculate_elder_ray            = elder_ray
calculate_volume_ratio         = vol_ratio
calculate_52wk_position        = pos_52wk
calculate_roc                  = roc
calculate_volume_momentum      = volume_momentum
calculate_obv_trend            = obv_trend
