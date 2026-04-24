"""AI Transparency Panel — v37.3
========================================================================
Her hisse için AI'ın aldığı kararın TAM kırılımını üretir:
  • Faz 1: Al Puanı tabanı (teknik + temel + formasyon — build_ai_breakdown)
  • Faz 2: Brain confluence pattern eşleşmesi (geçmiş başarı oranı)
  • Faz 3: Triple Neural Network (alpha + beta + gamma) + konsensüs çarpanı
  • Faz 4: Hisseye özel hafıza (per-stock memory)
  • Faz 5: Time-of-week bonus (gün-bazlı tarihsel başarı)
  • Faz 6: Harmonik formasyonlar (Gartley, Bat, Butterfly, Crab)
  • Faz 7: SMC zengin yapı bonusu (FVG, Order Blocks, BOS/CHoCH)
  • Faz 8: Piyasa modu çarpanı (boğa/temkinli/ayı)

Ek olarak:
  • Confidence (0-100): NN uyum + örnek sayısı + sinyal yoğunluğu
  • Anomalies: birbiriyle çelişen sinyaller (örn. RSI<20 ama ADX güçlü düşüş)
"""
from __future__ import annotations
from typing import Any


def _n(x, d: float = 0.0) -> float:
    try: return float(x)
    except Exception: return d


def _label_pattern(key: str) -> str:
    """Confluence anahtarını okunur Türkçe etikete çevir."""
    parts = key.split("|")
    tr = {
        "RSI_EXT": "RSI aşırı aşırı satım", "RSI_LOW": "RSI aşırı satım",
        "RSI_MID": "RSI nötr-düşük",        "RSI_HIGH": "RSI yüksek",
        "MACD_G": "MACD Golden Cross",      "MACD_D": "MACD Death Cross",
        "MACD_N": "MACD nötr",
        "VOL_XX": "Patlama hacim (3x+)",    "VOL_X": "Yüksek hacim (2x+)",
        "VOL_H": "Artan hacim (1.5x+)",     "VOL_N": "Normal hacim",
        "SAR_UP": "SAR yükseliş",           "SAR_DN": "SAR düşüş", "SAR_NO": "SAR nötr",
        "BB_SQ": "BB sıkışması",            "BB_NO": "BB normal",
        "ADX_UP": "ADX yükseliş",           "ADX_DN": "ADX düşüş", "ADX_NO": "ADX zayıf",
        "TR_UP": "Trend yukarı",            "TR_DN": "Trend aşağı", "TR_NO": "Trend yan",
        "CMF_P": "CMF pozitif (para girişi)","CMF_N": "CMF negatif", "CMF_NO": "CMF nötr",
        "ST_UP": "Supertrend AL",           "ST_DN": "Supertrend SAT", "ST_NO": "Supertrend nötr",
        "HU_UP": "Hull yukarı",             "HU_DN": "Hull aşağı", "HU_NO": "Hull nötr",
    }
    return " + ".join(tr.get(p, p) for p in parts[:5])


def _detect_anomalies(stock: dict) -> list[str]:
    """Birbiriyle çelişen güçlü sinyaller — AI'ın dikkat etmesi gereken durumlar."""
    out: list[str] = []
    rsi = _n(stock.get("rsi"), 50)
    adx_v = _n(stock.get("adxVal"), 0)
    adx_d = stock.get("adxDir") or "notr"
    vol = _n(stock.get("volRatio"), 1)
    macd = stock.get("macdCross") or ""
    div_rsi = stock.get("divRsi") or ""
    smc = stock.get("smcBias") or ""
    cmf_v = _n(stock.get("cmf"), 0)
    bb_pct = _n(stock.get("bbPct"), 50)

    if rsi < 25 and adx_v >= 30 and adx_d == "dusus":
        out.append("⚠️ RSI dipte ama ADX güçlü düşüş — düşen bıçağı yakalama riski")
    if rsi > 75 and macd == "death":
        out.append("⚠️ RSI tepede + MACD Death Cross — momentum çöküyor")
    if vol >= 3.0 and bb_pct > 90:
        out.append("⚠️ Patlama hacim + BB üst bant — euphoria/dağıtım riski")
    if div_rsi == "boga" and cmf_v < -0.15:
        out.append("⚠️ RSI boğa diverjansı ama para çıkışı — sinyal zayıf olabilir")
    if smc == "bullish" and adx_d == "dusus" and adx_v >= 25:
        out.append("⚠️ SMC boğa görüşü ama ADX düşüş trendi onaylıyor — çelişki")
    if vol < 0.5 and macd == "golden":
        out.append("⚠️ Hacimsiz MACD Golden Cross — sinyal güvenilirliği düşük")
    return out


def _confidence_score(active_n: int, divergent: bool,
                      conf_n: int, psm_n: int,
                      pos_signals: int, neg_signals: int) -> int:
    """0-100 güven puanı:
      • NN konsensüs gücü (active_n / divergent)
      • Brain örnek hacmi (confluence n + per-stock n)
      • Sinyal yoğunluğu ve uyumu (pos vs neg dengesi)
    """
    nn_c = {0: 0, 1: 25, 2: 55, 3: 85}.get(active_n, 0)
    if divergent: nn_c = max(0, nn_c - 25)

    sample_c = min(40, conf_n * 2 + psm_n * 3)

    total = pos_signals + neg_signals
    if total == 0:
        bal_c = 0
    else:
        ratio = pos_signals / total if pos_signals >= neg_signals else neg_signals / total
        density = min(1.0, total / 12.0)
        bal_c = int(round((ratio - 0.5) * 50 * density))

    return max(0, min(100, int(round((nn_c * 0.45) + (sample_c * 0.30) + (bal_c * 0.25 + 25)))))


def build_full_ai_explain(stock: dict, base_breakdown: dict | None = None) -> dict:
    """Hisse için tam AI karar kırılımı.

    `base_breakdown`: build_ai_breakdown çıktısı (opsiyonel; verilmezse sadece
    üst-katman bonuslar gösterilir).
    """
    code  = (stock.get("code") or "").upper()
    fiyat = _n(stock.get("guncel"), 0)

    phases: list[dict] = []
    pos_signals = 0
    neg_signals = 0

    # ── Faz 1: Al Puanı tabanı (teknik + temel + formasyon) ──────────────
    base_items = (base_breakdown or {}).get("items") or []
    base_pos = 0; base_neg = 0
    for it in base_items:
        try:
            v = int(str(it[2]).replace("+", "").replace("%", "")) if it[2] else 0
        except Exception: v = 0
        if v > 0: base_pos += v; pos_signals += 1
        elif v < 0: base_neg += v; neg_signals += 1
    phases.append({
        "name": "📊 Al Puanı Tabanı (Teknik + Temel + Formasyon)",
        "points": base_pos + base_neg,
        "items": [
            ["Pozitif sinyal toplamı", f"+{base_pos}", "neon-grn"],
            ["Negatif sinyal toplamı", f"{base_neg}",  "neon-red"],
            ["Toplam sinyal sayısı",   f"{len(base_items)}", "muted"],
            ["Net Al Puanı katkısı",   f"{base_pos + base_neg:+d}", "neon-cy"],
        ],
    })

    # ── Faz 2-5: Brain (lazy import — circular avoid) ─────────────────────
    try:
        from .brain import (
            brain_load, brain_get_confluence_bonus, brain_get_time_bonus,
            neural_dual_bonus,
        )
        from .scoring_extras import get_confluence_key
        brain = brain_load()
    except Exception:
        brain = {}

    # Faz 2 — Confluence
    conf_bonus = 0
    conf_n = 0
    conf_items: list[list] = []
    try:
        conf_bonus = brain_get_confluence_bonus(stock, brain)
        key = get_confluence_key(stock)
        cp = brain.get("confluence_patterns") or {}
        data = cp.get(key) or {}
        conf_n = int(data.get("count", 0) or 0)
        wr = float(data.get("win_rate", 0) or 0)
        avg = float(data.get("avg_ret", 0) or 0)
        weight = float(data.get("weight", 1.0) or 1.0)
        if conf_n >= 4:
            conf_items.append([f"Pattern: {_label_pattern(key)}", "tam eşleşme", "neon-cy"])
            conf_items.append([f"Geçmiş örnek sayısı", f"{conf_n} işlem", "muted"])
            conf_items.append([f"Geçmiş kazanma oranı", f"%{wr:.1f}", "neon-grn" if wr >= 55 else ("neon-red" if wr < 45 else "muted")])
            conf_items.append([f"Geçmiş ortalama getiri", f"{avg:+.2f}%", "neon-grn" if avg > 0 else "neon-red"])
            conf_items.append([f"Pattern güven ağırlığı", f"×{weight:.2f}", "muted"])
        else:
            # prefix fallback bilgisi
            prefix = "|".join(key.split("|")[:3])
            agg_n = sum(int(d.get("count", 0) or 0) for k, d in cp.items()
                        if isinstance(d, dict) and k.startswith(prefix + "|"))
            if agg_n >= 8:
                conf_items.append([f"Tam pattern: {_label_pattern(key)}", "yetersiz örnek", "muted"])
                conf_items.append([f"Prefix yedeği: RSI+MACD+Hacim", f"{agg_n} işlem", "neon-cy"])
                conf_items.append(["Prefix güven katsayısı", "×0.6", "muted"])
            else:
                conf_items.append([f"Pattern: {_label_pattern(key)}", "öğrenme aşamasında", "muted"])
                conf_items.append(["Toplanmış örnek", f"{conf_n}/4 (en az gerekli)", "muted"])
        if conf_bonus != 0:
            if conf_bonus > 0: pos_signals += 1
            else: neg_signals += 1
    except Exception:
        pass
    phases.append({
        "name": "🧠 Beyin: Confluence Pattern (geçmiş başarı)",
        "points": conf_bonus,
        "items": conf_items or [["Pattern verisi yok", "—", "muted"]],
    })

    # Faz 3 — Triple Neural Network
    nn_items: list[list] = []
    nn_total = 0
    try:
        final_b, alpha, beta, gamma, active_n, divergent = neural_dual_bonus(stock, brain)
        nn_total = int(final_b)
        nA = (brain.get("neural_net")       or {})
        nB = (brain.get("neural_net_beta")  or {})
        nG = (brain.get("neural_net_gamma") or {})
        def _row(name, val, nn):
            tr = int(nn.get("trained_samples", 0) or 0)
            acc = float(nn.get("recent_accuracy", 50.0) or 50.0)
            cls = "neon-grn" if val > 0 else ("neon-red" if val < 0 else "muted")
            tag = f"{val:+d} puan  •  {tr} örnek eğitildi  •  isabet %{acc:.1f}"
            return [f"NN-{name}", tag, cls]
        nn_items.append(_row("Alpha (ana ağ)",  int(alpha), nA))
        nn_items.append(_row("Beta  (rakip)",   int(beta),  nB))
        nn_items.append(_row("Gamma (üçüncü)",  int(gamma), nG))
        # konsensüs çarpanı
        if active_n == 3 and not divergent:
            nn_items.append(["Konsensüs", "3/3 tam uyum (×1.50)", "neon-grn"])
        elif active_n == 2 and not divergent:
            nn_items.append(["Konsensüs", "2/3 çoğunluk (×1.10)", "neon-grn"])
        elif divergent:
            nn_items.append(["Konsensüs", "Beyinler bölünmüş (×0.40)", "neon-red"])
        elif active_n == 1:
            nn_items.append(["Konsensüs", "Tek beyin (×0.65)", "muted"])
        nn_items.append(["NN Final Bonus", f"{nn_total:+d}", "neon-cy"])
        if nn_total != 0:
            if nn_total > 0: pos_signals += 1
            else: neg_signals += 1
    except Exception as e:
        nn_items.append(["NN hata", str(e), "neon-red"])
        active_n = 0; divergent = False
    phases.append({
        "name": "🧬 Üçlü Yapay Sinir Ağı (Alpha + Beta + Gamma)",
        "points": nn_total,
        "items": nn_items,
    })

    # Faz 4 — Per-Stock Memory
    psm_n = 0
    psm_bonus = 0
    psm_items: list[list] = []
    try:
        psm = (brain.get("per_stock_memory") or {}).get(code) or {}
        psm_n = int(psm.get("n", 0) or 0)
        if psm_n >= 4:
            hits = int(psm.get("hits", 0) or 0)
            wr = hits / psm_n * 100 if psm_n else 0
            avg_ret = float(psm.get("ret_sum", 0.0) or 0.0) / psm_n
            conf = min(1.0, (psm_n - 3) / 12.0)
            if   wr >= 70 and avg_ret > 2: psm_bonus = int(round( 10 * conf))
            elif wr >= 60 and avg_ret > 0: psm_bonus = int(round(  6 * conf))
            elif wr <= 30 and avg_ret < 0: psm_bonus = int(round(-10 * conf))
            elif wr <= 40:                  psm_bonus = int(round( -5 * conf))
            psm_items.append([f"{code} özelinde tahmin sayısı", f"{psm_n} işlem", "muted"])
            psm_items.append([f"İsabet oranı", f"%{wr:.1f}", "neon-grn" if wr >= 60 else ("neon-red" if wr < 40 else "muted")])
            psm_items.append([f"Ortalama gerçek getiri", f"{avg_ret:+.2f}%", "neon-grn" if avg_ret > 0 else "neon-red"])
            psm_items.append([f"Güven katsayısı", f"×{conf:.2f}", "muted"])
            if psm_bonus != 0:
                if psm_bonus > 0: pos_signals += 1
                else: neg_signals += 1
        else:
            psm_items.append([f"{code} hafızası", f"{psm_n}/4 örnek (öğrenme)", "muted"])
    except Exception:
        psm_items.append(["Hafıza", "veri yok", "muted"])
    phases.append({
        "name": f"💾 Hisseye Özel Hafıza ({code})",
        "points": psm_bonus,
        "items": psm_items,
    })

    # Faz 5 — Time-of-week
    time_b = 0
    time_items: list[list] = []
    try:
        time_b = brain_get_time_bonus(brain)
        import datetime as _dt
        dow = _dt.date.today().isoweekday()
        gun_tr = ["Pazartesi","Salı","Çarşamba","Perşembe","Cuma","Cumartesi","Pazar"][dow-1]
        tp = brain.get("time_patterns") or {}
        td = tp.get(f"dow_{dow}") or {}
        n = int(td.get("count", 0) or 0)
        if n >= 3:
            time_items.append([f"Bugün ({gun_tr}) tarihsel örnek", f"{n} işlem", "muted"])
            time_items.append(["Bu güne özel kazanma oranı", f"%{float(td.get('win_rate',0)):.1f}", "muted"])
            time_items.append(["Ortalama getiri", f"{float(td.get('avg_ret',0)):+.2f}%", "muted"])
            time_items.append(["Final ağırlığı", "×0.5 (puan etkisi yarıya indirilir)", "muted"])
        else:
            time_items.append([f"Bugün ({gun_tr})", f"{n}/3 örnek (öğrenme)", "muted"])
        if time_b != 0:
            if time_b > 0: pos_signals += 1
            else: neg_signals += 1
    except Exception:
        time_items.append(["Zaman bonusu", "veri yok", "muted"])
    phases.append({
        "name": "📅 Haftanın Günü (zaman bazlı bonus)",
        "points": int(round(time_b * 0.5)),  # final ağırlık 0.5
        "items": time_items,
    })

    # ── Faz 6: Harmonik formasyonlar ──────────────────────────────────────
    harm_items: list[list] = []
    harm_total = 0
    for harm in (stock.get("harmonics") or []):
        if not isinstance(harm, dict): continue
        h_conf = _n(harm.get("confidence"))
        h_type = harm.get("type", "")
        h_prz  = _n(harm.get("prz"))
        h_pat  = harm.get("pattern", "Harmonik")
        if h_conf < 65: continue
        prz_near = h_prz > 0 and fiyat > 0 and abs(fiyat - h_prz) / h_prz < 0.03
        bonus = 0
        if h_type == "bullish":
            bonus = int(round((h_conf - 60) / 4))
            if prz_near: bonus += 15
            bonus = min(25, bonus)
            harm_items.append([f"🔷 {h_pat} (boğa)", f"+{bonus} • güven %{h_conf:.0f}{' • PRZ yakını' if prz_near else ''}", "neon-grn"])
            pos_signals += 1
        elif h_type == "bearish":
            bonus = -min(20, int(round((h_conf - 60) / 5)) + (10 if prz_near else 0))
            harm_items.append([f"🔻 {h_pat} (ayı)", f"{bonus} • güven %{h_conf:.0f}{' • PRZ yakını' if prz_near else ''}", "neon-red"])
            neg_signals += 1
        harm_total += bonus
    if not harm_items:
        harm_items.append(["Aktif harmonik formasyon", "yok", "muted"])
    phases.append({
        "name": "🎯 Harmonik Formasyonlar (Gartley/Bat/Butterfly/Crab)",
        "points": harm_total,
        "items": harm_items,
    })

    # ── Faz 7: SMC zengin yapı ────────────────────────────────────────────
    smc_items: list[list] = []
    smc_total = 0
    try:
        from .scoring import smc_score_bonus as _smc_bonus
        smc_full = stock.get("smc") or stock.get("smcFull")
        if smc_full and isinstance(smc_full, dict):
            smc_total = int(_smc_bonus(smc_full, fiyat))
            bias = smc_full.get("bias") or stock.get("smcBias") or "notr"
            obs = [o for o in (smc_full.get("orderBlocks") or []) if isinstance(o, dict)]
            fvgs = [f for f in (smc_full.get("fvg") or []) if isinstance(f, dict)]
            liq = smc_full.get("liquidity") or {}
            bos = smc_full.get("bos") or smc_full.get("structure") or "—"
            smc_items.append(["Genel SMC bias", bias, "neon-grn" if bias == "bullish" else ("neon-red" if bias == "bearish" else "muted")])
            smc_items.append(["Yapı (BOS/CHoCH)", str(bos), "muted"])
            smc_items.append(["Order Block sayısı", str(len(obs)), "muted"])
            smc_items.append(["Fair Value Gap sayısı", str(len(fvgs)), "muted"])
            if liq: smc_items.append(["Likidite seviyeleri", f"{len(liq) if isinstance(liq,(list,dict)) else 0} adet", "muted"])
        else:
            bias = stock.get("smcBias") or "notr"
            if   bias == "bullish": smc_total =  10
            elif bias == "bearish": smc_total = -10
            smc_items.append(["SMC bias (basit)", bias, "muted"])
        if smc_total != 0:
            if smc_total > 0: pos_signals += 1
            else: neg_signals += 1
    except Exception:
        smc_items.append(["SMC", "veri yok", "muted"])
    phases.append({
        "name": "🏛️ Smart Money Concepts (Order Block + FVG + Likidite)",
        "points": smc_total,
        "items": smc_items,
    })

    # ── Faz 8: Piyasa modu çarpanı ────────────────────────────────────────
    try:
        from .scoring_extras import get_market_mode
        mode = get_market_mode()
    except Exception:
        mode = "normal"
    mode_items: list[list] = []
    mode_pts = 0
    if   mode == "ayi":      mode_pts = -35; mode_items.append(["Ayı modu", "AI puanından %35 kesinti", "neon-red"])
    elif mode == "temkinli": mode_pts = -15; mode_items.append(["Temkinli mod", "AI puanından %15 kesinti", "neon-red"])
    elif mode == "bull":     mode_pts =  +5; mode_items.append(["Boğa modu", "+5 mutlak bonus", "neon-grn"])
    else:                    mode_items.append(["Normal mod", "çarpan etkisi yok", "muted"])
    phases.append({
        "name": "🌍 Piyasa Modu Çarpanı",
        "points": mode_pts,
        "items": mode_items,
    })

    # ── Confidence + Anomalies ─────────────────────────────────────────────
    conf_score = _confidence_score(active_n if 'active_n' in locals() else 0,
                                   divergent if 'divergent' in locals() else False,
                                   conf_n, psm_n, pos_signals, neg_signals)
    anomalies = _detect_anomalies(stock)

    return {
        "code": code,
        "phases": phases,
        "confidence": conf_score,
        "anomalies": anomalies,
        "aiScore": int(stock.get("aiScore") or 0),
        "alPuani": int(stock.get("alPuani") or 0),
        "decision": stock.get("autoThinkDecision") or stock.get("aiKarar") or "—",
        "pos_signals": pos_signals,
        "neg_signals": neg_signals,
    }
