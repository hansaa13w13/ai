"""Sinyal geçmişi — PHP logSignalHistory ile birebir uyumlu liste şeması.

PHP cache dosyası ($SIGNAL_HISTORY_FILE) bir JSON listesidir; her eleman bir
pick snapshot'ı içerir (code, date, price, aiScore, hedefler, result5/10/20...).
update_signal_outcomes ve ai_performance_stats bu liste şemasını okur.
"""
from __future__ import annotations
import datetime
from typing import Any
from . import config
from .utils import load_json, save_json, now_str


def _load_list() -> list[dict]:
    raw = load_json(config.SIGNAL_HISTORY_FILE, [])
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "signals" in raw:
        return []
    return []


def _save_list(data: list[dict]) -> None:
    save_json(config.SIGNAL_HISTORY_FILE, data)


def log_signal(pick: dict, market_mode: str = "bull") -> bool:
    """PHP logSignalHistory($pick) birebir port.

    Aynı kod için günde bir kez kayıt yapar (dedup).
    Liste başına eklenir, en fazla 600 kayıt tutar.
    """
    history = _load_list()
    code = (pick.get("code") or "").strip()
    if not code:
        return False
    today = datetime.date.today().isoformat()
    for h in history:
        if (h.get("code") or "") == code and str(h.get("date", "")).startswith(today):
            return False  # zaten bugün loglanmış

    forms = pick.get("formations") or []
    targets = pick.get("targets") or {}
    entry = {
        "code":       code,
        "date":       now_str(),
        "price":      float(pick.get("guncel", 0) or 0),
        "aiScore":    int(pick.get("aiScore", 0) or 0),
        "alPuani":    int(pick.get("alPuan", 0) or 0),
        "squality":   int(pick.get("signalQuality", 0) or 0),
        "rsi":        float(pick.get("rsi", 50) or 50),
        "stochK":     float(pick.get("stochK", 50) or 50),
        "volRatio":   float(pick.get("volRatio", 1.0) or 1.0),
        "pos52wk":    float(pick.get("pos52wk", 50) or 50),
        "trend":      pick.get("trend", "Notr"),
        "sektor":     pick.get("sektor", "genel"),
        "marketCap":  float(pick.get("marketCap", 0) or 0),
        "hizScore":   int(pick.get("hizScore", 0) or 0),
        "formations":     [f.get("ad", "") for f in forms],
        "formation_tips": [f.get("tip", "") for f in forms],
        "h1":         float(targets.get("sell1", 0) or 0),
        "h3":         float(targets.get("sell3", 0) or 0),
        "stop":       float(targets.get("stop", 0) or 0),
        "marketMode": market_mode,
        "result5":    None,
        "result10":   None,
        "result20":   None,
    }
    history.insert(0, entry)
    if len(history) > 600:
        history = history[:600]
    _save_list(history)
    return True


def log_top_picks(picks: list[dict], market_mode: str = "bull",
                  top_n: int = 20, min_ai_score: int = 100) -> int:
    """Tarama sonrası top picks'i toplu logla."""
    n = 0
    for p in picks[:top_n]:
        if int(p.get("aiScore", 0) or 0) < min_ai_score:
            continue
        if log_signal(p, market_mode):
            n += 1
    return n


# ── Geriye dönük uyumluluk: eski record_signal/get_recent API'si ────────────
def load_history() -> list[dict]:
    return _load_list()


def save_history(data: list[dict]) -> None:
    _save_list(data if isinstance(data, list) else [])


def record_signal(code: str, signal_type: str, score: int, reason: str = "") -> None:
    """Hafif kayıt (dedup eski API)."""
    log_signal({
        "code": code, "guncel": 0, "aiScore": score,
        "formations": [{"ad": signal_type, "tip": "info"}],
        "trend": reason or "Notr",
    })


def get_recent(code: str, hours: int = 24) -> list[dict]:
    out = []
    cutoff = datetime.datetime.now().timestamp() - hours * 3600
    for s in _load_list():
        if s.get("code") != code:
            continue
        try:
            ts = datetime.datetime.strptime(s["date"], "%Y-%m-%d %H:%M:%S").timestamp()
            if ts >= cutoff:
                out.append(s)
        except (ValueError, KeyError):
            continue
    return out
