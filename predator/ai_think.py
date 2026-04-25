"""AI düşünme motoru — aiAutoThink + aiDriven* fonksiyonları (PHP karşılığı)."""
from __future__ import annotations
from . import config
from .market import get_market_mode
from .brain import brain_load


def ai_auto_think(stock: dict, consensus: dict | None = None, market_mode: str = "") -> dict:
    """PHP aiAutoThink birebir karşılığı: zincirleme akıl yürütme."""
    if not market_mode:
        market_mode = get_market_mode()
    consensus = consensus or {}

    rsi = float(stock.get("rsi", 50) or 50)
    macd = stock.get("macdCross", "none")
    sar = stock.get("sarDir", "notr")
    vol = float(stock.get("volRatio", 1) or 1)
    cmf = float(stock.get("cmf", 0) or 0)
    adx = float(stock.get("adxVal", 0) or 0)
    pos52 = float(stock.get("pos52wk", 50) or 50)
    smc = stock.get("smcBias", "notr")
    ofi = stock.get("ofiSig", "notr")
    hull = stock.get("hullDir", "notr")
    st = stock.get("supertrendDir", "notr")
    vwap = stock.get("vwapPos", "icinde")
    cci = float(stock.get("cci", 0) or 0)
    mfi = float(stock.get("mfi", 50) or 50)
    obv = stock.get("obvTrend", "notr")
    forms = stock.get("formations") or []
    ai_score = int(stock.get("aiScore", 0) or 0)
    pred_b = int(stock.get("predBonus", 0) or 0)
    sektor = stock.get("sektor", "genel")
    cap = float(stock.get("marketCap", 0) or 0)
    adil = float(stock.get("adil", 0) or 0)
    guncel = float(stock.get("guncel", 1) or 1)
    sig_q = int(stock.get("signalQuality", 0) or 0)
    keltner = stock.get("keltnerPos", "notr")
    ema_cross = stock.get("emaCrossDir", "none")
    stoch = float(stock.get("stochK", 50) or 50)

    steps: list[str] = []
    adj = 0
    bull_ev = 0
    bear_ev = 0

    # ── ADIM 1: Teknik sinyal gücü
    tech_b = tech_x = 0
    if rsi < 20:
        tech_b += 3; steps.append(f"RSI aşırı satım bölgesi ({rsi:.1f}) → güçlü toparlanma sinyali")
    elif rsi < 30:
        tech_b += 2; steps.append(f"RSI satım bölgesinde ({rsi:.1f}) → dip oluşumu")
    elif rsi > 78:
        tech_x += 3; steps.append(f"RSI kritik aşırı alım ({rsi:.1f}) → yüksek düşüş riski")
    elif rsi > 70:
        tech_x += 2; steps.append(f"RSI aşırı alım bölgesi ({rsi:.1f}) → düşüş riski")

    if macd == "golden":
        tech_b += 2; steps.append("MACD altın kesişimi → yükseliş trendi başlıyor")
    elif macd == "death":
        tech_x += 2; steps.append("MACD ölüm kesişimi → düşüş trendi baskısı")

    if sar == "yukselis": tech_b += 1
    if hull == "yukselis": tech_b += 1
    if st == "yukselis":
        tech_b += 2; steps.append("Supertrend yükseliş yönünde — trend takip sinyali onaylandı")
    if ema_cross == "golden":
        tech_b += 2; steps.append("EMA 9/21 altın kesişimi → kısa vadeli momentum")
    if stoch < 20: tech_b += 1
    if cci < -100: tech_b += 1
    if keltner == "alt_bant":
        tech_b += 1; steps.append("Keltner kanalı altında — aşırı satım zone'unda")

    if adx >= 35:
        if st == "yukselis" or sar == "yukselis":
            tech_b += 2; steps.append(f"ADX {adx:.0f} — güçlü trend + yükseliş yönü: momentum ivmeli")
    elif adx >= 25:
        if st == "yukselis": tech_b += 1
    elif adx < 15:
        if tech_b > tech_x:
            steps.append(f"ADX {adx:.0f} — trend gücü zayıf, sinyal güvenilirliği düşük")

    bull_forms = [f for f in forms if f.get("tip") != "bearish"]
    bear_forms = [f for f in forms if f.get("tip") == "bearish"]
    if len(bull_forms) >= 3:
        tech_b += 3; steps.append(f"{len(bull_forms)} boğa formasyonu → çoklu-pattern güçlü onay")
    elif len(bull_forms) >= 2:
        tech_b += 2; steps.append(f"{len(bull_forms)} boğa formasyonu → multi-pattern onay")
    if bear_forms:
        tech_x += len(bear_forms) + 1
        steps.append(f"{len(bear_forms)} ayı formasyonu — dikkat gerekli")

    tech_net = tech_b - tech_x
    if tech_net >= 7:
        adj += 16; bull_ev += 3
        steps.append(f"Teknik: {tech_b}/{tech_b + tech_x} boğa sinyali — çok güçlü kurulum")
    elif tech_net >= 5:
        adj += 12; bull_ev += 2
        steps.append(f"Teknik: {tech_b}/{tech_b + tech_x} boğa sinyali — güçlü kurulum")
    elif tech_net >= 3:
        adj += 7; bull_ev += 1
    elif tech_net >= 1:
        adj += 3; bull_ev += 1
    elif tech_net <= -4:
        adj -= 12; bear_ev += 3
        steps.append("Teknik: Baskın ayı sinyali — kaçınılmalı")
    elif tech_net <= -2:
        adj -= 8; bear_ev += 2
        steps.append("Teknik: Baskın ayı sinyali — dikkatli olunmalı")
    elif tech_net < 0:
        adj -= 3; bear_ev += 1

    # ── ADIM 2: Hacim / Para akışı
    vol_b = vol_x = 0
    if vol >= 4.0:
        vol_b += 4; steps.append(f"Devasa hacim ({vol:.1f}x) → kurumsal kırılım — çok güçlü sinyal")
    elif vol >= 3.0:
        vol_b += 3; steps.append(f"Çok güçlü hacim ({vol:.1f}x) → kurumsal pozisyon açılışı olası")
    elif vol >= 2.0:
        vol_b += 2; steps.append(f"Güçlü hacim ({vol:.1f}x) → alıcı baskısı var")
    elif vol >= 1.5: vol_b += 1
    elif vol < 0.5:
        vol_x += 3; steps.append(f"Çok düşük hacim ({vol:.1f}x) → ilgi yok, likidite riski")
    elif vol < 0.7:
        vol_x += 2

    if cmf > 0.20:
        vol_b += 3; steps.append(f"CMF güçlü pozitif ({cmf:.2f}) → yoğun kurumsal para girişi")
    elif cmf > 0.10:
        vol_b += 2; steps.append(f"CMF pozitif ({cmf:.2f}) → para girişi var")
    elif cmf < -0.20:
        vol_x += 3; steps.append("CMF güçlü negatif → kurumsal para çıkışı")
    elif cmf < -0.10:
        vol_x += 2

    if ofi == "guclu_alis":
        vol_b += 2; steps.append("OFI güçlü alış → anlık sipariş akışı alıcı tarafında")
    elif ofi == "alis": vol_b += 1
    elif ofi == "guclu_satis":
        vol_x += 2; steps.append("OFI güçlü satış → anlık sipariş satıcı tarafında")
    elif ofi == "satis": vol_x += 1

    if mfi < 20:
        vol_b += 2; steps.append(f"MFI aşırı satım ({mfi:.0f}) → para akışı dip bölgede")
    elif mfi < 30: vol_b += 1
    elif mfi > 80: vol_x += 2
    if obv == "yukselis": vol_b += 1

    vol_net = vol_b - vol_x
    if vol_net >= 6:
        adj += 14; bull_ev += 3; steps.append("Hacim/Para akışı: Kurumsal birikim güçlü")
    elif vol_net >= 4:
        adj += 10; bull_ev += 2
    elif vol_net >= 2:
        adj += 5; bull_ev += 1
    elif vol_net <= -4:
        adj -= 12; bear_ev += 3; steps.append("Hacim/OFI: Yoğun para çıkışı — riskten kaçın")
    elif vol_net <= -2:
        adj -= 8; bear_ev += 2; steps.append("Hacim/OFI: Para çıkışı tespit edildi")
    elif vol_net < 0:
        adj -= 3; bear_ev += 1

    # ── ADIM 3: Piyasa bağlamı
    if market_mode == "bull":
        adj += 8; bull_ev += 1
        steps.append("Piyasa boğa modunda → tüm sinyaller daha güvenilir")
    elif market_mode == "temkinli":
        adj -= 3; steps.append("Piyasa temkinli modda → seçici olunmalı, pozisyon küçük tutulmalı")
    elif market_mode == "ayi":
        adj -= 15; bear_ev += 2
        steps.append("Piyasa ayı modunda → yalnızca çok güçlü kurulumlar değerlendirilmeli")

    if smc == "bullish":
        adj += 6; bull_ev += 1
        steps.append("SMC: Kurumsal alım zonu aktif — akıllı para birikimi görünüyor")
    elif smc == "bearish":
        adj -= 5; bear_ev += 1

    if vwap == "alt2":
        adj += 8; bull_ev += 1; steps.append("VWAP 2σ altında → derin aşırı satım, güçlü reversal")
    elif vwap == "alt1": adj += 4
    elif vwap == "ust2":
        adj -= 6; bear_ev += 1

    # ── ADIM 4: Geçmiş öğrenme
    if pred_b > 20:
        adj += 8; bull_ev += 1
        steps.append(f"AI geçmiş hafıza bonusu yüksek (+{pred_b}) → benzer kurulumlar başarılı")
    elif pred_b > 0:
        adj += min(5, int(round(pred_b * 0.4))); bull_ev += 1
    elif pred_b < -15:
        adj -= 6; bear_ev += 1
        steps.append(f"AI geçmiş hafıza uyarısı ({pred_b}) → benzer kurulumlar tarihsel olarak zayıf")
    elif pred_b < 0:
        adj += max(-3, int(round(pred_b * 0.3)))

    agree_bull = consensus.get("agree_bull", 0)
    if agree_bull >= 6:
        adj += 10; bull_ev += 2
        steps.append(f"{agree_bull}/7 sistemden AL oyu → nadir ve güçlü konsensüs")
    elif agree_bull >= 5:
        adj += 6; bull_ev += 1
    elif agree_bull >= 4:
        adj += 3
    elif agree_bull <= 2:
        adj -= 5; bear_ev += 1

    # ── ADIM 5: Risk
    if adil > 0 and guncel > 0:
        pot = (adil - guncel) / guncel * 100
        if pot > 40:
            adj += 10; bull_ev += 1; steps.append(f"Graham adil değeri %{pot:.1f} yukarıda")
        elif pot > 20:
            adj += 5; bull_ev += 1
        elif pot < -20:
            adj -= 6; bear_ev += 1; steps.append(f"Graham: Hisse %{abs(pot):.1f} üzerinde — aşırı değerli")

    if pos52 < 5:
        adj += 8; bull_ev += 1; steps.append(f"52 haftalık dibin %{pos52:.1f} yakınında — derin değer")
    elif pos52 < 15: adj += 4
    elif pos52 > 90:
        adj -= 5; bear_ev += 1

    if sig_q >= 8:
        adj += 5; bull_ev += 1; steps.append(f"Sinyal kalitesi yüksek ({sig_q}/10)")
    elif sig_q < 3: adj -= 5

    # ── ADIM 5b: Özel Bonus Sinyalleri (v37.10)
    # Sleeper / Sibling / EarlyCatch — bunlar ayrı bir analiz katmanından geliyor
    # ve sektör/teknik sinyallerden bağımsız değer taşıyor. Önceki versiyonda
    # AI Karar bunları hiç görmüyordu → sibling=100 olan hisseye KAÇIN verebiliyordu.
    sleeper_b = int(stock.get("sleeperBonus", 0) or 0)
    sibling_b = int(stock.get("siblingBonus", 0) or 0)
    early_b   = int(stock.get("earlyCatchBonus", 0) or 0)
    pred_score = float(stock.get("predatorScore", 0) or 0)

    if sleeper_b >= 70:
        adj += 12; bull_ev += 2
        steps.append(f"Uyuyan Mücevher kuvvetli (+{sleeper_b}) — düşük PD + dipte birikim")
    elif sleeper_b >= 50:
        adj += 8; bull_ev += 1
        steps.append(f"Uyuyan Mücevher (+{sleeper_b}) — sessiz akıllı para sinyali")
    elif sleeper_b >= 30:
        adj += 4; bull_ev += 1

    if sibling_b >= 80:
        adj += 14; bull_ev += 2
        steps.append(f"Ortak Kardeş kuvvetli (+{sibling_b}) — büyük abi katlamış, küçük kardeş geride")
    elif sibling_b >= 40:
        adj += 7; bull_ev += 1
        steps.append(f"Ortak Kardeş (+{sibling_b}) — referans hisse pozitif")
    elif sibling_b >= 10:
        adj += 3

    if early_b >= 15:
        adj += 8; bull_ev += 1
        steps.append(f"Erken Yakalama (+{early_b}) — sektör henüz uyurken dipteyiz")
    elif early_b >= 10:
        adj += 4; bull_ev += 1

    # ── ADIM 6: Karar
    # final_score artık predator_score'u da hesaba katar — sırf bonus olmadan
    # AL diyemeyiz, ama tüm bonusları toplamış bir hisseye de KAÇIN diyemeyiz.
    base_score = ai_score + adj
    if pred_score > 0:
        # predatorScore daha bütünsel — ona daha fazla ağırlık ver
        final_score = int(round(base_score * 0.45 + pred_score * 0.55))
    else:
        final_score = base_score
    mode_bonus = 5 if market_mode == "bull" else (-8 if market_mode == "ayi" else 0)

    # Confidence formülü v37.10 — daha geniş dağılım, tavana hızlı vurmaz
    # Bull-bear netliğini ön plana al, skoru daha hafif ağırlıkla kullan
    ev_diff = bull_ev - bear_ev
    raw_conf = 50 + ev_diff * 6 + (final_score - 80) * 0.20 + mode_bonus
    confidence = int(max(10, min(95, raw_conf)))

    # Özel bonus VETO: yüksek bonus + zayıf bear kanıtı varsa KAÇIN olamaz
    special_total = sleeper_b + sibling_b + early_b
    bonus_protection = (special_total >= 80 and bear_ev <= 3)

    if bull_ev >= 6 and bear_ev <= 1 and final_score >= 110:
        decision = "GÜÇLÜ AL"
        confidence = max(confidence, 75)
        steps.append(f"KARAR: {bull_ev} boğa + {bear_ev} ayı, skor {final_score} → ÇOK GÜÇLÜ AL (Güven: %{confidence})")
    elif bull_ev >= 5 and bear_ev <= 2 and final_score >= 95:
        decision = "GÜÇLÜ AL"
        confidence = max(confidence, 68)
        steps.append(f"KARAR: {bull_ev} boğa, {bear_ev} ayı → GÜÇLÜ AL (Güven: %{confidence})")
    elif bull_ev >= 3 and bull_ev > bear_ev * 1.5 and final_score >= 70:
        decision = "AL"
        confidence = max(40, min(confidence, 80))
        steps.append(f"KARAR: Boğa ağırlıklı kanıt → AL (Güven: %{confidence})")
    elif bonus_protection and bull_ev >= bear_ev:
        # Bonus koruması: özel bonus toplamı 80+ ise KAÇIN'a izin verme
        decision = "AL"
        confidence = max(40, min(confidence, 70))
        steps.append(f"KARAR: Özel bonus toplamı yüksek (+{special_total}) — bonus korumalı AL (Güven: %{confidence})")
    elif bear_ev >= 5 or bear_ev > bull_ev * 2.5:
        if bonus_protection:
            decision = "DİKKAT"
            confidence = min(confidence, 60)
            steps.append(f"KARAR: Ayı baskın ama özel bonus (+{special_total}) koruyor → DİKKAT (Güven: %{confidence})")
        else:
            decision = "KAÇIN"
            confidence = max(50, min(confidence, 88))
            steps.append(f"KARAR: Ayı kanıtı baskın → KESİNLİKLE KAÇIN (Güven: %{confidence})")
    elif bear_ev >= 3 or bear_ev > bull_ev * 1.8:
        if bonus_protection:
            decision = "DİKKAT"
            confidence = min(confidence, 55)
            steps.append(f"KARAR: Ayı baskın ama bonus (+{special_total}) koruyor → DİKKAT (Güven: %{confidence})")
        else:
            decision = "KAÇIN"
            confidence = max(40, min(confidence, 80))
            steps.append(f"KARAR: Ayı kanıtı baskın → KAÇIN (Güven: %{confidence})")
    elif bear_ev > bull_ev:
        decision = "DİKKAT"
        confidence = min(confidence, 55)
    else:
        decision = "NÖTR"
        confidence = max(35, min(confidence, 65))

    if sektor and sektor != "genel":
        suffix = f" · Piyasa değeri: {round(cap)}M₺" if cap > 0 else ""
        steps.append(f"Sektör: {sektor}{suffix}")

    return {
        "score_adj": max(-50, min(50, adj)),
        "reasoning": " → ".join(steps[:8]),
        "confidence": confidence,
        "decision": decision,
        "bull_ev": bull_ev,
        "bear_ev": bear_ev,
        "steps": steps,
    }


# ── AI-Driven karar parametreleri ──────────────────────────────────────────
def ai_driven_min_score() -> int:
    brain = brain_load()
    accs = []
    for k in ("neural_net", "neural_net_beta", "neural_net_gamma"):
        a = float(brain.get(k, {}).get("recent_accuracy", 0) or 0)
        if a > 0: accs.append(a)
    if not accs: return config.OTO_MIN_SCORE
    avg = sum(accs) / len(accs)
    if avg >= 70: return max(48, config.OTO_MIN_SCORE - 12)
    if avg >= 62: return config.OTO_MIN_SCORE - 5
    if avg >= 54: return config.OTO_MIN_SCORE
    if avg >= 46: return config.OTO_MIN_SCORE + 10
    return config.OTO_MIN_SCORE + 20


def ai_driven_stop_multiplier(adx_val: float = 0) -> float:
    brain = brain_load()
    a = float(brain.get("neural_net", {}).get("recent_accuracy", 50) or 50)
    b = float(brain.get("neural_net_beta", {}).get("recent_accuracy", 50) or 50)
    g = float(brain.get("neural_net_gamma", {}).get("recent_accuracy", 50) or 50)
    avg = (a + b + g) / 3
    base = 2.2 if adx_val >= 25 else 1.8
    if avg >= 70: return round(base * 0.73, 2)
    if avg >= 62: return round(base * 0.88, 2)
    if avg >= 54: return base
    if avg >= 46: return round(base * 1.22, 2)
    return round(base * 1.50, 2)


def ai_driven_max_hold_days(pos: dict) -> int:
    dec = pos.get("ai_decision_live", pos.get("ai_decision", "NÖTR"))
    conf = int(pos.get("ai_conf_live", pos.get("ai_conf", 50)) or 50)
    if dec == "GÜÇLÜ AL" and conf >= 72: return 6
    if dec == "AL" and conf >= 60:       return 5
    if dec == "DİKKAT":                  return 3
    if dec in ("KAÇIN", "SAT"):          return 1
    return config.OTO_MAX_HOLD_DAYS


def ai_driven_market_bias() -> str:
    brain = brain_load()
    a = float(brain.get("neural_net", {}).get("recent_accuracy", 0) or 0)
    b = float(brain.get("neural_net_beta", {}).get("recent_accuracy", 0) or 0)
    g = float(brain.get("neural_net_gamma", {}).get("recent_accuracy", 0) or 0)
    train_cnt = int(brain.get("neural_net", {}).get("trained_samples", 0) or 0)
    if train_cnt < 50 or (a + b + g) == 0:
        return "notr"
    avg = (a + b + g) / 3
    spread = max(a, b, g) - min(a, b, g)
    if spread > 25: return "notr"
    rw = int(brain.get("stats", {}).get("recent_wins", 0))
    rt = int(brain.get("stats", {}).get("recent_total", 0))
    win_rate = (rw / rt * 100) if rt > 5 else avg
    if win_rate >= 65 and avg >= 60: return "bull_bias"
    if win_rate < 40 or avg < 45:    return "bear_bias"
    return "notr"


def ai_driven_risk_pct() -> float:
    brain = brain_load()
    rw = int(brain.get("stats", {}).get("recent_wins", 0))
    rt = int(brain.get("stats", {}).get("recent_total", 0))
    if rt < 5: return config.OTO_MAX_RISK_PCT
    win_rate = rw / rt
    avg_win = float(brain.get("stats", {}).get("avg_win_pct", 5.0))
    avg_loss = float(brain.get("stats", {}).get("avg_loss_pct", 3.0))
    if avg_loss <= 0: return config.OTO_MAX_RISK_PCT
    b = avg_win / avg_loss
    kelly = (win_rate * b - (1 - win_rate)) / b
    kelly = max(0.0, min(0.25, kelly))
    half = kelly * 0.5
    return max(0.01, min(half, config.OTO_MAX_RISK_PCT * 2))
