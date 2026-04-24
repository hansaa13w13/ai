"""Adaptive Intelligence Layer — v37.4
========================================================================
AI'ın eşik değerlerini, pozisyon büyüklüğünü ve karar limitlerini son
gerçek başarısına göre OTOMATİK ayarlar. Sabit kodlu eşikler yerine
veri-güdümlü eşikler kullanır.

Modüller:
  • compute_adaptive_thresholds — son 30 gün performansından AL/GÜÇLÜ AL eşiği
  • detect_performance_drift     — son 7 gün vs ömür-boyu winrate karşılaştırma
  • kelly_position_size          — Kelly Kriteri ile pozisyon yüzdesi
  • get_regime_multiplier        — boğa/ayı modunda eşik genişletme/sıkma
  • get_sector_reliability       — sektör bazlı geçmiş başarı
  • get_full_adaptive_state      — tek-çağrıda tüm adaptif veriler

Önbellek: 1 saatte bir hesaplanır (utils.json'da `adaptive_state` anahtarı).
"""
from __future__ import annotations
import datetime as _dt
from . import config
from .utils import load_json, save_json


# Varsayılan (cold-start) eşikler
DEFAULT_THRESHOLDS = {
    "guclu_al": 90,   # ai_think.py içinde hardcoded "final_score >= 90"
    "al":       75,   # "final_score >= 75"
    "al_lite":  55,   # "final_score >= 55"
    "kacin":    35,   # düşüş kararı eşiği
    "win_target": 0.60,   # %60 win-rate hedefi
    "strong_target": 0.70,
}

# Önbellek yolu — 1 saat TTL
_CACHE_FILE = config.CACHE_DIR / "predator_adaptive_state.json"
_CACHE_TTL_SEC = 3600


def _now_ts() -> float:
    return _dt.datetime.now().timestamp()


def _hist_in_window(days: int = 30) -> list[dict]:
    """Son N gün içinde sonucu (result5) belli olmuş kayıtları döndür."""
    hist = load_json(config.SIGNAL_HISTORY_FILE, []) or []
    cutoff = _dt.date.today() - _dt.timedelta(days=days)
    out: list[dict] = []
    for h in hist:
        if h.get("result5") is None:
            continue
        try:
            d = _dt.datetime.fromisoformat(str(h.get("date", "")).replace("Z", "+00:00")).date()
        except Exception:
            try:
                d = _dt.datetime.strptime(str(h.get("date", ""))[:10], "%Y-%m-%d").date()
            except Exception:
                continue
        if d >= cutoff:
            out.append(h)
    return out


def compute_adaptive_thresholds(window_days: int = 30) -> dict:
    """Son N gün gerçek getirilerinden AL/GÜÇLÜ AL eşiği üret.

    Mantık:
      • aiScore'u 20'lik kova'lara böl.
      • Her kova için win-rate (result5 > 0) hesapla.
      • Win-rate ≥ %70 olan EN DÜŞÜK kova → GÜÇLÜ AL eşiği
      • Win-rate ≥ %60 olan EN DÜŞÜK kova → AL eşiği
      • Win-rate ≤ %35 olan EN DÜŞÜK kova → KAÇIN eşiği (üstü)
      • Yetersiz veri (< 15 örnek) → varsayılan eşikler
    """
    rows = _hist_in_window(window_days)
    if len(rows) < 15:
        return {**DEFAULT_THRESHOLDS, "method": "default", "samples": len(rows)}

    buckets: dict[int, dict] = {}
    for h in rows:
        score = int(h.get("aiScore") or 0)
        b = (score // 20) * 20
        ret = float(h.get("result5") or 0)
        d = buckets.setdefault(b, {"n": 0, "win": 0, "ret_sum": 0.0})
        d["n"] += 1
        d["ret_sum"] += ret
        if ret > 0:
            d["win"] += 1

    # Yeterli örneği olan kovaları sırala (düşükten yükseğe)
    valid = sorted([(b, d) for b, d in buckets.items() if d["n"] >= 3])

    guclu_al = DEFAULT_THRESHOLDS["guclu_al"]
    al       = DEFAULT_THRESHOLDS["al"]
    kacin    = DEFAULT_THRESHOLDS["kacin"]
    found_strong = False
    found_buy    = False

    for b, d in valid:
        wr = d["win"] / d["n"]
        if not found_strong and wr >= 0.70:
            guclu_al = b; found_strong = True
        if not found_buy and wr >= 0.60:
            al = b; found_buy = True

    # En kötü performanslı düşük kova → kaçın eşiği
    for b, d in valid:
        wr = d["win"] / d["n"]
        if wr <= 0.35:
            kacin = max(kacin, b + 20)
            break

    # Tutarlılık: GÜÇLÜ AL >= AL + 10
    if guclu_al < al + 10:
        guclu_al = al + 15

    # Toplam istatistik
    tot_n = sum(d["n"] for d in buckets.values())
    tot_w = sum(d["win"] for d in buckets.values())
    tot_r = sum(d["ret_sum"] for d in buckets.values())

    return {
        "guclu_al": int(guclu_al),
        "al":       int(al),
        "al_lite":  max(45, int(al) - 20),
        "kacin":    int(kacin),
        "win_target": 0.60,
        "strong_target": 0.70,
        "method":   "adaptive",
        "samples":  tot_n,
        "lifetime_winrate": round(tot_w / max(tot_n, 1) * 100, 1),
        "lifetime_avg_ret": round(tot_r / max(tot_n, 1), 2),
        "buckets": {str(b): {"n": d["n"], "wr": round(d["win"]/d["n"]*100, 1), "ret": round(d["ret_sum"]/d["n"], 2)}
                    for b, d in buckets.items() if d["n"] >= 3},
        "window_days": window_days,
    }


def detect_performance_drift(short_days: int = 7, long_days: int = 30) -> dict:
    """Son 7 gün vs son 30 gün karşılaştırması — başarı düşüyor mu?

    Drift > 10pp → AI'ın yeniden kalibre edilmesi öneriliyor.
    """
    short = _hist_in_window(short_days)
    long_ = _hist_in_window(long_days)

    def _wr(rows):
        evals = [r for r in rows if r.get("result5") is not None]
        if not evals: return None, 0
        wins = sum(1 for r in evals if float(r.get("result5") or 0) > 0)
        return round(wins / len(evals) * 100, 1), len(evals)

    swr, sn = _wr(short)
    lwr, ln = _wr(long_)
    if swr is None or lwr is None or sn < 5:
        return {"status": "insufficient_data", "short": swr, "long": lwr,
                "short_n": sn, "long_n": ln}

    delta = swr - lwr
    if   delta <= -15: status = "critical_drift"
    elif delta <= -10: status = "drift_warning"
    elif delta >=  15: status = "improvement"
    elif delta >=  10: status = "improvement_mild"
    else:              status = "stable"

    recommendation = ""
    if status == "critical_drift":
        recommendation = "AI yeniden eğitilmeli — eşikler %20 yükseltildi"
    elif status == "drift_warning":
        recommendation = "Performans düşüşü — eşikler %10 yükseltildi"
    elif status == "improvement":
        recommendation = "Güçlü iyileşme — eşikler hafifletilebilir"

    return {
        "status": status, "delta_pp": round(delta, 1),
        "short_winrate": swr, "long_winrate": lwr,
        "short_n": sn, "long_n": ln,
        "recommendation": recommendation,
    }


def kelly_position_size(win_rate: float, avg_win_pct: float,
                        avg_loss_pct: float, max_frac: float = 0.25) -> dict:
    """Kelly Kriteri pozisyon büyüklüğü.

    f* = (bp - q) / b  — burada b = avg_win/avg_loss, p = win_rate, q = 1-p
    Yarı-Kelly (×0.5) uygulanır (gerçek dünya volatilite koruması).
    `max_frac`: tek pozisyon için maksimum sermaye payı (varsayılan %25).
    """
    p = max(0.01, min(0.99, win_rate))
    q = 1 - p
    aw = max(0.1, abs(avg_win_pct))
    al = max(0.1, abs(avg_loss_pct))
    b = aw / al
    f_star = (b * p - q) / b
    f_half = max(0, f_star * 0.5)
    f_capped = min(max_frac, f_half)
    return {
        "kelly_full":   round(f_star, 4),
        "kelly_half":   round(f_half, 4),
        "recommended":  round(f_capped, 4),
        "recommended_pct": round(f_capped * 100, 2),
        "interpretation":
            "agresif yatırım önerilir" if f_capped >= 0.15 else
            "orta düzey pozisyon"      if f_capped >= 0.08 else
            "küçük pozisyon"            if f_capped >  0    else
            "POZİSYON AÇMA — beklenen değer negatif",
    }


def get_regime_multiplier(market_mode: str) -> dict:
    """Piyasa moduna göre eşik genişletme/sıkma."""
    mults = {
        "ayi":      {"thresh_mul": 1.20, "size_mul": 0.50, "note": "Ayı modu — eşikler %20 yükseltildi, pozisyonlar yarıya"},
        "temkinli": {"thresh_mul": 1.10, "size_mul": 0.75, "note": "Temkinli — eşikler %10 yukarı, pozisyonlar %75"},
        "bull":     {"thresh_mul": 0.95, "size_mul": 1.00, "note": "Boğa modu — eşikler %5 hafifletildi"},
        "normal":   {"thresh_mul": 1.00, "size_mul": 1.00, "note": "Normal mod — varsayılan eşikler"},
    }
    return mults.get(market_mode, mults["normal"])


def get_sector_reliability(window_days: int = 60) -> dict:
    """Hangi sektörler tarihsel olarak daha güvenilir tahmin üretiyor?"""
    rows = _hist_in_window(window_days)
    by_sek: dict[str, dict] = {}
    for h in rows:
        sek = (h.get("sektor") or "genel").strip()
        d = by_sek.setdefault(sek, {"n": 0, "win": 0, "ret": 0.0})
        d["n"] += 1
        ret = float(h.get("result5") or 0)
        d["ret"] += ret
        if ret > 0: d["win"] += 1
    out = []
    for sek, d in by_sek.items():
        if d["n"] < 3: continue
        out.append({
            "sektor": sek, "n": d["n"],
            "winrate": round(d["win"] / d["n"] * 100, 1),
            "avg_ret": round(d["ret"] / d["n"], 2),
            "score":   round(d["win"] / d["n"] * 100 + d["ret"] / d["n"] * 2, 1),
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return {"sectors": out[:15], "samples": len(rows)}


def get_full_adaptive_state(force_refresh: bool = False) -> dict:
    """Tek çağrıda TÜM adaptif intelligence verileri.

    1 saatte bir yeniden hesaplanır (TTL cache).
    """
    cached = load_json(_CACHE_FILE, {}) or {}
    if not force_refresh and cached:
        ts = float(cached.get("computed_at", 0) or 0)
        if _now_ts() - ts < _CACHE_TTL_SEC:
            return cached

    # 30 günlük adaptive eşikler
    th = compute_adaptive_thresholds(30)
    drift = detect_performance_drift(7, 30)

    # Drift varsa eşikleri otomatik ayarla
    drift_mult = 1.0
    if drift.get("status") == "critical_drift":
        drift_mult = 1.20
    elif drift.get("status") == "drift_warning":
        drift_mult = 1.10
    elif drift.get("status") == "improvement":
        drift_mult = 0.95

    if drift_mult != 1.0:
        th["guclu_al"] = int(round(th["guclu_al"] * drift_mult))
        th["al"]       = int(round(th["al"]       * drift_mult))
        th["al_lite"]  = int(round(th["al_lite"]  * drift_mult))
        th["drift_adjustment"] = f"×{drift_mult:.2f}"

    # Piyasa modu çarpanı
    try:
        from .scoring_extras import get_market_mode
        mode = get_market_mode()
    except Exception:
        mode = "normal"
    regime = get_regime_multiplier(mode)
    th["guclu_al"] = int(round(th["guclu_al"] * regime["thresh_mul"]))
    th["al"]       = int(round(th["al"]       * regime["thresh_mul"]))

    # Lifetime istatistiklerden Kelly
    wr = th.get("lifetime_winrate", 50) / 100.0
    avg_ret = th.get("lifetime_avg_ret", 0)
    avg_win  = max(2.0, abs(avg_ret) * 1.5) if avg_ret > 0 else 4.0
    avg_loss = max(2.0, abs(avg_ret) * 1.5) if avg_ret < 0 else 3.0
    kelly = kelly_position_size(wr, avg_win, avg_loss)

    sektor = get_sector_reliability(60)

    state = {
        "thresholds":  th,
        "drift":       drift,
        "regime":      {"mode": mode, **regime},
        "kelly":       kelly,
        "sector_reliability": sektor,
        "computed_at": _now_ts(),
    }
    save_json(_CACHE_FILE, state)
    return state


def get_adaptive_decision_thresholds() -> tuple[int, int, int]:
    """ai_think.py'da kullanılacak (guclu_al, al, kacin) tuple."""
    try:
        st = get_full_adaptive_state()
        th = st.get("thresholds", {})
        return (int(th.get("guclu_al", 90)),
                int(th.get("al", 75)),
                int(th.get("kacin", 35)))
    except Exception:
        return (90, 75, 35)
