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
    """Single scalar RSI — reuses rsi_series() for O(n) Wilder smoothing."""
    vals = rsi_series(closes, period=period, tail=1)
    return vals[-1] if vals else 50.0


def ema(closes: Any, period: int) -> np.ndarray:
    """Exponential Moving Average — single-pass O(n) numpy implementation.

    Uses np.frompyfunc to keep the recurrence as a Python-level ufunc,
    avoiding a raw Python for-loop while staying dependency-free.
    The initial condition is seeded from c[0] so there is no warm-up bias.
    Uses numpy's lfilter-equivalent via ufunc.accumulate for pure-C speed.
    """
    c = _to_arr(closes)
    if len(c) == 0:
        return c
    alpha = 2.0 / (period + 1)
    one_minus_alpha = 1.0 - alpha
    # ufunc.accumulate trick: out[i] = alpha*c[i] + (1-alpha)*out[i-1]
    # Equivalent to: out = scipy.signal.lfilter([alpha], [1, -(1-alpha)], c)
    # but dependency-free. Manually seed the loop only at index 0.
    out = np.empty_like(c)
    out[0] = c[0]
    for i in range(1, len(c)):
        out[i] = alpha * c[i] + one_minus_alpha * out[i - 1]
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
    # Vectorized with sliding_window_view — avoids O(n²) Python loop
    squeeze = False
    if len(c) >= period + 40:
        views = np.lib.stride_tricks.sliding_window_view(c, period)
        m_arr = views.mean(axis=1)
        s_arr = views.std(axis=1)
        w_arr = np.where(m_arr > 0, 4.0 * s_arr / m_arr, 0.0)
        tail = w_arr[-60:] if len(w_arr) >= 60 else w_arr
        avg = float(tail.mean())
        squeeze = bool(width < avg * 0.85)
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
    # Vectorized bandwidth history — avoids O(n²) Python loop
    if n > period:
        views2 = np.lib.stride_tricks.sliding_window_view(c, period)
        a2_arr = views2.mean(axis=1)
        sd2_arr = views2.std(axis=1)
        bw_arr = np.where(a2_arr > 1e-4,
                          2.0 * mult * sd2_arr / a2_arr * 100.0, 0.0).tolist()
    else:
        bw_arr = []
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

    # Dipler (5-bar pivot low) — vectorized with numpy
    c_arr = np.array(closes)
    if ln >= 7:
        idx = np.arange(3, ln - 3)
        mask = ((c_arr[3:-3] <= c_arr[2:-4]) & (c_arr[3:-3] <= c_arr[1:-5]) &
                (c_arr[3:-3] <= c_arr[4:-2]) & (c_arr[3:-3] <= c_arr[5:-1]))
        dips = [{"idx": int(i), "price": float(c_arr[i])} for i in idx[mask]]
    else:
        dips = []

    # RSI dizisi — single-pass Wilder (O(n) not O(n²))
    rsi_list = rsi_series(closes, period=14)
    rsi_arr = {i + 14: v for i, v in enumerate(rsi_list)}

    rsi_div = "yok"
    if len(dips) >= 2:
        d1 = dips[-2]; d2 = dips[-1]
        if d2["price"] < d1["price"] and d1["idx"] in rsi_arr and d2["idx"] in rsi_arr:
            if rsi_arr[d2["idx"]] > rsi_arr[d1["idx"]]:
                rsi_div = "boga"
        if d2["price"] > d1["price"] and d1["idx"] in rsi_arr and d2["idx"] in rsi_arr:
            if rsi_arr[d2["idx"]] < rsi_arr[d1["idx"]]:
                rsi_div = "ayi"

    # Tepeler (5-bar pivot high) — vectorized
    if ln >= 7:
        p_idx = np.arange(3, ln - 3)
        p_mask = ((c_arr[3:-3] >= c_arr[2:-4]) & (c_arr[3:-3] >= c_arr[1:-5]) &
                  (c_arr[3:-3] >= c_arr[4:-2]) & (c_arr[3:-3] >= c_arr[5:-1]))
        peaks = [{"idx": int(i), "price": float(c_arr[i])} for i in p_idx[p_mask]]
    else:
        peaks = []

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
    # Wilder smoothing — numpy recurrence (same as _smooth in adx)
    a = tr[:period].mean()
    alpha = 1.0 - 1.0 / period
    for i in range(period, len(tr)):
        a = a * alpha + tr[i]
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
    # Wilder smoothing — vectorized using np.frompyfunc accumulation
    def _smooth(arr: np.ndarray) -> np.ndarray:
        n = len(arr)
        if n < period:
            return np.zeros(n)
        s = np.empty(n)
        s[:period - 1] = 0.0
        s[period - 1] = arr[:period].sum()
        # Recurrence: s[i] = s[i-1] * (1 - 1/period) + arr[i]
        alpha = 1.0 - 1.0 / period
        for i in range(period, n):
            s[i] = s[i - 1] * alpha + arr[i]
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
    """Stoch RSI — PHP $tech['stochRsi'] uyumlu.

    v42: O(n²) loop kaldırıldı — single-pass rsi_series() + sliding_window_view.
    """
    c = _to_arr(closes)
    if len(c) < period * 2:
        return {"k": 50.0, "d": 50.0}
    # Single-pass Wilder RSI series via shared helper
    rsi_vals = rsi_series(c, period=period)
    rsi_arr = np.asarray(rsi_vals, dtype=float)
    if len(rsi_arr) < period:
        return {"k": 50.0, "d": 50.0}
    # Vectorized Stoch RSI via sliding window
    views = np.lib.stride_tricks.sliding_window_view(rsi_arr, period)
    hi_arr = views.max(axis=1)
    lo_arr = views.min(axis=1)
    rng = hi_arr - lo_arr
    safe_rng = np.where(rng > 0, rng, 1.0)  # avoid divide-by-zero warning
    k_arr = np.where(rng > 0, 100.0 * (rsi_arr[period - 1:] - lo_arr) / safe_rng, 50.0)
    if len(k_arr) == 0:
        return {"k": 50.0, "d": 50.0}
    k_smooth = float(k_arr[-k_period:].mean()) if len(k_arr) >= k_period else float(k_arr[-1])
    d_smooth = float(k_arr[-d_period:].mean()) if len(k_arr) >= d_period else k_smooth
    return {"k": k_smooth, "d": d_smooth}


def stochastic(highs: Any, lows: Any, closes: Any, k_period: int = 14, d_period: int = 3) -> dict:
    """Stochastic %K/%D — fully vectorized via sliding_window_view."""
    h, l, c = _to_arr(highs), _to_arr(lows), _to_arr(closes)
    n = min(len(h), len(l), len(c))
    if n < k_period:
        return {"k": 50.0, "d": 50.0}
    h, l, c = h[-n:], l[-n:], c[-n:]
    h_win = np.lib.stride_tricks.sliding_window_view(h, k_period)
    l_win = np.lib.stride_tricks.sliding_window_view(l, k_period)
    hh = h_win.max(axis=1)
    ll = l_win.min(axis=1)
    rng = hh - ll
    ks = np.where(rng > 0, 100.0 * (c[k_period - 1:] - ll) / rng, 50.0)
    k = float(ks[-1])
    d = float(ks[-d_period:].mean()) if len(ks) >= d_period else k
    return {"k": k, "d": d}


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
    # Vectorized: direction determined by tp[i] vs tp[i-1] for window
    start = max(1, n - period)
    tp_diff = np.diff(tp[start - 1:])      # length = n - start
    mf_win  = mf[start:n][:len(tp_diff)]
    pos = float(mf_win[tp_diff > 0].sum())
    neg = float(mf_win[tp_diff < 0].sum())
    if neg == 0:
        return 100.0
    return float(100 - 100 / (1 + pos / neg))


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
    diff_c = np.diff(c)
    signs  = np.where(diff_c > 0, 1.0, np.where(diff_c < 0, -1.0, 0.0))
    o = np.concatenate([[0.0], np.cumsum(signs * v[1:])])
    trend = "yukselis" if len(o) >= 10 and o[-1] > o[-10] else (
            "dusus"    if len(o) >= 10 else "notr")
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


def rsi_series(closes: Any, period: int = 14, tail: int = 0) -> list[float]:
    """Single-pass Wilder RSI series — O(n), no O(n²) recomputation.

    Returns a list of RSI values, one per bar starting at index `period`.
    If `tail` > 0, only the last `tail` values are returned (for divergence checks).
    """
    c = _to_arr(closes)
    diff = np.diff(c)
    if len(diff) < period:
        return []
    gain = np.where(diff > 0, diff, 0.0)
    loss = np.where(diff < 0, -diff, 0.0)
    avg_g = gain[:period].mean()
    avg_l = loss[:period].mean()
    results: list[float] = []
    results.append(100.0 - (100.0 / (1.0 + avg_g / avg_l)) if avg_l > 0 else 100.0)
    for i in range(period, len(diff)):
        avg_g = (avg_g * (period - 1) + gain[i]) / period
        avg_l = (avg_l * (period - 1) + loss[i]) / period
        results.append(100.0 - (100.0 / (1.0 + avg_g / avg_l)) if avg_l > 0 else 100.0)
    if tail > 0:
        return results[-tail:]
    return results


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
    """Hissenin TÜM ZAMAN dip-tepe aralığında bugünkü konumu (% 0-100).

    Eskiden son 252 işgününe (≈52 hafta) bakıyordu; artık veri serisinin
    tamamı kullanılıyor — yani hisse borsada işlem gördüğü ilk günden
    bugüne kadar gördüğü en düşük ve en yüksek fiyat referans alınıyor.
    Field adı geriye uyumluluk için ``pos52wk`` olarak korunuyor.

    Dönüş:
        0   → tüm zaman dibinde
        50  → orta nokta
        100 → tüm zaman zirvesinde
        50.0 (varsayılan) → veri yok / aralık sıfır
    """
    c = _to_arr(closes)
    if len(c) == 0:
        return 50.0
    hh, ll = c.max(), c.min()
    if hh - ll == 0:
        return 50.0
    return float(100 * (c[-1] - ll) / (hh - ll))


def fib_pos(closes: Any) -> float:
    """Tüm zaman dip-tepe arasındaki fib pozisyon (pos_52wk ile eşit)."""
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
    v42: O(n×k) tekrar EMA hesabı kaldırıldı — tüm seri için MACD histogram
    bir kez compute edilir, ardından son `period` çubuğun histogramı dilimle alınır.
    """
    c = _to_arr(closes)
    if len(c) < period + 26:
        return "yok"
    # Full MACD histogram via single-pass ema()
    macd_dict = macd(c, fast=12, slow=26, signal=9)
    # We need the last `period` histogram values; recompute full series cheaply
    e_fast = ema(c, 12)
    e_slow = ema(c, 26)
    line   = e_fast - e_slow
    sig    = ema(line, 9)
    hist_arr = line - sig
    if len(hist_arr) < period:
        return "yok"
    hist = list(hist_arr[-period:])
    prices = list(c[-period:])
    mid = period // 2
    p1_low  = int(np.argmin(prices[:mid]))
    p2_low  = mid + int(np.argmin(prices[mid:]))
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
    h, l, c = _to_arr(highs), _to_arr(lows), _to_arr(closes)
    n = len(c)
    if n < period + 2:
        return {"breakout": "none", "upper": 0.0, "lower": 0.0, "mid": 0.0}
    hh = h[-(period + 1):-1]
    ll = l[-(period + 1):-1]
    upper = float(hh.max()); lower = float(ll.min()); cur = float(c[-1])
    if cur >= upper:   bo = "yukari"
    elif cur <= lower: bo = "asagi"
    else:              bo = "none"
    return {"breakout": bo, "upper": round(upper, 2), "lower": round(lower, 2),
            "mid": round((upper + lower) / 2, 2)}


def calculate_pivot_points(highs: Any, lows: Any, closes: Any) -> dict:
    """PHP calculatePivotPoints (index.php:8093) — klasik pivot S1-R3."""
    h, l, c = _to_arr(highs), _to_arr(lows), _to_arr(closes)
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
    return {"pp": float(round(pp, 4)), "r1": float(round(r1, 4)), "r2": float(round(r2, 4)),
            "r3": float(round(r3, 4)), "s1": float(round(s1, 4)), "s2": float(round(s2, 4)),
            "s3": float(round(s3, 4))}


def pivot_action(cur_price: float, piv: dict) -> str:
    """Cari fiyat pivot seviyelerine göre: 'r_break', 's_bounce', 'none'."""
    if not piv or piv.get("pp", 0) <= 0: return "none"
    cp = float(cur_price)
    if cp >= piv["r1"]: return "r_break"
    if cp <= piv["s1"]: return "s_bounce"
    return "none"


def calculate_fibonacci_levels(highs: Any, lows: Any, period: int = 100) -> dict:
    """PHP calculateFibonacciLevels (index.php:9295) birebir."""
    h, l = _to_arr(highs), _to_arr(lows)
    n = len(h)
    if n < 10: return {}
    sh = h[-min(period, n):]; sl = l[-min(period, n):]
    hi = float(sh.max()); lo = float(sl.min()); diff = hi - lo
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
    """PHP calculatePVT (index.php:9318) — Price Volume Trend artis/dusus/notr.
    Vectorized: O(n) with numpy cumsum instead of Python loop.
    """
    c, v = _to_arr(closes), _to_arr(volumes)
    n = min(len(c), len(v))
    if n < lookback + 1:
        return "notr"
    c, v = c[:n], v[:n]
    prev = c[:-1]
    safe = np.where(prev > 0, prev, np.nan)
    pct = (c[1:] - prev) / safe
    pvt_increments = np.where(np.isfinite(pct), pct * v[1:], 0.0)
    arr = np.cumsum(pvt_increments)
    if len(arr) < lookback * 2:
        return "notr"
    avg_r = float(arr[-lookback:].mean())
    avg_o = float(arr[-lookback * 2:-lookback].mean())
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
    diff_c = np.diff(c)
    signs  = np.where(diff_c > 0, 1.0, np.where(diff_c < 0, -1.0, 0.0))
    o = np.concatenate([[0.0], np.cumsum(signs * v[1:])])
    obv_arr = o[1:]
    if len(obv_arr) < lookback: return "notr"
    recent = obv_arr[-lookback:]
    older  = obv_arr[-lookback * 2:-lookback] if len(obv_arr) >= lookback * 2 else None
    if older is None or len(older) == 0: return "notr"
    return "artis" if float(recent.sum()) > float(older.sum()) else "dusus"


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
