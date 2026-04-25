"""Uyuyan Mücevher (Sleeping Gem) puanlama modülü.

Düşük piyasa değerli + 52 hafta dibinde + uzun süre yatay seyreden +
henüz harekete başlamamış + akıllı paranın sessizce sızdığı + yüksek
potansiyele sahip hisselere ekstra bonus puan üretir.

Hem ``scoring.py`` hem ``scoring_phpmatch.py`` ve breakdown ekranı
aynı mantığı bu modülden alır.
"""
from __future__ import annotations

from typing import Any


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def sleeper_breakdown(stock: dict) -> tuple[int, list[tuple[str, str, int]]]:
    """Uyuyan Mücevher puanını ve kalem listesini döndür.

    Dönüş:
        (toplam_puan, [(emoji, açıklama, puan), ...])
    """
    items: list[tuple[str, str, int]] = []

    cap = _f(stock.get("marketCap"))
    if cap <= 0 or cap >= 5_000:
        return 0, items

    pos52 = _f(stock.get("pos52wk"), 50)
    roc60 = _f(stock.get("roc60"))
    roc20 = _f(stock.get("roc20"))
    roc5 = _f(stock.get("roc5"))
    rsi = _f(stock.get("rsi"), 50)
    mfi = _f(stock.get("mfi"), 50)
    cmf = _f(stock.get("cmf"))
    adx = _f(stock.get("adxVal"))
    vol_r = _f(stock.get("volRatio"), 1.0)
    halkak = _f(stock.get("halkAciklik"))

    # ── Guard 1: Zaten patlamış mı? ───────────────────────────────
    if stock.get("katlamis"):
        return 0, items
    if pos52 > 55:
        return 0, items
    if roc60 > 35:
        return 0, items
    # Hacim spike + güçlü mum → artık "uyuyan" değil
    if vol_r > 3.5 and roc5 > 6:
        return 0, items

    # ── 1. Lot/Cap büyüklüğü ──────────────────────────────────────
    if cap < 250:
        items.append(("💎", f"Nano Cap — lotu çok az ({round(cap)}M₺)", 14))
    elif cap < 500:
        items.append(("🏷️", f"Mikro Cap — lotu az ({round(cap)}M₺)", 10))
    elif cap < 1_000:
        items.append(("🏷️", f"Küçük Cap ({round(cap/1000,2)}B₺)", 6))
    elif cap < 2_500:
        items.append(("🏷️", f"Düşük Cap ({round(cap/1000,2)}B₺)", 3))

    # ── 2. 52 Hafta dibe yakınlık ─────────────────────────────────
    if pos52 < 10:
        items.append(("📉", f"52 hafta tabanında (%{round(pos52)})", 14))
    elif pos52 < 20:
        items.append(("📉", f"52 hafta dip bölgesinde (%{round(pos52)})", 9))
    elif pos52 < 35:
        items.append(("📉", f"52 hafta alt çeyreğinde (%{round(pos52)})", 4))

    # ── 3. Uzun süredir yatay seyir ───────────────────────────────
    if abs(roc60) < 8 and abs(roc20) < 5 and abs(roc5) < 3:
        items.append(("🛌", "Çok uzun süredir yatay (60g/20g/5g hareketsiz)", 14))
    elif abs(roc60) < 12 and abs(roc5) < 4:
        items.append(("🛌", "Uzun süredir yatay seyir (60g hareketsiz)", 10))
    elif abs(roc60) < 20 and abs(roc5) < 6:
        items.append(("🛌", "Yatay seyir devam ediyor", 5))

    # ── 4. Volatilite sıkışması (TTM Squeeze derinliği) ───────────
    bb_sq = bool(stock.get("bbSqueeze"))
    kelt_sq = bool(stock.get("keltnerSqueeze"))
    bb_d = stock.get("bb") or {}
    bb_width = _f(bb_d.get("width") if isinstance(bb_d, dict) else 0)
    if bb_sq and kelt_sq:
        items.append(("🎯", "TTM Squeeze: BB + Keltner birlikte sıkışmış", 12))
    elif bb_sq:
        items.append(("🎯", "Bollinger Band sıkışması", 6))
    if 0 < bb_width < 4:
        items.append(("🪤", f"Aşırı dar BB ({round(bb_width,1)}%) — patlama yakın", 6))

    # ── 5. Sessiz akıllı para sızması ─────────────────────────────
    obv_trend = stock.get("obvTrend")
    net_para = _f(stock.get("netParaAkis"))
    para_gir = _f(stock.get("paraGiris"))
    quiet_signals = 0
    if cmf > 0.05 and abs(roc20) < 5:
        quiet_signals += 1
    if obv_trend == "artis" and abs(roc20) < 5:
        quiet_signals += 1
    if mfi > 35 and rsi < 50 and abs(roc20) < 5:
        # MFI yukarı, RSI hala dipte — tipik akkıllı para diverjansı
        quiet_signals += 1
    if net_para > 0 and para_gir > 0 and (net_para / max(para_gir * 2, 1)) > 0.05 and abs(roc20) < 5:
        quiet_signals += 1
    if quiet_signals >= 3:
        items.append(("🤫", "Sessiz akıllı para sızıyor (CMF/OBV/MFI/Akış pozitif, fiyat yatay)", 16))
    elif quiet_signals >= 2:
        items.append(("🤫", "Akıllı para birikim sinyali", 10))
    elif quiet_signals >= 1:
        items.append(("🤫", "Birikim emaresi", 4))

    # ── 6. Boğa diverjansı ────────────────────────────────────────
    div_rsi = stock.get("divRsi")
    div_macd = stock.get("divMacd")
    if div_rsi == "boga":
        items.append(("🔄", "RSI boğa diverjansı (dipte güç toplama)", 12))
    if div_macd == "boga":
        items.append(("🔄", "MACD boğa diverjansı", 10))

    # ── 7. SMC + Order Flow teyidi ────────────────────────────────
    smc_bias = stock.get("smcBias")
    ofi = stock.get("ofiSig")
    smc = stock.get("smc") or {}
    sweep = (smc.get("sweep") if isinstance(smc, dict) else None) or "none"
    if smc_bias == "bullish" and ofi in ("alis", "guclu_alis"):
        items.append(("🐳", "SMC boğa + alış emir akışı (kurumsal hazırlık)", 12))
    elif smc_bias == "bullish":
        items.append(("🐳", "SMC boğa yapı", 6))
    if sweep in ("alt_likidite", "low_sweep", "bullish_sweep", "bull"):
        items.append(("🌊", "Likidite süpürmesi (alt taraftan) — geri dönüş bekleniyor", 8))

    # ── 8. VWAP/Destek altı seans onayı ──────────────────────────
    vwap_pos = stock.get("vwapPos")
    if vwap_pos == "alt2":
        items.append(("📍", "Seans içi VWAP'ın iki band altında (sürekli birikim)", 8))
    elif vwap_pos == "alt1":
        items.append(("📍", "Seans içi VWAP altında", 4))
    sup = _f(stock.get("sup"))
    fiyat = _f(stock.get("guncel"))
    if sup > 0 and fiyat > 0:
        sd = (fiyat - sup) / fiyat * 100
        if sd < 2:
            items.append(("🧱", f"Sağlam destek üstünde (%{round(sd,1)})", 6))

    # ── 9. Free float "tatlı nokta" ──────────────────────────────
    if 10 <= halkak <= 35 and cap < 2000:
        items.append(("🎈", f"Az lot + uygun halka açıklık (%{round(halkak)}) — hızlı hareket potansiyeli", 8))

    # ── 10. Yüksek potansiyel teyidi ─────────────────────────────
    adil = _f(stock.get("adil"))
    pddd = _f(stock.get("pddd"))
    fk = _f(stock.get("fk"))
    if adil > 0 and fiyat > 0:
        upside = (adil - fiyat) / fiyat
        if upside > 1.0:
            items.append(("🎯", f"Adil değere göre +%{round(upside*100)} potansiyel", 14))
        elif upside > 0.5:
            items.append(("🎯", f"Adil değere göre +%{round(upside*100)} potansiyel", 9))
        elif upside > 0.3:
            items.append(("🎯", f"Adil değere göre +%{round(upside*100)} potansiyel", 6))
    if 0 < pddd < 0.7:
        items.append(("💰", f"PD/DD {round(pddd,2)} — defter değerinin çok altında", 8))
    elif 0 < pddd < 1.0:
        items.append(("💰", f"PD/DD {round(pddd,2)} — defter değerinin altında", 5))
    if 0 < fk < 6:
        items.append(("💵", f"F/K {round(fk,1)} — çok ucuz", 6))

    # ── 11. Sağlam zemin (uyuyan AMA sağlıklı) ───────────────────
    net_kar = _f(stock.get("netKar"))
    son4c = _f(stock.get("sonDortCeyrek"))
    borc = _f(stock.get("borcOz"))
    healthy = 0
    if net_kar > 0:
        healthy += 1
    if son4c > 0:
        healthy += 1
    if 0 < borc < 1.0:
        healthy += 1
    if healthy >= 3:
        items.append(("🛡️", "Sağlam zemin: kâr pozitif + son 4 çeyrek kârlı + düşük borç", 10))
    elif healthy >= 2:
        items.append(("🛡️", "Temel sağlamlık tamam", 5))

    # ── 12. Aşırı satım onayı (henüz harekete başlamamış) ────────
    if rsi < 40 and mfi < 40 and adx < 20:
        items.append(("😴", "RSI/MFI düşük + ADX zayıf — uyuyor", 6))

    total = sum(p for _, _, p in items)
    return total, items
