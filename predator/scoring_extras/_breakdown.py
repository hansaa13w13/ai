"""AI Breakdown — puan kırılımı (build_ai_breakdown)."""

from __future__ import annotations

from ..market import get_market_mode
from ..utils import parse_api_num


def build_ai_breakdown(fiyat: float, adil: float, tech: dict, fin: dict,
                       formations: list[dict], market_cap_m: float,
                       ai_score: int, al_puani: int,
                       sektor: str = "", signal_quality: int = 0) -> dict:
    """PHP buildAIBreakdown birebir — radar/açıklama için puan kırılımı."""
    items: list[list] = []
    mode = get_market_mode()

    if adil > 0:
        pot = (adil - fiyat) / max(fiyat, 0.001)
        if   pot > 1.0: items.append(["✅", f"Adil değerin {round(pot*100)}% altında (çok ucuz)", "+50"])
        elif pot > 0.3: items.append(["✅", f"Adil değerin {round(pot*100)}% altında", "+30"])
        elif pot > 0.1: items.append(["✅", f"Adil değer altında (%{round(pot*100)})", "+18"])
        elif pot < -0.4: items.append(["⛔", f"Adil değerin %{round(abs(pot)*100)} üzerinde (pahalı)", "-25"])
        elif pot < -0.2: items.append(["⚠️", f"Adil değerin %{round(abs(pot)*100)} üzerinde", "-15"])

    rsi = float(tech.get("rsi") or 50)
    if   rsi < 20: items.append(["✅", f"RSI aşırı aşırı satım ({round(rsi,1)})", "+28"])
    elif rsi < 30: items.append(["✅", f"RSI aşırı satım bölgesinde ({round(rsi,1)})", "+17"])
    elif rsi < 40: items.append(["✅", f"RSI hafif aşırı satım ({round(rsi,1)})", "+10"])
    elif rsi > 85: items.append(["⛔", f"RSI aşırı alım — yüksek risk ({round(rsi,1)})", "-22"])
    elif rsi > 75: items.append(["⚠️", f"RSI aşırı alım bölgesine yakın ({round(rsi,1)})", "-14"])

    macd = tech.get("macd") or {}
    if (macd.get("cross") or "") == "golden":   items.append(["✅", "MACD Golden Cross (yükseliş teyidi)", "+22"])
    elif (macd.get("cross") or "") == "death":  items.append(["⛔", "MACD Death Cross (düşüş sinyali)", "-20"])
    elif (macd.get("hist") or 0) > 0:           items.append(["✅", "MACD histogramı pozitif", "+5"])

    div = tech.get("divergence") or {}
    if (div.get("rsi") or "") == "boga":  items.append(["⚡", "Yükseliş RSI Diverjansı (güçlü sinyal)", "+25"])
    if (div.get("macd") or "") == "boga": items.append(["⚡", "Yükseliş MACD Diverjansı", "+20"])
    if (div.get("rsi") or "") == "ayi":   items.append(["⛔", "Düşüş RSI Diverjansı (dikkat!)", "-20"])

    srsi = tech.get("stochRsi") or {"k": 50, "d": 50}
    sk = float(srsi.get("k") or 50)
    sd = float(srsi.get("d") or 50)
    if sk < 10 and sk > sd: items.append(["✅", "StochRSI dipte yükseliş kesişimi", "+20"])
    elif sk < 20:           items.append(["✅", "StochRSI aşırı satım", "+8"])
    elif sk > 90:           items.append(["⚠️", "StochRSI aşırı alım", "-11"])

    ichi = tech.get("ichimoku") or {}
    if (ichi.get("signal") or "") == "ustunde":  items.append(["✅", "Ichimoku bulutunun üzerinde", "+12"])
    elif (ichi.get("signal") or "") == "altinda": items.append(["⛔", "Ichimoku bulutunun altında", "-14"])
    if (ichi.get("tkCross") or "") == "golden":  items.append(["✅", "Ichimoku TK Golden Cross", "+10"])

    sar = tech.get("sar") or {"direction": "notr"}
    if sar.get("direction") == "yukselis": items.append(["✅", "Parabolic SAR yükseliş modunda", "+12"])
    elif sar.get("direction") == "dusus":  items.append(["⛔", "Parabolic SAR düşüş modunda", "-10"])

    bb = tech.get("bb") or {"pct": 50}
    bb_pct = float(bb.get("pct") or 50)
    if   bb_pct < 5:  items.append(["✅", "BB alt bantında (aşırı satım)", "+17"])
    elif bb_pct < 15: items.append(["✅", "BB alt bölgesinde", "+11"])
    elif bb_pct > 95: items.append(["⛔", "BB üst bantında (aşırı alım)", "-17"])
    if bb.get("squeeze"): items.append(["⚡", "Bollinger Sıkışması (kırılım bekleniyor)", "+10"])

    wr = float(tech.get("williamsR") or -50)
    if   wr <= -90: items.append(["✅", f"Williams %R aşırı satım ({round(wr)})", "+16"])
    elif wr <= -80: items.append(["✅", f"Williams %R dip bölgesinde ({round(wr)})", "+12"])
    elif wr >= -10: items.append(["⛔", f"Williams %R aşırı alım ({round(wr)})", "-14"])

    cmf_v = float(tech.get("cmf") or 0)
    if   cmf_v > 0.25:  items.append(["✅", f"CMF güçlü para girişi ({round(cmf_v,2)})", "+12"])
    elif cmf_v > 0.10:  items.append(["✅", f"CMF pozitif para akışı ({round(cmf_v,2)})", "+8"])
    elif cmf_v < -0.25: items.append(["⛔", f"CMF kurumsal çıkış sinyali ({round(cmf_v,2)})", "-12"])
    elif cmf_v < -0.10: items.append(["⚠️", f"CMF negatif para akışı ({round(cmf_v,2)})", "-7"])

    mfi_v = float(tech.get("mfi") or 50)
    if   mfi_v < 10: items.append(["✅", f"MFI aşırı satım ({round(mfi_v)})", "+17"])
    elif mfi_v < 20: items.append(["✅", f"MFI dip bölgesinde ({round(mfi_v)})", "+11"])
    elif mfi_v > 90: items.append(["⛔", f"MFI aşırı alım ({round(mfi_v)})", "-14"])
    elif mfi_v > 80: items.append(["⚠️", f"MFI alım doygunluğuna yakın ({round(mfi_v)})", "-8"])

    adx = tech.get("adx") or {}
    adx_v = float(adx.get("adx") or 0)
    adx_d = adx.get("dir") or "notr"
    if adx_d == "yukselis" and adx_v >= 40:   items.append(["✅", f"ADX çok güçlü yükseliş trendi ({round(adx_v)})", "+20"])
    elif adx_d == "yukselis" and adx_v >= 25: items.append(["✅", f"ADX güçlü yükseliş trendi ({round(adx_v)})", "+13"])
    elif adx_d == "dusus" and adx_v >= 30:    items.append(["⛔", f"ADX güçlü düşüş trendi ({round(adx_v)})", "-18"])

    st = tech.get("supertrend") or {}
    if (st.get("direction") or "") == "yukselis": items.append(["✅", f"Supertrend yükseliş modunda (destek: {round(float(st.get('value') or 0),2)})", "+12"])
    elif (st.get("direction") or "") == "dusus":  items.append(["⛔", f"Supertrend düşüş modunda (direnç: {round(float(st.get('value') or 0),2)})", "-12"])

    ema_c = tech.get("emaCross") or {}
    if (ema_c.get("cross") or "") == "golden":   items.append(["✅", "EMA 9/21 Golden Cross (yükseliş)", "+14"])
    elif (ema_c.get("cross") or "") == "death":  items.append(["⛔", "EMA 9/21 Death Cross (düşüş)", "-13"])
    elif ema_c.get("fastAboveSlow"):             items.append(["✅", "EMA 9 > EMA 21 (yükselen ivme)", "+5"])

    trix = tech.get("trix") or {}
    if (trix.get("cross") or "") == "bullish":     items.append(["⚡", "TRIX sıfır yukarı kesiyor (güçlü ivme)", "+10"])
    elif (trix.get("cross") or "") == "bearish":   items.append(["⛔", "TRIX sıfır aşağı kesiyor", "-9"])
    elif (trix.get("signal") or "") == "yukselis": items.append(["✅", "TRIX pozitif bölgede", "+4"])

    cmo = float(tech.get("cmo") or 0)
    if   cmo < -50: items.append(["✅", f"CMO aşırı satım bölgesinde ({round(cmo)})", "+10"])
    elif cmo < -30: items.append(["✅", f"CMO satım aşırılığı ({round(cmo)})", "+5"])
    elif cmo >  50: items.append(["⛔", f"CMO aşırı alım bölgesinde ({round(cmo)})", "-10"])
    elif cmo >  30: items.append(["⚠️", f"CMO alım doygunluğu ({round(cmo)})", "-5"])

    ao = tech.get("awesomeOsc") or {}
    if (ao.get("cross") or "") == "bullish":      items.append(["⚡", "Awesome Osc. sıfır üstüne geçiyor (güçlü)", "+10"])
    elif (ao.get("cross") or "") == "bearish":    items.append(["⛔", "Awesome Osc. sıfır altına iniyor", "-10"])
    elif (ao.get("signal") or "") == "yukselis":  items.append(["✅", "Awesome Oscillator pozitif", "+4"])
    elif (ao.get("signal") or "") == "dusus":     items.append(["⚠️", "Awesome Oscillator negatif", "-4"])

    hull = tech.get("hullDir") or "notr"
    if   hull == "yukselis": items.append(["✅", "Hull MA yükselen yönde", "+7"])
    elif hull == "dusus":    items.append(["⛔", "Hull MA düşen yönde", "-6"])

    elder = tech.get("elder") or {}
    if   (elder.get("signal") or "") == "guclu_boga": items.append(["✅", "Elder Ray güçlü boğa (Bull Power pozitif)", "+9"])
    elif (elder.get("signal") or "") == "guclu_ayi":  items.append(["⛔", "Elder Ray güçlü ayı (Bear Power negatif)", "-8"])

    uo = float(tech.get("ultimateOsc") or 50)
    if   uo < 30: items.append(["✅", f"Ultimate Oscillator aşırı satım ({round(uo)})", "+9"])
    elif uo < 40: items.append(["✅", f"Ultimate Oscillator dip bölgesi ({round(uo)})", "+5"])
    elif uo > 70: items.append(["⛔", f"Ultimate Oscillator aşırı alım ({round(uo)})", "-9"])

    pvt = tech.get("pvt") or "notr"
    if   pvt == "artis": items.append(["✅", "PVT yükselen hacim/fiyat trendi", "+5"])
    elif pvt == "dusus": items.append(["⚠️", "PVT düşen hacim/fiyat trendi", "-4"])

    pos52 = float(tech.get("pos52wk") or 50)
    if   pos52 < 10: items.append(["💎", f"52 hafta dibine yakın (%{round(pos52)})", "+12"])
    elif pos52 < 20: items.append(["✅", f"52 hafta alt bölgesinde (%{round(pos52)})", "+8"])
    elif pos52 > 90: items.append(["⚠️", f"52 hafta zirvesine yakın (%{round(pos52)})", "-10"])

    vol_r = float(tech.get("volRatio") or 1)
    if   vol_r > 3.0: items.append(["🔊", f"Çok yüksek hacim ({round(vol_r,1)}x ortalamanın)", "+14"])
    elif vol_r > 2.0: items.append(["🔊", f"Yüksek hacim ({round(vol_r,1)}x)", "+9"])
    elif vol_r < 0.7: items.append(["⚠️", f"Düşük hacim ({round(vol_r,1)}x) — dikkat", "-10"])

    for f in formations:
        tip = f.get("tip") or ""
        tip_tr = {
            "reversal": "dönüş formasyonu",
            "breakout": "kırılım formasyonu",
            "momentum": "momentum formasyonu",
            "bearish":  "düşüş formasyonu ⚠️",
        }.get(tip, "formasyon")
        guc = float(f.get("guc") or 60)
        if tip == "bearish":
            penalty = int((guc - 60) * 1.8 + 22)
            items.append(["🔻", f"{f.get('emoji','')} {f.get('ad','')} {tip_tr} (güç: {int(guc)})", f"-{penalty}"])
        else:
            extra = 6 if tip == "reversal" else (5 if tip == "breakout" else 3)
            bonus = int((guc - 60) * 0.9 + extra)
            items.append(["🔷", f"{f.get('emoji','')} {f.get('ad','')} {tip_tr} (güç: {int(guc)})", f"+{bonus}"])

    if market_cap_m > 0:
        if   market_cap_m < 250:    items.append(["💎", f"Nano Cap — çok yüksek büyüme potansiyeli ({round(market_cap_m)}M₺)", "+32"])
        elif market_cap_m < 500:    items.append(["🏷️", f"Mikro Cap — yüksek büyüme potansiyeli ({round(market_cap_m)}M₺)", "+24"])
        elif market_cap_m < 1000:   items.append(["🏷️", f"Küçük Cap ({round(market_cap_m/1000,2)}B₺)", "+16"])
        elif market_cap_m < 2500:   items.append(["🏷️", f"Düşük Cap ({round(market_cap_m/1000,2)}B₺)", "+8"])
        elif market_cap_m > 50000:  items.append(["⚠️", "Büyük Cap — yavaş büyüme beklentisi", "-10"])

    # ── Uyuyan Mücevher Combo Açıklaması (merkezi modül) ──────────────
    try:
        from ._sleeper import sleeper_breakdown
        # tech + fin alanlarından zenginleştirilmiş bir stock-benzeri dict üret
        _stk: dict = {}
        for _src in (tech, fin):
            if isinstance(_src, dict):
                for _k, _v in _src.items():
                    _stk.setdefault(_k, _v)
        if market_cap_m and not _stk.get("marketCap"):
            _stk["marketCap"] = market_cap_m
        if fiyat and not _stk.get("guncel"):
            _stk["guncel"] = fiyat
        if adil and not _stk.get("adil"):
            _stk["adil"] = adil
        # API tarafında bazı finansal alanlar büyük harfle gelir → alias ekle
        _alias_map = {
            "halkAciklik": fin.get("halkakAciklik"),
            "netParaAkis": fin.get("netParaAkis"),
            "paraGiris": fin.get("paraGiris"),
            "borcOz": fin.get("borcOz"),
            "netKar": parse_api_num(fin.get("NetKar") or 0),
            "pddd": parse_api_num(fin.get("PiyDegDefterDeg") or 0),
            "fk": parse_api_num(fin.get("FK") or 0),
            "sonDortCeyrek": fin.get("sonDortCeyrek"),
        }
        for _k, _v in _alias_map.items():
            if _v not in (None, "") and not _stk.get(_k):
                _stk[_k] = _v
        sleeper_total, sleeper_items = sleeper_breakdown(_stk)
        if sleeper_total > 0:
            items.append(["💤", f"━━━ UYUYAN MÜCEVHER (+{sleeper_total} bonus) ━━━", f"+{sleeper_total}"])
            for _emoji, _msg, _pts in sleeper_items:
                items.append([_emoji, f"  ↳ {_msg}", f"+{_pts}"])
    except Exception:
        pass

    net_kar  = parse_api_num(fin.get("NetKar") or 0)
    fk       = parse_api_num(fin.get("FK") or 0)
    pddd     = parse_api_num(fin.get("PiyDegDefterDeg") or 0)
    roe_d    = float(fin.get("roe") or 0)
    nkm      = float(fin.get("netKarMarj") or 0)
    fkm      = float(fin.get("faalKarMarj") or 0)
    cari     = float(fin.get("cariOran") or 0)
    borc     = float(fin.get("borcOz") or 0)
    tmt      = float(fin.get("lastTemettu") or 0)
    bdl      = bool(fin.get("recentBedelsiz") or False)

    if   net_kar > 0: items.append(["✅", "Net kâr pozitif", "+20"])
    elif net_kar < 0: items.append(["⛔", "Net zarar — şirket zarar ediyor", "-20"])
    if   0 < fk < 8:  items.append(["✅", f"Düşük F/K oranı ({round(fk,1)}) — ucuz", "+15"])
    elif fk > 30:     items.append(["⚠️", f"Yüksek F/K oranı ({round(fk,1)}) — pahalı", "-10"])
    if 0 < pddd < 1.0: items.append(["✅", "PD/DD < 1 — defter değerinin altında", "+12"])

    if   roe_d > 25: items.append(["✅", f"ROE çok yüksek (%{round(roe_d,1)}) — özsermaye getirisi güçlü", "+14"])
    elif roe_d > 15: items.append(["✅", f"ROE iyi (%{round(roe_d,1)})", "+10"])
    elif roe_d < 0:  items.append(["⛔", f"ROE negatif (%{round(roe_d,1)})", "-8"])

    if   nkm > 20: items.append(["✅", f"Net kâr marjı güçlü (%{round(nkm,1)})", "+10"])
    elif nkm > 8:  items.append(["✅", f"Net kâr marjı pozitif (%{round(nkm,1)})", "+6"])
    elif nkm < 0:  items.append(["⛔", f"Net kâr marjı negatif (%{round(nkm,1)})", "-10"])

    if   fkm > 20: items.append(["✅", f"Faaliyet kâr marjı güçlü (%{round(fkm,1)})", "+8"])
    elif fkm < 0:  items.append(["⛔", f"Faaliyet zararı (%{round(fkm,1)})", "-8"])

    if   cari > 2.0: items.append(["✅", f"Cari oran sağlam ({round(cari,2)}) — likidite güçlü", "+8"])
    elif 0 < cari < 0.8: items.append(["⛔", f"Cari oran kritik düşük ({round(cari,2)})", "-10"])

    if   0 < borc < 0.3: items.append(["✅", f"Çok düşük borçluluk (B/Ö: {round(borc,2)})", "+8"])
    elif borc > 4.0:     items.append(["⛔", f"Çok yüksek borçluluk (B/Ö: {round(borc,2)})", "-14"])

    if   tmt > 5: items.append(["💰", f"Yüksek temettü verimi (%{round(tmt,1)})", "+10"])
    elif tmt > 2: items.append(["💰", f"Temettü verimi pozitif (%{round(tmt,1)})", "+5"])
    elif tmt > 0: items.append(["💰", f"Temettü var (%{round(tmt,1)})", "+2"])
    if bdl:       items.append(["🎁", "Son dönemde bedelsiz sermaye artışı", "+8"])

    # ── PHP v31 ek finansal kalemler (index.php satır 7148-7212 birebir) ──────
    brut_kar  = float(fin.get("brutKarMarj") or 0)
    roa_v     = float(fin.get("roa") or 0)
    ret3m     = float(fin.get("ret3m") or 0)
    nakit_o   = float(fin.get("nakitOran") or 0)
    likit_o   = float(fin.get("likitOran") or 0)
    kaldirac  = float(fin.get("kaldiraci") or 0)
    stok_dev  = float(fin.get("stokDevirH") or 0)
    alacak_dev= float(fin.get("alacakDevirH") or 0)
    aktif_dev = float(fin.get("aktifDevir") or 0)
    kvsa_borc = float(fin.get("kvsaBorcOran") or 0)
    net_para  = float(fin.get("netParaAkis") or 0)
    para_gir  = float(fin.get("paraGiris") or 0)
    halkak    = float(fin.get("halkakAciklik") or 0)
    son4c     = float(fin.get("sonDortCeyrek") or 0)
    taban_f   = float(fin.get("tabanFark") or 0)

    # Brüt Kar Marjı
    if   brut_kar > 50: items.append(["✅", f"Brüt kar marjı çok yüksek (%{round(brut_kar,1)})", "+4"])
    elif brut_kar > 30: items.append(["✅", f"Brüt kar marjı iyi (%{round(brut_kar,1)})", "+2"])
    elif 0 < brut_kar < 5: items.append(["⚠️", f"Brüt kar marjı çok düşük (%{round(brut_kar,1)})", "-3"])

    # ROA
    if   roa_v > 15: items.append(["✅", f"ROA çok yüksek — varlık verimliliği güçlü (%{round(roa_v,1)})", "+4"])
    elif roa_v > 8:  items.append(["✅", f"ROA iyi (%{round(roa_v,1)})", "+2"])
    elif roa_v < 0:  items.append(["⛔", f"ROA negatif — varlık verimsizliği (%{round(roa_v,1)})", "-4"])

    # 3 Aylık Gerçek Getiri
    if   ret3m > 40:  items.append(["🚀", f"3A gerçek getiri çok yüksek (+%{round(ret3m,1)})", "+15"])
    elif ret3m > 20:  items.append(["✅", f"3A gerçek getiri güçlü (+%{round(ret3m,1)})", "+8"])
    elif ret3m > 10:  items.append(["✅", f"3A getiri pozitif (+%{round(ret3m,1)})", "+4"])
    elif ret3m < -40: items.append(["⛔", f"3A getiri çok negatif (%{round(ret3m,1)})", "-18"])
    elif ret3m < -20: items.append(["⛔", f"3A getiri negatif (%{round(ret3m,1)})", "-10"])

    # Nakit Oran
    if   nakit_o > 1.0: items.append(["✅", f"Nakit oran güçlü ({round(nakit_o,2)}) — yüksek likidite", "+4"])
    elif 0 < nakit_o < 0.1: items.append(["⚠️", f"Nakit oran çok düşük ({round(nakit_o,2)})", "-3"])

    # Likit Oran
    if   likit_o > 1.5: items.append(["✅", f"Likit oran güçlü ({round(likit_o,2)})", "+3"])
    elif 0 < likit_o < 0.5: items.append(["⚠️", f"Likit oran zayıf ({round(likit_o,2)})", "-4"])

    # Kaldıraç
    if   0 < kaldirac < 0.3: items.append(["✅", f"Düşük kaldıraç ({round(kaldirac,2)}) — sağlam bilanço", "+3"])
    elif kaldirac > 0.7:     items.append(["⚠️", f"Yüksek kaldıraç ({round(kaldirac,2)})", "-4"])

    # Stok + Alacak Devir Hızı
    if stok_dev > 15:
        items.append(["✅", f"Stok devir hızı yüksek ({round(stok_dev,1)}x) — hızlı satış", "+2"])
    if alacak_dev > 15:
        items.append(["✅", f"Alacak devir hızı yüksek ({round(alacak_dev,1)}x) — hızlı tahsilat", "+3"])
    elif 0 < alacak_dev < 3:
        items.append(["⚠️", f"Alacak devir hızı düşük ({round(alacak_dev,1)}x) — tahsilat sorunu", "-3"])

    # Aktif Devir Hızı
    if aktif_dev > 2.0:
        items.append(["✅", f"Aktif devir hızı güçlü ({round(aktif_dev,2)}x) — varlık verimliliği", "+3"])

    # Kısa Vade Borç Oranı
    if kvsa_borc > 0.7:
        items.append(["⚠️", f"Kısa vade borç oranı yüksek ({round(kvsa_borc,2)}) — vade riski", "-3"])

    # Net Para Akışı
    if net_para > 0 and para_gir > 0:
        akis = net_para / max(para_gir * 2, 1)
        if   akis > 0.20: items.append(["💹", f"Güçlü net para girişi — kurumsal alım ({round(net_para/1e6,1)}M₺)", "+7"])
        elif akis > 0.08: items.append(["💹", f"Net para girişi var ({round(net_para/1e6,1)}M₺)", "+3"])
    elif net_para < 0 and para_gir > 0:
        cikis = abs(net_para) / max(para_gir * 2, 1)
        if cikis > 0.20: items.append(["📉", f"Güçlü net para çıkışı — kurumsal satım ({round(net_para/1e6,1)}M₺)", "-6"])

    # Halka Açıklık
    if   halkak > 60: items.append(["✅", f"Yüksek halka açıklık (%{round(halkak)}) — likidite güçlü", "+4"])
    elif 0 < halkak < 10: items.append(["⚠️", f"Düşük halka açıklık (%{round(halkak)}) — düşük likidite", "-4"])

    # Son 4 Çeyrek Kümülatif Kâr/Zarar
    if   son4c > 0: items.append(["✅", "Son 4 çeyrek kümülatif kâr pozitif", "+2"])
    elif son4c < 0: items.append(["⛔", "Son 4 çeyrek kümülatif zarar", "-4"])

    # Taban Fiyatına Yakınlık
    if 0 < taban_f < 3:
        items.append(["💎", f"Taban fiyatına çok yakın (%{round(taban_f,1)})", "+5"])

    # ── KAP "Tipe Dönüşüm" Bonusu (dipteki hisseler) ──────────────────
    try:
        from ._kap_news import kap_tipe_donusum_bonus
        # tech içinden kod & pos52'yi türet
        _kap_stk: dict = {}
        for _src in (tech, fin):
            if isinstance(_src, dict):
                for _k, _v in _src.items():
                    _kap_stk.setdefault(_k, _v)
        # code; tech/fin içinde olmayabilir → uppercase doğrudan
        _kap_stk.setdefault("code", (tech.get("code") or fin.get("code") or "").upper())
        if _kap_stk.get("code"):
            kap_total, kap_items = kap_tipe_donusum_bonus(_kap_stk)
            if kap_total > 0:
                items.append(["📜", f"━━━ KAP TİPE DÖNÜŞÜM (+{kap_total} bonus) ━━━",
                              f"+{kap_total}"])
                for _emoji, _msg, _pts in kap_items:
                    sign = "+" if _pts >= 0 else ""
                    items.append([_emoji, f"  ↳ {_msg}",
                                  f"{sign}{_pts}" if _pts else ""])
    except Exception:
        pass

    if signal_quality > 0:
        items.append(["⚡", "Zamanlama & sinyal konsensüsü Al Puanına dahil", f"+{signal_quality * 5}"])

    if   mode == "temkinli": items.append(["⚠️", "Genel piyasa temkinli modda (eşik yükseltildi)", "-15%"])
    elif mode == "ayi":      items.append(["⛔", "Genel piyasa ayı modunda (çok seçici)", "-35%"])
    elif mode == "bull":     items.append(["✅", "Genel piyasa boğa modunda", "+5"])

    return {
        "items":   items,
        "aiScore": ai_score,
        "alPuani": al_puani,
        "mode":    mode,
        "toplam":  len(items),
    }
