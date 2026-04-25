"""AI hafıza motoru: snapshot, learn, prediction bonus, neural ensembling."""
from __future__ import annotations
import math
import time
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from . import config, neural
from .utils import load_json, save_json, today_str, now_str

# v37.4: Brain dosyası için RMW (read-modify-write) yarış durumu kilidi.
# Daemon eğitirken aynı anda kullanıcı `/?action=neural_train` çağırırsa
# biri diğerinin yazdığı ağırlıkları ezerdi. RLock ile içiçe çağrı güvenli.
_BRAIN_RMW_LOCK = threading.RLock()


@contextmanager
def brain_lock() -> Iterator[None]:
    """`with brain_lock(): brain = brain_load(); ...; brain_save(brain)` deseni
    için içiçe-güvenli (reentrant) kilit context manager.
    """
    _BRAIN_RMW_LOCK.acquire()
    try:
        yield
    finally:
        _BRAIN_RMW_LOCK.release()

# ── Ayı formasyon listesi (predBonus hesabında kullanılır)
BEARISH_FORM_NAMES = {
    "ÇİFT TEPE", "BAŞ&OMUZ", "DÜŞEN ÜÇGEN", "KARANLIK BULUT", "YUTAN AYI",
    "AKŞAM YILDIZI", "AYI BAYRAĞI", "MARUBOZU AYI", "KEMER TUTMA↓",
    "DOJİ YILDIZ TEPE", "AKŞAM DOJİ", "UZUN ÜST GÖLGE", "SÜPER TREND↓",
    "EMA ÖLÜM KES.", "DIŞ BAR DÜŞÜŞ", "MACD DIV AYI", "DUSME 3 YOL",
    "GENİŞLEYEN FRM.", "KANAL ASAGI KIR.", "RSI AYI DIV.", "RSI TEPE+MACD",
    "GAP DOWN", "YÜKS. KAMA", "3 KARA KARGA", "HARAMİ AYI",
    "MEZAR TAŞI DOJİ", "FIŞKİRAN YILDIZ", "CIMBIZ TEPE", "3 İÇERİDEN AŞA.",
    "AYI TEPME",
}


def brain_default() -> dict:
    """PHP brainDefault — sıfırdan başlatılmış brain şeması."""
    ind_def = {"weight": 1.0, "count": 0, "win": 0, "total_ret": 0.0, "ema_wr": 50.0}
    ind_keys = [
        "rsi_extreme", "rsi_oversold", "stoch_oversold", "bb_lower", "bb_squeeze",
        "52wk_low", "cmo_oversold", "ult_osc_oversold",
        "macd_golden", "sar_yukselis", "ichi_above", "adx_strong",
        "supertrend_bull", "hull_bull", "ema9_21_golden", "trix_bullish",
        "ao_bullish", "div_bullish", "cmf_positive", "vol_surge", "keltner_below",
        "smc_bullish", "ofi_strong_buy", "ofi_buy",
        "vwap_below1", "vwap_below2", "vol_low_regime",
    ]
    return {
        "version":          3,
        "total_scans":      0,
        "last_updated":     "",
        "created_at":       now_str(),
        "snapshots":        {},
        "learned_weights": {
            "formation": {},
            "indicator": {k: dict(ind_def) for k in ind_keys},
        },
        "sector_perf":         {},
        "sector_mode_matrix":  {},
        "volatility_learning": {},
        "confluence_patterns": {},
        "time_patterns":       {},
        "prediction_accuracy": {"toplam": 0, "dogru": 0, "oran": 0.0},
        "stats": {"recent_wins": 0, "recent_total": 0,
                  "avg_win_pct": 5.0, "avg_loss_pct": 3.0},
        "neural_net":       neural.make_net("alpha"),
        "neural_net_beta":  neural.make_net("beta"),
        "neural_net_gamma": neural.make_net("gamma"),
    }


def brain_load() -> dict:
    data = load_json(config.AI_BRAIN_FILE, {})
    if not isinstance(data, dict):
        data = {}
    # Defansif onarım: eski sürümlerden kalan corrupt yapılar (örn. formation,
    # volatility_learning bazen [] olarak kalıyor → setdefault patlıyor).
    # Beklenen tip dict olan tüm üst-seviye alanları zorla.
    _DICT_FIELDS = (
        "snapshots", "sector_perf", "sector_mode_matrix",
        "volatility_learning", "confluence_patterns", "time_patterns",
    )
    for _f in _DICT_FIELDS:
        if not isinstance(data.get(_f), dict):
            data[_f] = {}

    if not isinstance(data.get("learned_weights"), dict):
        data["learned_weights"] = {"formation": {}, "indicator": {}}
    lw = data["learned_weights"]
    for _sub in ("formation", "indicator"):
        if not isinstance(lw.get(_sub), dict):
            lw[_sub] = {}

    if not isinstance(data.get("prediction_accuracy"), dict):
        data["prediction_accuracy"] = {"toplam": 0, "dogru": 0, "oran": 0.0}
    if not isinstance(data.get("stats"), dict):
        data["stats"] = {"recent_wins": 0, "recent_total": 0,
                         "avg_win_pct": 5.0, "avg_loss_pct": 3.0}
    data.setdefault("neural_net", neural.make_net("alpha"))
    data.setdefault("neural_net_beta", neural.make_net("beta"))
    data.setdefault("neural_net_gamma", neural.make_net("gamma"))
    data.setdefault("created_at", now_str())
    return data


def brain_learn_confluence(brain: dict, stock: dict, ret: float) -> None:
    """PHP brainLearnConfluence — confluence pattern + time-of-week öğrenmesi.

    İndikatör konfigürasyonunu (RSI/MACD/SAR/SMC vb. anahtarlanmış imza)
    bir 'confluence_patterns' altında istatistik tutar. min 6 örnekten sonra
    Bayesian güven faktörüyle weight verir (0.3-2.5 aralığında).
    """
    from .scoring_extras import get_confluence_key
    key = get_confluence_key(stock)
    cps = brain.setdefault("confluence_patterns", {})
    c = cps.setdefault(key, {"count": 0, "win": 0, "total_ret": 0.0,
                             "avg_ret": 0.0, "win_rate": 0.0, "weight": 1.0})
    c["count"] = int(c["count"]) + 1
    if ret > 0: c["win"] = int(c["win"]) + 1
    c["total_ret"] = float(c["total_ret"]) + float(ret)
    c["avg_ret"]   = round(c["total_ret"] / c["count"], 2)
    c["win_rate"]  = round(c["win"] / c["count"] * 100, 1)
    if c["count"] >= 6:
        wr_f = c["win_rate"] / 60.0
        r_f  = 1.0 + (c["avg_ret"] / 12.0)
        confidence = min(1.0, (c["count"] - 6) / 24.0)
        raw_w = (wr_f * 0.6 + r_f * 0.4)
        c["weight"] = round(max(0.3, min(2.5, 1.0 + (raw_w - 1.0) * max(0.3, confidence))), 3)

    # Haftanın günü (1=Pzt..5=Cum) — time-of-week pattern
    import datetime as _dt
    scan_date = stock.get("scanDate") or today_str()
    try:
        dt_obj = _dt.datetime.strptime(scan_date.split(" ")[0], "%Y-%m-%d")
        dow = dt_obj.isoweekday()
    except Exception:
        dow = _dt.date.today().isoweekday()
    tk = f"dow_{dow}"
    tps = brain.setdefault("time_patterns", {})
    t = tps.setdefault(tk, {"count": 0, "win": 0, "total_ret": 0.0,
                            "avg_ret": 0.0, "win_rate": 0.0, "weight": 1.0})
    t["count"] = int(t["count"]) + 1
    if ret > 0: t["win"] = int(t["win"]) + 1
    t["total_ret"] = float(t["total_ret"]) + float(ret)
    t["avg_ret"]   = round(t["total_ret"] / t["count"], 2)
    t["win_rate"]  = round(t["win"] / t["count"] * 100, 1)
    if t["count"] >= 8:
        wr_f = t["win_rate"] / 55.0
        r_f  = 1.0 + (t["avg_ret"] / 15.0)
        t["weight"] = round(max(0.5, min(1.8, (wr_f + r_f) / 2.0)), 3)


def brain_get_confluence_bonus(stock: dict, brain: dict | None = None) -> int:
    """PHP brainGetConfluenceBonus (index.php:3311) birebir."""
    if brain is None:
        brain = brain_load()
    cp = brain.get("confluence_patterns") or {}
    if not cp: return 0
    from .scoring_extras import get_confluence_key
    key = get_confluence_key(stock)
    data = cp.get(key)
    n_full = int((data or {}).get("count", 0) or 0)

    # v37.2: Tam anahtar yetersizse, ilk 3 boyutla (RSI|MACD|VOL) prefix eşleşmesi
    # ara — yüksek kardinalite (3^11) sorununa karşı kısmi sinyal kurtarma.
    if not data or n_full < 4:
        prefix = "|".join(key.split("|")[:3]) + "|"
        agg_n = 0; agg_wr = 0.0; agg_ret = 0.0; agg_w = 0.0
        for k, d in cp.items():
            if not isinstance(d, dict): continue
            if not k.startswith(prefix): continue
            c = int(d.get("count", 0) or 0)
            if c < 2: continue
            agg_n += c
            agg_wr += float(d.get("win_rate", 50) or 50) * c
            agg_ret += float(d.get("avg_ret", 0) or 0) * c
            agg_w += float(d.get("weight", 1.0) or 1.0) * c
        if agg_n < 8: return 0
        wr  = agg_wr / agg_n
        avg = agg_ret / agg_n
        w   = (agg_w / agg_n) * 0.6  # prefix güveni daha düşük
    else:
        wr  = float(data.get("win_rate", 50) or 50)
        avg = float(data.get("avg_ret", 0) or 0)
        w   = float(data.get("weight", 1.0) or 1.0)

    if   wr >= 75 and avg > 5: return int(min(25, round(w * 20)))
    elif wr >= 65 and avg > 0: return int(min(18, round(w * 14)))
    elif wr >= 55:             return int(min(10, round(w * 7)))
    elif wr <= 30 and avg < 0: return int(max(-20, round(-w * 16)))
    elif wr <= 40:             return int(max(-10, round(-w * 8)))
    return 0


def brain_get_time_bonus(brain: dict | None = None) -> int:
    """PHP brainGetTimeBonus (index.php:3333) birebir."""
    if brain is None:
        brain = brain_load()
    tp = brain.get("time_patterns") or {}
    import datetime as _dt
    dow = _dt.date.today().isoweekday()
    data = tp.get(f"dow_{dow}")
    if not data or int(data.get("count", 0) or 0) < 3:
        return 0
    wr  = float(data.get("win_rate", 50) or 50)
    avg = float(data.get("avg_ret", 0) or 0)
    if   wr >= 70 and avg > 3: return  8
    elif wr >= 60:             return  5
    elif wr <= 35 and avg < 0: return -8
    elif wr <= 45:             return -4
    return 0


def neural_get_bonus(stock: dict, brain: dict | None = None,
                     net_key: str = "neural_net") -> int:
    """PHP neuralGetBonus / Beta / Gamma birebir + v38 kalibrasyon.

    Belirtilen NN'den (alpha/beta/gamma) skor delta'sını üretir.

    v38 değişiklikleri:
      • Eşik 5 → 20 örnek (eskiden 5 örnekle skor bonusu üretiliyordu, çok riskli)
      • Sıcaklık-kalibre tahmin (predict_calibrated) → aşırı güvenden korunma
      • Aritmetik delta artık ham olasılığa değil kalibre olasılığa dayalı
    """
    if brain is None:
        brain = brain_load()
    nn = brain.get(net_key)
    if not nn or "weights" not in nn:
        return 0
    trained = int(nn.get("trained_samples", 0) or 0)
    if trained < 20:
        return 0
    try:
        prob, conf = neural.predict_calibrated(nn, stock)
    except Exception:
        return 0
    delta = (prob - 0.5) * 80.0
    return int(round(delta * (0.20 + conf * 0.80)))


def neural_dual_bonus(stock: dict, brain: dict | None = None) -> tuple:
    """PHP neuralGetDualBonus birebir port — Triple Brain (alpha+beta+gamma) birleşik bonus.

    Returns: (final_bonus, alpha, beta, gamma, active_count, divergent)
      - active_count: 1, 2 veya 3 (kaç beyin aktif sinyal verdi)
      - divergent: True ise beyinler bölünmüş (zayıf sinyal)
    Çoğunluk konsensüs çarpanları:
      - 3/3 tam konsensüs → ×1.50
      - 2/3 çoğunluk     → ×1.10
      - 1/3 bölünmüş     → ×0.40
      - 2 aktif & uyumlu → ×1.15, uyumsuz → ×0.50
      - 1 aktif tek başına → ×0.65
    """
    if brain is None:
        brain = brain_load()
    alpha = neural_get_bonus(stock, brain, "neural_net")
    beta  = neural_get_bonus(stock, brain, "neural_net_beta")
    gamma = neural_get_bonus(stock, brain, "neural_net_gamma")

    active = (1 if alpha != 0 else 0) + (1 if beta != 0 else 0) + (1 if gamma != 0 else 0)
    if active == 0:
        return (0, 0, 0, 0, 0, False)

    aA = float((brain.get("neural_net")       or {}).get("recent_accuracy", 50.0) or 50.0)
    aB = float((brain.get("neural_net_beta")  or {}).get("recent_accuracy", 50.0) or 50.0)
    aG = float((brain.get("neural_net_gamma") or {}).get("recent_accuracy", 50.0) or 50.0)

    # v38: Çeşitlilik cezası — eğer iki ağ neredeyse özdeş tahmin veriyorsa,
    # bu ikisinin "iki ayrı oy" sayılması yanıltıcı (aslında aynı görüş).
    # Aralarındaki bonus farkı (mutlak) küçükse (≤8 puan), her birinin ağırlığını
    # 0.85x'e indir → farklılaşan ağın katkısı görece artar.
    def _div_penalty(x: int, y: int) -> float:
        return 0.85 if abs(x - y) <= 8 else 1.0
    aA *= _div_penalty(alpha, beta) * _div_penalty(alpha, gamma)
    aB *= _div_penalty(beta, alpha) * _div_penalty(beta, gamma)
    aG *= _div_penalty(gamma, alpha) * _div_penalty(gamma, beta)

    tot = aA + aB + aG
    wA = aA / tot if tot > 0 else 1/3
    wB = aB / tot if tot > 0 else 1/3
    wG = aG / tot if tot > 0 else 1/3

    # Tek beyin aktif — indirimli
    if active == 1:
        solo = alpha if alpha != 0 else (beta if beta != 0 else gamma)
        return (int(round(solo * 0.65)), alpha, beta, gamma, 1, False)

    # İki beyin aktif — uyumluluk kontrolü
    if active == 2:
        vals, dirs = [], []
        sw = (wA if alpha else 0) + (wB if beta else 0) + (wG if gamma else 0)
        if alpha != 0: vals.append(alpha * (wA / sw)); dirs.append(alpha > 0)
        if beta  != 0: vals.append(beta  * (wB / sw)); dirs.append(beta  > 0)
        if gamma != 0: vals.append(gamma * (wG / sw)); dirs.append(gamma > 0)
        avg = sum(vals) * 3  # PHP normalize katsayısı
        agree = len(set(dirs)) == 1
        mult  = 1.15 if agree else 0.50
        return (int(round(avg * mult)), alpha, beta, gamma, 2 if agree else 1, not agree)

    # 3 beyin aktif — Triple Brain rekabeti
    bull_votes = (1 if alpha > 0 else 0) + (1 if beta > 0 else 0) + (1 if gamma > 0 else 0)
    avg = wA * alpha + wB * beta + wG * gamma
    if bull_votes == 3 or bull_votes == 0:
        final = int(round(avg * 1.50)); active_n = 3; div = False
    elif bull_votes == 2:
        final = int(round(avg * 1.10)); active_n = 2; div = False
    else:
        final = int(round(avg * 0.40)); active_n = 1; div = True
    # v37.2: Hisseye özel hafıza — bu kod için tahmin doğruluğu varsa düzelt
    final += _per_stock_memory_bonus(stock, brain)
    return (final, alpha, beta, gamma, active_n, div)


def _per_stock_memory_bonus(stock: dict, brain: dict) -> int:
    """v37.2: Her hissenin geçmiş tahmin başarısı kayıt altında.

    brain['per_stock_memory'][CODE] = {n, hits, ret_sum} → win-rate * deneyim
    katsayısı ile -10..+10 ek puan üretir. Yeterli örnek (>=4) yoksa 0.
    """
    try:
        code = (stock.get("code") or "").upper()
        if not code: return 0
        psm = (brain.get("per_stock_memory") or {}).get(code)
        if not psm: return 0
        n = int(psm.get("n", 0) or 0)
        if n < 4: return 0
        hits = int(psm.get("hits", 0) or 0)
        wr = hits / n
        avg_ret = float(psm.get("ret_sum", 0.0) or 0.0) / n
        conf = min(1.0, (n - 3) / 12.0)  # 4..15 örnek → 0..1
        if   wr >= 0.70 and avg_ret > 2: return int(round( 10 * conf))
        elif wr >= 0.60 and avg_ret > 0: return int(round(  6 * conf))
        elif wr <= 0.30 and avg_ret < 0: return int(round(-10 * conf))
        elif wr <= 0.40:                  return int(round( -5 * conf))
        return 0
    except Exception:
        return 0


def per_stock_memory_update(brain: dict, code: str, predicted_bonus: int, ret: float) -> None:
    """Tahmin sonrası gerçekleşen getiri ile hisseye özel hafızayı güncelle."""
    if not code or abs(predicted_bonus) < 3:
        return
    psm = brain.setdefault("per_stock_memory", {})
    rec = psm.setdefault(code.upper(), {"n": 0, "hits": 0, "ret_sum": 0.0})
    rec["n"] = int(rec.get("n", 0) or 0) + 1
    if (predicted_bonus > 0) == (ret > 0):
        rec["hits"] = int(rec.get("hits", 0) or 0) + 1
    rec["ret_sum"] = float(rec.get("ret_sum", 0.0) or 0.0) + float(ret)





def brain_save(brain: dict) -> None:
    brain["last_updated"] = now_str()
    save_json(config.AI_BRAIN_FILE, brain)


def brain_save_snapshot(brain: dict, stock: dict) -> None:
    code = stock.get("code", "").strip()
    if not code:
        return
    today = today_str()
    snaps = brain["snapshots"].setdefault(code, [])
    if any(s.get("date") == today for s in snaps):
        return

    pred_bonus = 0
    try:
        pred_bonus = brain_get_prediction_bonus(brain, stock)
    except Exception:
        pass

    forms = [f.get("ad", "") for f in (stock.get("formations") or [])]

    snap = {
        "date": today,
        "price": float(stock.get("guncel", 0) or 0),
        "aiScore": int(stock.get("aiScore", 0) or 0),
        "rsi": float(stock.get("rsi", 50) or 50),
        "pos52wk": float(stock.get("pos52wk", 50) or 50),
        "volRatio": float(stock.get("volRatio", 1) or 1),
        "macdCross": stock.get("macdCross", "none"),
        "sarDir": stock.get("sarDir", "notr"),
        "ichiSig": stock.get("ichiSig", "notr"),
        "divRsi": stock.get("divRsi", "yok"),
        "stochK": float(stock.get("stochK", 50) or 50),
        "stochD": float(stock.get("stochD", 50) or 50),
        "bbSqueeze": bool(stock.get("bbSqueeze", False)),
        "cmf": float(stock.get("cmf", 0) or 0),
        "mfi": float(stock.get("mfi", 50) or 50),
        "adxVal": float(stock.get("adxVal", 0) or 0),
        "adxDir": stock.get("adxDir", "notr"),
        "formations": forms,
        "trend": stock.get("trend", "Notr"),
        "marketMode": stock.get("marketMode", "bull"),
        "sektor": stock.get("sektor", "genel"),
        "signalQ": int(stock.get("signalQuality", 0) or 0),
        "predictedBonus": pred_bonus,
        "supertrendDir": stock.get("supertrendDir", "notr"),
        "hullDir": stock.get("hullDir", "notr"),
        "emaCrossDir": stock.get("emaCrossDir", "none"),
        "trixCross": stock.get("trixCross", "none"),
        "cmo": float(stock.get("cmo", 0) or 0),
        "awesomeOscSig": stock.get("awesomeOscSig", "notr"),
        "keltnerPos": stock.get("keltnerPos", "notr"),
        "smcBias": stock.get("smcBias", "notr"),
        "ofiSig": stock.get("ofiSig", "notr"),
        "volRegime": stock.get("volRegime", "normal"),
        "vwapPos": stock.get("vwapPos", "icinde"),
        "ultimateOsc": float(stock.get("ultimateOsc", 50) or 50),
        "cci": float(stock.get("cci", 0) or 0),
        "aroonOsc": float(stock.get("aroonOsc", 0) or 0),
        "fibPos": float(stock.get("fibPos", 50) or 50),
        "elderBull": float(stock.get("elderBull", 0) or 0),
        "williamsR": float(stock.get("williamsR", -50) or -50),
        "outcome3": None, "outcome5": None, "outcome10": None,
        "outcome21": None, "outcome_ret": None,
        "hizScore": int(stock.get("hizScore", 0) or 0),
        # Uyuyan Mücevher etiketi — sonradan gerçek getirisi takip edilir
        "sleeperBonus": int(stock.get("sleeperBonus", 0) or 0),
        "earlyCatchBonus": int(stock.get("earlyCatchBonus", 0) or 0),
        "isSleeper": int(stock.get("sleeperBonus", 0) or 0) >= 50,
        "isEarlyCatch": int(stock.get("earlyCatchBonus", 0) or 0) >= 10,
        "marketCap": float(stock.get("marketCap", 0) or 0),
        # Ortak Kardeş etiketi — büyük abi katlamış, kardeş henüz hareketsiz
        "siblingBonus": int(stock.get("siblingBonus", 0) or 0),
        "siblingRefCode": stock.get("siblingRefCode", ""),
        "siblingPdOrani": float(stock.get("siblingPdOrani", 0) or 0),
        "isSibling": int(stock.get("siblingBonus", 0) or 0) > 0,
    }
    snaps.insert(0, snap)
    if len(snaps) > 90:
        brain["snapshots"][code] = snaps[:90]


def brain_update_outcomes(brain: dict, current_prices: dict[str, float]) -> None:
    """v38.1: Her olgunlaşan 7-günlük snapshot için Triple Brain DÜELLO çalıştırır.

    1. 3 ağ da snapshot'ı tahmin etti → her birinin gerçek yöne hata mesafesi
       hesaplanır (|p - actual|).
    2. En kötü tahmin eden ağ(lar) "loser" olarak işaretlenir.
    3. `dual_brain_knowledge_transfer` çağrılır → kayıp ağ(lar)a ekstra eğitim
       adımı (lr×2.2) atılır + `dual_brain_stats`'a düello yazılır.
    Sonuç: pasif ensemble → aktif rekabet. Kim daha doğru tahmin ederse
    `current_champion` o olur, sayaçlar (alpha_wins/beta_wins/gamma_wins) artar.
    """
    from .observability import log_event, log_exc
    now = time.time()
    for code, snaps in brain["snapshots"].items():
        cp = current_prices.get(code)
        if not cp or cp <= 0:
            continue
        for snap in snaps:
            ts = time.mktime(time.strptime(snap["date"] + " 00:00:00", "%Y-%m-%d %H:%M:%S"))
            days_diff = int((now - ts) / 86400)
            entry = float(snap.get("price", 0) or 0)
            if entry <= 0:
                continue
            ret = (cp - entry) / entry * 100
            # v38: outcome3 — 3 günlük getiri ile hafif (0.5x weight) eğitim
            # Erken sinyal verir, ancak nihai etiket olarak yeterince stabil değil.
            if snap.get("outcome3") is None and days_diff >= 3:
                snap["outcome3"] = round(ret, 2)
                # 3-günlük outcome ile sadece Beta'yı (kısa-vadeli) yarım ağırlıkla eğit.
                # Alpha (uzun vadeli) ve Gamma (orta) burada eğitilmez → çakışma azalır.
                try:
                    neural.train_on_outcome(brain["neural_net_beta"], snap, ret * 0.7)
                except Exception as e:
                    log_exc("brain", f"train Beta outcome3 fail ({code})", e, code=code)
            if snap.get("outcome5") is None and days_diff >= 7:
                snap["outcome5"] = round(ret, 2)
                snap["outcome_ret"] = round(ret, 2)
                _track_pred_accuracy(brain, snap, ret)
                brain_learn_from_snapshot(brain, snap, ret)
                # v37.2: Hisseye özel hafıza
                try:
                    per_stock_memory_update(brain, code,
                                            int(snap.get("predictedBonus", 0) or 0), ret)
                except Exception as e:
                    log_exc("brain", f"per_stock_memory fail ({code})", e, code=code)
                # ── DÜELLO: standart eğitimden ÖNCE her ağın tahminini al
                snap_for_pred = dict(snap, code=code)
                try:
                    p_alpha = float(neural.predict(brain["neural_net"], snap_for_pred))
                    p_beta = float(neural.predict(brain["neural_net_beta"], snap_for_pred))
                    p_gamma = float(neural.predict(brain["neural_net_gamma"], snap_for_pred))
                except Exception as e:
                    log_exc("brain", f"duel predict fail ({code})", e, code=code)
                    p_alpha = p_beta = p_gamma = 0.5
                # Üçlü ağı eğit (ana sinyal — 7 gün)
                neural.train_on_outcome(brain["neural_net"], snap, ret)
                neural.train_on_outcome(brain["neural_net_beta"], snap, ret)
                neural.train_on_outcome(brain["neural_net_gamma"], snap, ret)
                # ── Düello sonucunu hesapla ve transfer/stat güncelle
                try:
                    loser = _decide_duel_loser(p_alpha, p_beta, p_gamma, ret)
                    from .scoring_extras import dual_brain_knowledge_transfer
                    dual_brain_knowledge_transfer(brain, snap_for_pred, ret, loser)
                except Exception as e:
                    log_exc("brain", f"dual_brain_knowledge_transfer fail ({code})",
                            e, code=code)
            if snap.get("outcome10") is None and days_diff >= 14:
                snap["outcome10"] = round(ret, 2)
                # v38: 14-günlük getiri ile Alpha (uzun vadeli) ek eğitim — yarım ağırlıkla.
                # Daha uzun perspektifi öğrenir.
                try:
                    neural.train_on_outcome(brain["neural_net"], snap, ret * 0.6)
                except Exception as e:
                    log_exc("brain", f"train Alpha outcome10 fail ({code})", e, code=code)
            if snap.get("outcome21") is None and days_diff >= 21:
                snap["outcome21"] = round(ret, 2)
                # v38: 21-günlük getiri ile Gamma (en uzun) takviye — küçük ağırlıkla.
                try:
                    neural.train_on_outcome(brain["neural_net_gamma"], snap, ret * 0.5)
                except Exception as e:
                    log_exc("brain", f"train Gamma outcome21 fail ({code})", e, code=code)


def _decide_duel_loser(p_alpha: float, p_beta: float, p_gamma: float,
                       ret: float) -> str:
    """Triple Brain düellosu: hangi ağ(lar) kaybetti?

    Hata = |p - actual|, actual = 1 if ret>0 else 0.
    En yüksek hata = kayıp. Bağ varsa "tie" döner.

    Loser etiketleri (PHP uyumlu):
      • "beta"        → yalnız Beta kaybetti  → Alpha+Gamma kazandı, Alpha şampiyon
      • "alpha"       → yalnız Alpha kaybetti → Beta+Gamma kazandı, Beta şampiyon
      • "alpha_beta"  → hem Alpha hem Beta kaybetti → Gamma şampiyon
      • "beta_gamma"  → Beta+Gamma kaybetti → Alpha şampiyon
      • "alpha_gamma" → Alpha+Gamma kaybetti → Beta şampiyon
      • "all" / "tie" → düz beraberlik
    """
    actual = 1.0 if ret > 0 else 0.0
    err = {
        "alpha": abs(p_alpha - actual),
        "beta":  abs(p_beta - actual),
        "gamma": abs(p_gamma - actual),
    }
    # Toleransla "yakın" olanları yenmiş say; aşikar farklı olan kaybetsin.
    EPS = 0.08
    worst = max(err.values())
    losers = sorted([k for k, v in err.items() if (worst - v) < EPS])
    if len(losers) == 3:
        return "tie"
    if len(losers) == 1:
        return losers[0]  # tek kayıp
    # iki kayıp → şampiyonu komplemente et
    if losers == ["alpha", "beta"]:
        return "alpha_beta"      # Gamma kazandı
    if losers == ["beta", "gamma"]:
        return "beta_gamma"      # Alpha kazandı
    if losers == ["alpha", "gamma"]:
        return "alpha_gamma"     # Beta kazandı
    return "tie"


def _track_pred_accuracy(brain: dict, snap: dict, ret: float) -> None:
    pb = int(snap.get("predictedBonus", 0))
    if abs(pb) < 5:
        return
    pa = brain["prediction_accuracy"]
    pa["toplam"] = int(pa.get("toplam", 0)) + 1
    if (pb > 0) == (ret > 0):
        pa["dogru"] = int(pa.get("dogru", 0)) + 1
    pa["oran"] = round(pa["dogru"] / max(1, pa["toplam"]) * 100, 1)


def brain_update_indicator(indicators: dict, key: str, win: bool, ret: float) -> None:
    ind = indicators.setdefault(key, {"weight": 1.0, "count": 0, "win": 0, "total_ret": 0.0})
    alpha = 0.15
    ind["count"] = int(ind.get("count", 0)) + 1
    if win: ind["win"] = int(ind.get("win", 0)) + 1
    ind["total_ret"] = float(ind.get("total_ret", 0.0)) + ret
    if ind["count"] >= 5:
        wr = ind["win"] / ind["count"]
        avg = ind["total_ret"] / ind["count"]
        n = ind["count"]
        confidence = min(1.0, (n - 4) / 46.0)
        raw = 0.4 + wr * 1.2 + (avg / 20.0)
        new_w = 1.0 + (raw - 1.0) * confidence
        ind["weight"] = round(max(0.4, min(2.0, new_w)), 3)
        ind["ema_wr"] = round(ind.get("ema_wr", 50.0) * (1 - alpha) + (100.0 if win else 0.0) * alpha, 2)


def brain_learn_from_snapshot(brain: dict, snap: dict, ret: float) -> None:
    win = ret > 0

    # Yakınlık faktörü
    snap_date = snap.get("date", today_str())
    days_diff = max(0, int((time.time() - time.mktime(time.strptime(snap_date, "%Y-%m-%d"))) / 86400))
    recency = max(0.5, 1.0 - (days_diff / 730.0) * 0.5)

    # Formasyon öğrenmesi
    forms_w = brain["learned_weights"].setdefault("formation", {})
    for name in (snap.get("formations") or []):
        if not name: continue
        f = forms_w.setdefault(name, {"weight": 1.0, "count": 0, "win": 0, "total_ret": 0.0,
                                      "avg_ret": 0.0, "win_rate": 0.0})
        f["count"] = float(f.get("count", 0)) + recency
        if win: f["win"] = float(f.get("win", 0)) + recency
        f["total_ret"] = float(f.get("total_ret", 0)) + ret * recency
        f["avg_ret"] = round(f["total_ret"] / f["count"], 2) if f["count"] > 0 else 0.0
        f["win_rate"] = round(f["win"] / f["count"] * 100, 1) if f["count"] > 0 else 50.0
        if f["count"] >= 3:
            wr_factor = f["win_rate"] / 60.0
            ret_factor = 1.0 + (f["avg_ret"] / 15.0)
            confidence = min(1.0, max(0.0, (f["count"] - 3) / 17.0))
            raw = (wr_factor + ret_factor) / 2.0
            new_w = 1.0 + (raw - 1.0) * confidence
            f["weight"] = round(max(0.4, min(2.0, new_w)), 3)

    # İndikatör öğrenmesi
    inds = brain["learned_weights"].setdefault("indicator", {})
    rsi = float(snap.get("rsi", 50))
    if rsi < 20: brain_update_indicator(inds, "rsi_extreme", win, ret)
    elif rsi < 30: brain_update_indicator(inds, "rsi_oversold", win, ret)
    if snap.get("macdCross") == "golden": brain_update_indicator(inds, "macd_golden", win, ret)
    if snap.get("sarDir") == "yukselis":  brain_update_indicator(inds, "sar_yukselis", win, ret)
    if snap.get("divRsi") == "boga":      brain_update_indicator(inds, "div_bullish", win, ret)
    if snap.get("bbSqueeze"):             brain_update_indicator(inds, "bb_squeeze", win, ret)
    if float(snap.get("adxVal", 0)) >= 25 and snap.get("adxDir") == "yukselis":
        brain_update_indicator(inds, "adx_strong", win, ret)
    if float(snap.get("cmf", 0)) > 0.1:   brain_update_indicator(inds, "cmf_positive", win, ret)
    if float(snap.get("pos52wk", 50)) < 15: brain_update_indicator(inds, "52wk_low", win, ret)
    if float(snap.get("stochK", 50)) < 20: brain_update_indicator(inds, "stoch_oversold", win, ret)
    if float(snap.get("volRatio", 1)) > 2.5: brain_update_indicator(inds, "vol_surge", win, ret)
    if snap.get("ichiSig") == "ustunde":  brain_update_indicator(inds, "ichi_above", win, ret)
    if snap.get("supertrendDir") == "yukselis": brain_update_indicator(inds, "supertrend_bull", win, ret)
    if snap.get("hullDir") == "yukselis": brain_update_indicator(inds, "hull_bull", win, ret)
    if snap.get("emaCrossDir") == "golden": brain_update_indicator(inds, "ema9_21_golden", win, ret)
    if snap.get("trixCross") == "bullish": brain_update_indicator(inds, "trix_bullish", win, ret)
    if snap.get("awesomeOscSig") == "yukselis": brain_update_indicator(inds, "ao_bullish", win, ret)
    if float(snap.get("cmo", 0)) < -50:   brain_update_indicator(inds, "cmo_oversold", win, ret)
    if float(snap.get("ultimateOsc", 50)) < 30: brain_update_indicator(inds, "ult_osc_oversold", win, ret)
    if snap.get("keltnerPos") == "alt_bant": brain_update_indicator(inds, "keltner_below", win, ret)
    if snap.get("smcBias") == "bullish":  brain_update_indicator(inds, "smc_bullish", win, ret)
    if snap.get("ofiSig") == "guclu_alis": brain_update_indicator(inds, "ofi_strong_buy", win, ret)
    elif snap.get("ofiSig") == "alis":    brain_update_indicator(inds, "ofi_buy", win, ret)
    if snap.get("vwapPos") == "alt2":     brain_update_indicator(inds, "vwap_below2", win, ret)
    elif snap.get("vwapPos") == "alt1":   brain_update_indicator(inds, "vwap_below1", win, ret)
    if snap.get("volRegime") == "dusuk":  brain_update_indicator(inds, "vol_low_regime", win, ret)

    # Momentum kombinasyon öğrenmesi
    mc = 0
    if rsi < 35: mc += 1
    if snap.get("macdCross") == "golden": mc += 1
    if snap.get("supertrendDir") == "yukselis": mc += 1
    if snap.get("hullDir") == "yukselis": mc += 1
    if snap.get("emaCrossDir") == "golden": mc += 1
    if snap.get("smcBias") == "bullish": mc += 1
    if mc >= 4: brain_update_indicator(inds, "momentum_quad", win, ret)
    elif mc >= 3: brain_update_indicator(inds, "momentum_triple", win, ret)

    # Volatilite rejimine göre öğrenme
    vreg = snap.get("volRegime", "normal")
    vl = brain["volatility_learning"].setdefault(vreg, {"count": 0, "win": 0, "total_ret": 0.0,
                                                         "avg_ret": 0.0, "win_rate": 0.0})
    vl["count"] = int(vl.get("count", 0)) + 1
    if win: vl["win"] = int(vl.get("win", 0)) + 1
    vl["total_ret"] = float(vl.get("total_ret", 0)) + ret
    vl["avg_ret"] = round(vl["total_ret"] / vl["count"], 2)
    vl["win_rate"] = round(vl["win"] / vl["count"] * 100, 1)

    # Sektör × Mode matrisi
    sm_key = f"{snap.get('sektor', 'genel')}|{snap.get('marketMode', 'bull')}"
    sm = brain["sector_mode_matrix"].setdefault(sm_key, {"count": 0, "win": 0, "total_ret": 0.0,
                                                          "avg_ret": 0.0, "win_rate": 0.0})
    sm["count"] = int(sm.get("count", 0)) + 1
    if win: sm["win"] = int(sm.get("win", 0)) + 1
    sm["total_ret"] = float(sm.get("total_ret", 0)) + ret
    sm["avg_ret"] = round(sm["total_ret"] / sm["count"], 2)
    sm["win_rate"] = round(sm["win"] / sm["count"] * 100, 1)

    # Sektör performansı
    sektor = snap.get("sektor", "genel")
    sp = brain["sector_perf"].setdefault(sektor, {"count": 0, "win": 0, "total_ret": 0.0,
                                                   "avg_ret": 0.0, "win_rate": 0.0})
    sp["count"] = int(sp.get("count", 0)) + 1
    if win: sp["win"] = int(sp.get("win", 0)) + 1
    sp["total_ret"] = float(sp.get("total_ret", 0)) + ret
    sp["avg_ret"] = round(sp["total_ret"] / sp["count"], 2)
    sp["win_rate"] = round(sp["win"] / sp["count"] * 100, 1)


def _ind_bonus(ind: dict) -> int:
    w = float(ind.get("weight", 1.0))
    c = int(ind.get("count", 0))
    if c < 3:
        return 0
    if w >= 1.5: return 8
    if w >= 1.2: return 5
    if w >= 1.05: return 2
    if w <= 0.6: return -8
    if w <= 0.85: return -3
    return 0


def brain_get_prediction_bonus(brain: dict | None, stock: dict) -> int:
    """Geçmiş öğrenilmiş ağırlıklara göre -30 ile +35 arası skor delta."""
    if brain is None:
        brain = brain_load()
    lw = brain.get("learned_weights") or {}
    forms_w = lw.get("formation", {}) or {}
    inds_w = lw.get("indicator", {}) or {}
    if not isinstance(forms_w, dict): forms_w = {}
    if not isinstance(inds_w, dict):  inds_w = {}
    bonus = 0

    for f in (stock.get("formations") or []):
        name = f.get("ad", "")
        tip = f.get("tip", "")
        info = forms_w.get(name)
        if not info or int(info.get("count", 0)) < 3:
            continue
        w = float(info.get("weight", 1.0))
        wr = float(info.get("win_rate", 50))
        avg = float(info.get("avg_ret", 0))
        is_bear = (tip == "bearish") or (name in BEARISH_FORM_NAMES)
        if is_bear:
            if wr >= 60 and avg < 0: bonus -= 20
            elif wr >= 50:           bonus -= 12
            else:                    bonus -= 6
        else:
            if   w >= 1.4 and wr >= 60 and avg > 0: bonus += 22
            elif w >= 1.4 and wr >= 60:             bonus += 18
            elif w >= 1.2 and wr >= 55:             bonus += 12
            elif w >= 1.1 and avg > 3:              bonus += 8
            elif w >= 1.1:                          bonus += 6
            elif w <= 0.6 and wr < 35:              bonus -= 20
            elif w <= 0.8 and avg < -2:             bonus -= 12
            elif w <= 0.8:                          bonus -= 8

    rsi = float(stock.get("rsi", 50) or 50)
    if rsi < 20 and "rsi_extreme" in inds_w: bonus += _ind_bonus(inds_w["rsi_extreme"])
    elif rsi < 30 and "rsi_oversold" in inds_w: bonus += _ind_bonus(inds_w["rsi_oversold"])
    if stock.get("macdCross") == "golden" and "macd_golden" in inds_w: bonus += _ind_bonus(inds_w["macd_golden"])
    if stock.get("sarDir") == "yukselis" and "sar_yukselis" in inds_w: bonus += _ind_bonus(inds_w["sar_yukselis"])
    if stock.get("divRsi") == "boga" and "div_bullish" in inds_w: bonus += _ind_bonus(inds_w["div_bullish"])
    if stock.get("bbSqueeze") and "bb_squeeze" in inds_w: bonus += _ind_bonus(inds_w["bb_squeeze"])
    if float(stock.get("adxVal", 0)) >= 25 and stock.get("adxDir") == "yukselis" and "adx_strong" in inds_w:
        bonus += _ind_bonus(inds_w["adx_strong"])
    if float(stock.get("cmf", 0)) > 0.1 and "cmf_positive" in inds_w: bonus += _ind_bonus(inds_w["cmf_positive"])
    if float(stock.get("pos52wk", 50)) < 15 and "52wk_low" in inds_w: bonus += _ind_bonus(inds_w["52wk_low"])
    if float(stock.get("stochK", 50)) < 20 and "stoch_oversold" in inds_w: bonus += _ind_bonus(inds_w["stoch_oversold"])
    if float(stock.get("volRatio", 1)) > 2.5 and "vol_surge" in inds_w: bonus += _ind_bonus(inds_w["vol_surge"])
    if stock.get("ichiSig") == "ustunde" and "ichi_above" in inds_w: bonus += _ind_bonus(inds_w["ichi_above"])
    if stock.get("supertrendDir") == "yukselis" and "supertrend_bull" in inds_w: bonus += _ind_bonus(inds_w["supertrend_bull"])
    if stock.get("hullDir") == "yukselis" and "hull_bull" in inds_w: bonus += _ind_bonus(inds_w["hull_bull"])
    if stock.get("smcBias") == "bullish" and "smc_bullish" in inds_w: bonus += _ind_bonus(inds_w["smc_bullish"])
    if stock.get("ofiSig") == "guclu_alis" and "ofi_strong_buy" in inds_w: bonus += _ind_bonus(inds_w["ofi_strong_buy"])

    return max(-30, min(35, bonus))


def neural_bootstrap(brain: dict, stocks: list[dict]) -> int:
    """Üç ağı kural-bazlı sentetik veriyle 6 epoch eğitir.
    Return: bootstrap'a dahil edilen örnek sayısı.
    """
    if not stocks:
        return 0
    samples = []
    for s in stocks:
        ai = float(s.get("aiScore", s.get("alPuan", 0)) or 0)
        hiz = float(s.get("hizScore", 0) or 0)
        rsi = float(s.get("rsi", 50) or 50)
        vol = float(s.get("volRatio", 1) or 1)
        mfi = float(s.get("mfi", 50) or 50)
        h1 = float((s.get("targets") or {}).get("sell1", s.get("h1", 0)) or 0)
        g = float(s.get("guncel", 0) or 0)
        has_bear = any((f.get("tip") == "bearish") for f in (s.get("formations") or []))
        has_upside = (g > 0 and h1 > g)
        target = None
        if ai >= 250 and hiz >= 11 and vol >= 2.0 and not has_bear and has_upside and rsi < 65:
            target = 0.88
        elif ai >= 180 and hiz >= 8 and vol >= 1.5 and not has_bear and has_upside:
            target = 0.75
        elif ai >= 130 and hiz >= 5 and not has_bear and has_upside:
            target = 0.63
        elif ai < 60 or (rsi > 72 and mfi > 70) or (has_bear and ai < 100):
            target = 0.16
        elif has_bear or ai < 80 or rsi > 68:
            target = 0.28
        elif 80 <= ai < 130:
            target = 0.48
        if target is None:
            continue
        synth = {**s, "marketMode": s.get("marketMode", "bull"), "hizScore": hiz}
        ret = abs((h1 - g) / max(1, g) * 100) if target > 0.5 else -5.0
        samples.append((synth, target, ret if target > 0.5 else -abs(ret)))

    if not samples:
        return 0

    import random
    for net_key in ("neural_net", "neural_net_beta", "neural_net_gamma"):
        arch_name = "alpha" if net_key == "neural_net" else ("beta" if net_key.endswith("beta") else "gamma")
        brain[net_key] = neural.make_net(arch_name)
        brain[net_key]["bootstrap"] = True
        for _ in range(6):
            random.shuffle(samples)
            for snap, target, ret in samples:
                neural.train_step(brain[net_key], snap, target)
        brain[net_key]["trained_samples"] = len(samples) * 6
    return len(samples)


def neural_train_epochs(brain: dict, epochs: int = 1) -> int:
    """Snapshot havuzundan rastgele örnek seçip eğit.

    v37.3 iyileştirmeleri:
      • %15 doğrulama (validation) bölmesi → her epoch sonu val-loss izlenir
      • Erken durdurma (early stopping): val-loss ardışık 2 epoch artarsa dur
      • Epoch başı tek karıştırma + tekrar eden epoch'larda yeniden karıştır
      • Net bazında bağımsız izleme (alpha/beta/gamma ayrı erken durur)
    """
    samples = []
    for code, snaps in brain.get("snapshots", {}).items():
        for snap in snaps:
            r = snap.get("outcome_ret")
            if r is not None:
                samples.append((snap, float(r)))
    if not samples:
        return 0

    import random
    random.shuffle(samples)
    n = len(samples)
    val_n = max(1, int(n * 0.15)) if n >= 10 else 0
    val_set = samples[:val_n] if val_n else []
    train_set = samples[val_n:] if val_n else samples

    def _val_loss(net):
        if not val_set or "weights" not in net:
            return None
        total = 0.0
        for snap, ret in val_set:
            tgt = 0.5 + 0.45 * math.tanh(ret / 15.0)
            tgt = max(0.05, min(0.95, tgt))
            try:
                p = neural.predict(net, snap)
                total += (p - tgt) ** 2
            except Exception:
                pass
        return total / max(1, len(val_set))

    net_keys = ("neural_net", "neural_net_beta", "neural_net_gamma")
    stopped = {k: False for k in net_keys}
    prev_val = {k: None for k in net_keys}
    rises = {k: 0 for k in net_keys}

    for ep in range(max(1, epochs)):
        random.shuffle(train_set)
        for snap, ret in train_set:
            for k in net_keys:
                if stopped[k]:
                    continue
                neural.train_on_outcome(brain[k], snap, ret)
        # Epoch sonu val kontrolü
        for k in net_keys:
            if stopped[k]:
                continue
            vl = _val_loss(brain[k])
            if vl is None:
                continue
            net = brain[k]
            hist = net.get("loss_history") or []
            hist.append(round(float(vl), 6))
            net["loss_history"] = hist[-50:]
            if prev_val[k] is not None and vl > prev_val[k] * 1.01:
                rises[k] += 1
                if rises[k] >= 2:
                    stopped[k] = True
                    net["early_stopped_epoch"] = ep + 1
            else:
                rises[k] = 0
            prev_val[k] = vl

    return len(samples)


def neural_negative_bootstrap(brain: dict, stocks: list[dict],
                              epochs: int = 4) -> dict:
    """Negatif örneklerle eğitim: AI'ya 'neden bu hisse KAÇIN' öğretir.

    `allStocks` (artık 579 hissenin tam verisi) içinden:
      • AI=KAÇIN veya skor < 60 → güçlü olumsuz örnek (target 0.05–0.18)
      • AI=DİKKAT veya 60 ≤ skor < 100 → zayıf olumsuz (target 0.20–0.32)
      • Aşırı ısınmış (RSI>72 + MFI>70) → 0.10
      • Bearish formasyon + düşüş trendi → 0.08
      • AI=GÜÇLÜ AL ve skor ≥ 250 → güçlü pozitif (target 0.85)
      • AI=AL ve skor ≥ 150 → orta pozitif (target 0.68)

    Pozitif/negatif dengeli karışımla ağırlıklandırılır (eğitim sapması olmasın).
    Return: {"positive": n_pos, "negative": n_neg, "total": ..., "epochs": ...}
    """
    if not stocks:
        return {"positive": 0, "negative": 0, "total": 0, "epochs": 0}

    pos: list[tuple[dict, float]] = []
    neg: list[tuple[dict, float]] = []

    for s in stocks:
        ai = (s.get("autoThinkDecision") or "").upper()
        score = float(s.get("score", 0) or 0)
        rsi = float(s.get("rsi", 50) or 50)
        mfi = float(s.get("mfi", 50) or 50)
        trend = (s.get("trend") or "").lower()
        forms = s.get("formations") or []
        has_bear = any((f.get("tip") == "bearish") for f in forms)
        has_bull = any((f.get("tip") == "bullish") for f in forms)
        vol = float(s.get("volRatio", 1) or 1)
        h1 = float(s.get("h1", 0) or 0)
        cur = float(s.get("guncel", 0) or 0)
        has_upside = (cur > 0 and h1 > cur)
        sq = int(float(s.get("signalQuality", 0) or 0))

        target = None

        # — GÜÇLÜ NEGATİF —
        if ai == "KAÇIN" or score < 35:
            target = 0.06
        elif rsi > 78 and mfi > 75:
            target = 0.10
        elif has_bear and trend in ("dusus", "dusüş", "düşüş", "düsüs") and score < 80:
            target = 0.08
        elif score < 60 and not has_bull:
            target = 0.16
        # — ZAYIF NEGATİF —
        elif ai == "DİKKAT" or (60 <= score < 100):
            target = 0.28
        # — POZİTİF —
        elif ai == "GÜÇLÜ AL" and score >= 250 and has_upside and vol >= 2.0 and rsi < 72:
            target = 0.88
        elif ai == "AL" and score >= 150 and has_upside and not has_bear:
            target = 0.70
        elif score >= 200 and sq >= 6 and has_upside:
            target = 0.75
        elif 100 <= score < 150 and not has_bear:
            target = 0.50

        if target is None:
            continue
        snap = {**s, "marketMode": s.get("marketMode", "bull"),
                "hizScore": float(s.get("hizScore", 0) or 0)}
        if target < 0.4:
            neg.append((snap, target))
        else:
            pos.append((snap, target))

    if not pos and not neg:
        return {"positive": 0, "negative": 0, "total": 0, "epochs": 0}

    # Dengeli karışım: ağırlıkça eşit (oversample minoritesi)
    import random
    if pos and neg:
        if len(pos) > len(neg) * 1.5:
            mult = max(1, len(pos) // max(1, len(neg)))
            neg_balanced = neg * mult
            pos_balanced = pos
        elif len(neg) > len(pos) * 1.5:
            mult = max(1, len(neg) // max(1, len(pos)))
            pos_balanced = pos * mult
            neg_balanced = neg
        else:
            pos_balanced, neg_balanced = pos, neg
    else:
        pos_balanced, neg_balanced = pos, neg

    samples = pos_balanced + neg_balanced
    if not samples:
        return {"positive": len(pos), "negative": len(neg), "total": 0, "epochs": 0}

    eff_epochs = max(1, epochs)
    for net_key in ("neural_net", "neural_net_beta", "neural_net_gamma"):
        if net_key not in brain or not brain[net_key]:
            brain[net_key] = neural.make_net(
                "alpha" if net_key == "neural_net" else
                ("beta" if net_key.endswith("beta") else "gamma"))
        for _ in range(eff_epochs):
            random.shuffle(samples)
            for snap, tgt in samples:
                neural.train_step(brain[net_key], snap, tgt)
        brain[net_key]["trained_samples"] = (
            int(brain[net_key].get("trained_samples", 0) or 0)
            + len(samples) * eff_epochs)

    # Tüm modüller için eğitim sayacı
    brain["last_negative_train"] = {
        "ts": now_str() if False else __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "positive_samples": len(pos),
        "negative_samples": len(neg),
        "balanced_total": len(samples),
        "epochs": eff_epochs,
    }
    return {"positive": len(pos), "negative": len(neg),
            "total": len(samples), "epochs": eff_epochs}


def neural_ensemble_predict(brain: dict, stock: dict) -> dict:
    """Üç ağdan topluluk tahmini. 0..1 arası.

    v37.3 iyileştirmeleri:
      • Doğruluk-ağırlıklı topluluk: her ağın `recent_accuracy` EMA'sı ile
        ağırlıklandırılmış softmax-vari ortalama. Düşük performanslı ağ
        topluluğu zehirlemez.
      • Konsensüs (consensus): üç ağın aynı yönde (>=0.5 veya <0.5) olma oranı.
      • Confidence: |avg-0.5| × 2 × (1 - spread) × consensus → 0..1.
        Yüksek confidence = "üç ağ da güçlü ve hemfikir".
      • Yön: 'bull' / 'bear' / 'notr' (0.45-0.55 arası nötr bant).
    """
    nets = [
        ("alpha", brain.get("neural_net") or {}),
        ("beta",  brain.get("neural_net_beta") or {}),
        ("gamma", brain.get("neural_net_gamma") or {}),
    ]
    preds = {}
    raw_preds = {}
    cal_confs = {}
    weights = {}
    for name, net in nets:
        # v38: Sıcaklık-kalibre tahmin — aşırı güveni törpüler, sonra topluluğa girer.
        p_cal, c_cal = neural.predict_calibrated(net, stock)
        p_raw = neural.predict(net, stock)
        # Doğruluk EMA tabanlı ağırlık (50%=baseline → w=1.0; 75%=w≈1.5; 25%=w≈0.5)
        acc = float(net.get("recent_accuracy", 50.0) or 50.0)
        # eğitilmemiş ağa düşük ağırlık
        trained = int(net.get("trained_samples", 0) or 0)
        readiness = min(1.0, trained / 50.0) if trained > 0 else 0.2
        w = max(0.2, min(2.0, (acc / 50.0))) * (0.4 + 0.6 * readiness)
        # v38: Kalibre güveni de ağırlığa katarsın → güveni düşük ağ daha az ses çıkarır.
        w *= (0.5 + 0.5 * c_cal)
        preds[name] = p_cal
        raw_preds[name] = p_raw
        cal_confs[name] = c_cal
        weights[name] = w

    a, b, c = preds["alpha"], preds["beta"], preds["gamma"]
    wsum = sum(weights.values()) or 1.0
    avg = (a * weights["alpha"] + b * weights["beta"]
           + c * weights["gamma"]) / wsum
    plain_avg = (a + b + c) / 3.0
    spread = max(a, b, c) - min(a, b, c)

    # Konsensüs: aynı yönde olan ağ sayısı / 3
    dirs = [1 if x >= 0.5 else -1 for x in (a, b, c)]
    bulls = sum(1 for d in dirs if d > 0)
    consensus = max(bulls, 3 - bulls) / 3.0

    # Confidence (0..1)
    margin = abs(avg - 0.5) * 2.0
    confidence = max(0.0, min(1.0, margin * (1.0 - min(spread, 1.0)) * consensus))

    if avg >= 0.55:
        direction = "bull"
    elif avg <= 0.45:
        direction = "bear"
    else:
        direction = "notr"

    return {
        # v38: 'alpha/beta/gamma' artık KALİBRE olasılıklar (yumuşatılmış).
        # Ham çıktıya da ihtiyaç olursa 'raw' alanı.
        "alpha": round(a, 4), "beta": round(b, 4), "gamma": round(c, 4),
        "raw": {k: round(v, 4) for k, v in raw_preds.items()},
        "calibration_conf": {k: round(v, 3) for k, v in cal_confs.items()},
        "avg": round(avg, 4),
        "plain_avg": round(plain_avg, 4),
        "spread": round(spread, 4),
        "consensus": round(consensus, 3),
        "confidence": round(confidence, 4),
        "direction": direction,
        "weights": {k: round(v, 3) for k, v in weights.items()},
    }


def brain_indicator_bonus(ind: dict) -> int:
    """PHP brainIndicatorBonus (index.php:3032) v35 birebir.
    Tek bir indikatör istatistiği için Bayesian güvenle ölçeklenmiş bonus."""
    count = int(ind.get("count", 0))
    if count < 3: return 0
    w = float(ind.get("weight", 1.0))
    ret = float(ind.get("total_ret", 0)) / count if count > 0 else 0.0
    ema_wr = float(ind.get("ema_wr", 0))
    if ema_wr > 0:
        raw_wr = (float(ind.get("win", 0)) / count * 100.0) if count > 0 else 50.0
        blend  = ema_wr * 0.45 + raw_wr * 0.55
        w = max(0.3, min(2.2, w * (blend / 58.0)))
    confidence = min(1.0, max(0.0, (count - 3) / 35.0))
    if   w >= 1.5  and ret > 0: base = 16
    elif w >= 1.5:              base = 13
    elif w >= 1.2  and ret > 0: base = 10
    elif w >= 1.2:              base =  7
    elif w >= 1.05 and ret > 0: base =  5
    elif w >= 1.05:             base =  3
    elif w <= 0.6  and ret < 0: base = -16
    elif w <= 0.6:              base = -13
    elif w <= 0.8  and ret < 0: base =  -8
    elif w <= 0.8:              base =  -6
    else:                       base =   0
    return int(round(base * (0.35 + confidence * 0.65)))
