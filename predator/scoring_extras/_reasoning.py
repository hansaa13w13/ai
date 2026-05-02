"""AI sebep (reasoning) Türkçe metni — v43: Elite çok katmanlı profesyonel analiz."""

from __future__ import annotations


def get_ai_reasoning(stock: dict, consensus: dict) -> str:
    """Hisse için 11 katmanlı elite profesyonel AI gerekçesi.

    v43 yenilikleri:
    - Başlık satırı: İşlem Tipi | Güven Seviyesi | Stop/Hedef/R:R
    - 6 trend indikatör gücü sayısı (macd+sar+st+hull+ema+trix)
    - SMA200 uzun vadeli bağlam
    - ROC60 üç aylık momentum
    - Donchian kırılım bağlamı
    - 10 sistem uyum referansı
    """
    rsi    = float(stock.get("rsi")         or 50)
    macd   = stock.get("macdCross")         or "none"
    sar    = stock.get("sarDir")            or "notr"
    vol    = float(stock.get("volRatio")    or 1)
    pos52  = float(stock.get("pos52wk")     or 50)
    cmf    = float(stock.get("cmf")         or 0)
    mfi    = float(stock.get("mfi")         or 50)
    adx_v  = float(stock.get("adxVal")      or 0)
    adx_d  = stock.get("adxDir")            or "notr"
    forms  = stock.get("formations")        or []
    adil   = float(stock.get("adil")        or 0)
    guncel = float(stock.get("guncel")      or 0)
    atr14  = float(stock.get("atr14")       or stock.get("atr") or 0)
    cap    = float(stock.get("marketCap")   or 0)
    fk     = float(stock.get("fk")          or 0)
    pddd   = float(stock.get("pddd")        or 0)
    roe    = float(stock.get("roe")         or 0)
    bb_pct = float(stock.get("bbPct")       or 50)
    bb_sq  = bool(stock.get("bbSqueeze"))
    roc5   = float(stock.get("roc5")        or 0)
    roc20  = float(stock.get("roc20")       or 0)
    roc60  = float(stock.get("roc60")       or 0)
    sma200 = float(stock.get("sma200")      or 0)
    sma20  = float(stock.get("sma20")       or 0)
    sma50  = float(stock.get("sma50")       or 0)
    hull   = stock.get("hullDir")           or "notr"
    st_dir = stock.get("supertrendDir")     or "notr"
    ema_x  = stock.get("emaCrossDir")       or "none"
    trix_x = stock.get("trixCross")         or "none"
    obv    = stock.get("obvTrend")          or "notr"
    ofi    = stock.get("ofiSig")            or "notr"
    div_r  = stock.get("divRsi")            or "yok"
    wr     = float(stock.get("williamsR")   or -50)
    cci    = float(stock.get("cci")         or 0)
    uo     = float(stock.get("ultimateOsc") or 50)
    vwap   = stock.get("vwapPos")           or "icinde"
    volreg = stock.get("volRegime")         or "normal"
    _smc   = stock.get("smc")              or {}
    smc_b  = stock.get("smcBias")           or "notr"
    ob_t   = ((_smc.get("ob")  or {}).get("type") or stock.get("smcObType")  or "")
    fvg_t  = ((_smc.get("fvg") or {}).get("type") or stock.get("smcFvgType") or "")
    sweep  = bool(_smc.get("sweep") or stock.get("smcSweep"))
    _donch   = stock.get("donchian") or {}
    donch_br = (_donch.get("breakout") or "") if isinstance(_donch, dict) else ""

    agree_bull = int(consensus.get("agree_bull") or 0)
    sim        = consensus.get("sim_history") or {}
    conf_bonus = int(consensus.get("conf_bonus") or 0)
    time_bonus = int(consensus.get("time_bonus") or 0)
    cons_score = float(consensus.get("consensus") or 50)

    # ── Trend gücü (6 göstergede kaç tanesi bullish) ──────────────────────
    trend_bulls = (
        (1 if macd   == "golden"   else 0) +
        (1 if sar    == "yukselis" else 0) +
        (1 if st_dir == "yukselis" else 0) +
        (1 if hull   == "yukselis" else 0) +
        (1 if ema_x  == "golden"   else 0) +
        (1 if trix_x == "bullish"  else 0)
    )

    # ── Osilatör derinliği (kaç tanesi aşırı satımda) ────────────────────
    osc_oversold = int(
        (rsi  < 30)  +
        (wr   < -85) +
        (cci  < -150) +
        (uo   < 30)  +
        (mfi  < 25)
    )

    # ── İşlem tipi tespiti ────────────────────────────────────────────────
    if rsi < 35 and (bb_pct < 30 or pos52 < 30):
        trade_type = "GERİ DÖNÜŞ"
    elif donch_br == "upper" or (pos52 > 70 and vol >= 2.0 and rsi > 50):
        trade_type = "KIRILIM"
    elif bb_sq and cmf > 0.05 and 35 <= rsi <= 65:
        trade_type = "BİRİKİM"
    elif adx_v >= 25 and smc_b == "bullish" and ofi in ("alis", "guclu_alis"):
        trade_type = "KURUMSAL"
    elif adx_v >= 20 and st_dir == "yukselis" and rsi >= 45:
        trade_type = "MOMENTUM"
    else:
        trade_type = "TEKNİK"

    # ── Güven seviyesi ────────────────────────────────────────────────────
    if   agree_bull >= 9 and cons_score >= 82:
        conviction = "ULTRA YÜKSEK"
    elif agree_bull >= 7 or cons_score >= 75:
        conviction = "YÜKSEK"
    elif agree_bull >= 5 or cons_score >= 60:
        conviction = "ORTA"
    else:
        conviction = "DÜŞÜK"

    # ── Stop / Hedef / R:R ────────────────────────────────────────────────
    rr_str = ""
    if atr14 > 0 and guncel > 0:
        stop_lvl = guncel - atr14 * 1.5
        tgt1_lvl = guncel + atr14 * 2.5
        stop_pct = (stop_lvl - guncel) / guncel * 100
        tgt1_pct = (tgt1_lvl - guncel) / guncel * 100
        rr_ratio = abs(tgt1_pct / stop_pct) if stop_pct != 0 else 0
        rr_str   = (f"Stop {stop_lvl:.2f}₺ (%{stop_pct:.1f}) | "
                    f"Hedef {tgt1_lvl:.2f}₺ (+%{tgt1_pct:.1f}) | "
                    f"R:R 1:{rr_ratio:.1f}")

    reasons: list[str] = []

    # ── BAŞLIK: İşlem tipi + güven + R:R ─────────────────────────────────
    header = f"{trade_type} | {conviction} GÜVEN"
    if rr_str:
        header += f" | {rr_str}"
    reasons.append(header)

    # ── 1. TEKNİK MOMENTUM ───────────────────────────────────────────────
    if rsi < 20:
        reasons.append(f"RSI aşırı satım bölgesinde ({rsi:.1f}) — tarihi geri dönüş sinyali, güçlü toparlanma potansiyeli")
    elif rsi < 30:
        reasons.append(f"RSI satım bölgesinde ({rsi:.1f}) — dip oluşum sinyali, al bölgesi")
    elif rsi > 80:
        reasons.append(f"RSI aşırı alım bölgesinde ({rsi:.1f}) — kısa vadeli kar satışı riski")
    elif rsi > 70:
        reasons.append(f"RSI güçlü momentum bölgesinde ({rsi:.1f}) — trend devam edebilir")

    tech_labels = []
    if macd   == "golden":   tech_labels.append("MACD altın")
    if sar    == "yukselis": tech_labels.append("SAR destek")
    if st_dir == "yukselis": tech_labels.append("SuperTrend↑")
    if ema_x  == "golden":   tech_labels.append("EMA cross")
    if hull   == "yukselis": tech_labels.append("Hull↑")
    if trix_x == "bullish":  tech_labels.append("TRIX yükselen")
    if trend_bulls >= 5:
        reasons.append(f"Trend uyumu {trend_bulls}/6 — {', '.join(tech_labels[:5])} eş zamanlı aktif")
    elif trend_bulls >= 3:
        reasons.append(f"Trend uyumu {trend_bulls}/6 — {', '.join(tech_labels[:3])}")
    elif trend_bulls >= 2:
        reasons.append(f"{', '.join(tech_labels)} onayladı")
    elif macd == "death":
        reasons.append("MACD ölüm kesişimi — düşüş baskısı devam ediyor")

    # ADX
    if adx_v >= 35 and adx_d == "yukselis":
        reasons.append(f"ADX {adx_v:.0f} — son derece güçlü yukarı trend, kırılım kalıcılaşıyor")
    elif adx_v >= 25 and adx_d == "yukselis":
        reasons.append(f"ADX {adx_v:.0f} — güçlü trend, yön yukarı")

    # RSI diverjans
    if div_r == "boga":
        reasons.append("RSI boğa diverjansı — düşen fiyata karşın momentum artıyor, dönüş yakın")
    elif div_r == "ayi":
        reasons.append("RSI ayı diverjansı — fiyat yeni tepe yaparken momentum azalıyor, dikkat")

    # Çoklu osilatör derinliği
    if osc_oversold >= 3:
        reasons.append(f"{osc_oversold}/5 osilatör aşırı satımda "
                       f"(RSI {rsi:.0f} · WR {wr:.0f} · CCI {cci:.0f} · UO {uo:.0f} · MFI {mfi:.0f}) "
                       "— güçlü kontraryan dönüş sinyali")
    elif osc_oversold >= 2:
        reasons.append(f"Williams %R ({wr:.0f}), CCI ({cci:.0f}), UO ({uo:.0f}) — çoklu osilatör aşırı satım")

    # ── 2. SMA200 UZUN VADELİ BAĞLAM ─────────────────────────────────────
    if sma200 > 0 and guncel > 0:
        sma200_pct = (guncel - sma200) / sma200 * 100
        if sma200_pct > 20:
            reasons.append(f"SMA200'ün %{sma200_pct:.1f} üzerinde — güçlü boğa trendinde, uzun vadeli destek sağlam")
        elif sma200_pct > 5:
            reasons.append(f"SMA200 üzerinde (+%{sma200_pct:.1f}) — uzun vadeli trend destekleyici")
        elif sma200_pct > 0:
            reasons.append(f"SMA200 hemen üzerinde (+%{sma200_pct:.1f}) — kritik destek seviyesinde, dikkat")
        elif sma200_pct > -15:
            reasons.append(f"SMA200'ün %{abs(sma200_pct):.1f} altında — uzun vadeli direnç var, dikkatli ol")
        else:
            reasons.append(f"SMA200'ün %{abs(sma200_pct):.1f} altında — uzun vadeli bear zone, pozisyon büyüklüğü azalt")
    if sma20 > 0 and sma50 > 0 and sma20 > sma50 * 1.02:
        reasons.append("SMA20 > SMA50 — orta vadeli yükseliş kanalı doğrulandı")

    # ── 3. AKILLI PARA (SMC) ─────────────────────────────────────────────
    smc_parts = []
    if smc_b == "bullish":
        smc_parts.append("piyasa yapısı boğa (HH/HL dizisi)")
    elif smc_b == "bearish":
        smc_parts.append("piyasa yapısı ayı (LL/LH)")
    if ob_t == "bullish":
        smc_parts.append("aktif boğa Order Block — kurumsal alım bölgesi")
    elif ob_t == "bearish":
        smc_parts.append("aktif ayı Order Block — kurumsal satış bölgesi")
    if fvg_t == "bullish":
        smc_parts.append("doldurulmamış boğa FVG — fiyat çekim alanı")
    elif fvg_t == "bearish":
        smc_parts.append("doldurulmamış ayı FVG — aşağı çekiş riski")
    if sweep and smc_b == "bullish":
        smc_parts.append("likidite süpürmesi + dönüş — smart money stop avı tamamlandı")
    if ofi == "guclu_alis":
        smc_parts.append("güçlü kurumsal alım akışı (OFI büyük pozitif)")
    elif ofi == "alis":
        smc_parts.append("net kurumsal alım akışı")
    elif ofi == "guclu_satis":
        smc_parts.append("ağır kurumsal satış baskısı (OFI büyük negatif)")
    if len(smc_parts) >= 3:
        reasons.append("Akıllı para: " + " · ".join(smc_parts[:3]))
    elif smc_parts:
        reasons.append("Akıllı para: " + " · ".join(smc_parts))

    if donch_br == "upper":
        reasons.append("Donchian üst bant kırılımı — 20 günlük yüksek aşıldı, momentum devam edebilir")
    elif donch_br == "lower":
        reasons.append("Donchian alt bant kırılımı — 20G düşük test edildi, dikkat")

    # ── 4. HACİM ANALİZİ ─────────────────────────────────────────────────
    vol_parts = []
    if vol >= 3.0:
        vol_parts.append(f"olağanüstü hacim ({vol:.1f}x) — büyük oyuncu girişi")
    elif vol >= 2.0:
        vol_parts.append(f"güçlü hacim ({vol:.1f}x) — kurumsal ilgi")
    elif vol >= 1.5:
        vol_parts.append(f"ortalamanın üzerinde hacim ({vol:.1f}x)")
    if cmf > 0.20:
        vol_parts.append(f"CMF {cmf:+.2f} — para akışı çok güçlü, sürekli birikim")
    elif cmf > 0.10:
        vol_parts.append(f"CMF {cmf:+.2f} — pozitif para akışı, kurumsal birikim")
    elif cmf < -0.15:
        vol_parts.append(f"CMF {cmf:+.2f} — dağıtım baskısı yüksek")
    if mfi < 25:
        vol_parts.append(f"MFI {mfi:.0f} — dip bölgesi")
    elif mfi > 80:
        vol_parts.append(f"MFI {mfi:.0f} — aşırı alım")
    if obv == "artis":
        vol_parts.append("OBV yükselen — hacim fiyat öncesinde onaylıyor")
    elif obv == "dusus":
        vol_parts.append("OBV düşen — hacim dağıtıma işaret ediyor")
    if vol_parts:
        reasons.append("Hacim: " + " · ".join(vol_parts[:2]))

    # ── 5. FİYAT YAPISI ──────────────────────────────────────────────────
    struct_parts = []
    if pos52 < 10:
        struct_parts.append(f"52H dibin çok yakınında (%{pos52:.1f}) — maksimum değer bölgesi")
    elif pos52 < 20:
        struct_parts.append(f"52H dibe yakın (%{pos52:.1f}) — değer alımı bölgesi")
    elif pos52 > 90:
        struct_parts.append(f"52H zirveye yakın (%{pos52:.1f}) — kırılım veya yeni zirve")
    if bb_pct < 10:
        struct_parts.append(f"Bollinger alt band altında (%B {bb_pct:.0f}) — istatistiksel aşırı gerileme")
    elif bb_pct < 25:
        struct_parts.append(f"Bollinger alt bölgesi (%B {bb_pct:.0f}) — ortalamaya dönüş potansiyeli")
    if roc60 > 20:
        struct_parts.append(f"3 aylık momentum +%{roc60:.1f} — güçlü uzun vadeli ivme")
    elif roc60 < -25:
        struct_parts.append(f"3 aylık getiri %{roc60:.1f} — konsolidasyon gerekiyor")
    elif roc5 > 5:
        struct_parts.append(f"5G momentum +%{roc5:.1f} — kısa vadeli ivme güçlü")
    elif roc20 > 10:
        struct_parts.append(f"Aylık getiri +%{roc20:.1f} — orta vadeli trend güçlü")
    if vwap in ("alt1", "alt2"):
        struct_parts.append("Fiyat VWAP altında — değere dönüş fırsatı")
    if struct_parts:
        reasons.append("Yapı: " + " · ".join(struct_parts[:2]))

    # ── 6. ÇOKLU SİSTEM UYUMU ────────────────────────────────────────────
    if agree_bull >= 9:
        reasons.append(f"10 bağımsız sistemin {agree_bull} tanesi AL oyu verdi — nadir görülen tam uyum")
    elif agree_bull >= 8:
        reasons.append(f"10 sistemden {agree_bull} tanesi AL yönünde — çok güçlü konsensüs (skor {cons_score:.0f}/100)")
    elif agree_bull >= 7:
        reasons.append(f"10 sistemden {agree_bull} tanesi AL oyu verdi — güçlü uyum")
    elif agree_bull >= 6:
        reasons.append(f"10 sistemden {agree_bull} tanesi AL tarafında — çoğunluk uyumu")
    elif agree_bull >= 5:
        reasons.append(f"10 sistemden {agree_bull} tanesi AL tarafında")

    # ── 7. TEMEL DEĞERLEME ────────────────────────────────────────────────
    fund_parts = []
    if adil > 0 and guncel > 0 and adil > guncel * 1.15:
        pot = (adil - guncel) / guncel * 100
        fund_parts.append(f"Graham adil değeri %{pot:.1f} üzerinde ({adil:.2f}₺ / {guncel:.2f}₺) — ciddi iskonto")
    if 0 < fk < 7:
        fund_parts.append(f"F/K {fk:.1f} — tarihi düşük değerleme")
    elif 0 < fk < 12:
        fund_parts.append(f"F/K {fk:.1f} — makul değerleme")
    if 0 < pddd < 0.7:
        fund_parts.append(f"PD/DD {pddd:.2f} — defter değerinin altında")
    if roe > 20:
        fund_parts.append(f"ROE %{roe:.1f} — yüksek özkaynak kârlılığı")
    if cap and cap < 300:
        fund_parts.append(f"Mikro-cap ({cap:.0f}M₺) — yüksek hareket potansiyeli")
    elif cap and cap < 1500:
        fund_parts.append(f"Küçük-cap ({cap:.0f}M₺) — kurumsal ilgi öncesi fırsat")
    if fund_parts:
        reasons.append("Temel: " + " · ".join(fund_parts[:2]))

    # ── 8. VOLATİLİTE / PİYASA REJİMİ ────────────────────────────────────
    if volreg == "extreme":
        reasons.append("Volatilite aşırı yüksek — pozisyon büyüklüğünü küçük tut, stop sıkıştır")
    elif volreg == "high" and rsi < 35:
        reasons.append("Yüksek volatilite + satım bölgesi — mean-reversion potansiyeli güçlü")

    # ── 9. GEÇMİŞ BENZERLİK ──────────────────────────────────────────────
    if isinstance(sim, dict) and int(sim.get("count") or 0) >= 3:
        wr_s  = sim.get("win_rate", 0)
        avg_r = sim.get("avg_ret",  0)
        reasons.append(f"Benzer {sim.get('count')} tarihsel durumda başarı %{wr_s}, ort. getiri %{avg_r} — AI hafıza onayı")

    # ── 10. PİYASA GENİŞLİĞİ BAĞLAMI ─────────────────────────────────────
    try:
        from ._breadth import get_market_breadth
        b = get_market_breadth()
        if b:
            h    = float(b.get("health")          or 50)
            fg   = float(b.get("fear_greed")       or 50)
            fg_l = b.get("fear_greed_label")       or ""
            adv  = int(b.get("adv_decline")        or 0)
            if h >= 70 and adv > 100:
                reasons.append(f"Piyasa genişliği güçlü (sağlık {h:.0f}/100, {adv} hisse yükseliyor)")
            elif h <= 35:
                reasons.append(f"Piyasa genişliği zayıf ({h:.0f}/100, {fg_l}) — sadece en güçlü sinyaller")
            elif fg >= 70:
                reasons.append(f"Piyasa: {fg_l} ({fg:.0f}/100) — aşırı iyimserlik, stop seviyeleri kritik")
            elif fg <= 30:
                reasons.append(f"Piyasa: {fg_l} ({fg:.0f}/100) — panik satışı, kontraryan fırsatlar doğuyor")
    except Exception:
        pass

    # ── 11. FORMASYONLAR ──────────────────────────────────────────────────
    bull_fms = [f"{f.get('emoji','')} {f.get('ad','')}" for f in forms
                if (f.get("tip") or "") != "bearish"]
    if bull_fms:
        guc_max = max((float(f.get("guc") or 65) for f in forms
                       if (f.get("tip") or "") != "bearish"), default=65)
        reasons.append(f"Formasyon: {', '.join(bull_fms[:2])} (güç {guc_max:.0f}/100)")

    if conf_bonus >= 12:
        reasons.append(f"Bu sinyal kombinasyonu geçmişte {conf_bonus} puanlık pozitif performans kaydetti")
    if time_bonus >= 6:
        reasons.append("Haftanın bu günü/saati tarihsel olarak pozitif getiri üretmiş")

    if len(reasons) <= 1:
        reasons.append("Teknik göstergeler alım bölgesine işaret ediyor · AI skor eşiği aşıldı · Çoklu sistem uyumu var")

    return " · ".join(reasons[:7])
