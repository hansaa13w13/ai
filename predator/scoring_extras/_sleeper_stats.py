"""Uyuyan Mücevher etiketli sinyallerin gerçek getirilerini takip eder.

Beyin snapshot'larında ``isSleeper=True`` olarak işaretlenen kayıtların
3/7/14/21 günlük gerçek getirilerini toplar; toplam sinyal, kazanma
oranı, ortalama getiri ve en iyi 5 hisse listesini döndürür.

Bu modül brain dosyasını yalnızca okur (yan etki yok).
"""
from __future__ import annotations

from .. import config
from ..utils import load_json


def _agg(samples: list[float]) -> dict:
    n = len(samples)
    if n == 0:
        return {"n": 0, "win_pct": 0.0, "avg_ret": 0.0,
                "median_ret": 0.0, "best": 0.0, "worst": 0.0}
    wins = sum(1 for r in samples if r > 0)
    avg = sum(samples) / n
    sorted_s = sorted(samples)
    median = sorted_s[n // 2] if n % 2 else (sorted_s[n // 2 - 1] + sorted_s[n // 2]) / 2
    return {
        "n": n,
        "win_pct": round(wins / n * 100, 1),
        "avg_ret": round(avg, 2),
        "median_ret": round(median, 2),
        "best": round(max(samples), 2),
        "worst": round(min(samples), 2),
    }


def sleeper_performance_stats() -> dict:
    """Uyuyan Mücevher etiketli snapshot'ların gerçek performansı.

    Dönüş:
        {
            "total_labeled": int,
            "matured_5d": int,
            "by_horizon": {
                "3d": {n, win_pct, avg_ret, median_ret, best, worst},
                "7d": {...},
                "14d": {...},
                "21d": {...},
            },
            "top_realized": [
                {code, date, sleeperBonus, ret7, ret14, ret21, marketCap},
                ...
            ],
            "by_bonus_bucket": { "50-75": {...}, "75-100": {...}, ...},
            "early_catch": { "n", "win_pct", "avg_ret" },
        }
    """
    brain = load_json(config.AI_BRAIN_FILE, {}) or {}
    snaps_by_code = brain.get("snapshots") or {}
    if not snaps_by_code:
        return {"total_labeled": 0, "matured_5d": 0, "by_horizon": {},
                "top_realized": [], "by_bonus_bucket": {}, "early_catch": {}}

    labeled: list[tuple[str, dict]] = []
    for code, snaps in snaps_by_code.items():
        for s in snaps:
            if s.get("isSleeper"):
                labeled.append((code, s))

    if not labeled:
        return {"total_labeled": 0, "matured_5d": 0, "by_horizon": {},
                "top_realized": [], "by_bonus_bucket": {}, "early_catch": {}}

    # Horizon bazlı toplulaştır
    horizons = {"3d": "outcome3", "7d": "outcome5",
                "14d": "outcome10", "21d": "outcome21"}
    by_horizon: dict[str, dict] = {}
    for label, key in horizons.items():
        samples = [float(s.get(key)) for _, s in labeled if s.get(key) is not None]
        by_horizon[label] = _agg(samples)

    # Bonus bucket — sleeperBonus seviyesine göre kazanma oranı
    buckets: dict[str, list[float]] = {
        "50-75": [], "75-100": [], "100-125": [], "125+": [],
    }
    for _, s in labeled:
        ret7 = s.get("outcome5")
        if ret7 is None:
            continue
        sb = int(s.get("sleeperBonus", 0) or 0)
        if sb < 50:
            continue
        if sb < 75:
            buckets["50-75"].append(float(ret7))
        elif sb < 100:
            buckets["75-100"].append(float(ret7))
        elif sb < 125:
            buckets["100-125"].append(float(ret7))
        else:
            buckets["125+"].append(float(ret7))
    by_bonus_bucket = {k: _agg(v) for k, v in buckets.items() if v}

    # En iyi gerçekleşen 10 sinyal
    realized: list[dict] = []
    for code, s in labeled:
        ret = s.get("outcome10") or s.get("outcome5") or s.get("outcome3")
        if ret is None:
            continue
        realized.append({
            "code": code,
            "date": s.get("date", ""),
            "sleeperBonus": int(s.get("sleeperBonus", 0) or 0),
            "earlyCatchBonus": int(s.get("earlyCatchBonus", 0) or 0),
            "ret3": s.get("outcome3"),
            "ret7": s.get("outcome5"),
            "ret14": s.get("outcome10"),
            "ret21": s.get("outcome21"),
            "marketCap": round(float(s.get("marketCap", 0) or 0), 0),
            "best": round(float(ret), 2),
        })
    realized.sort(key=lambda x: x.get("best", 0), reverse=True)
    top_realized = realized[:10]

    # Erken yakalama performansı
    ec_samples = [
        float(s.get("outcome5"))
        for _, s in labeled
        if s.get("isEarlyCatch") and s.get("outcome5") is not None
    ]
    early_catch = _agg(ec_samples) if ec_samples else {"n": 0}

    matured_5d = sum(1 for _, s in labeled if s.get("outcome5") is not None)

    return {
        "total_labeled": len(labeled),
        "matured_5d": matured_5d,
        "by_horizon": by_horizon,
        "top_realized": top_realized,
        "by_bonus_bucket": by_bonus_bucket,
        "early_catch": early_catch,
    }
