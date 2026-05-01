"""Katlama Hedefleri Modülü — Tüm verileri kullanarak H1/H2/H3 tespit.

Mevcut calculate_buy_sell_targets sadece swing dirençleri + basit R/R kullanır.
Bu modül ek olarak şu kaynakları entegre eder:
  1) Fibonacci EKSTANSİYONLARI (1.236, 1.382, 1.618, 2.0, 2.618, 4.236)
  2) Graham adil değeri
  3) SMC Order Block / FVG seviyeleri
  4) VWAP Bant hedefleri
  5) 52 hafta yüksek seviyesi
  6) Donchian üst kanal
  7) Katlama DNA benzerlik bonusu
  8) Brain/Neural tahmin ağırlığı
  9) Hacim / momentum çarpanı
  10) Halka açıklık + marketCap faktörü
  11) ATR tabanlı dinamik hedefler (AI çarpanlı)
  12) Sektör momentum ağırlığı

Her seviye (H1/H2/H3) en güçlü kaynaklardan oy birliğiyle belirlenir.
KatlamaScore (0-100) hissenin 2X/3X/5X potansiyelini puanlar.
"""
from __future__ import annotations

import math
from typing import Any


# ── yardımcılar ─────────────────────────────────────────────────────────────

def _n(v: Any, default: float = 0.0) -> float:
    """Güvenli float dönüşümü — dict/list/None/NaN toleranslı."""
    if isinstance(v, dict):
        for k in ("value", "val", "adx", "rsi", "score", "current", "close"):
            if k in v:
                v = v[k]
                break
        else:
            return default
    if isinstance(v, (list, tuple)):
        v = v[-1] if v else default
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default


def _pct(new: float, base: float) -> float:
    """Yüzde değişim (base > 0 garantili)."""
    if base <= 0:
        return 0.0
    return round((new - base) / base * 100, 2)


# ── Fibonacci Ekstansiyon Hedefleri ──────────────────────────────────────────

def _fib_extensions(swing_low: float, swing_high: float, from_price: float) -> dict:
    """
    Klasik Fibonacci ekstansiyonu: (swing_high - swing_low) * oran + swing_low
    ve aynı zamanda swing_high üzerinden projeksiyon.

    Döner: {ext1236, ext1382, ext1618, ext200, ext2618, ext4236}
    """
    if swing_high <= swing_low or swing_high <= 0 or swing_low <= 0:
        return {}
    diff = swing_high - swing_low
    # Standart Fibonacci ekstansiyon oranları
    exts = {
        "ext1000": round(swing_high + diff * 0.000, 2),   # zirve kendisi
        "ext1236": round(swing_high + diff * 0.236, 2),
        "ext1382": round(swing_high + diff * 0.382, 2),
        "ext1618": round(swing_high + diff * 0.618, 2),
        "ext200":  round(swing_high + diff * 1.000, 2),
        "ext2618": round(swing_high + diff * 1.618, 2),
        "ext4236": round(swing_high + diff * 3.236, 2),
    }
    # Sadece mevcut fiyatın üzerindeki seviyeleri döndür
    return {k: v for k, v in exts.items() if v > from_price * 1.005}


# ── SMC seviye çıkarıcı ───────────────────────────────────────────────────────

def _smc_targets(smc: dict | None, from_price: float) -> list[tuple[float, str, int]]:
    """SMC Order Block + FVG dirençlerini (fiyat, kaynak, güç) listesi olarak döndür."""
    targets: list[tuple[float, str, int]] = []
    if not isinstance(smc, dict):
        return targets
    for ob in (smc.get("orderBlocks") or []):
        if not isinstance(ob, dict):
            continue
        if ob.get("type") != "bullish" or ob.get("mitigated"):
            continue
        top = _n(ob.get("top"))
        if top > from_price * 1.01:
            targets.append((top, "SMC-OB", int(_n(ob.get("strength"), 3))))
    for fvg in (smc.get("fvg") or []):
        if not isinstance(fvg, dict):
            continue
        if fvg.get("type") != "bullish" or fvg.get("filled"):
            continue
        top = _n(fvg.get("top"))
        if top > from_price * 1.01:
            targets.append((top, "SMC-FVG", 3))
    return targets


# ── Ağırlıklı hedef seçici ──────────────────────────────────────────────────

def _pick_target(candidates: list[tuple[float, str, int]],
                 above: float, max_ratio: float = 5.0) -> tuple[float, str]:
    """
    Birden fazla kaynak hedefini birleştirip en yüksek oy alan seviyeyi seç.
    candidates: [(fiyat, kaynak, güç), ...]
    above: bu değerin üstünde olmalı
    max_ratio: above * max_ratio'dan büyük olanları ele.
    """
    valid = [(p, src, w) for p, src, w in candidates
             if p > above * 1.005 and p <= above * max_ratio and p > 0]
    if not valid:
        return 0.0, ""
    # ±2% kümele, toplu güç hesabı
    sorted_v = sorted(valid, key=lambda x: x[0])
    clusters: list[list[tuple[float, str, int]]] = []
    cur_cl: list[tuple[float, str, int]] = [sorted_v[0]]
    for item in sorted_v[1:]:
        if abs(item[0] - cur_cl[0][0]) / max(cur_cl[0][0], 0.01) < 0.022:
            cur_cl.append(item)
        else:
            clusters.append(cur_cl)
            cur_cl = [item]
    clusters.append(cur_cl)
    best_score = -1
    best_price = 0.0
    best_src = ""
    for cl in clusters:
        total_w = sum(w for _, _, w in cl)
        avg_p = sum(p * w for p, _, w in cl) / max(total_w, 1)
        srcs = "+".join(sorted({s for _, s, _ in cl}))
        if total_w > best_score:
            best_score = total_w
            best_price = round(avg_p, 2)
            best_src = srcs
    return best_price, best_src


# ══════════════════════════════════════════════════════════════════════════════
# ANA FONKSİYON: calculate_katlama_targets
# ══════════════════════════════════════════════════════════════════════════════

def calculate_katlama_targets(
    stock: dict,
    clustered_levels: list | None = None,
    katlama_archive: list | None = None,
) -> dict:
    """
    Tüm verileri kullanarak geliştirilmiş H1/H2/H3 katlama hedeflerini hesapla.

    Parametreler
    ────────────
    stock            : Scan çıktısı (tüm teknik + temel alanlar dolu olmalı)
    clustered_levels : find_swing_levels → cluster_levels çıktısı (opsiyonel)
    katlama_archive  : Geçmiş katlama DNA arşivi (opsiyonel)

    Dönüş
    ─────
    {
      "h1": float,          # Hedef 1 (muhafazakâr)
      "h2": float,          # Hedef 2 (orta)
      "h3": float,          # Hedef 3 (agresif / katlama)
      "h1Src": str,
      "h2Src": str,
      "h3Src": str,
      "h1Pct": float,       # Mevcut fiyata göre % artış
      "h2Pct": float,
      "h3Pct": float,
      "katlamaScore": int,  # 0-100
      "katlamaLevel": str,  # "5X"|"3X"|"2X"|"1.5X"|"NORMAL"
      "katlamaPotansiyel": float,   # H3/fiyat çarpanı (ör. 3.2 = 3.2X)
      "katlamaReasons": list[dict], # Neden katlama adayı?
      "fibTargets": dict,
      "allCandidates": list,        # debug — tüm aday seviyeler
    }
    """
    fiyat = _n(stock.get("guncel"))
    if fiyat <= 0:
        return _empty_result()

    atr    = _n(stock.get("atr14") or stock.get("atr"))
    adil   = _n(stock.get("adil"))
    adx    = _n(stock.get("adxVal"))
    rsi    = _n(stock.get("rsi"), 50)
    vol_r  = _n(stock.get("volRatio"), 1)
    cmf    = _n(stock.get("cmf"))
    pos52  = _n(stock.get("pos52wk"), 50)
    halk   = _n(stock.get("halkakAciklik"), 50)
    cap    = _n(stock.get("marketCap"))
    sma20  = _n(stock.get("sma20"))
    sma50  = _n(stock.get("sma50"))
    sma200 = _n(stock.get("sma200"))
    bb_hi  = _n(stock.get("bbHigh"))
    don_up = _n((stock.get("donchian") or {}).get("upper") if isinstance(stock.get("donchian"), dict) else 0)
    vwap   = _n(stock.get("vwap"))
    h52    = _n(stock.get("yuksek52"))        # 52 hafta yüksek
    sar_val = _n((stock.get("sar") or {}).get("sar") if isinstance(stock.get("sar"), dict) else stock.get("sarVal"))
    ret1m  = _n(stock.get("ret1m"))
    ret3m  = _n(stock.get("ret3m"))
    neural_b = _n(stock.get("neuralBonus"))
    sleeper  = _n(stock.get("sleeperBonus"))
    early_b  = _n(stock.get("earlyCatchBonus"))
    kap_b    = _n(stock.get("kapNewsBonus"))
    fib      = stock.get("fib") or stock.get("fibonacci") or {}
    smc      = stock.get("smc") or {}
    ai_score = _n(stock.get("aiScore"))

    clustered_levels = clustered_levels or stock.get("clusteredLevels") or []

    # ── Fibonacci swing noktaları ────────────────────────────────────────────
    # Mevcut fib dict'ten swing high/low al; yoksa 52h ve SMA'lardan tahmin et
    fib_high = _n(fib.get("high")) if isinstance(fib, dict) else 0.0
    fib_low  = _n(fib.get("low"))  if isinstance(fib, dict) else 0.0
    if fib_high <= 0:
        fib_high = h52 if h52 > fiyat else fiyat * 1.1
    if fib_low <= 0:
        fib_low = fiyat * 0.5   # kaba tahmin

    fib_ext = _fib_extensions(fib_low, fib_high, fiyat)

    # ── Tüm aday hedef seviyeleri topla ────────────────────────────────────
    candidates: list[tuple[float, str, int]] = []

    # 1) Fibonacci ekstansiyon seviyeleri
    ext_weights = {
        "ext1000": 3, "ext1236": 4, "ext1382": 5,
        "ext1618": 7, "ext200": 6, "ext2618": 5, "ext4236": 4,
    }
    for k, v in fib_ext.items():
        if v > fiyat * 1.005:
            candidates.append((v, f"Fib-{k}", ext_weights.get(k, 3)))

    # 2) Fibonacci retracement levels üzerinde kalan (geri dönüş sonrası direnç)
    if isinstance(fib, dict):
        fib_direncs = {
            "fib236": 4, "fib382": 5, "fib500": 4,
            "fib618": 5, "fib786": 3,
        }
        for k, w in fib_direncs.items():
            p = _n(fib.get(k))
            if p > fiyat * 1.01:
                candidates.append((p, f"FibR-{k}", w))

    # 3) Graham adil değeri
    if adil > fiyat * 1.03 and adil < fiyat * 6.0:
        w = 8 if adil < fiyat * 2.0 else (6 if adil < fiyat * 3.5 else 4)
        candidates.append((adil, "Graham", w))

    # 4) SMC Order Block / FVG
    for p, src, w in _smc_targets(smc, fiyat):
        candidates.append((p, src, w))

    # 5) Donchian üst kanal
    if don_up > fiyat * 1.01:
        candidates.append((don_up, "Donchian", 4))

    # 6) Bollinger üst bant
    if bb_hi > fiyat * 1.01:
        candidates.append((bb_hi, "BB-Üst", 3))

    # 7) 52 hafta yüksek
    if h52 > fiyat * 1.02:
        candidates.append((h52, "52H-Yük", 6))

    # 8) SMA dirençler (fiyatın üzerindeyse)
    for p, src, w in [(sma20, "SMA20", 3), (sma50, "SMA50", 4), (sma200, "SMA200", 6)]:
        if p > fiyat * 1.015:
            candidates.append((p, src, w))

    # 9) Swing dirençler (clustered_levels)
    for lv in clustered_levels:
        lp = _n(lv.get("price")); strength = int(_n(lv.get("strength"), 1))
        if lv.get("type") == "res" and fiyat * 1.01 < lp < fiyat * 5.0:
            candidates.append((lp, "Swing", min(strength + 1, 8)))

    # 10) ATR tabanlı hedefler (AI çarpanla)
    if atr > 0:
        try:
            from .scoring import _ai_driven_stop_multiplier
            am = _ai_driven_stop_multiplier(adx)
        except Exception:
            am = 2.0
        for ratio, src in [(2.5, "ATR-H1"), (4.0, "ATR-H2"), (6.0, "ATR-H3"), (9.0, "ATR-H3+")]:
            t = round(fiyat + atr * ratio * am, 2)
            if t > fiyat * 1.03 and t < fiyat * 6.0:
                candidates.append((t, src, 3))

    # 11) VWAP bant hedefleri
    vwap_bands = stock.get("vwapBands") or {}
    if isinstance(vwap_bands, dict):
        for k in ("upper2", "upper3", "upper4"):
            p = _n(vwap_bands.get(k))
            if p > fiyat * 1.01 and p < fiyat * 5.0:
                candidates.append((p, f"VWAP-{k}", 4))

    # ── Katlama Skoru hesabı ─────────────────────────────────────────────────
    ks = 0  # katlamaScore (0-100)
    reasons: list[dict] = []

    def _add_reason(key: str, label: str, w: int, val: str = "") -> None:
        nonlocal ks
        ks += w
        reasons.append({"key": key, "label": label, "weight": w, "value": val})

    # 52 hafta pozisyon — dibe yakın = katlama potansiyeli yüksek
    if pos52 <= 10:
        _add_reason("pos52_cok_dip", "🐣 52H dibinde (üst %10)", 18, f"%{pos52:.0f}")
    elif pos52 <= 25:
        _add_reason("pos52_dip", "📉 52H dip bölgesi", 12, f"%{pos52:.0f}")
    elif pos52 <= 40:
        _add_reason("pos52_orta_dip", "📊 52H orta-dip", 7, f"%{pos52:.0f}")

    # Hacim patlaması
    if vol_r >= 4.0:
        _add_reason("vol_patlama", "🔥 Olağanüstü hacim patlaması", 16, f"{vol_r:.1f}x")
    elif vol_r >= 2.5:
        _add_reason("vol_yuksek", "📊 Güçlü hacim artışı", 10, f"{vol_r:.1f}x")
    elif vol_r >= 1.5:
        _add_reason("vol_artan", "↑ Artan hacim", 5, f"{vol_r:.1f}x")

    # CMF para akışı
    if cmf > 0.25:
        _add_reason("cmf_kuvvetli", "💰 Güçlü kurumsal para girişi", 10, f"CMF {cmf:.3f}")
    elif cmf > 0.12:
        _add_reason("cmf_pozitif", "💵 CMF pozitif akış", 6, f"CMF {cmf:.3f}")

    # SMC yapısı
    smc_bias = str(smc.get("bias", "") if isinstance(smc, dict) else "").lower()
    if smc_bias in ("bull", "bullish"):
        _add_reason("smc_boga", "🧩 SMC boğa yapısı", 10, "BOS/CHoCH yukarı")
    if isinstance(smc, dict) and (smc.get("bos") or {}).get("dir") == "up" if isinstance(smc.get("bos"), dict) else str(smc.get("bos", "")).startswith("bullish"):
        _add_reason("smc_bos", "🎯 SMC BOS kırılımı", 8, "yapı kırıldı ↑")

    # Brain/Neural bonus
    if neural_b >= 12:
        _add_reason("brain_guclu", "🧠 Triple Brain güçlü konsensüs", 12, f"+{neural_b:.0f}")
    elif neural_b >= 7:
        _add_reason("brain_orta", "🧠 Brain konsensüs olumlu", 7, f"+{neural_b:.0f}")

    # Uyuyan mücevher / erken yakalama
    if sleeper >= 60:
        _add_reason("sleeper", "💤 Uyuyan mücevher tespiti", 12, f"+{sleeper:.0f}")
    elif sleeper >= 30:
        _add_reason("sleeper_orta", "💤 Uyuyan mücevher adayı", 7, f"+{sleeper:.0f}")
    if early_b >= 15:
        _add_reason("early_catch", "🎣 Erken yakalama fırsatı", 10, f"+{early_b:.0f}")

    # KAP haberleri
    if kap_b >= 20:
        _add_reason("kap_haber", "📜 KAP katalist haberi", 8, f"+{kap_b:.0f}")

    # Dar halka açıklık + yüksek hacim = patlatma riski
    if 0 < halk < 20 and vol_r >= 1.5:
        _add_reason("dar_float", "🎈 Dar halka açıklık + hacim", 12, f"%{halk:.0f}")
    elif 0 < halk < 35 and vol_r >= 2.0:
        _add_reason("kucuk_float", "🎈 Küçük float + hacim artışı", 7, f"%{halk:.0f}")

    # Küçük piyasa değeri
    if 0 < cap < 500_000_000:
        _add_reason("micro_cap", "🔬 Mikro Piyasa Değeri", 8, f"{cap/1e6:.0f}M₺")
    elif 0 < cap < 1_500_000_000:
        _add_reason("small_cap", "🔬 Küçük Piyasa Değeri", 5, f"{cap/1e6:.0f}M₺")

    # Momentum geçmişi
    if ret1m >= 50:
        _add_reason("ret1m", "🚀 1 aylık getiri +%50+", 8, f"%{ret1m:.0f}")
    elif ret1m >= 25:
        _add_reason("ret1m_guclu", "📈 1 aylık güçlü getiri", 5, f"%{ret1m:.0f}")
    if ret3m >= 100:
        _add_reason("ret3m_2x", "🏆 3 aylık +%100 (2X)", 10, f"%{ret3m:.0f}")
    elif ret3m >= 50:
        _add_reason("ret3m_guclu", "📈 3 aylık +%50+", 6, f"%{ret3m:.0f}")

    # Graham değeri potansiyeli
    if adil > fiyat * 2.0:
        gr_mult = round(adil / fiyat, 1)
        _add_reason("graham_potansiyel", f"📊 Graham değeri {gr_mult}X üzerinde", 10, f"Adil: {adil:.2f}₺")
    elif adil > fiyat * 1.5:
        _add_reason("graham_ust", "📊 Graham değeri %50+ üzerinde", 6, f"Adil: {adil:.2f}₺")

    # RSI dip + momentum
    if rsi < 30:
        _add_reason("rsi_asiri_satis", "📉 RSI aşırı satım", 7, f"RSI {rsi:.0f}")
    elif rsi < 45:
        _add_reason("rsi_dip", "📉 RSI dip bölgesi", 4, f"RSI {rsi:.0f}")

    # Katlama DNA benzerliği (geçmiş katlama yapanların DNA'sına ne kadar benziyor?)
    if katlama_archive:
        try:
            from .tavan_katlama import tavan_dna, _cosine
            dna = tavan_dna(stock)
            sims = []
            for rec in katlama_archive[-200:]:
                rdna = rec.get("dna") or {}
                if not rdna:
                    continue
                s = _cosine(dna, rdna)
                if s >= 70:
                    sims.append(s)
            if sims:
                avg_sim = sum(sims) / len(sims)
                bonus = min(15, int((avg_sim - 70) / 30 * 15))
                if bonus >= 5:
                    _add_reason("katlama_dna", f"🧬 Geçmiş katlama DNA benzerliği", bonus,
                                f"%{avg_sim:.0f} ({len(sims)} eşleşme)")
        except Exception:
            pass

    ks = min(100, ks)

    # ── H1/H2/H3 seçimi ─────────────────────────────────────────────────────
    h1, h1_src = _pick_target(candidates, above=fiyat, max_ratio=2.5)
    h2, h2_src = _pick_target(candidates, above=max(h1 * 1.04, fiyat * 1.15), max_ratio=4.0)
    h3, h3_src = _pick_target(candidates, above=max(h2 * 1.04, fiyat * 1.35), max_ratio=6.0)

    # Fallback: sabit oran hedefler
    if h1 <= 0:
        h1 = round(fiyat * (1.15 if ks >= 50 else 1.10), 2)
        h1_src = "Oran-H1"
    if h2 <= 0:
        h2 = round(fiyat * (1.35 if ks >= 50 else 1.25), 2)
        h2_src = "Oran-H2"
    if h3 <= 0:
        h3 = round(fiyat * (2.0 if ks >= 70 else (1.6 if ks >= 50 else 1.45)), 2)
        h3_src = "Oran-H3"

    # Monotonik kontrol
    if h2 <= h1 * 1.03:
        h2 = round(h1 * 1.12, 2)
        h2_src = h2_src + "*"
    if h3 <= h2 * 1.03:
        h3 = round(h2 * 1.20, 2)
        h3_src = h3_src + "*"

    # ── KatlamaLevel ────────────────────────────────────────────────────────
    potansiyel = round(h3 / fiyat, 2) if fiyat > 0 else 1.0
    if   potansiyel >= 5.0: level = "5X"
    elif potansiyel >= 3.0: level = "3X"
    elif potansiyel >= 2.0: level = "2X"
    elif potansiyel >= 1.5: level = "1.5X"
    else:                   level = "NORMAL"

    # Yüksek skor ama potansiyel düşükse seviyeyi azami ayarla
    if ks >= 75 and level == "NORMAL":
        level = "1.5X"
    if ks >= 85 and level in ("NORMAL", "1.5X"):
        level = "2X"

    reasons.sort(key=lambda x: x["weight"], reverse=True)

    return {
        "h1":       h1,
        "h2":       h2,
        "h3":       h3,
        "h1Src":    h1_src,
        "h2Src":    h2_src,
        "h3Src":    h3_src,
        "h1Pct":    _pct(h1, fiyat),
        "h2Pct":    _pct(h2, fiyat),
        "h3Pct":    _pct(h3, fiyat),
        "katlamaScore":       ks,
        "katlamaLevel":       level,
        "katlamaPotansiyel":  potansiyel,
        "katlamaReasons":     reasons,
        "fibTargets":         fib_ext,
        "allCandidates": sorted(
            [{"price": p, "src": s, "weight": w} for p, s, w in candidates if p > fiyat],
            key=lambda x: x["price"],
        ),
    }


def _empty_result() -> dict:
    return {
        "h1": 0, "h2": 0, "h3": 0,
        "h1Src": "", "h2Src": "", "h3Src": "",
        "h1Pct": 0, "h2Pct": 0, "h3Pct": 0,
        "katlamaScore": 0,
        "katlamaLevel": "NORMAL",
        "katlamaPotansiyel": 1.0,
        "katlamaReasons": [],
        "fibTargets": {},
        "allCandidates": [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Toplu radar — tüm allStocks cache üzerinden katlama adayları
# ══════════════════════════════════════════════════════════════════════════════

def katlama_radar(
    stocks: list[dict],
    min_score: int = 30,
    top_n: int = 50,
    katlama_archive: list | None = None,
) -> list[dict]:
    """
    Hisse listesini tarayıp katlama adaylarını skora göre sıralar.

    Her hisseye katlamaInfo alanı eklenir ve min_score eşiğini geçenler
    katlamaScore'a göre sıralanmış listede döner.
    """
    result = []
    for stock in stocks:
        info = calculate_katlama_targets(
            stock,
            clustered_levels=stock.get("clusteredLevels"),
            katlama_archive=katlama_archive,
        )
        if info["katlamaScore"] >= min_score or info["katlamaLevel"] in ("2X", "3X", "5X"):
            entry = {
                "code":        stock.get("code", ""),
                "name":        stock.get("name", ""),
                "guncel":      _n(stock.get("guncel")),
                "sektor":      stock.get("sektor", ""),
                "aiScore":     _n(stock.get("aiScore")),
                "predatorScore": _n(stock.get("predatorScore") or stock.get("score")),
                "volRatio":    _n(stock.get("volRatio"), 1),
                "rsi":         _n(stock.get("rsi"), 50),
                "pos52wk":     _n(stock.get("pos52wk"), 50),
                "halkakAciklik": _n(stock.get("halkakAciklik")),
                "marketCap":   _n(stock.get("marketCap")),
                "katlamaInfo": info,
            }
            result.append(entry)
    result.sort(key=lambda x: x["katlamaInfo"]["katlamaScore"], reverse=True)
    return result[:top_n]
