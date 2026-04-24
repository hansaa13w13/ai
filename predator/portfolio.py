"""Otomatik portföy yönetimi — pozisyon aç/kapat/yükle/kaydet."""
from __future__ import annotations
import time
import threading
from contextlib import contextmanager
from typing import Any, Iterator
from . import config
from .utils import load_json, save_json, now_str
from .sectors import get_sector_group

# v37.9: Pozisyon dosyası RMW yarış durumu kilidi.
# Engine multi-position iter ederken oto_close_position kendi load/save yapardı —
# engine'in elindeki bayat dict, sıradaki yazışta kapanan pozisyonu diriltebiliyordu.
_OTO_RMW_LOCK = threading.RLock()


@contextmanager
def oto_lock() -> Iterator[None]:
    """`with oto_lock(): oto = oto_load(); ...; oto_save(oto)` deseni için
    içiçe-güvenli (reentrant) kilit context manager.
    """
    _OTO_RMW_LOCK.acquire()
    try:
        yield
    finally:
        _OTO_RMW_LOCK.release()


def oto_load() -> dict:
    data = load_json(config.OTO_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("positions", {})
    data.setdefault("history", [])
    stats = data.setdefault("stats", {})
    if not isinstance(stats, dict):
        stats = {}
        data["stats"] = stats
    # Eski PHP anahtarlarını yenilerine taşı (geri-uyum)
    legacy_map = {"toplam": "total_trades", "kar": "wins", "zarar": "losses",
                  "toplam_pct": "total_pnl"}
    for old_k, new_k in legacy_map.items():
        if old_k in stats and new_k not in stats:
            stats[new_k] = stats[old_k]
    # Beklenen tüm sub-key'lerin var olduğundan emin ol
    for k, v in (("total_trades", 0), ("wins", 0), ("losses", 0),
                 ("total_pnl", 0.0), ("max_dd", 0.0), ("win_rate", 0.0)):
        stats.setdefault(k, v)
    data.setdefault("created_at", now_str())
    return data


def oto_save(data: dict) -> None:
    data["last_updated"] = now_str()
    save_json(config.OTO_FILE, data)


def oto_log(msg: str, kind: str = "info") -> None:
    logs = load_json(config.OTO_LOG_FILE, [])
    if not isinstance(logs, list):
        logs = []
    logs.insert(0, {"time": now_str("%H:%M:%S"), "date": now_str("%Y-%m-%d"),
                    "msg": msg, "type": kind})
    if len(logs) > 500:
        logs = logs[:500]
    save_json(config.OTO_LOG_FILE, logs)


def oto_buy_position(pick: dict) -> bool:
    """Yeni pozisyon aç. PHP otoBuyPosition karşılığı."""
    code = pick.get("code", "").strip().upper()
    if not code:
        return False
    cur = float(pick.get("guncel", 0) or 0)
    h1 = float(pick.get("h1", 0) or 0)
    h2 = float(pick.get("h2", h1 * 1.05) or 0)
    h3 = float(pick.get("h3", h1 * 1.10) or 0)
    stop = float(pick.get("stop", 0) or 0)
    if cur <= 0 or h1 <= 0 or stop <= 0:
        oto_log(f"GEÇERSİZ FİYAT: {code} cur={cur} h1={h1} stop={stop}", "warn")
        return False

    risk_pct = config.OTO_MAX_RISK_PCT
    risk_amount = config.OTO_PORTFOLIO_VALUE * risk_pct
    risk_per_share = max(0.01, cur - stop)
    qty = max(1, int(risk_amount / risk_per_share))
    cost = qty * cur
    if cost > config.OTO_PORTFOLIO_VALUE:
        qty = max(1, int(config.OTO_PORTFOLIO_VALUE / cur))
        cost = qty * cur

    rr = (h1 - cur) / risk_per_share if risk_per_share > 0 else 0

    pos = {
        "code": code,
        "entry": cur,
        "guncel": cur,
        "qty": qty,
        "cost": round(cost, 2),
        "h1": h1, "h2": h2, "h3": h3,
        "stop": stop,
        "stpct": round((cur - stop) / cur * 100, 2) if cur > 0 else 0,
        "rr": round(rr, 2),
        "score": int(pick.get("score", 0) or 0),
        "hizScore": int(pick.get("hizScore", 0) or 0),
        "signalQuality": int(pick.get("signalQuality", 0) or 0),
        "ai_decision": pick.get("autoThinkDecision", "NÖTR"),
        "ai_decision_live": pick.get("autoThinkDecision", "NÖTR"),
        "ai_conf": int(pick.get("autoThinkConf", 50) or 50),
        "ai_conf_live": int(pick.get("autoThinkConf", 50) or 50),
        "ai_reason": pick.get("autoThinkReason", ""),
        "sektor": pick.get("sektor") or get_sector_group(code),
        "atr14": float(pick.get("atr14", 0) or 0),
        "bought_at": now_str(),
        "last_check": now_str(),
        "h1_hit": False, "h2_hit": False,
        "trail_active": False, "trail_high": cur,
        "pnl_pct": 0.0,
    }

    data = oto_load()
    data["positions"][code] = pos
    oto_save(data)
    oto_log(f"AÇILDI: {code} qty={qty} entry={cur:.2f}₺ stop={stop:.2f}₺ h1={h1:.2f}₺ rr={rr:.2f}", "buy")
    return True


def oto_close_position(code: str, exit_price: float, reason: str) -> float:
    """Pozisyonu kapat ve K/Z yüzdesini döndür."""
    data = oto_load()
    pos = data["positions"].get(code)
    if not pos:
        return 0.0
    entry = float(pos.get("entry", 0))
    qty = int(pos.get("qty", 0))
    pnl_pct = ((exit_price - entry) / entry * 100) if entry > 0 else 0.0
    pnl_amount = (exit_price - entry) * qty

    record = {
        **pos,
        "exit": exit_price,
        "exit_at": now_str(),
        "reason": reason,
        "pnl_pct": round(pnl_pct, 2),
        "pnl_amount": round(pnl_amount, 2),
    }
    data["history"].insert(0, record)
    if len(data["history"]) > 500:
        data["history"] = data["history"][:500]

    stats = data["stats"]
    stats["total_trades"] += 1
    if pnl_pct > 0: stats["wins"] += 1
    else: stats["losses"] += 1
    stats["total_pnl"] = round(stats.get("total_pnl", 0) + pnl_amount, 2)
    if stats["total_trades"] > 0:
        stats["win_rate"] = round(stats["wins"] / stats["total_trades"] * 100, 1)

    del data["positions"][code]
    oto_save(data)

    # Brain istatistiklerini güncelle — Kelly Criterion için gerçek işlem verileri
    try:
        from .brain import brain_load, brain_save
        brain = brain_load()
        recent = data["history"][:20]
        r_wins = r_total = 0
        sum_win = sum_loss = cnt_win = cnt_loss = 0
        for t in recent:
            tp = float(t.get("pnl_pct", 0) or 0)
            r_total += 1
            if tp >= 0:
                r_wins += 1; sum_win += tp; cnt_win += 1
            else:
                sum_loss += abs(tp); cnt_loss += 1
        if not isinstance(brain.get("stats"), dict):
            brain["stats"] = {}
        brain["stats"]["recent_wins"] = r_wins
        brain["stats"]["recent_total"] = r_total
        brain["stats"]["avg_win_pct"] = round(sum_win / cnt_win, 2) if cnt_win > 0 else 5.0
        brain["stats"]["avg_loss_pct"] = round(sum_loss / cnt_loss, 2) if cnt_loss > 0 else 3.0
        brain["stats"]["stats_updated"] = now_str()
        brain_save(brain)
    except Exception:
        pass

    return pnl_pct


def oto_fetch_live_price(code: str) -> float:
    from .api_client import fetch_live_price
    return fetch_live_price(code)
