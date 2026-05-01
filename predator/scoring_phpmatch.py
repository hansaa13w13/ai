"""PHP v35 calculateAlPuani + calculateAISmartScore BİREBİR portu.

Bu dosya, index.php:10563-11031 (calculateAlPuani) ve index.php:10110-10359
(calculateAISmartScore) fonksiyonlarını Python stock dict'i üzerinden
aynı eşik/çarpan/bonus değerleriyle yeniden üretir.
Amaç: PHP top-10 sıralaması ile Python top-25 sıralamasının birebir
eşleşmesi.
"""
from __future__ import annotations
from typing import Any

from . import config
from .scoring import _get_sector_thresholds, calculate_consensus_multiplier


def _n(x: Any, default: float = 0.0) -> float:
    try:
        if x is None: return default
        return float(x)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# calculateAlPuani — PHP index.php:10563 birebir
# ─────────────────────────────────────────────────────────────────────────────
def _adapt_stock_fields(stock: dict, fiyat: float) -> None:
    """v37.1: Skor fonksiyonlarının beklediği ama scan'in farklı isim/yapıda
    sakladığı alanları normalize eder. (Sessiz puan kayıplarını önler.)"""
    # macdVal: scan stores nested macd.macd
    if "macdVal" not in stock:
        m = stock.get("macd") or {}
        if isinstance(m, dict): stock["macdVal"] = _n(m.get("macd"))
    # diPlus / diMinus: scan stores nested adx.plusDI / adx.minusDI
    if "diPlus" not in stock or "diMinus" not in stock:
        a = stock.get("adx") or {}
        if isinstance(a, dict):
            stock.setdefault("diPlus",  _n(a.get("plusDI")))
            stock.setdefault("diMinus", _n(a.get("minusDI")))
    # halkAciklik typo (scan: halkakAciklik)
    if "halkAciklik" not in stock and "halkakAciklik" in stock:
        stock["halkAciklik"] = stock["halkakAciklik"]
    # ichiBullish: derive from ichimoku structure
    if "ichiBullish" not in stock:
        ic = stock.get("ichimoku") or {}
        if isinstance(ic, dict):
            sa = _n(ic.get("spanA")); sb = _n(ic.get("spanB"))
            kt = _n(ic.get("kumoTop"))
            stock["ichiBullish"] = bool(sa > sb and fiyat > 0 and kt > 0 and fiyat > kt)
    # sup: en yakın altta olan clustered destek
    if "sup" not in stock and fiyat > 0:
        cl = stock.get("clusteredLevels") or []
        if isinstance(cl, list):
            below = []
            for lv in cl:
                if not isinstance(lv, dict): continue
                p = _n(lv.get("price") or lv.get("level") or lv.get("p"))
                if 0 < p < fiyat: below.append(p)
            if below: stock["sup"] = max(below)


def calculate_al_puani(stock: dict) -> int:
    fiyat = _n(stock.get("guncel"))
    adil  = _n(stock.get("adil"))
    if fiyat <= 0: return 0
    _adapt_stock_fields(stock, fiyat)
    sektor = stock.get("sektor") or config.SEKTOR_GENEL
    st = _get_sector_thresholds(sektor)
    rsi_mult = float(st.get("rsi_bonus_mult", 1.0))
    fk_ucuz   = float(st.get("fk_ucuz", 10))
    fk_pahali = float(st.get("fk_pahali", 25))

    score = 0

    # ── Adil Değer (Graham) ─────────────────────────────────────────────
    if adil > 0:
        pot = (adil - fiyat) / fiyat
        if   pot > 1.0:  score += 50
        elif pot > 0.5:  score += 40
        elif pot > 0.3:  score += 30
        elif pot > 0.1:  score += 18
        elif pot > 0.0:  score += 8
        elif pot < -0.4: score -= 25
        elif pot < -0.2: score -= 15
        elif pot < 0.0:  score -= 5

    # ── RSI — sektör çarpanı ────────────────────────────────────────────
    rsi = _n(stock.get("rsi"), 50)
    if   rsi < 15: score += round(28 * rsi_mult)
    elif rsi < 20: score += round(22 * rsi_mult)
    elif rsi < 30: score += round(17 * rsi_mult)
    elif rsi < 40: score += round(10 * rsi_mult)
    elif rsi > 85: score -= 22
    elif rsi > 75: score -= 14
    elif rsi > 65: score -= 6

    # ── MACD ────────────────────────────────────────────────────────────
    mcross = stock.get("macdCross", "none")
    mhist  = _n(stock.get("macdHist"))
    mval   = _n(stock.get("macdVal"))  # opsiyonel
    if   mcross == "golden":          score += 22
    elif mhist > 0 and mval > 0:      score += 10
    elif mhist > 0:                   score += 5
    if   mcross == "death":           score -= 20
    elif mhist < 0 and mval < 0:      score -= 10

    # ── Stochastic RSI ──────────────────────────────────────────────────
    sk = _n(stock.get("stochK"), 50); sd = _n(stock.get("stochD"), 50)
    if   sk < 10 and sk > sd: score += 20
    elif sk < 20 and sk > sd: score += 14
    elif sk < 20:              score += 8
    elif sk > 90 and sk < sd: score -= 20
    elif sk > 80:              score -= 11

    # ── Bollinger Bands ─────────────────────────────────────────────────
    bb_pct = _n(stock.get("bbPct"), 50)
    if   bb_pct < 5:  score += 17
    elif bb_pct < 15: score += 11
    elif bb_pct < 25: score += 5
    elif bb_pct > 95: score -= 17
    elif bb_pct > 80: score -= 9
    if stock.get("bbSqueeze"): score += 10

    # ── SMA Dizisi (gracefully skip if yok) ─────────────────────────────
    sma20  = _n(stock.get("sma20"));  sma50 = _n(stock.get("sma50")); sma200 = _n(stock.get("sma200"))
    if sma20 > 0 and sma50 > 0 and sma200 > 0:
        if   fiyat > sma20 and sma20 > sma50 and sma50 > sma200: score += 15
        elif fiyat > sma50 and sma50 > sma200:                   score += 8
        elif fiyat < sma20 and sma20 < sma50 and sma50 < sma200: score -= 14
        if fiyat < sma200 and fiyat > sma200 * 0.95:             score += 6
    if sma50 > 0 and sma200 > 0:
        score += 8 if sma50 > sma200 else -8

    # ── Hull MA ─────────────────────────────────────────────────────────
    hull = stock.get("hullDir", "notr")
    if   hull == "yukselis": score += 10
    elif hull == "dusus":    score -= 10

    # ── Destek Yakınlığı ────────────────────────────────────────────────
    sup = _n(stock.get("sup"))
    if sup > 0 and fiyat > 0:
        sd_ = (fiyat - sup) / fiyat * 100
        if   sd_ < 1:  score += 22
        elif sd_ < 3:  score += 16
        elif sd_ < 6:  score += 11
        elif sd_ < 12: score += 5
        elif sd_ > 40: score -= 8

    # ── ROC 20 / 5 / 60 ─────────────────────────────────────────────────
    roc20 = _n(stock.get("roc20")); roc5 = _n(stock.get("roc5")); roc60 = _n(stock.get("roc60"))
    if   roc20 > 15:  score += 10
    elif roc20 > 5:   score += 5
    elif roc20 < -20: score -= 10
    elif roc20 < -8:  score -= 5
    if roc20 > 30: score -= 8
    if roc20 > 20 and rsi > 70: score -= 12
    if   roc5 > 5:  score += 6
    elif roc5 > 2:  score += 3
    elif roc5 < -5: score -= 6
    elif roc5 < -2: score -= 3
    if   roc60 > 25:  score += 8
    elif roc60 > 10:  score += 4
    elif roc60 < -25: score -= 8
    elif roc60 < -10: score -= 4

    # ── OBV ─────────────────────────────────────────────────────────────
    score += 11 if stock.get("obvTrend") == "artis" else -5

    # ── Finansallar ─────────────────────────────────────────────────────
    net_kar = _n(stock.get("netKar"))
    if net_kar != 0:
        score += 20 if net_kar > 0 else -20

    fk = _n(stock.get("fk"))
    if fk > 0:
        if   fk < fk_ucuz * 0.5: score += 15
        elif fk < fk_ucuz:        score += 8
        elif fk < fk_ucuz * 1.5: score += 3
        elif fk > fk_pahali:      score -= 10

    pddd = _n(stock.get("pddd"))
    if   0 < pddd < 0.8: score += 12
    elif 0 < pddd < 1.5: score += 6
    elif pddd > 4:        score -= 8

    roe = _n(stock.get("roe"))
    if   roe > 30: score += 14
    elif roe > 20: score += 10
    elif roe > 10: score += 5
    elif roe < 0:  score -= 8

    nkm = _n(stock.get("netKarMarj"))
    if   nkm > 25: score += 10
    elif nkm > 10: score += 6
    elif nkm > 0:  score += 2
    elif nkm < -5: score -= 10
    elif nkm < 0:  score -= 5

    fkm = _n(stock.get("faalKarMarj"))
    if   fkm > 20: score += 8
    elif fkm > 10: score += 4
    elif fkm < -5: score -= 8
    elif fkm < 0:  score -= 4

    cari = _n(stock.get("cariOran"))
    if   cari > 2.5: score += 8
    elif cari > 1.5: score += 4
    elif cari > 1.0: score += 2
    elif 0 < cari < 0.7: score -= 10
    elif 0 < cari < 1.0: score -= 4

    bo = _n(stock.get("borcOz"))
    if   0 < bo < 0.3: score += 8
    elif 0 < bo < 0.7: score += 4
    elif bo > 4.0:      score -= 14
    elif bo > 2.5:      score -= 8
    elif bo > 1.5:      score -= 4

    nk = _n(stock.get("nakitOran"))
    if   nk > 1.5: score += 6
    elif nk > 0.8: score += 3
    elif 0 < nk < 0.1: score -= 4

    temettu = _n(stock.get("lastTemettu"))
    if   temettu > 5: score += 10
    elif temettu > 2: score += 5
    elif temettu > 0: score += 2

    # recentBedelsiz: geçmiş dağıtım (gerçekleşmiş) → puan VERİLMEZ; kap_bedelsiz_bonus kullanılır.

    net_pa = _n(stock.get("netParaAkis"));  pg = _n(stock.get("paraGiris"))
    if pg > 0 and net_pa > 0:
        akis_r = net_pa / max(pg * 2, 1)
        if   akis_r > 0.2:  score += 10
        elif akis_r > 0.08: score += 5
    elif net_pa < 0 and pg > 0:
        cikis_r = abs(net_pa) / max(pg * 2, 1)
        if cikis_r > 0.2: score -= 8

    ha = _n(stock.get("halkAciklik"))
    if   ha > 60: score += 4
    elif 0 < ha < 10: score -= 4

    s4c = _n(stock.get("sonDortCeyrek"))
    if   s4c > 0: score += 3
    elif s4c < 0: score -= 5

    ret3m = _n(stock.get("ret3m"))
    if   ret3m > 40:  score += 8
    elif ret3m > 20:  score += 4
    elif ret3m < -40: score -= 10
    elif ret3m < -20: score -= 5

    # ── Williams %R ─────────────────────────────────────────────────────
    wr = _n(stock.get("williamsR"), -50)
    if   wr <= -90: score += 16
    elif wr <= -80: score += 12
    elif wr <= -70: score += 7
    elif wr >= -10: score -= 14
    elif wr >= -20: score -= 8

    # ── ADX ─────────────────────────────────────────────────────────────
    adx_v = _n(stock.get("adxVal")); adx_d = stock.get("adxDir", "notr")
    di_p = _n(stock.get("diPlus")); di_m = _n(stock.get("diMinus"))
    if adx_d == "yukselis":
        if   adx_v >= 40: score += 20
        elif adx_v >= 25: score += 13
        elif adx_v >= 15: score += 6
    elif adx_d == "dusus":
        if   adx_v >= 40: score -= 18
        elif adx_v >= 25: score -= 10
    if   di_p > di_m and adx_v >= 20: score += 8
    elif di_p < di_m and adx_v >= 20: score -= 6

    # ── MFI ─────────────────────────────────────────────────────────────
    mfi = _n(stock.get("mfi"), 50)
    if   mfi < 10: score += 17
    elif mfi < 20: score += 11
    elif mfi < 30: score += 5
    elif mfi > 90: score -= 14
    elif mfi > 80: score -= 8
    elif mfi > 70: score -= 3

    # ── CMF ─────────────────────────────────────────────────────────────
    cmf = _n(stock.get("cmf"))
    if   cmf > 0.25: score += 12
    elif cmf > 0.10: score += 8
    elif cmf > 0.00: score += 4
    elif cmf < -0.25: score -= 12
    elif cmf < -0.10: score -= 7
    elif cmf < 0.00:  score -= 2

    # ── SAR ─────────────────────────────────────────────────────────────
    sar_d = stock.get("sarDir", "notr")
    if   sar_d == "yukselis": score += 12
    elif sar_d == "dusus":    score -= 10

    # ── Ichimoku ────────────────────────────────────────────────────────
    ichi = stock.get("ichiSig", "notr")
    ichi_bull = bool(stock.get("ichiBullish", False))
    if   ichi == "ustunde": score += 18 if ichi_bull else 12
    elif ichi == "altinda": score -= 14
    elif ichi == "icinde":  score -= 2
    tk = stock.get("ichiTkCross", "none")
    if   tk == "golden": score += 10
    elif tk == "death":  score -= 10

    # ── Aroon ───────────────────────────────────────────────────────────
    a_up = _n(stock.get("aroonUp"), 50); a_dn = _n(stock.get("aroonDown"), 50)
    a_osc = _n(stock.get("aroonOsc"))
    if   a_up >= 100 and a_dn <= 0:   score += 15
    elif a_up >= 70  and a_dn <= 30:  score += 10
    elif a_up >= 50  and a_dn <= 50:  score += 5
    elif a_dn >= 70  and a_up <= 30:  score -= 14
    if   a_osc > 50:   score += 5
    elif a_osc < -50: score -= 5

    # ── VWAP ────────────────────────────────────────────────────────────
    vwap = _n(stock.get("vwap"))
    if vwap > 0 and fiyat > 0:
        vd = (fiyat - vwap) / vwap * 100
        if   vd > 5:   score += 10
        elif vd > 0:   score += 6
        elif vd < -10: score -= 8
        elif vd < 0:   score -= 3

    # ── Divergence ──────────────────────────────────────────────────────
    div_rsi = stock.get("divRsi", "yok"); div_macd = stock.get("divMacd", "yok")
    if div_rsi  == "boga":      score += 25
    if div_macd == "boga":      score += 20
    if div_rsi  == "ayi":       score -= 20
    if div_macd == "ayi_gizli": score -= 12

    # ── CCI ─────────────────────────────────────────────────────────────
    cci = _n(stock.get("cci"))
    if   cci < -200: score += 10
    elif cci < -100: score += 7
    elif cci >  200: score -= 10
    elif cci >  100: score -= 6

    # ── Elder Ray ───────────────────────────────────────────────────────
    elder = stock.get("elderSignal", "notr")
    if   elder == "guclu_boga": score += 10
    elif elder == "guclu_ayi":  score -= 8

    # ── Donchian ────────────────────────────────────────────────────────
    don = stock.get("donchian") or {}
    br = don.get("breakout", "none") if isinstance(don, dict) else "none"
    if   br == "yukari": score += 12
    elif br == "asagi":  score -= 12

    # ── Volume ──────────────────────────────────────────────────────────
    vr = _n(stock.get("volRatio"), 1.0); vm = _n(stock.get("volMomentum"))
    if   vr > 3.0 and roc20 > 0: score += 14
    elif vr > 2.0 and roc20 > 0: score += 9
    elif vr > 1.5 and roc20 > 0: score += 4
    if   vm > 50:  score += 6
    elif vm < -50: score -= 4
    if vr < 0.7 and roc20 > 5: score -= 10

    # ── 52 Hafta Pozisyonu ──────────────────────────────────────────────
    p52 = _n(stock.get("pos52wk"), 50)
    if   p52 < 10: score += 12
    elif p52 < 20: score += 8
    elif p52 < 30: score += 3
    elif p52 > 90: score -= 10
    elif p52 > 80: score -= 5

    # ── Keltner ─────────────────────────────────────────────────────────
    kpos = stock.get("keltnerPos", "notr")
    if   kpos == "alt_bant": score += 12
    elif kpos == "ust_bant": score -= 10
    if stock.get("bbSqueeze") and stock.get("keltnerSqueeze"): score += 15

    # ── Ultimate Osc ────────────────────────────────────────────────────
    uo = _n(stock.get("ultimateOsc"), 50)
    if   uo < 30: score += 12
    elif uo < 40: score += 6
    elif uo > 70: score -= 10
    elif uo > 60: score -= 5

    # ── Pivot ───────────────────────────────────────────────────────────
    piv = stock.get("pivot") or {}
    if isinstance(piv, dict) and fiyat > 0:
        pp = _n(piv.get("pp")); s1 = _n(piv.get("s1")); s2 = _n(piv.get("s2")); r1 = _n(piv.get("r1"))
        if s1 > 0 and abs(fiyat - s1) / fiyat < 0.015: score += 10
        if s2 > 0 and abs(fiyat - s2) / fiyat < 0.015: score += 15
        if pp > 0 and fiyat > pp: score += 5
        if r1 > 0 and fiyat > r1: score -= 8

    # ── Supertrend ──────────────────────────────────────────────────────
    stdir = stock.get("supertrendDir", "notr")
    if   stdir == "yukselis": score += 12
    elif stdir == "dusus":    score -= 12

    # ── TRIX ────────────────────────────────────────────────────────────
    trx = stock.get("trixCross", "none")
    if   trx == "bullish":  score += 14
    elif trx == "bearish":  score -= 12
    elif stock.get("trixSig") == "yukselis": score += 6
    elif stock.get("trixSig") == "dusus":    score -= 5

    # ── CMO ─────────────────────────────────────────────────────────────
    cmo = _n(stock.get("cmo"))
    if   cmo < -50: score += 14
    elif cmo < -30: score += 8
    elif cmo < -10: score += 3
    elif cmo >  50: score -= 12
    elif cmo >  30: score -= 7
    elif cmo >  10: score -= 3

    # ── Awesome Osc ─────────────────────────────────────────────────────
    ao_sig = stock.get("awesomeOscSig", "notr"); ao_cross = stock.get("awesomeOscCross", "none")
    if   ao_cross == "bullish":   score += 12
    elif ao_cross == "bearish":   score -= 11
    elif ao_sig == "yukselis":    score += 6
    elif ao_sig == "dusus":       score -= 5

    # ── EMA 9/21 Cross ──────────────────────────────────────────────────
    ec = stock.get("emaCrossDir", "none")
    if   ec == "golden":  score += 13
    elif ec == "death":   score -= 11
    elif stock.get("emaFastAboveSlow"): score += 6
    else: score -= 4

    # ── Fibonacci ───────────────────────────────────────────────────────
    fibD = stock.get("fib") or {}
    if isinstance(fibD, dict) and fibD and fiyat > 0:
        matched = False
        for key in ("fib618", "fib786", "fib500", "fib382"):
            fp = _n(fibD.get(key))
            if fp > 0 and abs(fiyat - fp) / fiyat < 0.012:
                score += 12 if key in ("fib618", "fib786") else 8
                matched = True
                break
        if not matched:
            fh = _n(fibD.get("high"));  f236 = _n(fibD.get("fib236"))
            if   fh > 0   and abs(fiyat - fh)  / fiyat < 0.012: score -= 12
            elif f236 > 0 and abs(fiyat - f236) / fiyat < 0.012: score -= 8

    # ── PVT ─────────────────────────────────────────────────────────────
    pvt = stock.get("pvt", "notr")
    if   pvt == "artis": score += 8
    elif pvt == "dusus": score -= 6

    # ── Konsensüs Çarpanı ───────────────────────────────────────────────
    sigs = []
    def _ad(s):
        if s in ("bull", "bear"): sigs.append(s)
    _ad("bull" if rsi < 35 else "bear" if rsi > 65 else "n")
    _ad("bull" if mhist > 0 else "bear")
    _ad("bull" if sk < 30 else "bear" if sk > 70 else "n")
    _ad("bull" if bb_pct < 30 else "bear" if bb_pct > 70 else "n")
    _ad("bull" if stock.get("trend") == "yukselis" else "bear")
    _ad("bull" if wr < -70 else "bear" if wr > -30 else "n")
    _ad("bull" if adx_d == "yukselis" else "bear")
    _ad("bull" if mfi < 40 else "bear" if mfi > 60 else "n")
    _ad("bull" if cmf > 0 else "bear")
    _ad("bull" if sar_d == "yukselis" else "bear")
    _ad("bull" if ichi == "ustunde" else "bear" if ichi == "altinda" else "n")
    _ad("bull" if a_osc > 0 else "bear")
    _ad("bull" if div_rsi == "boga" else "bear" if div_rsi == "ayi" else "n")
    _ad("bull" if stock.get("obvTrend") == "artis" else "bear")
    _ad("bull" if hull == "yukselis" else "bear" if hull == "dusus" else "n")
    _ad("bull" if uo < 40 else "bear" if uo > 60 else "n")
    _ad("bull" if stdir == "yukselis" else "bear" if stdir == "dusus" else "n")
    _ad("bull" if cmo < -20 else "bear" if cmo > 30 else "n")
    _ad("bull" if ao_sig == "yukselis" else "bear" if ao_sig == "dusus" else "n")
    _ad("bull" if stock.get("emaFastAboveSlow") else "bear")
    _ad("bull" if pvt == "artis" else "bear" if pvt == "dusus" else "n")
    _ad("bull" if stock.get("trixSig") == "yukselis" else "bear" if stock.get("trixSig") == "dusus" else "n")
    score = int(round(score * calculate_consensus_multiplier(sigs)))

    # ── Sektör RSI extra ────────────────────────────────────────────────
    if sektor:
        rsi_as = float(st.get("rsi_asiri_satis", 35))
        if rsi <= rsi_as:
            extra = (rsi_as - rsi) / max(rsi_as, 1)
            score += int(round(extra * 15 * max(0.0, rsi_mult - 1.0)))

    return max(0, min(800, score))


# ─────────────────────────────────────────────────────────────────────────────
# calculateAISmartScore — PHP index.php:10110 birebir
# ─────────────────────────────────────────────────────────────────────────────
def calculate_ai_smart_score(base_score: int, stock: dict) -> int:
    ai = int(base_score)
    formations = stock.get("formations") or []
    mode = stock.get("marketMode") or "bull"
    sektor = stock.get("sektor") or config.SEKTOR_GENEL
    fiyat = _n(stock.get("guncel"))
    cap_m = _n(stock.get("marketCap"))

    # Formasyon bonusları
    form_bonus = 0; bear_pen = 0
    for f in formations:
        tip = f.get("tip", "")
        guc = _n(f.get("guc"), 60)
        if tip == "bearish":
            bear_pen += int((guc - 60) * 1.8 + 22)
        else:
            b = int((guc - 60) * 0.9)
            if tip == "reversal": b += 6
            if tip == "breakout": b += 5
            if tip == "momentum": b += 3
            form_bonus += b
    ai += form_bonus
    ai -= bear_pen
    bear_forms = [f for f in formations if f.get("tip") == "bearish"]
    if len(bear_forms) >= 2: ai -= 20
    if len(bear_forms) >= 3: ai -= 15
    bull_forms = [f for f in formations if f.get("tip") != "bearish"]
    if len(bull_forms) >= 2: ai += 10
    if len(bull_forms) >= 3: ai += 6
    tips = [f.get("tip") for f in formations]
    vol_r = _n(stock.get("volRatio"), 1.0)
    if "reversal" in tips and "breakout" in tips: ai += 12
    if form_bonus > 0 and vol_r >= 1.5: ai += 8
    if form_bonus > 0 and vol_r < 0.9:  ai -= 10
    if bear_pen > 0 and vol_r >= 1.5: ai -= 5

    # Piyasa değeri — küçük cap'lere agresif bonus (lotu az / düşük PD)
    if cap_m > 0:
        if   cap_m < 250:    ai += 32   # Nano cap — çok yüksek potansiyel
        elif cap_m < 500:    ai += 24   # Mikro cap
        elif cap_m < 1_000:  ai += 16   # Küçük cap
        elif cap_m < 2_500:  ai += 8
        elif cap_m < 5_000:  ai += 4
        elif cap_m < 20_000: ai += 1
        elif cap_m > 50_000: ai -= 8

    # ── Uyuyan Mücevher Combo Bonus (merkezi modül) ────────────────────
    # Düşük PD + 52H dibinde + uzun süredir yatay + sessiz akıllı para +
    # diverjans + SMC + sağlam zemin + yüksek potansiyel — hepsi tek yerde.
    try:
        from .scoring_extras import sleeper_breakdown, early_catch_bonus
        sleeper_total, sleeper_items = sleeper_breakdown(stock)
        ai += sleeper_total
        stock["sleeperBonus"] = sleeper_total
        stock["sleeperItems"] = sleeper_items
        # Sektör rotasyon — erken yakalama bonusu
        ec_total, ec_items = early_catch_bonus(stock)
        ai += ec_total
        stock["earlyCatchBonus"] = ec_total
        stock["earlyCatchItems"] = ec_items
    except Exception:
        pass

    # Sektör bonusları
    rsi   = _n(stock.get("rsi"), 50)
    pos52 = _n(stock.get("pos52wk"), 50)
    roc60 = _n(stock.get("roc60"))
    roc5  = _n(stock.get("roc5"))
    mfi   = _n(stock.get("mfi"), 50)
    cmf   = _n(stock.get("cmf"))
    adx_v = _n(stock.get("adxVal")); adx_d = stock.get("adxDir", "notr")

    if sektor and sektor != config.SEKTOR_GENEL:
        st = _get_sector_thresholds(sektor)
        rsi_as = float(st.get("rsi_asiri_satis", 35)); rsi_aa = float(st.get("rsi_asiri_alim", 65))
        if rsi < rsi_as and mfi < (rsi_as + 10) and cmf > -0.05:
            derinlik = max(0, (rsi_as - rsi) / max(rsi_as, 1))
            ai += int(round(derinlik * 20))
        if sektor in (config.SEKTOR_BANKA, config.SEKTOR_SIGORTA):
            fk = _n(stock.get("fk"))
            if fk > 0 and fk < st["fk_ucuz"]: ai += 12
            if adx_v >= 20 and adx_d == "yukselis": ai += 8
        if sektor == config.SEKTOR_TEKNOLOJI:
            if pos52 < 30 and roc60 > -30 and roc5 > 0: ai += 15
            if pos52 < 20 and rsi < 35: ai += 10
        if sektor == config.SEKTOR_ENERJI:
            if pos52 < 25 and cmf > 0: ai += 12
        if sektor == config.SEKTOR_GAYRIMENKUL:
            pddd = _n(stock.get("pddd"))
            if   0 < pddd < 0.7: ai += 15
            elif 0 < pddd < 1.0: ai += 8
        if sektor in (config.SEKTOR_METAL, config.SEKTOR_INSAAT):
            if roc60 > 0 and adx_v >= 20 and adx_d == "yukselis": ai += 10
        if sektor == config.SEKTOR_HOLDING:
            fk = _n(stock.get("fk"))
            if pos52 < 20 and fk > 0 and fk < st["fk_ucuz"] * 1.2: ai += 12
        if sektor in (config.SEKTOR_PERAKENDE, config.SEKTOR_GIDA):
            if roc60 > 20 and rsi < rsi_aa: ai += 8
        if sektor == config.SEKTOR_TEKSTIL:
            bo = _n(stock.get("borcOz")); bkm = _n(stock.get("brutKarMarj"))
            if 0 < bo < 0.8 and bkm > 20: ai += 12
            if pos52 < 30 and roc5 > 0 and rsi < rsi_as + 10: ai += 10
            if 0 < bkm < 5: ai -= 8
        if sektor == config.SEKTOR_KIMYA:
            roe = _n(stock.get("roe")); bkm = _n(stock.get("brutKarMarj")); bo = _n(stock.get("borcOz"))
            if roe > 15 and bkm > 25: ai += 12
            if 0 < bo < 0.5 and rsi < rsi_as + 5: ai += 8
            if adx_v >= 20 and adx_d == "yukselis" and roc60 > 0: ai += 6
        if sektor == config.SEKTOR_ULASIM:
            cari = _n(stock.get("cariOran")); nk = _n(stock.get("nakitOran")); bo = _n(stock.get("borcOz"))
            if cari > 1.2 and nk > 0.3: ai += 10
            if 0 < bo < 1.0 and pos52 < 30: ai += 8
            if bo > 5.0: ai -= 12
            if cmf > 0.1 and roc5 > 0: ai += 6
        if sektor == config.SEKTOR_ILETISIM:
            temettu = _n(stock.get("lastTemettu")); pddd = _n(stock.get("pddd"))
            faal = _n(stock.get("faalKarMarj")); netpa = _n(stock.get("netParaAkis"))
            if   temettu > 3: ai += 12
            elif temettu > 0: ai += 5
            if 0 < pddd < 1.5 and faal > 10: ai += 10
            if netpa > 0 and rsi < rsi_aa: ai += 6
            if roc60 < -20 and temettu > 2: ai += 8

    # Aşırı ısınma cezası
    if   pos52 > 88 and roc60 > 90: ai -= 60
    elif pos52 > 82 and roc60 > 65: ai -= 42
    elif pos52 > 75 and roc60 > 40: ai -= 22
    if   roc5 > 20 and rsi > 70: ai -= 25
    elif roc5 > 12 and rsi > 65: ai -= 15

    # Makro mod
    if mode == "temkinli":
        ai = int(round(ai * 0.85))
    elif mode == "ayi":
        ai = int(round(ai * 0.65))
        net_kar = _n(stock.get("netKar")); pddd = _n(stock.get("pddd"))
        if 0 < pddd < 0.8 and net_kar > 0: ai += 15
    elif mode == "bull":
        ai += 12

    # 52H dip + RSI dip
    if   pos52 < 10 and rsi < 25: ai += 15
    elif pos52 < 15 and rsi < 30: ai += 10
    elif pos52 < 25 and rsi < 40: ai += 5

    # VWAP Band (alt/ust 1/2 sigma)
    vbpos = stock.get("vwapBandPos", stock.get("vwapPos", "icinde"))
    if   vbpos == "alt2": ai += 14
    elif vbpos == "alt1": ai += 7
    elif vbpos == "ust2": ai -= 12
    elif vbpos == "ust1": ai -= 5

    # OFI
    ofi = stock.get("ofiSig", "notr")
    if   ofi == "guclu_alis":  ai += 12
    elif ofi == "alis":         ai += 6
    elif ofi == "guclu_satis":  ai -= 10
    elif ofi == "satis":        ai -= 5

    # Adaptive Vol
    avReg = stock.get("volRegime", "normal")
    if   avReg == "ekstrem": ai -= 12
    elif avReg == "dusuk":   ai += 5

    # SMC bias — zengin yapı bonusu (PHP smcScoreBonus birebir)
    from .scoring import smc_score_bonus as _smc_bonus
    smc_full = stock.get("smc") or stock.get("smcFull")
    if smc_full and isinstance(smc_full, dict):
        ai += _smc_bonus(smc_full, fiyat)
    else:
        smc = stock.get("smcBias", "notr")
        if   smc == "bullish": ai += 10
        elif smc == "bearish": ai -= 10

    # ── Harmonik formasyon bonusu (PHP index.php:10310 birebir) ───────────
    harmonics = stock.get("harmonics") or []
    if isinstance(harmonics, list):
        for harm in harmonics:
            if not isinstance(harm, dict): continue
            h_conf = _n(harm.get("confidence"))
            h_type = harm.get("type", "")
            h_prz  = _n(harm.get("prz"))
            if h_conf < 65: continue
            prz_near = h_prz > 0 and fiyat > 0 and abs(fiyat - h_prz) / h_prz < 0.03
            if h_type == "bullish":
                bonus = int(round((h_conf - 60) / 4))
                if prz_near: bonus += 15
                ai += min(25, bonus)
            elif h_type == "bearish":
                penalty = int(round((h_conf - 60) / 5))
                if prz_near: penalty += 10
                ai -= min(20, penalty)

    # ── Brain confluence + time bonus (PHP index.php:10287 birebir) ───────
    try:
        from .brain import brain_get_confluence_bonus, brain_get_time_bonus, brain_load
        _brain = brain_load()
        ai += brain_get_confluence_bonus(stock, _brain)
        ai += int(round(brain_get_time_bonus(_brain) * 0.5))
    except Exception:
        pass

    return max(0, min(1000, ai))
