"""Skorlama modülü — PHP calculateAISmartScore, calculateSignalQuality,
calculateHizScore, calculate_buy_sell_targets ile birebir eşleştirilmiş."""
from __future__ import annotations
from . import config


# ── Sektör eşik değerleri (PHP getSectorThresholds birebir) ──────────────────
_SECTOR_THRESHOLDS: dict[str, dict] = {
    config.SEKTOR_BANKA:       {"rsi_asiri_satis": 40, "rsi_asiri_alim": 70, "fk_ucuz": 8,  "fk_pahali": 18, "rsi_bonus_mult": 0.9},
    config.SEKTOR_SIGORTA:     {"rsi_asiri_satis": 38, "rsi_asiri_alim": 68, "fk_ucuz": 8,  "fk_pahali": 18, "rsi_bonus_mult": 0.9},
    config.SEKTOR_TEKNOLOJI:   {"rsi_asiri_satis": 30, "rsi_asiri_alim": 75, "fk_ucuz": 20, "fk_pahali": 50, "rsi_bonus_mult": 1.1},
    config.SEKTOR_ENERJI:      {"rsi_asiri_satis": 35, "rsi_asiri_alim": 68, "fk_ucuz": 8,  "fk_pahali": 20, "rsi_bonus_mult": 1.0},
    config.SEKTOR_PERAKENDE:   {"rsi_asiri_satis": 33, "rsi_asiri_alim": 67, "fk_ucuz": 12, "fk_pahali": 30, "rsi_bonus_mult": 1.0},
    config.SEKTOR_INSAAT:      {"rsi_asiri_satis": 33, "rsi_asiri_alim": 67, "fk_ucuz": 10, "fk_pahali": 22, "rsi_bonus_mult": 1.0},
    config.SEKTOR_GAYRIMENKUL: {"rsi_asiri_satis": 35, "rsi_asiri_alim": 65, "fk_ucuz": 12, "fk_pahali": 25, "rsi_bonus_mult": 0.95},
    config.SEKTOR_HOLDING:     {"rsi_asiri_satis": 33, "rsi_asiri_alim": 67, "fk_ucuz": 8,  "fk_pahali": 20, "rsi_bonus_mult": 1.0},
    config.SEKTOR_TEKSTIL:     {"rsi_asiri_satis": 33, "rsi_asiri_alim": 67, "fk_ucuz": 8,  "fk_pahali": 18, "rsi_bonus_mult": 1.0},
    config.SEKTOR_KIMYA:       {"rsi_asiri_satis": 33, "rsi_asiri_alim": 68, "fk_ucuz": 10, "fk_pahali": 22, "rsi_bonus_mult": 1.0},
    config.SEKTOR_GIDA:        {"rsi_asiri_satis": 32, "rsi_asiri_alim": 67, "fk_ucuz": 10, "fk_pahali": 22, "rsi_bonus_mult": 1.0},
    config.SEKTOR_METAL:       {"rsi_asiri_satis": 33, "rsi_asiri_alim": 67, "fk_ucuz": 7,  "fk_pahali": 18, "rsi_bonus_mult": 1.05},
    config.SEKTOR_ULASIM:      {"rsi_asiri_satis": 35, "rsi_asiri_alim": 67, "fk_ucuz": 8,  "fk_pahali": 20, "rsi_bonus_mult": 1.0},
    config.SEKTOR_ILETISIM:    {"rsi_asiri_satis": 32, "rsi_asiri_alim": 70, "fk_ucuz": 12, "fk_pahali": 28, "rsi_bonus_mult": 1.05},
    config.SEKTOR_TURIZM:      {"rsi_asiri_satis": 33, "rsi_asiri_alim": 67, "fk_ucuz": 12, "fk_pahali": 28, "rsi_bonus_mult": 1.0},
    config.SEKTOR_KAGIT:       {"rsi_asiri_satis": 33, "rsi_asiri_alim": 67, "fk_ucuz": 8,  "fk_pahali": 18, "rsi_bonus_mult": 1.0},
    config.SEKTOR_MOBILYA:     {"rsi_asiri_satis": 33, "rsi_asiri_alim": 67, "fk_ucuz": 8,  "fk_pahali": 18, "rsi_bonus_mult": 1.0},
    config.SEKTOR_SAGLIK:      {"rsi_asiri_satis": 30, "rsi_asiri_alim": 70, "fk_ucuz": 15, "fk_pahali": 35, "rsi_bonus_mult": 1.1},
    config.SEKTOR_SPOR:        {"rsi_asiri_satis": 33, "rsi_asiri_alim": 67, "fk_ucuz": 15, "fk_pahali": 40, "rsi_bonus_mult": 0.9},
}
_SECTOR_DEFAULTS = {"rsi_asiri_satis": 35, "rsi_asiri_alim": 65, "fk_ucuz": 10, "fk_pahali": 25, "rsi_bonus_mult": 1.0}


def _get_sector_thresholds(sektor: str) -> dict:
    return _SECTOR_THRESHOLDS.get(sektor, _SECTOR_DEFAULTS)


# ── calculateSignalQuality (PHP birebir) ─────────────────────────────────────
def calculate_signal_quality(stock: dict) -> int:
    """Sinyal kalitesi 0-10. PHP calculateSignalQuality birebir."""
    sq = 0

    rsi     = float(stock.get("rsi", 50) or 50)
    stoch_k = float(stock.get("stochK", 50) or 50)
    stoch_d = float(stock.get("stochD", 50) or 50)
    mfi     = float(stock.get("mfi", 50) or 50)
    cmf     = float(stock.get("cmf", 0) or 0)
    wr      = float(stock.get("williamsR", -50) or -50)
    cci     = float(stock.get("cci", 0) or 0)
    vol     = float(stock.get("volRatio", 1) or 1)
    pos52   = float(stock.get("pos52wk", 50) or 50)
    adx_dir = stock.get("adxDir", "notr")
    adx_val = float(stock.get("adxVal", 0) or 0)
    sar     = stock.get("sarDir", "notr")
    macd    = stock.get("macdCross", "none")
    ichi    = stock.get("ichiSig", "notr")
    div_rsi = stock.get("divRsi", "yok")
    div_macd= stock.get("divMacd", "yok")
    bb_sq   = bool(stock.get("bbSqueeze", False))
    obv     = stock.get("obvTrend", "notr")
    hull    = stock.get("hullDir", "notr")
    _trix = stock.get("trix")
    if isinstance(_trix, dict):
        trix_v = float(_trix.get("value", 0) or 0)
    else:
        trix_v = float(_trix or 0)
    elder   = stock.get("elderSignal", "notr")
    st_dir  = stock.get("supertrendDir", "notr")
    ema_c   = stock.get("emaCrossDir", "none")
    forms   = stock.get("formations") or []

    # ── PLAN 1: Fuzzy Threshold — Aşırı satım (0–3 puan) ─────────────────
    rsi_f   = 1.0 if rsi < 20   else ((42 - rsi) / 22 if rsi < 42 else 0.0)
    stoch_f = 1.0 if stoch_k < 10 else ((32 - stoch_k) / 22 if stoch_k < 32 else 0.0)
    mfi_f   = 1.0 if mfi < 15   else ((42 - mfi) / 27 if mfi < 42 else 0.0)
    wr_f    = 1.0 if wr <= -90  else ((-62 - wr) / 28 if wr <= -62 else 0.0)
    cci_f   = 1.0 if cci <= -200 else ((-80 - cci) / 120 if cci <= -80 else 0.0)
    oversold = rsi_f + stoch_f + mfi_f + wr_f + cci_f
    sq += int(round(min(3.0, oversold * 0.85)))

    # ── StochRSI Golden Cross ──────────────────────────────────────────────
    if stoch_k > stoch_d and stoch_k < 25 and stoch_d < 30:
        sq += 1

    # ── Trend teyidi ──────────────────────────────────────────────────────
    if sar == "yukselis":                     sq += 1
    if adx_dir == "yukselis" and adx_val >= 20: sq += 1
    if ichi == "ustunde":                     sq += 1
    if macd == "golden":                      sq += 1

    # ── Hacim onayı (Fuzzy, 0–2 puan) ────────────────────────────────────
    if   vol >= 3.5: sq += 2
    elif vol >= 2.0: sq += 1
    elif vol < 0.9:  sq -= 1

    # ── Diverjans bonusu ──────────────────────────────────────────────────
    if div_rsi  == "boga": sq += 2
    if div_macd == "boga": sq += 1

    # ── Formasyon bonusu (sinerji dahil) ──────────────────────────────────
    reversal_cnt = sum(1 for f in forms if f.get("tip") == "reversal")
    breakout_cnt = sum(1 for f in forms if f.get("tip") == "breakout")
    if len(forms) >= 1: sq += 1
    if len(forms) >= 2: sq += 1
    if reversal_cnt > 0 and breakout_cnt > 0: sq += 1

    # ── BB Squeeze ────────────────────────────────────────────────────────
    if bb_sq: sq += 1

    # ── Supertrend ────────────────────────────────────────────────────────
    if   st_dir == "yukselis": sq += 1
    elif st_dir == "dusus":    sq -= 1

    # ── EMA 9/21 Golden Cross ─────────────────────────────────────────────
    if   ema_c == "golden": sq += 1
    elif ema_c == "death":  sq -= 1

    # ── CMF para akışı ────────────────────────────────────────────────────
    if   cmf > 0.25: sq += 1
    elif cmf < -0.25: sq -= 1

    # ── OBV Trend ─────────────────────────────────────────────────────────
    if   obv == "yukselis": sq += 1
    elif obv == "dusus":    sq -= 1

    # ── MFI kesin aşırı satım ─────────────────────────────────────────────
    if   mfi < 10: sq += 2
    elif mfi < 20: sq += 1
    elif mfi > 90: sq -= 1

    # ── Hull MA yön teyidi ────────────────────────────────────────────────
    if   hull == "yukselis": sq += 1
    elif hull == "dusus":    sq -= 1

    # ── TRIX pozitif ivme ─────────────────────────────────────────────────
    if   trix_v > 0.15:  sq += 1
    elif trix_v < -0.15: sq -= 1

    # ── Elder Ray sinyal ──────────────────────────────────────────────────
    if   elder == "guclu_boga": sq += 1
    elif elder == "guclu_ayi":  sq -= 1

    # ── Isınma Cezası ─────────────────────────────────────────────────────
    if pos52 > 80 and rsi > 65:
        heat = int(round((pos52 - 80) / 6 + (rsi - 65) / 8))
        sq -= min(4, max(1, heat))
    if pos52 > 87: sq -= 2

    # ── Ayı cezaları ──────────────────────────────────────────────────────
    if div_rsi == "ayi":                      sq -= 3
    if macd == "death":                       sq -= 2
    if sar == "dusus" and adx_val >= 25:      sq -= 2

    return max(0, min(10, sq))


# ── calculateHizScore (PHP birebir) ──────────────────────────────────────────
def calculate_hiz_score(stock: dict) -> int:
    """Sprint hız skoru 0-15. PHP calculateHizScore birebir."""
    hz = 0

    roc5    = float(stock.get("roc5", 0) or 0)
    vol     = float(stock.get("volRatio", 1) or 1)
    vol_mom = float(stock.get("volMomentum", 0) or 0)
    bb_sq   = bool(stock.get("bbSqueeze", False))
    macd    = stock.get("macdCross", "none")
    sar     = stock.get("sarDir", "notr")
    adx_val = float(stock.get("adxVal", 0) or 0)
    adx_dir = stock.get("adxDir", "notr")
    rsi     = float(stock.get("rsi", 50) or 50)
    ichi    = stock.get("ichiSig", "notr")
    st_dir  = stock.get("supertrendDir", "notr")
    ema_c   = stock.get("emaCrossDir", "none")
    div_rsi = stock.get("divRsi", "yok")
    pos52   = float(stock.get("pos52wk", 50) or 50)
    forms   = stock.get("formations") or []

    # ── Kısa vadeli momentum (ROC5) ────────────────────────────────────────
    if   roc5 > 5:  hz += 3
    elif roc5 > 2:  hz += 2
    elif roc5 > 0:  hz += 1
    elif roc5 < -3: hz -= 2

    # ── Hacim patlaması ────────────────────────────────────────────────────
    if   vol >= 4.0: hz += 3
    elif vol >= 2.5: hz += 2
    elif vol >= 1.8: hz += 1
    elif vol < 0.8:  hz -= 1
    if vol_mom > 0:  hz += 1

    # ── BB Squeeze kırılımı ────────────────────────────────────────────────
    if bb_sq: hz += 3

    # ── MACD golden cross ─────────────────────────────────────────────────
    if macd == "golden": hz += 2

    # ── Parabolic SAR bullish ─────────────────────────────────────────────
    if sar == "yukselis": hz += 2

    # ── ADX güçlü yükseliş ────────────────────────────────────────────────
    if adx_dir == "yukselis" and adx_val >= 25: hz += 2
    elif adx_dir == "yukselis" and adx_val >= 18: hz += 1

    # ── RSI optimal bölge (32-52 = dipten dönüş başlamış) ─────────────────
    if   32 <= rsi <= 52: hz += 2
    elif 52 < rsi <= 62:  hz += 1
    elif rsi > 70:        hz -= 2

    # ── Ichimoku bulut üstü ───────────────────────────────────────────────
    if ichi == "ustunde": hz += 1

    # ── Supertrend ────────────────────────────────────────────────────────
    if   st_dir == "yukselis": hz += 1
    elif st_dir == "dusus":    hz -= 1

    # ── EMA 9/21 Golden Cross ─────────────────────────────────────────────
    if   ema_c == "golden": hz += 1
    elif ema_c == "death":  hz -= 1

    # ── RSI Boğa diverjansı ────────────────────────────────────────────────
    if div_rsi == "boga": hz += 2

    # ── Formasyon etkileri ────────────────────────────────────────────────
    for f in forms:
        if f.get("tip") == "breakout": hz += 2; break
    for f in forms:
        if f.get("tip") == "reversal": hz += 1; break
    for f in forms:
        if f.get("tip") == "momentum": hz += 1; break
    bear_cnt = sum(1 for f in forms if f.get("tip") == "bearish")
    if bear_cnt >= 1: hz -= 2
    if bear_cnt >= 2: hz -= 2

    # ── 52 haftanın çok dibindeyse ağır hareket eder ─────────────────────
    if pos52 < 5: hz -= 1

    return max(0, min(15, hz))


# ── calculateAISmartScore (PHP birebir — sektör bonusları dahil) ─────────────
def calculate_ai_score(stock: dict) -> int:
    """AI Puan (0-350). PHP calculateAISmartScore + calculateAlPuani birebir.
    v29 Plan 2: Sektöre özgü bonuslar dahil.

    v37: Tam birebir port `scoring_phpmatch` üzerinden devreye alındı."""
    try:
        from .scoring_phpmatch import calculate_al_puani, calculate_ai_smart_score
        base = calculate_al_puani(stock)
        stock["alPuani"] = base  # UI ve scoring_extras için kaydet
        return calculate_ai_smart_score(base, stock)
    except Exception:
        pass
    # ── Fallback: eski sadeleştirilmiş hesap ─────────────────────────────
    rsi    = float(stock.get("rsi", 50) or 50)
    adx    = float(stock.get("adxVal", 0) or 0)
    adx_d  = stock.get("adxDir", "notr")
    cmf    = float(stock.get("cmf", 0) or 0)
    mfi    = float(stock.get("mfi", 50) or 50)
    vol    = float(stock.get("volRatio", 1) or 1)
    pos52  = float(stock.get("pos52wk", 50) or 50)
    roc5   = float(stock.get("roc5", 0) or 0)
    roc60  = float(stock.get("roc60", 0) or 0)
    macd   = stock.get("macdCross", "none")
    sar    = stock.get("sarDir", "notr")
    st     = stock.get("supertrendDir", "notr")
    hull   = stock.get("hullDir", "notr")
    ichi   = stock.get("ichiSig", "notr")
    smc    = stock.get("smcBias", "notr")
    ofi    = stock.get("ofiSig", "notr")
    div    = stock.get("divRsi", "yok")
    bb_sq  = stock.get("bbSqueeze", False)
    vwap   = stock.get("vwapPos", "icinde")
    vol_reg= stock.get("volRegime", "normal")
    ema_c  = stock.get("emaCrossDir", "none")
    mode   = stock.get("marketMode", "bull")
    forms  = stock.get("formations") or []
    cap    = float(stock.get("marketCap", 0) or 0)
    adil   = float(stock.get("adil", 0) or 0)
    guncel = float(stock.get("guncel", 0) or 0)
    sq     = int(stock.get("signalQuality", 0) or 0)
    sektor = stock.get("sektor", config.SEKTOR_GENEL)

    # Finansal veriler (sektör bonusu için)
    fk         = float(stock.get("fk", 0) or 0)
    pddd       = float(stock.get("pddd", 0) or 0)
    borc_oz    = float(stock.get("borcOz", 0) or 0)
    brut_marj  = float(stock.get("brutKarMarj", 0) or 0)
    roe        = float(stock.get("roe", 0) or 0)
    cari_oran  = float(stock.get("cariOran", 0) or 0)
    nakit_oran = float(stock.get("nakitOran", 0) or 0)
    temettu    = float(stock.get("lastTemettu", 0) or 0)
    faal_marj  = float(stock.get("faalKarMarj", 0) or 0)
    net_para   = float(stock.get("netParaAkis", 0) or 0)
    net_kar    = float(stock.get("netKar", 0) or 0)

    # ── Base Score (calculateAlPuani benzeri) ────────────────────────────
    ai = 60  # PHP baseScore başlangıcı

    # Temel analiz (adil değer)
    if adil > 0 and guncel > 0:
        margin = (adil - guncel) / guncel * 100
        if   margin > 40: ai += 30
        elif margin > 20: ai += 18
        elif margin > 0:  ai += 8
        elif margin < -25: ai -= 15

    # RSI bazlı teknik
    if   rsi < 20: ai += 25
    elif rsi < 30: ai += 18
    elif rsi < 40: ai += 10
    elif rsi > 80: ai -= 18
    elif rsi > 70: ai -= 10

    # MACD
    if   macd == "golden": ai += 20
    elif macd == "death":  ai -= 15

    # SAR
    if sar == "yukselis":  ai += 10
    elif sar == "dusus":   ai -= 8

    # Supertrend
    if   st == "yukselis": ai += 15
    elif st == "dusus":    ai -= 12

    # Hull MA
    if hull == "yukselis": ai += 10

    # Ichimoku
    if   ichi == "ustunde": ai += 12
    elif ichi == "altinda": ai -= 10

    # RSI Diverjans
    if   div == "boga": ai += 18
    elif div == "ayi":  ai -= 15

    # ADX + Supertrend sinerji
    if adx >= 30:
        if   st == "yukselis": ai += 12
        elif st == "dusus":    ai -= 10

    # SMC
    if   smc == "bullish": ai += 12
    elif smc == "bearish": ai -= 10

    # BB Squeeze
    if bb_sq: ai += 8

    # Hacim
    if   vol >= 3.0: ai += 20
    elif vol >= 2.0: ai += 12
    elif vol >= 1.5: ai += 6
    elif vol < 0.5:  ai -= 15

    # CMF
    if   cmf > 0.2: ai += 15
    elif cmf > 0.1: ai += 8
    elif cmf < -0.1: ai -= 10

    # MFI
    if mfi < 25: ai += 12
    elif mfi > 75: ai -= 8

    # OFI
    if   ofi == "guclu_alis":  ai += 12
    elif ofi == "alis":         ai += 6
    elif ofi == "guclu_satis":  ai -= 10
    elif ofi == "satis":        ai -= 5

    # EMA Cross
    if   ema_c == "golden": ai += 8
    elif ema_c == "death":  ai -= 8

    # SignalQuality katkısı (PHP: al = min(250, al + signalQuality * 5))
    ai += sq * 5

    # ── Formasyon Bonusları (PHP calculateAISmartScore birebir) ──────────
    form_bonus = 0
    bear_penalty = 0
    for f in forms:
        tip = f.get("tip", "")
        guc = float(f.get("guc", 60) or 60)
        if tip == "bearish":
            penalty = int((guc - 60) * 1.8 + 22)
            bear_penalty += penalty
        else:
            bonus = int((guc - 60) * 0.9)
            if tip == "reversal": bonus += 6
            if tip == "breakout": bonus += 5
            if tip == "momentum": bonus += 3
            form_bonus += bonus
    ai += form_bonus
    ai -= bear_penalty

    bear_forms = [f for f in forms if f.get("tip") == "bearish"]
    if len(bear_forms) >= 2: ai -= 20
    if len(bear_forms) >= 3: ai -= 15

    bull_forms = [f for f in forms if f.get("tip") != "bearish"]
    if len(bull_forms) >= 2: ai += 10
    if len(bull_forms) >= 3: ai += 6

    # Formasyon × Hacim doğrulama sinerjisi
    tips = [f.get("tip") for f in forms]
    if "reversal" in tips and "breakout" in tips: ai += 12
    if form_bonus > 0 and vol >= 1.5: ai += 8
    if form_bonus > 0 and vol < 0.9:  ai -= 10
    if bear_penalty > 0 and vol >= 1.5: ai -= 5

    # ── Piyasa Değeri Ayarı ───────────────────────────────────────────────
    if cap > 0:
        if   cap < 500:    ai += 12
        elif cap < 1_000:  ai += 8
        elif cap < 5_000:  ai += 4
        elif cap < 20_000: ai += 2
        elif cap > 50_000: ai -= 8

    # ── v29: Sektör Bonusu (Plan 2 — PHP birebir) ────────────────────────
    if sektor and sektor != config.SEKTOR_GENEL:
        st_thresh = _get_sector_thresholds(sektor)
        rsi_asiri_satis = st_thresh["rsi_asiri_satis"]
        rsi_asiri_alim  = st_thresh["rsi_asiri_alim"]
        fk_ucuz         = st_thresh["fk_ucuz"]

        # Sektör RSI dip sinyali: RSI aşırı satım eşiğinin altında + hacim desteği
        if rsi < rsi_asiri_satis and mfi < (rsi_asiri_satis + 10) and cmf > -0.05:
            s_derinlik = max(0.0, (rsi_asiri_satis - rsi) / max(rsi_asiri_satis, 1))
            ai += int(round(s_derinlik * 20))  # Max ~20 puan

        # Banka/Sigorta: F/K ve özkaynak karlılığı odaklı ek bonus
        if sektor in (config.SEKTOR_BANKA, config.SEKTOR_SIGORTA):
            if fk > 0 and fk < fk_ucuz: ai += 12
            if adx >= 20 and adx_d == "yukselis": ai += 8

        # Teknoloji: momentum odaklı — 52 hafta dip + ROC toparlanma
        if sektor == config.SEKTOR_TEKNOLOJI:
            if pos52 < 30 and roc60 > -30 and roc5 > 0: ai += 15
            if pos52 < 20 and rsi < 35:                  ai += 10

        # Enerji: 52 hafta dibi + CMF pozitif = akıllı para giriyor
        if sektor == config.SEKTOR_ENERJI:
            if pos52 < 25 and cmf > 0: ai += 12

        # Gayrimenkul: PD/DD odaklı — düşük PD/DD = gizli değer
        if sektor == config.SEKTOR_GAYRIMENKUL:
            if pddd > 0 and pddd < 0.7:  ai += 15
            elif pddd > 0 and pddd < 1:  ai += 8

        # Metal/İnşaat: roc60 toparlanma + hacim combo
        if sektor in (config.SEKTOR_METAL, config.SEKTOR_INSAAT):
            if roc60 > 0 and adx >= 20 and adx_d == "yukselis": ai += 10

        # Holding: derin değer + piyasa dibi combo
        if sektor == config.SEKTOR_HOLDING:
            if pos52 < 20 and fk > 0 and fk < fk_ucuz * 1.2: ai += 12

        # Perakende/Gıda: güçlü momentum = fiyatlama gücü
        if sektor in (config.SEKTOR_PERAKENDE, config.SEKTOR_GIDA):
            if roc60 > 20 and rsi < rsi_asiri_alim: ai += 8

        # Tekstil: düşük borç + güçlü brüt marj + dip momentum
        if sektor == config.SEKTOR_TEKSTIL:
            if borc_oz > 0 and borc_oz < 0.8 and brut_marj > 20: ai += 12
            if pos52 < 30 and roc5 > 0 and rsi < rsi_asiri_satis + 10: ai += 10
            if 0 < brut_marj < 5: ai -= 8

        # Kimya/İlaç: brüt marj + ROE + düşük borç kombine bonus
        if sektor == config.SEKTOR_KIMYA:
            if roe > 15 and brut_marj > 25: ai += 12
            if borc_oz > 0 and borc_oz < 0.5 and rsi < rsi_asiri_satis + 5: ai += 8
            if adx >= 20 and adx_d == "yukselis" and roc60 > 0: ai += 6

        # Ulaşım: cari oran + nakit + düşük borç (operasyonel güvenlik)
        if sektor == config.SEKTOR_ULASIM:
            if cari_oran > 1.2 and nakit_oran > 0.3: ai += 10
            if borc_oz > 0 and borc_oz < 1.0 and pos52 < 30: ai += 8
            if borc_oz > 5.0: ai -= 12
            if cmf > 0.1 and roc5 > 0: ai += 6

        # İletişim/Medya: temettü verimi + serbest nakit akışı + düşük PD/DD
        if sektor == config.SEKTOR_ILETISIM:
            if temettu > 3: ai += 12
            elif temettu > 0: ai += 5
            if pddd > 0 and pddd < 1.5 and faal_marj > 10: ai += 10
            if net_para > 0 and rsi < rsi_asiri_alim: ai += 6
            if roc60 < -20 and temettu > 2: ai += 8

    # ── VWAP Bandı bonusu ─────────────────────────────────────────────────
    if   vwap == "alt2": ai += 14
    elif vwap == "alt1": ai += 7
    elif vwap == "ust2": ai -= 12
    elif vwap == "ust1": ai -= 5

    # ── Adaptif Volatilite rejim ──────────────────────────────────────────
    if   vol_reg == "ekstrem": ai -= 12
    elif vol_reg == "dusuk":   ai += 5

    # ── Aşırı Isınma Cezası (roc60 bazlı) ────────────────────────────────
    if   pos52 > 88 and roc60 > 90: ai -= 60
    elif pos52 > 82 and roc60 > 65: ai -= 42
    elif pos52 > 75 and roc60 > 40: ai -= 22
    if   roc5 > 20 and rsi > 70:    ai -= 25
    elif roc5 > 12 and rsi > 65:    ai -= 15

    # ── Piyasa Modu Çarpanı (PHP Plan 3) ──────────────────────────────────
    if mode == "temkinli":
        ai = int(round(ai * 0.85))
    elif mode == "ayi":
        ai = int(round(ai * 0.65))
        # Ayı modunda değer hisseleri koruma altında
        if pddd > 0 and pddd < 0.8 and net_kar > 0: ai += 15
    elif mode == "bull":
        ai += 12

    # ── 52h Dip + RSI Dip Sinerjisi ───────────────────────────────────────
    if   pos52 < 10 and rsi < 25: ai += 15
    elif pos52 < 15 and rsi < 30: ai += 10
    elif pos52 < 25 and rsi < 40: ai += 5

    return max(0, min(1000, ai))


# ── predatorScore hesabı (PHP predatorScore birebir) ─────────────────────────
def calculate_predator_score(stock: dict) -> float:
    """PHP formülü: aiScore*0.40 + hizScore*(100/15)*0.28 + expGainPct*3*0.20 + rrBonus*0.12 + momBonus"""
    ai_score  = float(stock.get("aiScore", 0) or 0)
    hiz_score = float(stock.get("hizScore", 0) or 0)
    guncel    = float(stock.get("guncel", 0) or 0)
    h1        = float(stock.get("h1", 0) or 0)
    rr        = float(stock.get("rr", 0) or 0)
    vol       = float(stock.get("volRatio", 1) or 1)
    bb_sq     = bool(stock.get("bbSqueeze", False))

    # Beklenen kazanç yüzdesi (H1 hedefine olan mesafe — en fazla %40)
    exp_gain = 0.0
    if guncel > 0 and h1 > guncel:
        exp_gain = min(40.0, (h1 - guncel) / guncel * 100)

    # Risk/Ödül kalite bonusu
    rr_bonus = 30.0 if rr >= 3.0 else (18.0 if rr >= 2.0 else (8.0 if rr >= 1.5 else 0.0))

    # Momentum patlaması bonusu
    mom_bonus = 0.0
    if vol >= 3.0 and hiz_score >= 9:      mom_bonus = 25.0
    elif vol >= 2.0 and hiz_score >= 7:    mom_bonus = 15.0
    elif bb_sq and hiz_score >= 6:         mom_bonus = 10.0

    return (ai_score * 0.40
            + hiz_score * (100.0 / 15.0) * 0.28
            + exp_gain * 3.0 * 0.20
            + rr_bonus * 0.12
            + mom_bonus)


# ── Hedef hesabı — PHP calculateBuySellTargets (index.php:11033) birebir ──────
def _ai_driven_stop_multiplier(adx_val: float) -> float:
    """PHP aiDrivenStopMultiplier (index.php:4998) birebir.
    Brain doğruluğu + ADX'e göre dinamik ATR çarpanı."""
    try:
        from .brain import brain_load
        b = brain_load()
        a = float(b.get("neural_net", {}).get("recent_accuracy", 50) or 50)
        bt = float(b.get("neural_net_beta", {}).get("recent_accuracy", 50) or 50)
        g = float(b.get("neural_net_gamma", {}).get("recent_accuracy", 50) or 50)
        avg = (a + bt + g) / 3
    except Exception:
        avg = 50.0
    base = 2.2 if adx_val >= 25 else 1.8
    if avg >= 70: return round(base * 0.73, 2)
    if avg >= 62: return round(base * 0.88, 2)
    if avg >= 54: return base
    if avg >= 46: return round(base * 1.22, 2)
    return round(base * 1.50, 2)


def calculate_buy_sell_targets(stock: dict, clustered_levels: list[dict] | None = None,
                               al_puani: int | None = None) -> dict:
    """PHP calculateBuySellTargets birebir.
    Dinamik ATR-adaptif stop + 3 hedef + bull/bear sinyal listesi.
    """
    fiyat = float(stock.get("guncel", 0) or 0)
    adil  = float(stock.get("adil", 0) or 0)
    if al_puani is None:
        al_puani = int(stock.get("alPuani", stock.get("aiScore", 0)) or 0)
    clustered_levels = clustered_levels or stock.get("clusteredLevels") or []

    if fiyat <= 0:
        return {"buy":0,"sell1":0,"sell2":0,"sell3":0,"stop":0,"rr1":0,"rr2":0,"rr3":0,
                "zone":"bekle","zoneScore":0,"stopPct":0,"gain1Pct":0,"gain2Pct":0,"gain3Pct":0,
                "stopMethod":"","buyMethod":"","confidence":0,"signals":[],
                "bullCount":0,"bearCount":0,"rr":0}

    atr      = float(stock.get("atr", stock.get("atr14", 0)) or 0)
    rsi      = float(stock.get("rsi", 50) or 50)
    sma20    = float(stock.get("sma20", 0) or 0)
    sma50    = float(stock.get("sma50", 0) or 0)
    sma200   = float(stock.get("sma200", 0) or 0)
    roc20    = float(stock.get("roc20", 0) or 0)
    vol_r    = float(stock.get("volRatio", 1.0) or 1.0)
    pos52    = float(stock.get("pos52wk", 50) or 50)
    cci      = float(stock.get("cci", 0) or 0)
    vwap     = float(stock.get("vwap", 0) or 0)
    wr       = float(stock.get("williamsR", -50) or -50)
    mfi      = float(stock.get("mfi", 50) or 50)
    cmf      = float(stock.get("cmf", 0) or 0)

    macd     = stock.get("macd") or {}
    macd_hist = float((macd.get("hist") if isinstance(macd, dict) else None) or stock.get("macdHist", 0) or 0)
    macd_cross = (macd.get("cross") if isinstance(macd, dict) else None) or stock.get("macdCross", "none")

    sr       = stock.get("stochRsi") or {}
    stoch_k  = float((sr.get("k") if isinstance(sr, dict) else None) or stock.get("stochK", 50) or 50)
    stoch_d  = float((sr.get("d") if isinstance(sr, dict) else None) or stock.get("stochD", 50) or 50)

    bb       = stock.get("bb") or {}
    bb_pct   = float((bb.get("pct") if isinstance(bb, dict) else None) or stock.get("bbPct", 50) or 50)
    bb_low   = float((bb.get("lower") if isinstance(bb, dict) else None) or 0)
    bb_high  = float((bb.get("upper") if isinstance(bb, dict) else None) or 0)
    bb_squeeze = bool((bb.get("squeeze") if isinstance(bb, dict) else None) or stock.get("bbSqueeze", False))

    sar      = stock.get("sar") or {}
    sar_dir  = (sar.get("direction") if isinstance(sar, dict) else None) or stock.get("sarDir", "notr")
    sar_val  = float((sar.get("sar") if isinstance(sar, dict) else None) or 0)

    ichi     = stock.get("ichimoku") or {}
    ichi_sig = (ichi.get("signal") if isinstance(ichi, dict) else None) or stock.get("ichiSig", "notr")
    ichi_tk  = (ichi.get("tkCross") if isinstance(ichi, dict) else None) or stock.get("ichiTkCross", "none")
    ichi_kumo_top = float((ichi.get("kumoTop") if isinstance(ichi, dict) else None) or 0)
    ichi_kumo_bot = float((ichi.get("kumoBot") if isinstance(ichi, dict) else None) or 0)
    ichi_tenkan = float((ichi.get("tenkan") if isinstance(ichi, dict) else None) or 0)
    ichi_kijun  = float((ichi.get("kijun") if isinstance(ichi, dict) else None) or 0)

    adx_d    = stock.get("adx") or {}
    adx_val  = float((adx_d.get("adx") if isinstance(adx_d, dict) else None) or stock.get("adxVal", 0) or 0)
    adx_dir  = (adx_d.get("dir") if isinstance(adx_d, dict) else None) or stock.get("adxDir", "notr")

    aroon    = stock.get("aroon") or {}
    a_up     = float((aroon.get("up") if isinstance(aroon, dict) else None) or stock.get("aroonUp", 50) or 50)
    a_dn     = float((aroon.get("down") if isinstance(aroon, dict) else None) or stock.get("aroonDown", 50) or 50)

    elder    = stock.get("elder") or {}
    elder_sig = (elder.get("signal") if isinstance(elder, dict) else None) or stock.get("elderSignal", "notr")

    don      = stock.get("donchian") or {}
    don_break = (don.get("breakout") if isinstance(don, dict) else None) or "none"
    don_upper = float((don.get("upper") if isinstance(don, dict) else None) or 0)
    don_lower = float((don.get("lower") if isinstance(don, dict) else None) or 0)

    div      = stock.get("divergence") or {}
    div_rsi  = (div.get("rsi") if isinstance(div, dict) else None) or stock.get("divRsi", "yok")
    div_macd = (div.get("macd") if isinstance(div, dict) else None) or stock.get("divMacd", "yok")

    st_d     = stock.get("supertrend") or {}
    st_dir   = (st_d.get("direction") if isinstance(st_d, dict) else None) or stock.get("supertrendDir", "notr")
    st_band  = float((st_d.get("value") if isinstance(st_d, dict) else None) or 0)

    ema_c_d  = stock.get("emaCross") or {}
    ema_cross_v = (ema_c_d.get("cross") if isinstance(ema_c_d, dict) else None) or stock.get("emaCrossDir", "none")
    ema_fast_above = bool((ema_c_d.get("fastAboveSlow") if isinstance(ema_c_d, dict) else None) or stock.get("emaFastAboveSlow", False))

    trix_d   = stock.get("trix") or {}
    trix_sig = (trix_d.get("signal") if isinstance(trix_d, dict) else None) or stock.get("trixSig", "notr")
    trix_cross = (trix_d.get("cross") if isinstance(trix_d, dict) else None) or stock.get("trixCross", "none")
    cmo_v    = float(stock.get("cmo", 0) or 0)
    ao_d     = stock.get("awesomeOsc") or {}
    ao_sig   = (ao_d.get("signal") if isinstance(ao_d, dict) else None) or stock.get("awesomeOscSig", "notr")
    ao_cross = (ao_d.get("cross") if isinstance(ao_d, dict) else None) or stock.get("awesomeOscCross", "none")
    hull_dir = stock.get("hullDir", "notr")
    pvt_dir  = stock.get("pvt", "notr")
    uo       = float(stock.get("ultimateOsc", 50) or 50)

    # Zone (al/limit/bekle/kacin)
    if   al_puani >= 130: zone = "al"
    elif al_puani >= 85:  zone = "limit"
    elif al_puani >= 45:  zone = "bekle"
    else:                  zone = "kacin"
    zone_score = min(200, int((al_puani / 250) * 200))

    # Immediate signals
    imm = 0
    if rsi < 30: imm += 1
    if stoch_k < 20 and stoch_k > stoch_d: imm += 1
    if macd_cross == "golden": imm += 1
    if wr <= -80: imm += 1
    if mfi < 20: imm += 1
    if bb_pct < 10: imm += 1
    if div_rsi == "boga" or div_macd == "boga": imm += 1
    if sar_dir == "yukselis" and sar_val > 0 and fiyat > sar_val * 1.001: imm += 1
    if ichi_tk == "golden": imm += 1
    if don_break == "yukari": imm += 1
    if cmf > 0.15 and macd_hist > 0: imm += 1
    if vol_r >= 2.0 and roc20 > 0: imm += 1
    if elder_sig == "guclu_boga": imm += 1
    if adx_dir == "yukselis" and adx_val >= 25: imm += 1
    if a_up >= 90 and a_dn < 20: imm += 1
    if st_dir == "yukselis": imm += 1
    if ema_cross_v == "golden": imm += 1
    if ao_cross == "bullish": imm += 1
    if trix_cross == "bullish": imm += 1
    if hull_dir == "yukselis" and ema_fast_above: imm += 1
    if uo < 30: imm += 1

    # Tüm destek/direnç toplama
    all_sup = []; all_res = []
    for lv in clustered_levels:
        lp = float(lv.get("price", 0) or 0); strength = int(lv.get("strength", 1) or 1)
        if lv.get("type") == "sup" and fiyat * 0.50 < lp < fiyat * 0.9985:
            all_sup.append({"price": lp, "strength": strength, "src": "swing"})
        if lv.get("type") == "res" and fiyat * 1.0015 < lp < fiyat * 2.5:
            all_res.append({"price": lp, "strength": strength, "src": "swing"})

    dyn_sup = [
        (sma20, "SMA20", 3), (sma50, "SMA50", 4), (sma200, "SMA200", 5),
        (bb_low, "BB Alt", 3),
        (sar_val if sar_dir == "yukselis" else 0, "SAR", 4),
        (ichi_kumo_top, "Kumo", 3), (ichi_kijun, "Kijun", 4),
        (vwap, "VWAP", 3), (don_lower, "Donchian", 2),
        (st_band if st_dir == "yukselis" and st_band > 0 else 0, "Supertrend", 4),
    ]
    for p, src, s in dyn_sup:
        if p > 0 and p < fiyat * 0.999:
            all_sup.append({"price": p, "strength": s, "src": src})

    dyn_res = [
        (sma20, "SMA20", 3), (sma50, "SMA50", 4), (sma200, "SMA200", 5),
        (bb_high, "BB Üst", 3),
        (sar_val if sar_dir == "dusus" else 0, "SAR", 4),
        (ichi_kumo_top, "Kumo", 3), (ichi_tenkan, "Tenkan", 3),
        (don_upper, "Donchian", 2),
    ]
    if adil > 0 and adil > fiyat * 1.04 and adil < fiyat * 4.0:
        dyn_res.append((adil, "Graham", 5))
    for p, src, s in dyn_res:
        if p > 0 and p > fiyat * 1.001:
            all_res.append({"price": p, "strength": s, "src": src})

    all_sup.sort(key=lambda x: -x["price"])
    all_res.sort(key=lambda x: x["price"])

    near_sup = 0.0; near_src = "fallback"
    for s in all_sup:
        if fiyat * 0.50 < s["price"] < fiyat * 0.999:
            if near_sup == 0 or s["price"] > near_sup:
                near_sup = s["price"]; near_src = s["src"]
    if near_sup <= 0:
        near_sup = fiyat * 0.92; near_src = "%8"

    res_levels = [r for r in all_res if r["price"] > fiyat * 1.015][:6]
    sup_dist = (fiyat - near_sup) / fiyat * 100

    # Buy logic
    if imm >= 5 and sup_dist < 8:
        buy_price = fiyat;            buy_method = f"MARKET({imm}sig)"
    elif imm >= 3 and sup_dist < 5:
        buy_price = fiyat * 0.999;    buy_method = "MARKET-YAKIN"
    elif imm >= 2 and sup_dist < 12:
        buy_price = max(near_sup * 1.005, fiyat * 0.985); buy_method = f"LİMİT-{near_src}"
    elif sar_dir == "yukselis" and sar_val > 0 and fiyat > sar_val:
        buy_price = sar_val * 1.005;  buy_method = "SAR"
    elif macd_cross == "golden" or ichi_tk == "golden":
        buy_price = fiyat * 0.998;    buy_method = "GOLDEN"
    elif bb_squeeze and don_break == "yukari":
        buy_price = fiyat;            buy_method = "MOMENTUM"
    elif sup_dist < 3:
        buy_price = near_sup * 1.003; buy_method = "DESTEK+"
    elif sup_dist < 10:
        buy_price = near_sup * 1.005; buy_method = "LİMİT"
    else:
        buy_price = near_sup * 1.005; buy_method = "DİP"
    buy_price = round(max(buy_price, fiyat * 0.70), 2)

    # Stop candidates
    stop_cands = []
    if atr > 0:
        am = _ai_driven_stop_multiplier(adx_val)
        stop_cands.append({"price": buy_price - atr * am, "src": f"ATR(AI×{round(am,2)})"})
    if near_sup > 0:
        stop_cands.append({"price": near_sup * 0.970, "src": "Des%3"})
        stop_cands.append({"price": near_sup * 0.980, "src": "Des%2"})
    if sar_val > 0 and sar_val < buy_price:
        stop_cands.append({"price": sar_val * 0.995, "src": "SAR"})
    if ichi_kumo_bot > 0 and ichi_kumo_bot < buy_price * 0.99:
        stop_cands.append({"price": ichi_kumo_bot * 0.985, "src": "Kumo"})
    if bb_low > 0 and bb_low < buy_price * 0.98:
        stop_cands.append({"price": bb_low * 0.985, "src": "BB"})
    if sma200 > 0 and sma200 < buy_price * 0.96:
        stop_cands.append({"price": sma200 * 0.975, "src": "SMA200"})

    stop_loss = 0.0; stop_method = "F"
    for sc in stop_cands:
        if sc["price"] > stop_loss and sc["price"] < buy_price * 0.99:
            stop_loss = sc["price"]; stop_method = sc["src"]

    max_sp = 0.12 if adx_val >= 30 else 0.09
    min_sp = 0.025
    if stop_loss <= 0 or stop_loss >= buy_price:
        stop_loss = buy_price * (1 - min_sp * 1.5); stop_method = "Varsayılan"
    stop_loss = max(stop_loss, buy_price * (1 - max_sp))
    stop_loss = min(stop_loss, buy_price * (1 - min_sp))
    stop_loss = round(stop_loss, 2)

    risk = max(buy_price - stop_loss, 0.0001)

    # Targets
    res_levels.sort(key=lambda r: r["price"])
    t1 = 0.0; t1_src = ""; t2 = 0.0; t2_src = ""; t3 = 0.0; t3_src = ""

    min_t1 = buy_price + risk * 1.5
    for r in res_levels:
        if r["price"] > min_t1: t1 = r["price"]; t1_src = r["src"]; break
    if t1 <= 0:
        t1 = buy_price + risk * 2.0; t1_src = "R/R2"

    min_t2 = max(t1 * 1.04, buy_price + risk * 3.0)
    for r in res_levels:
        if r["price"] > min_t2: t2 = r["price"]; t2_src = r["src"]; break
    if t2 <= 0 and adil > 0 and min_t2 < adil < buy_price * 4.0:
        t2 = adil; t2_src = "Graham"
    if t2 <= 0:
        t2 = buy_price + risk * 3.5; t2_src = "R/R3.5"

    min_t3 = max(t2 * 1.04, buy_price + risk * 5.0)
    for r in res_levels:
        if r["price"] > min_t3: t3 = r["price"]; t3_src = r["src"]; break
    if t3 <= 0 and adil > 0 and min_t3 < adil < buy_price * 4.0:
        t3 = adil; t3_src = "Graham"
    if t3 <= 0:
        t3 = buy_price + risk * 6.0; t3_src = "R/R6"

    if t2 <= t1 * 1.02: t2 = t1 * 1.05
    if t3 <= t2 * 1.02: t3 = t2 * 1.07
    t1 = round(t1, 2); t2 = round(t2, 2); t3 = round(t3, 2)

    confidence = min(100, int((al_puani / 250) * 85 + imm * 2))
    rr1 = round((t1 - buy_price) / risk, 1) if risk > 0 else 0
    rr2 = round((t2 - buy_price) / risk, 1) if risk > 0 else 0
    rr3 = round((t3 - buy_price) / risk, 1) if risk > 0 else 0

    # Sinyal listesi
    sig_defs = [
        (rsi < 30, "🟢", "RSI aşırı satım"),
        (rsi > 70, "🔴", "RSI aşırı alım"),
        (macd_cross == "golden", "🟢", "MACD Golden"),
        (macd_cross == "death",  "🔴", "MACD Death"),
        (stoch_k < 20, "🟢", "StochRSI dip"),
        (stoch_k > 80, "🔴", "StochRSI zirve"),
        (bb_pct < 10, "🟢", "BB alt"),
        (bb_squeeze,  "🟡", "BB sıkış"),
        (sar_dir == "yukselis", "🟢", "SAR ↑"),
        (sar_dir == "dusus",    "🔴", "SAR ↓"),
        (ichi_sig == "ustunde", "🟢", "Bulut üstü"),
        (ichi_sig == "altinda", "🔴", "Bulut altı"),
        (ichi_tk  == "golden",  "🟢", "İchi TK Golden"),
        (ichi_tk  == "death",   "🔴", "İchi TK Death"),
        (mfi < 20, "🟢", "MFI aşırı satım"),
        (mfi > 80, "🔴", "MFI aşırı alım"),
        (cmf > 0.15,  "🟢", "CMF para girişi"),
        (cmf < -0.15, "🔴", "CMF çıkış"),
        (adx_dir == "yukselis" and adx_val >= 25, "🟢", "ADX güçlü ↑"),
        (div_rsi  == "boga", "⚡", "RSI Diverjans"),
        (div_macd == "boga", "⚡", "MACD Diverjans"),
        (vol_r >= 2 and roc20 > 0, "🟢", "Hacim↑ Momentum"),
        (don_break == "yukari",   "🟢", "Donchian kırılım"),
        (pos52 <= 15, "🟢", "52H dip"),
        (st_dir == "yukselis", "🟢", "Supertrend ↑"),
        (st_dir == "dusus",    "🔴", "Supertrend ↓"),
        (ema_cross_v == "golden", "🟢", "EMA 9/21 Golden"),
        (ema_cross_v == "death",  "🔴", "EMA 9/21 Death"),
        (ema_cross_v == "none" and ema_fast_above,     "🟢", "EMA 9 > 21"),
        (ema_cross_v == "none" and not ema_fast_above, "🔴", "EMA 9 < 21"),
        (ao_cross == "bullish",  "🟢", "AO Sıfır ↑"),
        (ao_cross == "bearish",  "🔴", "AO Sıfır ↓"),
        (trix_cross == "bullish","🟢", "TRIX Kesişim ↑"),
        (trix_cross == "bearish","🔴", "TRIX Kesişim ↓"),
        (cmo_v < -50, "🟢", "CMO aşırı satım"),
        (cmo_v >  50, "🔴", "CMO aşırı alım"),
        (hull_dir == "yukselis", "🟢", "Hull MA ↑"),
        (hull_dir == "dusus",    "🔴", "Hull MA ↓"),
        (pvt_dir == "artis",     "🟢", "PVT artış"),
        (uo < 30, "🟢", "UO aşırı satım"),
        (uo > 70, "🔴", "UO aşırı alım"),
    ]
    sigs = [(emoji, name) for cond, emoji, name in sig_defs if cond]
    bull_count = sum(1 for s in sigs if s[0] in ("🟢", "⚡"))
    bear_count = sum(1 for s in sigs if s[0] == "🔴")

    return {
        "buy": buy_price, "sell1": t1, "sell2": t2, "sell3": t3, "stop": stop_loss,
        "rr1": rr1, "rr2": rr2, "rr3": rr3, "rr": rr1,
        "zone": zone, "zoneScore": zone_score,
        "stopPct":  round((buy_price - stop_loss) / buy_price * 100, 1),
        "gain1Pct": round((t1 - buy_price) / buy_price * 100, 1),
        "gain2Pct": round((t2 - buy_price) / buy_price * 100, 1),
        "gain3Pct": round((t3 - buy_price) / buy_price * 100, 1),
        "stopMethod": stop_method, "buyMethod": buy_method,
        "confidence": confidence, "signals": sigs,
        "bullCount": bull_count, "bearCount": bear_count,
        "immediateSignals": imm,
        "t1Src": t1_src, "t2Src": t2_src, "t3Src": t3_src,
    }


# ── PHP smcScoreBonus birebir port ───────────────────────────────────────────
def smc_score_bonus(smc: dict | None, current_price: float) -> int:
    """SMC yapısına göre AI skoruna katkı (-40..+60).

    Bias bullish: +18 baz, bullish OB içinde fiyat → +strength/10,
    bullish FVG içinde → +10, likidite süpürme → +strength/8,
    BOS bullish_bos → +15, bullish → +8, CHoCH → +12.
    Bias bearish: -15 baz, simetrik düşüşler.
    """
    if not smc or not isinstance(smc, dict):
        return 0
    bonus = 0
    bias = smc.get("bias", "notr")
    cp = float(current_price or 0)

    if bias == "bullish":
        bonus += 18
        for ob in (smc.get("orderBlocks") or []):
            if not isinstance(ob, dict): continue
            if (ob.get("type") != "bullish") or ob.get("mitigated"):
                continue
            top = float(ob.get("top", 0) or 0); bot = float(ob.get("bot", 0) or 0)
            if cp >= bot and cp <= top * 1.02:
                bonus += int(round(float(ob.get("strength", 0) or 0) / 10))
        for fvg in (smc.get("fvg") or []):
            if not isinstance(fvg, dict): continue
            if fvg.get("type") == "bullish" and not fvg.get("filled"):
                top = float(fvg.get("top", 0) or 0); bot = float(fvg.get("bot", 0) or 0)
                if cp >= bot and cp <= top * 1.01:
                    bonus += 10
        ls = smc.get("liquiditySweep") or {}
        if ls.get("bullish"):
            bonus += int(round(float(ls.get("strength", 0) or 0) / 8))
        bos = smc.get("bos", "")
        if bos == "bullish_bos": bonus += 15
        if bos == "bullish":     bonus += 8
        if smc.get("choch"):     bonus += 12
    elif bias == "bearish":
        bonus -= 15
        for ob in (smc.get("orderBlocks") or []):
            if (ob.get("type") != "bearish") or ob.get("mitigated"):
                continue
            top = float(ob.get("top", 0) or 0); bot = float(ob.get("bot", 0) or 0)
            if cp <= top and cp >= bot * 0.98:
                bonus -= int(round(float(ob.get("strength", 0) or 0) / 12))
        ls = smc.get("liquiditySweep") or {}
        if ls.get("bearish"): bonus -= 10
        bos = smc.get("bos", "")
        if isinstance(bos, str) and bos.startswith("bearish"):
            bonus -= 12

    return max(-40, min(60, bonus))


# ── PHP analyzeTechnical wrapper — chart_data alıp tam tech dict döner ───────
def analyze_technical(chart_data: list[dict]) -> dict:
    """PHP analyzeTechnical($chartData) sarmalayıcısı.

    chart_data: [{Open, High, Low, Close, Volume}, ...] formatında.
    scan.py'nin tüm tech alanlarını (sma, rsi, macd, bb, atr, adx, sar, ichi,
    aroon, vwap, elder, donchian, divergence, supertrend, trix, ao, smc,
    vwapBands, ofi, harmonics, techScore...) PHP ile birebir uyumlu döndürür.
    """
    from . import indicators as _ind, smc as _smc

    if not chart_data or not isinstance(chart_data, list) or len(chart_data) < 50:
        return {"sup": 0, "res": 0, "trend": "Notr", "rsi": 50, "techScore": 0,
                "sma20": 0, "sma50": 0, "sma200": 0, "atr": 0,
                "macd": {"macd": 0, "signal": 0, "hist": 0, "cross": "none"},
                "bb": {"pct": 50, "lower": 0, "upper": 0, "squeeze": False}}

    o = [float(b.get("Open", b.get("Close", 0)) or 0) for b in chart_data]
    h = [float(b.get("High", b.get("Close", 0)) or 0) for b in chart_data]
    l = [float(b.get("Low",  b.get("Close", 0)) or 0) for b in chart_data]
    c = [float(b.get("Close", 0) or 0) for b in chart_data]
    v = [float(b.get("Volume", 0) or 0) for b in chart_data]
    cnt = len(c); cur = c[-1]

    s365 = c[-min(365, cnt):]
    sup, res = min(s365), max(s365)
    sma20  = _ind.sma(c, 20)  if cnt >= 20  else cur
    sma50  = _ind.sma(c, 50)  if cnt >= 50  else sma20
    sma200 = _ind.sma(c, 200) if cnt >= 200 else sma50

    if   sma20 > sma50 and sma50 > sma200: trend = "Yukselis"
    elif sma20 < sma50 and sma50 < sma200: trend = "Dusus"
    else:                                    trend = "Notr"

    rsi   = _ind.rsi(c)
    macd  = _ind.macd(c)
    stoch = _ind.stoch_rsi(c) if hasattr(_ind, "stoch_rsi") else {"k": 50, "d": 50}
    bb    = _ind.bollinger(c)
    atr   = _ind.atr(h, l, c)
    obv_t = _ind.obv(c, v).get("trend", "notr")
    roc20 = _ind.roc(c, 20); roc60 = _ind.roc(c, 60)
    roc5  = (c[-1] - c[-6]) / max(c[-6], 0.0001) * 100 if cnt >= 6 else 0
    wr    = _ind.williams_r(h, l, c)
    adx   = _ind.adx(h, l, c)
    mfi   = _ind.mfi(h, l, c, v); cmf = _ind.cmf(h, l, c, v)
    sar   = _ind.parabolic_sar(h, l)
    ichi  = _ind.ichimoku(h, l, c)
    aroon = _ind.aroon(h, l)
    vwap  = _ind.vwap(h, l, c, v)
    elder = _ind.elder_ray(h, c)
    donch = _ind.calculate_donchian_breakout(h, l, c)
    cci   = _ind.cci(h, l, c)
    vol_r = _ind.vol_ratio(v); vol_m = _ind.vol_momentum(v)
    p52   = _ind.pos_52wk(c)
    hull  = _ind.hull_ma(c, 20)
    kelt  = _ind.keltner(h, l, c)
    uo    = _ind.ultimate_osc(h, l, c)
    st    = _ind.supertrend(h, l, c)
    trix  = _ind.trix(c)
    cmo   = _ind.chande_mo(c)
    ao    = _ind.awesome_osc(h, l)
    pvt_t = _ind.calculate_pvt(c, v)
    fib   = _ind.calculate_fibonacci_levels(h, l)

    bb_lo = float(bb.get("lower", 0) or 0); bb_hi = float(bb.get("upper", 0) or 0)
    bb_pct = ((cur - bb_lo) / (bb_hi - bb_lo) * 100) if bb_hi > bb_lo else 50.0
    bb["pct"] = bb_pct

    rsi_arr = [_ind.rsi(c[:i + 1]) for i in range(max(0, cnt - 25), cnt)]
    div = {"rsi": _ind.detect_rsi_divergence(c[-25:], rsi_arr),
           "macd": _ind.detect_macd_divergence(c)}

    smc_full = _smc.smc_analyze(h, l, o, c, v)
    ofi      = _smc.order_flow_imbalance(c, v)

    # ── techScore (PHP birebir) ─────────────────────────────────────────────
    ts = 50
    if   rsi < 20: ts += 20
    elif rsi < 30: ts += 14
    elif rsi < 40: ts += 7
    elif rsi > 80: ts -= 18
    elif rsi > 70: ts -= 10
    if macd["hist"] > 0: ts += 8
    if macd["cross"] == "golden": ts += 15
    elif macd["cross"] == "death": ts -= 15
    if macd["macd"] > 0 and macd["hist"] > 0: ts += 5
    elif macd["macd"] < 0 and macd["hist"] < 0: ts -= 5
    sk, sd = stoch["k"], stoch["d"]
    if sk < 20 and sk > sd: ts += 15
    elif sk < 20: ts += 10
    elif sk > 80 and sk < sd: ts -= 15
    elif sk > 80: ts -= 10
    if   bb_pct < 5:  ts += 12
    elif bb_pct < 20: ts += 7
    elif bb_pct > 95: ts -= 12
    elif bb_pct > 80: ts -= 7
    if bb.get("squeeze"): ts += 5
    if cur > sma20 and sma20 > sma50 and sma50 > sma200: ts += 15
    elif cur > sma20 and sma20 > sma50: ts += 8
    elif cur < sma20 and sma20 < sma50 and sma50 < sma200: ts -= 15
    elif cur < sma20 and sma20 < sma50: ts -= 8
    ts += 10 if sma50 > sma200 else -10
    ts += 10 if obv_t == "artis" else -5
    if   roc20 >  10: ts += 8
    elif roc20 >   5: ts += 4
    elif roc20 < -15: ts -= 8
    elif roc20 <  -5: ts -= 4
    if sup > 0:
        sd_pct = (cur - sup) / max(cur, 0.0001) * 100
        if   sd_pct < 2:  ts += 10
        elif sd_pct < 5:  ts += 6
        elif sd_pct > 40: ts -= 5
    if   wr < -80: ts += 8
    elif wr > -20: ts -= 6
    if adx["val"] >= 25 and adx["dir"] == "yukselis": ts += 10
    elif adx["val"] >= 25 and adx["dir"] == "dusus":  ts -= 8
    if   mfi < 20: ts += 8
    elif mfi > 80: ts -= 8
    if   cmf > 0.1:  ts += 6
    elif cmf < -0.1: ts -= 6
    ts += 8 if sar["dir"] == "yukselis" else -5
    if   ichi["sig"] == "ustunde": ts += 10
    elif ichi["sig"] == "altinda": ts -= 10
    if aroon.get("up", 50) > 70 and aroon.get("down", 50) < 30: ts += 8
    elif aroon.get("down", 50) > 70 and aroon.get("up", 50) < 30: ts -= 8
    vw_v = float(vwap.get("vwap", 0) or 0)
    if cur > vw_v and vw_v > 0: ts += 5
    elif cur < vw_v and vw_v > 0: ts -= 3
    if div["rsi"] == "boga": ts += 12
    if div["rsi"] == "ayi":  ts -= 10
    if   cci < -100: ts += 7
    elif cci >  100: ts -= 7
    if vol_r > 2.0 and roc20 > 0: ts += 6
    if donch.get("breakout") == "yukari": ts += 8
    if hull["dir"] == "yukselis": ts += 7
    elif hull["dir"] == "dusus":  ts -= 6
    if   kelt.get("pos") == "alt_bant":  ts += 5
    elif kelt.get("pos") == "ust_bant":  ts -= 5
    if   uo < 30: ts += 9
    elif uo < 40: ts += 5
    elif uo > 70: ts -= 9
    elif uo > 60: ts -= 5
    if   st["dir"] == "yukselis": ts += 8
    elif st["dir"] == "dusus":    ts -= 8
    if   trix.get("cross") == "bullish": ts += 7
    elif trix.get("cross") == "bearish": ts -= 7
    if   cmo < -50: ts += 8
    elif cmo < -30: ts += 4
    elif cmo >  50: ts -= 8
    elif cmo >  30: ts -= 4
    if   ao.get("cross") == "bullish": ts += 8
    elif ao.get("cross") == "bearish": ts -= 8
    if elder.get("signal") == "guclu_boga": ts += 6
    elif elder.get("signal") == "guclu_ayi":  ts -= 5
    if pvt_t == "artis": ts += 5
    elif pvt_t == "dusus": ts -= 4
    if   roc5 >  4: ts += 6
    elif roc5 >  2: ts += 3
    elif roc5 < -4: ts -= 6
    elif roc5 < -2: ts -= 3
    if   roc60 >  20: ts += 7
    elif roc60 >   8: ts += 3
    elif roc60 < -25: ts -= 7
    elif roc60 < -10: ts -= 3
    # SMC techScore katkısı
    sb = smc_full.get("bias", "notr")
    if sb == "bullish":
        ts += 12
        if smc_full.get("bos") == "bullish_bos": ts += 8
        if (smc_full.get("liquiditySweep") or {}).get("bullish"): ts += 6
        if smc_full.get("choch"): ts += 5
    elif sb == "bearish":
        ts -= 10
        if str(smc_full.get("bos", "")).startswith("bearish_bos"): ts -= 8
        if (smc_full.get("liquiditySweep") or {}).get("bearish"): ts -= 6
    # OFI katkısı
    if   ofi == "guclu_alis":  ts += 10
    elif ofi == "alis":         ts += 5
    elif ofi == "guclu_satis": ts -= 10
    elif ofi == "satis":        ts -= 5

    return {
        "sup": sup, "res": res, "trend": trend,
        "rsi": rsi, "macd": macd, "stochRsi": stoch, "bb": bb,
        "atr": atr, "roc5": round(roc5, 1), "roc20": roc20, "roc60": roc60,
        "obv": obv_t,
        "sma20": sma20, "sma50": sma50, "sma200": sma200,
        "techScore": max(0, min(100, ts)),
        "williamsR": round(wr, 1),
        "adx": {"adx": adx["val"], "dir": adx["dir"],
                "diPlus": adx.get("plusDI", 0), "diMinus": adx.get("minusDI", 0)},
        "mfi": round(mfi, 1), "cmf": round(cmf, 3),
        "sar": {"direction": sar["dir"], "sar": float(sar.get("sar", 0) or 0)},
        "ichimoku": ichi, "aroon": aroon,
        "vwap": vw_v, "elder": elder, "donchian": donch, "divergence": div,
        "cci": cci, "volRatio": vol_r, "volMomentum": vol_m, "pos52wk": p52,
        "hullDir": hull["dir"], "hullVal": float(hull.get("val", 0) or 0),
        "keltner": kelt, "ultimateOsc": uo,
        "supertrend": {"direction": st["dir"], "value": float(st.get("val", 0) or 0)},
        "trix": trix, "cmo": round(cmo, 1),
        "awesomeOsc": ao, "fibonacci": fib, "pvt": pvt_t,
        "smc": smc_full, "ofi": {"signal": ofi},
    }


# ── Consensus (unchanged) ─────────────────────────────────────────────────────
def calculate_consensus(stock: dict) -> dict:
    """7 alt-sistemden boğa/ayı oy sayar."""
    bull = bear = 0
    if stock.get("macdCross") == "golden":   bull += 1
    elif stock.get("macdCross") == "death":  bear += 1
    if stock.get("supertrendDir") == "yukselis": bull += 1
    elif stock.get("supertrendDir") == "dusus":  bear += 1
    if stock.get("smcBias") == "bullish":    bull += 1
    elif stock.get("smcBias") == "bearish":  bear += 1
    if stock.get("ofiSig") in ("alis", "guclu_alis"):   bull += 1
    elif stock.get("ofiSig") in ("satis", "guclu_satis"): bear += 1
    if stock.get("ichiSig") == "ustunde":    bull += 1
    elif stock.get("ichiSig") == "altinda":  bear += 1
    if stock.get("divRsi") == "boga":        bull += 1
    elif stock.get("divRsi") == "ayi":       bear += 1
    if stock.get("hullDir") == "yukselis":   bull += 1
    elif stock.get("hullDir") == "dusus":    bear += 1
    return {"agree_bull": bull, "agree_bear": bear, "total": 7}


def calculate_consensus_multiplier(signals: list[str]) -> float:
    """PHP calculateConsensusMultiplier (index.php:9336) v28 birebir.
    signals: ['bull','bear','bull',...] gibi. 1.0 nötr, 1.45 max boğa, 0.55 min ayı."""
    bull = sum(1 for s in signals if s == "bull")
    bear = sum(1 for s in signals if s == "bear")
    total = bull + bear
    if total == 0: return 1.0
    ratio = bull / total
    if   ratio >= 1.00: return 1.45
    elif ratio >= 0.87: return 1.30
    elif ratio >= 0.75: return 1.18
    elif ratio >= 0.65: return 1.08
    elif ratio >= 0.55: return 1.02
    elif ratio >= 0.45: return 0.98
    elif ratio >= 0.35: return 0.92
    elif ratio >= 0.25: return 0.82
    elif ratio >= 0.13: return 0.72
    elif ratio >  0.00: return 0.62
    return 0.55
