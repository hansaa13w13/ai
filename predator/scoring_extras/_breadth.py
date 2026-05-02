"""Piyasa genişliği (market breadth) hesaplaması ve cache — v42 genişletilmiş."""

from __future__ import annotations

from .. import config
from ..utils import load_json


_BREADTH_CACHE: dict | None = None


def get_market_breadth() -> dict:
    """Kapsamlı piyasa genişliği analizi — v42: RSI/SMC/OFI breadth eklendi."""
    global _BREADTH_CACHE
    if _BREADTH_CACHE is not None:
        return _BREADTH_CACHE
    data = load_json(config.ALLSTOCKS_CACHE, {}) or {}
    stocks = data.get("stocks") or []
    if not stocks:
        return {}
    total = len(stocks)

    # Temel sayaçlar
    rising = falling = above_ema = below_ema = 0
    macd_bull = macd_bear = vol_surge = rsi_oversold = 0
    cmf_pos = sar_up = 0

    # v42: Genişletilmiş sayaçlar
    rsi_above50 = rsi_strong_bull = 0          # RSI genişliği
    smc_bull = smc_bear = 0                     # SMC genişliği
    ofi_buy = ofi_sell = 0                      # OFI akışı
    bb_squeeze_cnt = 0                          # BB sıkışma sayısı
    strong_vol = 0                              # Güçlü hacim (≥3x)
    adx_strong = 0                              # Güçlü ADX trendi (≥25)
    supertrend_bull = 0                         # Supertrend yükselen
    net_change = 0.0
    rsi_sum = 0.0
    atr_pct_sum = 0.0
    atr_pct_cnt = 0

    for s in stocks:
        r = float(s.get("gunlukDegisim") or s.get("ret1d") or 0)
        net_change += r
        if r > 0:  rising  += 1
        elif r < 0: falling += 1

        t = s.get("trend") or ""
        if t == "Yukselis": above_ema += 1
        elif t == "Dusus":  below_ema += 1

        mc = s.get("macdCross") or ""
        if mc == "golden": macd_bull += 1
        elif mc == "death": macd_bear += 1

        vr = float(s.get("volRatio") or 1)
        if vr >= 3.0: strong_vol += 1
        if vr >= 2.0: vol_surge  += 1

        rsi_v = float(s.get("rsi") or 50)
        rsi_sum += rsi_v
        if rsi_v < 30:  rsi_oversold  += 1
        if rsi_v > 50:  rsi_above50   += 1
        if rsi_v > 60:  rsi_strong_bull += 1

        if float(s.get("cmf") or 0) > 0.05:  cmf_pos += 1
        if (s.get("sarDir") or "") == "yukselis": sar_up += 1

        # v42: SMC
        smcb = s.get("smcBias") or ""
        if smcb == "bullish": smc_bull += 1
        elif smcb == "bearish": smc_bear += 1

        # v42: OFI
        ofi = s.get("ofiSig") or ""
        if ofi in ("alis", "guclu_alis"):   ofi_buy  += 1
        elif ofi in ("satis", "guclu_satis"): ofi_sell += 1

        # v42: BB sıkışma
        if s.get("bbSqueeze"): bb_squeeze_cnt += 1

        # v42: ADX güçlü trend
        if float(s.get("adxVal") or 0) >= 25: adx_strong += 1

        # v42: Supertrend
        if (s.get("supertrendDir") or "") == "yukselis": supertrend_bull += 1

        # v42: ATR volatilite
        atr_v = float(s.get("atr14") or s.get("atr") or 0)
        price = float(s.get("guncel") or s.get("sma50") or 0)
        if atr_v > 0 and price > 0:
            atr_pct_sum += atr_v / price * 100
            atr_pct_cnt += 1

    adv_decline   = rising - falling
    breadth_pct   = round(rising / total * 100, 1) if total else 50.0
    ema_breadth   = round(above_ema / total * 100, 1) if total else 50.0
    macd_breadth  = round(macd_bull / total * 100, 1) if total else 50.0
    cmf_breadth   = round(cmf_pos / total * 100, 1) if total else 50.0
    avg_change    = round(net_change / total, 2) if total else 0.0
    avg_rsi       = round(rsi_sum / total, 1) if total else 50.0

    # v42: Yeni breadth metrikleri
    rsi_breadth   = round(rsi_above50 / total * 100, 1) if total else 50.0
    smc_breadth   = round(smc_bull / total * 100, 1) if total else 50.0
    ofi_breadth   = round(ofi_buy / total * 100, 1) if total else 50.0
    st_breadth    = round(supertrend_bull / total * 100, 1) if total else 50.0
    avg_atr_pct   = round(atr_pct_sum / atr_pct_cnt, 2) if atr_pct_cnt else 0.0

    # v42: Bileşik sağlık skoru — 6 katmanlı ağırlıklı
    health = round(
        breadth_pct  * 0.22 +
        ema_breadth  * 0.18 +
        macd_breadth * 0.15 +
        cmf_breadth  * 0.15 +
        rsi_breadth  * 0.15 +
        smc_breadth  * 0.08 +
        ofi_breadth  * 0.07,
        1
    )

    # Etiketler
    if   health >= 72: label, color, sig = "GÜÇLÜ",   "#00ff9d", "AL"
    elif health >= 58: label, color, sig = "ORTA",    "#ffea00", "BEKLE"
    elif health >= 42: label, color, sig = "ZAYIF",   "#ff9900", "BEKLE"
    else:              label, color, sig = "KRİTİK",  "#ff003c", "SAT"
    if   health >= 65: sig = "AL"
    elif health >= 45: sig = "BEKLE"
    else:              sig = "SAT"

    # v42: Piyasa korku/açgözlülük skoru (0=korku, 100=açgözlülük)
    fear_greed = round(
        breadth_pct * 0.30 +
        (100 - avg_atr_pct * 10) * 0.20 +
        ema_breadth  * 0.25 +
        smc_breadth  * 0.25,
        1
    )
    fear_greed = max(0.0, min(100.0, fear_greed))
    if   fear_greed >= 75: fg_label = "Aşırı Açgözlülük"
    elif fear_greed >= 60: fg_label = "Açgözlülük"
    elif fear_greed >= 40: fg_label = "Nötr"
    elif fear_greed >= 25: fg_label = "Korku"
    else:                  fg_label = "Aşırı Korku"

    res = {
        "total": total,
        "rising": rising, "falling": falling,
        "breadth_pct": breadth_pct, "ema_breadth": ema_breadth,
        "macd_breadth": macd_breadth, "cmf_breadth": cmf_breadth,
        "rsi_breadth": rsi_breadth, "smc_breadth": smc_breadth,
        "ofi_breadth": ofi_breadth, "st_breadth": st_breadth,
        "vol_surge_cnt": vol_surge, "strong_vol_cnt": strong_vol,
        "oversold_cnt": rsi_oversold, "rsi_strong_bull": rsi_strong_bull,
        "sar_up_cnt": sar_up, "adx_strong_cnt": adx_strong,
        "bb_squeeze_cnt": bb_squeeze_cnt, "supertrend_bull": supertrend_bull,
        "smc_bull_cnt": smc_bull, "smc_bear_cnt": smc_bear,
        "ofi_buy_cnt": ofi_buy, "ofi_sell_cnt": ofi_sell,
        "adv_decline": adv_decline, "avg_change": avg_change,
        "avg_rsi": avg_rsi, "avg_atr_pct": avg_atr_pct,
        "health": health, "health_label": label,
        "health_color": color, "signal": sig,
        "fear_greed": fear_greed, "fear_greed_label": fg_label,
    }
    _BREADTH_CACHE = res
    return res


def reset_breadth_cache() -> None:
    global _BREADTH_CACHE
    _BREADTH_CACHE = None
