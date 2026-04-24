"""Beyin tabanlı confluence ve zaman bonusları."""

from __future__ import annotations

from ..brain import brain_load
from ..utils import now_tr


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
