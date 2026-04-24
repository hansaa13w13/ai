"""AI performans istatistikleri, sinyal sonuçları ve kalibrasyon."""

from __future__ import annotations

import time
from datetime import datetime

from .. import config
from ..utils import load_json, save_json


def ai_performance_stats() -> dict:
    """PHP getAIPerformanceStats birebir."""
    hist = load_json(config.SIGNAL_HISTORY_FILE, []) or []
    if not hist:
        return {}
    toplam = 0
    kazanan = 0
    total_ret = 0.0
    by_score: dict[int, dict] = {}
    by_form: dict[str, dict] = {}
    for h in hist:
        if h.get("result5") is None:
            continue
        toplam += 1
        ret5 = float(h.get("result5") or 0)
        total_ret += ret5
        if ret5 > 0:
            kazanan += 1
        score = int(h.get("aiScore") or 0)
        bucket = (score // 20) * 20
        d = by_score.setdefault(bucket, {"toplam": 0, "kazanan": 0, "ret": 0.0})
        d["toplam"] += 1
        if ret5 > 0:
            d["kazanan"] += 1
        d["ret"] += ret5
        for f in h.get("formations") or []:
            if not f:
                continue
            df = by_form.setdefault(f, {"toplam": 0, "kazanan": 0})
            df["toplam"] += 1
            if ret5 > 0:
                df["kazanan"] += 1
    if toplam == 0:
        return {"toplam_sinyal": len(hist), "degerlendirilmis": 0}
    form_list = []
    for k, v in by_form.items():
        form_list.append({
            "ad": k,
            "basari": round(v["kazanan"] / v["toplam"] * 100, 1) if v["toplam"] else 0,
            "toplam": v["toplam"],
        })
    form_list.sort(key=lambda x: x["basari"], reverse=True)
    return {
        "toplam_sinyal": len(hist),
        "degerlendirilmis": toplam,
        "kazanma_orani": round(kazanan / toplam * 100, 1),
        "ort_getiri": round(total_ret / toplam, 2),
        "by_score": dict(sorted(by_score.items(), key=lambda x: -x[0])),
        "by_formation": form_list[:5],
    }


def update_signal_outcomes(current_stocks: list[dict]) -> bool:
    """PHP updateSignalOutcomes birebir. result5/10/20 doldurur."""
    hist = load_json(config.SIGNAL_HISTORY_FILE, []) or []
    if not hist:
        return False
    price_map: dict[str, float] = {}
    for s in current_stocks:
        c = s.get("code") or ""
        p = float(s.get("guncel") or 0)
        if c and p > 0:
            price_map[c] = p
    changed = False
    now = time.time()
    for h in hist:
        code = h.get("code") or ""
        if not code or code not in price_map or price_map[code] <= 0:
            continue
        entry_p = float(h.get("price") or 0)
        if entry_p <= 0:
            continue
        try:
            entry_time = datetime.fromisoformat((h.get("date") or "").replace("Z", "+00:00")).timestamp()
        except Exception:
            try:
                entry_time = datetime.strptime((h.get("date") or "")[:19], "%Y-%m-%d %H:%M:%S").timestamp()
            except Exception:
                continue
        days = int((now - entry_time) / 86400)
        cur_p = price_map[code]
        ret = round((cur_p - entry_p) / entry_p * 100, 2)
        if h.get("result5") is None and days >= 5:
            h["result5"] = ret
            changed = True
        if h.get("result10") is None and days >= 10:
            h["result10"] = ret
            changed = True
        if h.get("result20") is None and days >= 20:
            h["result20"] = ret
            changed = True
    if changed:
        save_json(config.SIGNAL_HISTORY_FILE, hist)
    return changed


def get_calibration_suggestions() -> list[dict]:
    """PHP getCalibrationSuggestions birebir."""
    hist = load_json(config.SIGNAL_HISTORY_FILE, []) or []
    if not hist:
        return []
    by_score: dict[str, dict] = {}
    total_eval = 0
    for h in hist:
        if h.get("result5") is None:
            continue
        total_eval += 1
        score = int(h.get("aiScore") or 0)
        bucket = (score // 20) * 20
        key = f"{bucket}-{bucket + 20}"
        d = by_score.setdefault(key, {"toplam": 0, "kazanan": 0, "bucket": bucket, "totalRet": 0.0})
        d["toplam"] += 1
        ret5 = float(h.get("result5") or 0)
        d["totalRet"] += ret5
        if ret5 > 0:
            d["kazanan"] += 1
    if total_eval < 10:
        return [{"tip": "info", "mesaj": "Yeterli sinyal geçmişi yok (en az 10 değerlendirme gerekli)", "renk": "#555"}]
    out = []
    for rng, d in by_score.items():
        if d["toplam"] < 3:
            continue
        basari = round(d["kazanan"] / d["toplam"] * 100)
        ort = round(d["totalRet"] / d["toplam"], 1)
        b = d["bucket"]
        if basari < 38 and b <= 100:
            out.append({"tip": "uyari", "mesaj": f"AI {rng} aralığı — başarı %{basari}, ort. %{ort} → Eşiği yükseltmeyi düşün", "renk": "#ff9900", "basari": basari, "aralik": rng})
        elif basari < 45 and b <= 80:
            out.append({"tip": "dikkat", "mesaj": f"AI {rng} aralığı — başarı %{basari} (düşük) → Bu sinyallere dikkatli ol", "renk": "#ffea00", "basari": basari, "aralik": rng})
        elif basari >= 68:
            out.append({"tip": "basarili", "mesaj": f"AI {rng} aralığı — başarı %{basari} ✅ Bu aralık güçlü performans gösteriyor", "renk": "#00ff9d", "basari": basari, "aralik": rng})
    return out
