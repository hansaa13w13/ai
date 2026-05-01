"""Tavan & Katlama Radarı — derinlemesine tespit, NEDEN analizi,
sıradaki tavan adayı tahmini ve DNA-tabanlı öğrenme motoru.

Bu modül üç görevi birleştirir:
  1) Tespit  — bir hisse şu an tavan mı, son N günde katlamış mı?
  2) NEDEN   — bu hareketin arkasındaki teknik+temel+akıllı para faktörleri
  3) TAHMİN  — geçmiş tavan/katlama hisselerinin DNA'sını topla, şu anki
              adayları cosine similarity + ağırlıklı skor ile sırala.

Tüm fonksiyonlar pure: stock dict + (opsiyonel) OHLCV + DNA arşivi alır,
sözlük döndürür. Yan etki yok (kayıt için ``record_tavan_event`` ayrı).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from . import config

# ── Kalıcı arşivler ────────────────────────────────────────────────────────
TAVAN_ARCHIVE_FILE   = config.CACHE_DIR / "predator_tavan_dna_archive.json"
KATLAMA_ARCHIVE_FILE = config.CACHE_DIR / "predator_katlama_dna_archive.json"
TAVAN_RADAR_CACHE    = config.CACHE_DIR / "predator_tavan_radar_cache.json"

# DNA arşivinde tutulacak maksimum kayıt sayısı (FIFO)
_MAX_DNA_RECORDS = 800

# Tavan eşiği — BIST günlük fiyat marjı genelde %10. tavanFark<=0.5 = tavanda.
_TAVAN_DIST_OK = 0.6      # tavana <= %0.6 kala = tavanda
_TAVAN_PCT_OK  = 9.0      # günlük değişim >= %9 = tavan kabul

# Katlama eşikleri (return'lerdeki min)
_KATLAMA_2X_PCT = 100.0   # son N günde +%100
_KATLAMA_3X_PCT = 200.0
_KATLAMA_5X_PCT = 400.0


# ═══════════════════════════════════════════════════════════════════════
# 1) TESPİT
# ═══════════════════════════════════════════════════════════════════════
def detect_tavan_status(stock: dict) -> dict:
    """Hissenin şu anki tavan durumunu hesapla.

    Döner:
      {
        "isTavan": bool,           # bugün tavan vurdu / şu an tavanda
        "isYakin": bool,           # tavana yakın (<%2)
        "dailyChange": float,      # günlük değişim %
        "distanceToTavan": float,  # tavana uzaklık % (0=tavanda)
        "level": str,              # "TAVAN" / "YAKIN" / "GUCLU" / "NORMAL"
      }
    """
    fark = float(stock.get("farkYuzde", 0) or 0)
    dist = float(stock.get("tavanFark", 99) or 99)
    is_tavan = (dist <= _TAVAN_DIST_OK and fark > 0) or fark >= _TAVAN_PCT_OK
    is_yakin = (not is_tavan) and (dist <= 2.0 and fark > 3.0)
    if is_tavan:
        level = "TAVAN"
    elif is_yakin:
        level = "YAKIN"
    elif fark >= 5.0:
        level = "GUCLU"
    else:
        level = "NORMAL"
    return {
        "isTavan": bool(is_tavan),
        "isYakin": bool(is_yakin),
        "dailyChange": round(fark, 2),
        "distanceToTavan": round(dist, 2),
        "level": level,
    }


def detect_katlama_status(stock: dict, ohlc: dict | None = None) -> dict:
    """Hissenin katlama (multi-bagger) durumunu hesapla.

    OHLC verilmezse ret1m / ret3m / retYil alanları kullanılır.
    Verilirse close[] dizisinden 60/120/250 bar pencerelerinde min'e göre
    artış oranı hesaplanır.

    Döner:
      {
        "isKatlamis": bool,
        "level": "5X"|"3X"|"2X"|"YOK",
        "kat":   float,            # toplam çarpan (1.0 = değişmedi)
        "windowDays": int,         # hangi pencerede yakalandı
        "fromPrice": float,        # dip fiyat
        "fromDate":  str,          # "" (ohlc varsa hesapla)
        "ret1m":  float,
        "ret3m":  float,
        "retYil": float,
      }
    """
    ret1m  = float(stock.get("ret1m", 0) or 0)
    ret3m  = float(stock.get("ret3m", 0) or 0)
    retYil = float(stock.get("retYil", 0) or 0)
    cur    = float(stock.get("guncel", 0) or 0)

    best_kat = 1.0
    best_win = 0
    best_from_price = 0.0

    # Önce hızlı yol: hazır getiriler
    candidates = [(30, ret1m), (90, ret3m), (252, retYil)]
    for days, ret in candidates:
        kat = 1.0 + (ret / 100.0)
        if kat > best_kat:
            best_kat = kat
            best_win = days
            if cur > 0 and kat > 0:
                best_from_price = cur / kat

    # OHLC varsa daha hassas: 60/120/250 bar pencerelerinde min'e göre
    if ohlc and ohlc.get("c"):
        c = ohlc["c"]
        for win in (60, 120, 250):
            if len(c) < 5: continue
            sub = c[-win:] if len(c) >= win else c
            mn = min(sub) if sub else 0
            if mn > 0:
                kat = c[-1] / mn
                if kat > best_kat:
                    best_kat = kat
                    best_win = win
                    best_from_price = mn

    if   best_kat >= 5.0: level = "5X"
    elif best_kat >= 3.0: level = "3X"
    elif best_kat >= 2.0: level = "2X"
    else:                 level = "YOK"

    return {
        "isKatlamis": best_kat >= 2.0,
        "level":      level,
        "kat":        round(best_kat, 2),
        "windowDays": best_win,
        "fromPrice":  round(best_from_price, 2),
        "fromDate":   "",
        "ret1m":      round(ret1m, 2),
        "ret3m":      round(ret3m, 2),
        "retYil":     round(retYil, 2),
    }


# ═══════════════════════════════════════════════════════════════════════
# 2) NEDEN motoru — bu hareket NEDEN oluyor / oldu?
# ═══════════════════════════════════════════════════════════════════════
def analyze_why(stock: dict) -> list[dict]:
    """Hareketin arkasındaki faktörleri sırala.

    Her faktör: {key, label, weight, value} formatında. Ağırlıklar 0-100.
    """
    f: list[dict] = []

    # Hacim patlaması — kurumsal ilgi
    vol_r = _safe_num(stock.get("volRatio"), 1)
    if vol_r >= 3.0:
        f.append({"key": "volume_blast", "label": "🔥 Hacim patlaması",
                  "weight": min(100, int(vol_r * 18)), "value": f"{vol_r:.2f}x ortalama"})
    elif vol_r >= 1.8:
        f.append({"key": "volume_high", "label": "📊 Hacim yükselişi",
                  "weight": int(vol_r * 22), "value": f"{vol_r:.2f}x ortalama"})

    # Akıllı para girişi — para giriş > para çıkış
    npa = _safe_num(stock.get("netParaAkis"), 0)
    pgi = _safe_num(stock.get("paraGiris"), 0)
    if npa > 0 and pgi > 0:
        oran = npa / max(pgi * 2, 1)
        if oran > 0.15:
            f.append({"key": "smart_money", "label": "💰 Akıllı para girişi",
                      "weight": min(100, int(oran * 250)),
                      "value": f"net +{npa:,.0f}₺ ({oran*100:.1f}%)"})
    cmf = _safe_num(stock.get("cmf"), 0)
    if cmf > 0.15:
        f.append({"key": "cmf_pos", "label": "💵 CMF kurumsal alım",
                  "weight": min(100, int(cmf * 200)), "value": f"CMF {cmf:.3f}"})

    # SMC — yapısal kırılım
    smc_bias = str(stock.get("smcBias", "") or "").lower()
    if smc_bias in ("bull", "bullish"):
        f.append({"key": "smc_bull", "label": "🧩 SMC boğa yapısı",
                  "weight": 70, "value": "BOS/CHoCH yukarı"})
    smc_pack = stock.get("smc") or {}
    if isinstance(smc_pack, dict):
        if (smc_pack.get("bos") or {}).get("dir") == "up":
            f.append({"key": "smc_bos", "label": "🎯 SMC BOS (yapı kırıldı)",
                      "weight": 75, "value": "yön: yukarı"})
        if (smc_pack.get("liquiditySweep") or {}).get("dir") == "down":
            f.append({"key": "smc_sweep", "label": "🎣 Likidite süpürmesi",
                      "weight": 60, "value": "stoplar tarandı"})

    # Donchian breakout
    donch = stock.get("donchian") or {}
    if isinstance(donch, dict) and donch.get("breakout") == "up":
        f.append({"key": "donch_break", "label": "📈 Donchian üst kırılımı",
                  "weight": 78, "value": "20G zirvesi aşıldı"})

    # Bollinger squeeze + üst bant patlama
    if stock.get("bbSqueeze"):
        bbp = _safe_num(stock.get("bbPct"), 50)
        if bbp > 80:
            f.append({"key": "bb_squeeze_break", "label": "⚡ BB sıkışma patlaması",
                      "weight": 72, "value": f"%B={bbp:.0f}"})

    # MACD altın kesişim
    if str(stock.get("macdCross", "") or "").lower() == "golden":
        f.append({"key": "macd_golden", "label": "🌟 MACD altın kesişim",
                  "weight": 55, "value": "yükseliş momentumu"})

    # EMA 9/21 altın kesişim
    if str(stock.get("emaCrossDir", "") or "") == "golden":
        f.append({"key": "ema_golden", "label": "✨ EMA 9/21 altın kesişim",
                  "weight": 50, "value": "kısa-vade momentum"})

    # Supertrend / SAR yön
    if str(stock.get("supertrendDir", "") or "").lower() in ("up", "long", "bull"):
        f.append({"key": "st_up", "label": "🚀 Supertrend yukarı",
                  "weight": 45, "value": "trend onayı"})

    # ADX güçlü trend
    adx_val = _safe_num(stock.get("adxVal"), 0)
    if adx_val >= 25:
        f.append({"key": "adx_strong", "label": "💪 Güçlü trend (ADX)",
                  "weight": min(100, int(adx_val * 2)), "value": f"ADX {adx_val:.0f}"})

    # RSI sweet spot (50-70 = momentum, 70+ = aşırı alım uyarı)
    rsi = _safe_num(stock.get("rsi"), 50)
    if 55 <= rsi <= 70:
        f.append({"key": "rsi_sweet", "label": "🎯 RSI momentum bölgesi",
                  "weight": 55, "value": f"RSI {rsi:.0f}"})
    elif rsi > 75:
        f.append({"key": "rsi_overbought", "label": "⚠ RSI aşırı alım",
                  "weight": 30, "value": f"RSI {rsi:.0f} (dikkat)"})

    # 52 hafta dipten uzak değilse — erken yakalama
    pos52 = _safe_num(stock.get("pos52wk"), 50)
    if pos52 < 25:
        f.append({"key": "low_base", "label": "🐣 52H dibe yakın",
                  "weight": 65, "value": f"%{pos52:.0f}"})
    elif pos52 > 90:
        f.append({"key": "high_base", "label": "🏔 52H zirveye yakın",
                  "weight": 25, "value": f"%{pos52:.0f}"})

    # Formasyonlar
    forms = stock.get("formations") or []
    if isinstance(forms, list):
        for fm in forms[:3]:
            if not isinstance(fm, dict): continue
            ad = fm.get("ad") or fm.get("name") or ""
            yon = str(fm.get("yon") or fm.get("dir") or "").lower()
            if ad and ("bull" in yon or "al" in yon or "up" in yon):
                f.append({"key": f"form_{ad}", "label": f"🕯 {ad}",
                          "weight": 60, "value": "boğa formasyonu"})

    # Bedelsiz / temettü
    if stock.get("recentBedelsiz"):
        f.append({"key": "bedelsiz", "label": "🎁 Bedelsiz haberi",
                  "weight": 75, "value": "son dönemde"})
    last_temettu = _safe_num(stock.get("lastTemettu"), 0)
    if last_temettu > 5:
        f.append({"key": "temettu", "label": "💸 Yüksek temettü",
                  "weight": 60, "value": f"%{last_temettu:.1f}"})

    # KAP / Tipe Dönüşüm bonusu varsa
    kap_b = int(stock.get("kapNewsBonus", 0) or 0)
    if kap_b > 0:
        f.append({"key": "kap_news", "label": "📜 KAP olumlu haber",
                  "weight": min(100, kap_b * 2), "value": f"+{kap_b} puan"})

    # IPO altında — düşük fiyat avantajı
    if stock.get("ipoAltinda"):
        ifk = _safe_num(stock.get("ipoFark"), 0)
        f.append({"key": "ipo_under", "label": "🏷 Halka arz altı",
                  "weight": 60, "value": f"{ifk:.1f}%"})

    # Sektör momentum / rotasyon
    eb = int(stock.get("earlyCatchBonus", 0) or 0)
    if eb >= 10:
        f.append({"key": "sector_rot", "label": "🔄 Sektör rotasyonu",
                  "weight": min(100, eb * 3), "value": f"+{eb} puan"})

    # Uyuyan mücevher
    sb = int(stock.get("sleeperBonus", 0) or 0)
    if sb >= 50:
        f.append({"key": "sleeper", "label": "💤 Uyuyan mücevher",
                  "weight": min(100, sb), "value": f"+{sb} puan"})

    # Düşük halka açıklık + alım = patlatma riski yüksek
    halkak = _safe_num(stock.get("halkakAciklik"), 0)
    if 0 < halkak < 25 and vol_r > 1.5:
        f.append({"key": "low_float_pump", "label": "🎈 Dar halka açıklık + hacim",
                  "weight": 70, "value": f"%{halkak:.0f} halka açık"})

    # Triple Brain konsensüsü güçlüyse
    nb = int(stock.get("neuralBonus", 0) or 0)
    if nb >= 8:
        f.append({"key": "brain_consensus", "label": "🧠 Triple Brain konsensüsü",
                  "weight": min(100, nb * 8), "value": f"+{nb} puan"})

    # Skor sırasına göre azalan
    f.sort(key=lambda x: x.get("weight", 0), reverse=True)
    return f


# ═══════════════════════════════════════════════════════════════════════
# 3) DNA — özellik vektörü çıkar
# ═══════════════════════════════════════════════════════════════════════
def _safe_num(v: Any, default: float = 0.0) -> float:
    """Güvenli sayıya dönüştürme — dict/list/None/NaN durumlarını ele alır."""
    if isinstance(v, dict):
        # Bazı göstergeler dict olarak gelir: {"value": 50, "adx": 50, ...}
        for k in ("value", "val", "adx", "rsi", "score", "current"):
            if k in v:
                v = v[k]; break
        else:
            return default
    if isinstance(v, (list, tuple)):
        v = v[-1] if v else default
    try:
        n = float(v)
        if math.isnan(n) or math.isinf(n): return default
        return n
    except (TypeError, ValueError):
        return default


def tavan_dna(stock: dict) -> dict:
    """Hisseden 16-boyutlu normalize DNA vektörü çıkar.

    Tüm değerler 0..1 aralığına sıkıştırılmış (cosine için kararlı).
    """
    def n01(v: float, lo: float, hi: float) -> float:
        if hi <= lo: return 0.0
        x = (v - lo) / (hi - lo)
        return max(0.0, min(1.0, x))

    rsi  = _safe_num(stock.get("rsi"), 50)
    adx  = _safe_num(stock.get("adxVal"))
    cmf  = _safe_num(stock.get("cmf"))
    volr = _safe_num(stock.get("volRatio"), 1)
    bbp  = _safe_num(stock.get("bbPct"), 50)
    pos52= _safe_num(stock.get("pos52wk"), 50)
    fark = _safe_num(stock.get("farkYuzde"))
    tdist= _safe_num(stock.get("tavanFark"), 10)
    roc5 = _safe_num(stock.get("roc5"))
    roc20= _safe_num(stock.get("roc20"))
    ret1 = _safe_num(stock.get("ret1m"))
    ret3 = _safe_num(stock.get("ret3m"))
    halk = _safe_num(stock.get("halkakAciklik"), 50)
    cap  = _safe_num(stock.get("marketCap"))
    npa  = _safe_num(stock.get("netParaAkis"))
    pgi  = _safe_num(stock.get("paraGiris"))
    npa_oran = (npa / max(pgi * 2, 1)) if pgi > 0 else 0

    macd_g = 1.0 if str(stock.get("macdCross", "")).lower() == "golden" else 0.0
    ema_g  = 1.0 if str(stock.get("emaCrossDir", "")) == "golden" else 0.0
    smc_b  = 1.0 if str(stock.get("smcBias", "")).lower() in ("bull", "bullish") else 0.0
    st_up  = 1.0 if str(stock.get("supertrendDir", "")).lower() in ("up", "long", "bull") else 0.0
    bbs    = 1.0 if stock.get("bbSqueeze") else 0.0
    donch_up = 1.0 if isinstance(stock.get("donchian"), dict) and stock["donchian"].get("breakout") == "up" else 0.0

    return {
        "rsi":      n01(rsi, 30, 80),
        "adx":      n01(adx, 10, 50),
        "cmf":      n01(cmf, -0.3, 0.5),
        "volRatio": n01(volr, 0.5, 4.0),
        "bbPct":    n01(bbp, 10, 100),
        "pos52":    n01(pos52, 0, 100),
        "fark":     n01(fark, -3, 10),
        "tDist":    n01(10 - tdist, 0, 10),     # tavana yakınsa yüksek
        "roc5":     n01(roc5, -10, 20),
        "roc20":    n01(roc20, -20, 50),
        "ret1m":    n01(ret1, -20, 80),
        "ret3m":    n01(ret3, -30, 150),
        "halkak":   1.0 - n01(halk, 5, 80),     # düşük halka açıklık = yüksek
        "smallCap": 1.0 - n01(math.log10(max(cap, 1) + 1), 0, 5),
        "smartMoney": n01(npa_oran, -0.2, 0.3),
        "macdGold": macd_g,
        "emaGold":  ema_g,
        "smcBull":  smc_b,
        "stUp":     st_up,
        "bbSq":     bbs,
        "donchUp":  donch_up,
    }


def _cosine(a: dict, b: dict) -> float:
    """Cosine similarity 0..100. Aynı anahtarlar üzerinden."""
    keys = set(a.keys()) & set(b.keys())
    if not keys: return 0.0
    dot = magA = magB = 0.0
    for k in keys:
        av = float(a.get(k, 0)); bv = float(b.get(k, 0))
        dot  += av * bv
        magA += av * av
        magB += bv * bv
    magA = math.sqrt(magA); magB = math.sqrt(magB)
    if magA < 1e-9 or magB < 1e-9: return 0.0
    return round((dot / (magA * magB)) * 100.0, 1)


# ═══════════════════════════════════════════════════════════════════════
# 4) ARŞİV — geçmiş tavan/katlama hisselerinin DNA'sını biriktir
# ═══════════════════════════════════════════════════════════════════════
def _load_archive(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_archive(path: Path, items: list[dict]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items[-_MAX_DNA_RECORDS:], ensure_ascii=False),
                        encoding="utf-8")
    except OSError:
        pass


def load_tavan_archive() -> list[dict]:
    return _load_archive(TAVAN_ARCHIVE_FILE)


def load_katlama_archive() -> list[dict]:
    return _load_archive(KATLAMA_ARCHIVE_FILE)


def record_tavan_event(stock: dict, dna: dict, event_type: str = "tavan") -> None:
    """Tavan/katlama gerçekleşen bir hissenin DNA'sını arşive yaz.

    Aynı kod için 24 saat içinde tekrar yazma.
    """
    path = TAVAN_ARCHIVE_FILE if event_type == "tavan" else KATLAMA_ARCHIVE_FILE
    items = _load_archive(path)
    code = stock.get("code", "")
    now = int(time.time())
    # Aynı koddan son kayıt 24h içindeyse atla
    for it in reversed(items[-50:]):
        if it.get("code") == code and (now - int(it.get("ts", 0))) < 86400:
            return
    items.append({
        "ts":       now,
        "code":     code,
        "name":     stock.get("name", code),
        "sektor":   stock.get("sektor", ""),
        "guncel":   _safe_num(stock.get("guncel")),
        "fark":     _safe_num(stock.get("farkYuzde")),
        "kat":      _safe_num((stock.get("katlamaInfo") or {}).get("kat"), 1.0),
        "marketCap":_safe_num(stock.get("marketCap")),
        "dna":      dna,
        "type":     event_type,
    })
    _save_archive(path, items)


# ═══════════════════════════════════════════════════════════════════════
# 5) TAHMİN — sıradaki tavan adayı?
# ═══════════════════════════════════════════════════════════════════════
def next_tavan_score(stock: dict, archive: list[dict] | None = None,
                     min_sim: float = 65.0, top_k: int = 3) -> dict:
    """Bu hissenin yakın gelecekte tavan/katlama yapma olasılığını puanla.

    Mantık:
      1. Hissenin DNA'sını çıkar.
      2. Geçmiş tavan/katlama DNA'larıyla cosine similarity hesapla.
      3. En benzer top_k pattern bul (sim >= min_sim).
      4. Heuristik faktörleri (hacim, akıllı para, SMC, BB squeeze, breakout)
         de ekle — arşiv azken bile çalışsın.
      5. Birleşik 0..100 skor + benzer geçmiş pattern listesi döndür.

    Döner:
      {
        "score": int (0-100),
        "level": "ÇOK_YÜKSEK"|"YÜKSEK"|"ORTA"|"DÜŞÜK",
        "similar": [{code, sim, kat, fark, sektor, ts, name}, ...],
        "factors": [...analyze_why çıktısı...],
        "heuristic": int (0-60),
        "patternBonus": int (0-40),
      }
    """
    archive = archive if archive is not None else load_tavan_archive()
    dna = tavan_dna(stock)
    self_code = (stock.get("code") or "").upper()

    # Pattern matching — arşivden en benzer N (hisse kendi geçmişiyle eşleşmesin)
    sims: list[tuple[float, dict]] = []
    for rec in archive:
        if (rec.get("code") or "").upper() == self_code:
            continue
        rdna = rec.get("dna") or {}
        if not rdna: continue
        sim = _cosine(dna, rdna)
        if sim >= min_sim:
            sims.append((sim, rec))
    sims.sort(key=lambda x: x[0], reverse=True)
    top = sims[:top_k]

    # Pattern bonus (0-50) — daha cömert
    if top:
        avg_sim = sum(s for s, _ in top) / len(top)
        # Taban +12, similarity bandı 65→100 üzerinden 0..38
        pattern_bonus = min(50, int((avg_sim - min_sim) / max(100 - min_sim, 1) * 38 + 12))
    else:
        pattern_bonus = 0

    # Heuristik (0-70) — arşiv olmasa bile çalışsın, agresif
    h = 0
    factors = analyze_why(stock)

    # Tavan'a yakınlık başlı başına ÇOK BÜYÜK sinyal
    tdist = _safe_num(stock.get("tavanFark"), 10)
    fark  = _safe_num(stock.get("farkYuzde"))
    if   tdist <= 1.5 and fark > 5: h += 28          # neredeyse tavan
    elif tdist <= 2.5 and fark > 4: h += 22
    elif tdist <= 4.0 and fark > 2: h += 14
    elif tdist <= 6.0 and fark > 0: h += 7

    vol_r = _safe_num(stock.get("volRatio"), 1)
    if   vol_r >= 3.5: h += 18                       # patlayan hacim
    elif vol_r >= 2.5: h += 14
    elif vol_r >= 1.6: h += 8
    elif vol_r >= 1.2: h += 4

    cmf = _safe_num(stock.get("cmf"))
    if   cmf > 0.25: h += 14
    elif cmf > 0.10: h += 8
    elif cmf > 0.02: h += 4

    if str(stock.get("smcBias", "")).lower() in ("bull", "bullish"): h += 8
    if isinstance(stock.get("donchian"), dict) and stock["donchian"].get("breakout") == "up": h += 10
    if stock.get("bbSqueeze") and _safe_num(stock.get("bbPct"), 50) > 75: h += 8
    if stock.get("macdGoldenCross"): h += 6
    if stock.get("emaGoldenCross"):  h += 5
    if str(stock.get("supertrend", "")).lower() == "up": h += 5

    # ADX trend gücü
    adx = _safe_num(stock.get("adx"))
    if adx >= 28: h += 6
    elif adx >= 20: h += 3

    # Aşırı alım cezası — yumuşak (kullanıcı yüksek puan istiyor)
    rsi = _safe_num(stock.get("rsi"), 50)
    if rsi > 82: h -= 6
    elif rsi > 78: h -= 3

    # Az halka açıklık + hacim = patlama riski
    halk = _safe_num(stock.get("halkakAciklik"))
    if 0 < halk < 15 and vol_r > 1.5: h += 10
    elif 0 < halk < 25 and vol_r > 1.3: h += 5

    # Smart money sinyali
    sm = _safe_num(stock.get("smartMoneyScore"))
    if sm >= 70: h += 8
    elif sm >= 50: h += 4

    h = max(0, min(80, h))
    score = max(0, min(100, h + pattern_bonus))

    # v40: Eşikler daha da düşürüldü → daha fazla aday "YÜKSEK/ÇOK_YÜKSEK" seviyesine geçer
    if   score >= 60: level = "ÇOK_YÜKSEK"
    elif score >= 40: level = "YÜKSEK"
    elif score >= 20: level = "ORTA"
    else:             level = "DÜŞÜK"

    similar_out = [{
        "code":   r.get("code", ""),
        "name":   r.get("name", ""),
        "sektor": r.get("sektor", ""),
        "sim":    round(s, 1),
        "kat":    r.get("kat", 1.0),
        "fark":   r.get("fark", 0),
        "type":   r.get("type", "tavan"),
        "ts":     r.get("ts", 0),
        "ageDays": int((time.time() - int(r.get("ts", 0))) / 86400) if r.get("ts") else 0,
    } for s, r in top]

    return {
        "score":        int(round(score)),
        "level":        level,
        "similar":      similar_out,
        "factors":      factors[:6],
        "heuristic":    int(h),
        "patternBonus": int(pattern_bonus),
        "archiveSize":  len(archive),
    }


# ═══════════════════════════════════════════════════════════════════════
# 6) Ana giriş — bir hisseye tüm tavan/katlama analizini uygula
# ═══════════════════════════════════════════════════════════════════════
def apply_tavan_katlama(stock: dict, ohlc: dict | None = None,
                        archive: list[dict] | None = None) -> dict:
    """Stock dict'ine tavan/katlama bilgilerini ekle ve bonusu döndür.

    Yan etki: stock dict şu alanlarla güncellenir:
      - tavanInfo, katlamaInfo, katlamis (bool), tavanReasons
      - nextTavanScore, nextTavanLevel, nextTavanSimilar, tavanRadarBonus

    Döner:
      {
        "bonus": int,            # aiScore'a eklenecek
        "tavan": dict,           # tavan info
        "katlama": dict,         # katlama info
        "next": dict,            # tahmin
        "reasons": list,         # neden listesi
      }
    """
    tavan   = detect_tavan_status(stock)
    katlama = detect_katlama_status(stock, ohlc)
    nxt     = next_tavan_score(stock, archive=archive)
    reasons = analyze_why(stock)

    stock["tavanInfo"]    = tavan
    # Yeni katlama_targets formatı (h1/h2/h3) zaten hesaplanmışsa üzerine yazma —
    # sadece tavanInfo/katlamis/isTavan bilgisini güncelle, hedef formatı koru.
    if not stock.get("katlamaInfo", {}).get("h1"):
        stock["katlamaInfo"] = katlama
    stock["katlamis"]     = bool(katlama["isKatlamis"])
    stock["isTavan"]      = bool(tavan["isTavan"])
    stock["tavanReasons"] = reasons[:6]
    stock["nextTavanScore"]   = nxt["score"]
    stock["nextTavanLevel"]   = nxt["level"]
    stock["nextTavanSimilar"] = nxt["similar"]
    stock["nextTavanFactors"] = nxt["factors"]

    # Bonus hesapla — v40 SÜPER AGRESİF (kullanıcı: "daha yüksek puan versin"):
    #  - Bugün tavan: +30
    #  - Bugün tavana yakın: +45 (yarın sürebilir)
    #  - Sıradaki tavan adayı (ÇOK_YÜKSEK ≥60): +85
    #  - YÜKSEK (≥40): +60
    #  - ORTA  (≥20): +35
    #  - DÜŞÜK (<20): +15
    #  - 5X katlamış: +18
    #  - 3X katlamış: +10
    #  - 2X katlamış: +5
    #  - Pattern bonus ek: +0..20
    bonus = 0
    if tavan["isTavan"]:                bonus += 30
    elif tavan["isYakin"]:              bonus += 45
    if   nxt["level"] == "ÇOK_YÜKSEK": bonus += 85
    elif nxt["level"] == "YÜKSEK":     bonus += 60
    elif nxt["level"] == "ORTA":       bonus += 35
    elif nxt["level"] == "DÜŞÜK":      bonus += 15
    if   katlama["level"] == "5X": bonus += 18
    elif katlama["level"] == "3X": bonus += 10
    elif katlama["level"] == "2X": bonus += 5
    # Pattern bonus güçlü → ek
    pb = int(nxt.get("patternBonus", 0) or 0)
    if pb >= 35:   bonus += 20
    elif pb >= 25: bonus += 12
    elif pb >= 15: bonus += 6

    bonus = min(150, bonus)  # toplam çatı (v40: 110 → 150)
    stock["tavanRadarBonus"] = bonus

    return {
        "bonus":   bonus,
        "tavan":   tavan,
        "katlama": katlama,
        "next":    nxt,
        "reasons": reasons,
    }


# ═══════════════════════════════════════════════════════════════════════
# 7) RADAR — tarama sonrası tüm hisselerden 3 bölümlü görüntü hazırla
# ═══════════════════════════════════════════════════════════════════════
def build_radar(all_stocks: list[dict]) -> dict:
    """Tarama sonrası radar verisini üret (UI için).

    Sections:
      - currently_tavan: bugün tavan vuran/yakın olan
      - katlama_yapanlar: katlamış hisseler (kat'a göre)
      - next_candidates: en yüksek tahmin skoruna sahip (henüz tavan değil)
      - comparisons: aday başına en benzer 3 geçmiş pattern (zaten her stock'ta var)
    """
    cur_tavan: list[dict] = []
    katlamalar: list[dict] = []
    candidates: list[dict] = []

    for s in all_stocks:
        if not isinstance(s, dict): continue
        ti = s.get("tavanInfo") or {}
        ki = s.get("katlamaInfo") or {}
        ns = int(s.get("nextTavanScore", 0) or 0)
        if ti.get("isTavan") or ti.get("isYakin"):
            cur_tavan.append({
                "code":   s.get("code"),
                "name":   s.get("name", s.get("code")),
                "guncel": s.get("guncel", 0),
                "fark":   ti.get("dailyChange", 0),
                "tDist":  ti.get("distanceToTavan", 0),
                "level":  ti.get("level"),
                "sektor": s.get("sektor", ""),
                "score":  s.get("score", s.get("predatorScore", 0)),
                "reasons":(s.get("tavanReasons") or [])[:5],
                "volRatio": s.get("volRatio", 1),
                "marketCap": s.get("marketCap", 0),
            })
        if ki.get("isKatlamis"):
            katlamalar.append({
                "code":   s.get("code"),
                "name":   s.get("name", s.get("code")),
                "guncel": s.get("guncel", 0),
                "kat":    ki.get("kat", 1.0),
                "level":  ki.get("level"),
                "windowDays": ki.get("windowDays", 0),
                "fromPrice": ki.get("fromPrice", 0),
                "ret3m":  ki.get("ret3m", 0),
                "retYil": ki.get("retYil", 0),
                "sektor": s.get("sektor", ""),
                "score":  s.get("score", s.get("predatorScore", 0)),
                "reasons":(s.get("tavanReasons") or [])[:5],
            })
        # Adaylar: tavanda olmayan + skor yüksek
        if ns >= 35 and not (ti.get("isTavan") or False):
            candidates.append({
                "code":   s.get("code"),
                "name":   s.get("name", s.get("code")),
                "guncel": s.get("guncel", 0),
                "fark":   s.get("farkYuzde", 0),
                "tDist":  s.get("tavanFark", 0),
                "score":  ns,
                "level":  s.get("nextTavanLevel"),
                "similar":(s.get("nextTavanSimilar") or [])[:3],
                "factors":(s.get("nextTavanFactors") or [])[:5],
                "sektor": s.get("sektor", ""),
                "aiScore": s.get("aiScore", 0),
                "predatorScore": s.get("predatorScore", 0),
                "volRatio": s.get("volRatio", 1),
                "rsi":    s.get("rsi", 50),
                "marketCap": s.get("marketCap", 0),
                "tavanRadarBonus": s.get("tavanRadarBonus", 0),
            })

    cur_tavan.sort(key=lambda x: (-(x.get("level") == "TAVAN"), -float(x.get("fark", 0) or 0)))
    katlamalar.sort(key=lambda x: -float(x.get("kat", 0) or 0))
    candidates.sort(key=lambda x: -int(x.get("score", 0) or 0))

    radar = {
        "ts":      int(time.time()),
        "currentlyTavan": cur_tavan[:30],
        "katlamalar":     katlamalar[:30],
        "nextCandidates": candidates[:25],
        "summary": {
            "tavanCount":     len([x for x in cur_tavan if x.get("level") == "TAVAN"]),
            "yakinCount":     len([x for x in cur_tavan if x.get("level") == "YAKIN"]),
            "katlamaCount":   len(katlamalar),
            "candidateCount": len(candidates),
            "archiveSize":    len(load_tavan_archive()),
        },
    }
    try:
        TAVAN_RADAR_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TAVAN_RADAR_CACHE.write_text(json.dumps(radar, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return radar


def load_radar_cached() -> dict:
    if not TAVAN_RADAR_CACHE.exists():
        return {"currentlyTavan": [], "katlamalar": [], "nextCandidates": [],
                "summary": {"tavanCount": 0, "yakinCount": 0,
                            "katlamaCount": 0, "candidateCount": 0,
                            "archiveSize": len(load_tavan_archive())}}
    try:
        return json.loads(TAVAN_RADAR_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {"currentlyTavan": [], "katlamalar": [], "nextCandidates": [], "summary": {}}


# ═══════════════════════════════════════════════════════════════════════
# 8) ARŞİV ÖĞRENME — tarama sonrası tavan/katlama vuran hisseleri kayıt et
# ═══════════════════════════════════════════════════════════════════════
def harvest_archives(all_stocks: list[dict]) -> dict:
    """Bugün tavan vuran ve katlamış hisseleri DNA arşivlerine ekle.

    Bu fonksiyon her tarama sonunda bir kez çağrılır. Dedup 24 saat.
    Döner: kaç yeni kayıt eklendi.
    """
    added_t = 0
    added_k = 0
    for s in all_stocks:
        if not isinstance(s, dict): continue
        ti = s.get("tavanInfo") or {}
        ki = s.get("katlamaInfo") or {}
        if ti.get("isTavan"):
            dna = tavan_dna(s)
            before = len(load_tavan_archive())
            record_tavan_event(s, dna, event_type="tavan")
            after = len(load_tavan_archive())
            if after > before: added_t += 1
        if ki.get("isKatlamis") and ki.get("level") in ("3X", "5X"):
            dna = tavan_dna(s)
            before = len(load_katlama_archive())
            record_tavan_event(s, dna, event_type="katlama")
            after = len(load_katlama_archive())
            if after > before: added_k += 1
    return {"tavan_added": added_t, "katlama_added": added_k}
