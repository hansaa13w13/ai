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
                 ("total_pnl", 0.0), ("max_dd", 0.0), ("win_rate", 0.0),
                 ("portfolio_value", config.OTO_PORTFOLIO_VALUE),
                 ("daily_pnl", 0.0), ("daily_date", ""),
                 # Streak + EV takibi (v2)
                 ("consecutive_losses", 0), ("consecutive_wins", 0),
                 ("max_consec_losses", 0), ("expected_value", 0.0),
                 ("avg_win_pct", 5.0), ("avg_loss_pct", 3.0)):
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


def _calc_limit_entry(cur: float, atr: float, sma20: float,
                       bb_lower: float, stop: float) -> tuple[float, str]:
    """ATR çekilme, SMA20 desteği veya Bollinger alt bandı kullanarak
    piyasa fiyatının altında optimal limit giriş fiyatı hesapla.

    Döner: (limit_entry_fiyatı, kaynak_etiketi)
    """
    candidates: list[tuple[float, str]] = []

    # ATR pullback — 0.4x ATR altı
    if atr > 0:
        candidates.append((cur - atr * 0.40, "ATR×0.4"))

    # SMA20 desteği — mevcut fiyatın %2-0.5 altındaysa geçerli
    if 0 < sma20 < cur and sma20 >= cur * 0.97:
        candidates.append((sma20, "SMA20"))

    # Bollinger alt bandı — mevcut fiyatın %4-0.5 altındaysa geçerli
    if 0 < bb_lower < cur and bb_lower >= cur * 0.96:
        candidates.append((bb_lower, "BB_ALT"))

    if candidates:
        # En yakın (en yüksek) desteği seç
        best_val, best_src = max(candidates, key=lambda t: t[0])
    else:
        # Veri yoksa basit %0.8 altı
        best_val, best_src = cur * 0.992, "PCT"

    # Güvenlik sınırları: stop'tan en az %1 üstünde, max cur*0.995 (çok az altı)
    best_val = max(best_val, stop * 1.01)
    best_val = min(best_val, cur * 0.995)

    # Eğer limit cur'dan çok az farklıysa (<%0.3) direkt piyasa al
    if cur - best_val < cur * 0.003:
        return cur, "PIYASA"

    return round(best_val, 4), best_src


def oto_buy_position(pick: dict) -> bool:
    """Yeni pozisyon aç — limit emirli akıllı giriş.

    v43: Piyasa fiyatından anında alım yerine ATR/SMA20/Bollinger bazlı
    limit giriş fiyatı hesaplanır. Fiyat limite düşerse tetiklenir,
    kaçarsa iptal edilir.
    """
    code = pick.get("code", "").strip().upper()
    if not code:
        return False
    cur    = float(pick.get("guncel", 0) or 0)
    atr    = float(pick.get("atr14", 0) or pick.get("atr", 0) or 0)
    sma20  = float(pick.get("sma20", 0) or 0)
    h1     = float(pick.get("h1", 0) or 0)
    h2     = float(pick.get("h2", h1 * 1.05) or 0)
    h3     = float(pick.get("h3", h1 * 1.10) or 0)
    stop   = float(pick.get("stop", 0) or 0)
    bb_lower = float(pick.get("bbLow", 0) or 0)
    if cur <= 0 or h1 <= 0 or stop <= 0:
        oto_log(f"GEÇERSİZ FİYAT: {code} cur={cur} h1={h1} stop={stop}", "warn")
        return False

    # ── Limit giriş fiyatını hesapla ──────────────────────────────────────
    limit_entry, limit_src = _calc_limit_entry(cur, atr, sma20, bb_lower, stop)

    # Limit zaten tetiklenmiş mi? (fiyat limitte veya çok az üstünde)
    if limit_src == "PIYASA" or cur <= limit_entry * 1.003:
        status = "AÇIK"
        entry  = cur
    else:
        status = "BEKLEYEN"
        entry  = 0.0  # limit henüz dolmadı

    # ── Risk ve adet hesabı — dinamik portföy değeri ile ──────────────────
    data_tmp = oto_load()
    live_pv = float(data_tmp.get("stats", {}).get(
        "portfolio_value", config.OTO_PORTFOLIO_VALUE) or config.OTO_PORTFOLIO_VALUE)
    eff_entry      = limit_entry
    risk_pct       = config.OTO_MAX_RISK_PCT
    risk_amount    = live_pv * risk_pct
    risk_per_share = max(0.01, eff_entry - stop)
    qty            = max(1, int(risk_amount / risk_per_share))
    cost           = qty * eff_entry
    if cost > live_pv:
        qty  = max(1, int(live_pv / eff_entry))
        cost = qty * eff_entry

    rr = (h1 - eff_entry) / risk_per_share if risk_per_share > 0 else 0

    pos = {
        "code":            code,
        "status":          status,
        "entry":           entry,
        "limit_entry":     limit_entry,
        "limit_src":       limit_src,
        "guncel":          cur,
        "qty":             qty,
        "cost":            round(cost, 2),
        "h1": h1, "h2": h2, "h3": h3,
        "stop":            stop,
        "stpct":           round((eff_entry - stop) / eff_entry * 100, 2) if eff_entry > 0 else 0,
        "rr":              round(rr, 2),
        "score":           int(pick.get("score", 0) or 0),
        "hizScore":        int(pick.get("hizScore", 0) or 0),
        "signalQuality":   int(pick.get("signalQuality", 0) or 0),
        "ai_decision":     pick.get("autoThinkDecision", "NÖTR"),
        "ai_decision_live": pick.get("autoThinkDecision", "NÖTR"),
        "ai_conf":         int(pick.get("autoThinkConf", 50) or 50),
        "ai_conf_live":    int(pick.get("autoThinkConf", 50) or 50),
        "ai_reason":       pick.get("autoThinkReason", ""),
        "sektor":          pick.get("sektor") or get_sector_group(code),
        "atr14":           float(pick.get("atr14", 0) or 0),
        "bought_at":       now_str(),
        "last_check":      now_str(),
        "h1_hit": False, "h2_hit": False,
        "trail_active": False, "trail_high": 0.0,
        "pnl_pct": 0.0,
        "partial_sold": False, "partial_sold_qty": 0,
        # Real Brain giriş tahmini — sonradan performans analizi için
        "rb_prob":  round(float(pick.get("rb_prob",  0.5) or 0.5), 4),
        "rb_conf":  round(float(pick.get("rb_conf",  0.0) or 0.0), 4),
    }

    data = oto_load()
    data["positions"][code] = pos
    oto_save(data)

    if status == "AÇIK":
        oto_log(
            f"AÇILDI (piyasa): {code} qty={qty} entry={cur:.2f}₺ "
            f"stop={stop:.2f}₺ h1={h1:.2f}₺ rr={rr:.2f}", "buy")
    else:
        discount = (cur - limit_entry) / cur * 100
        oto_log(
            f"LİMİT OLUŞTURULDU: {code} qty={qty} limit={limit_entry:.2f}₺ "
            f"(piyasa:{cur:.2f}₺, -%{discount:.1f}, kaynak:{limit_src}) "
            f"stop={stop:.2f}₺ h1={h1:.2f}₺", "limit")
    return True


def oto_close_position(code: str, exit_price: float, reason: str,
                        qty_to_close: int = 0) -> float:
    """Pozisyonu kapat veya kısmen kapat; K/Z yüzdesini döndür.

    qty_to_close > 0 → sadece o kadar lot sat, pozisyon devam eder (kısmi çıkış)
    qty_to_close = 0 → tamamını kapat (eski davranış korunur)
    """
    data = oto_load()
    pos = data["positions"].get(code)
    if not pos:
        return 0.0
    entry     = float(pos.get("entry", 0))
    total_qty = int(pos.get("qty", 0))

    # Kaç lot satılacak
    if 0 < qty_to_close < total_qty:
        qty_closed = qty_to_close
        is_partial = True
    else:
        qty_closed = total_qty
        is_partial = False

    pnl_pct    = ((exit_price - entry) / entry * 100) if entry > 0 else 0.0
    pnl_amount = (exit_price - entry) * qty_closed

    record = {
        **pos,
        "exit":        exit_price,
        "exit_at":     now_str(),
        "reason":      reason + ("_partial" if is_partial else ""),
        "qty_closed":  qty_closed,
        "pnl_pct":     round(pnl_pct, 2),
        "pnl_amount":  round(pnl_amount, 2),
    }
    data["history"].insert(0, record)
    if len(data["history"]) > 500:
        data["history"] = data["history"][:500]

    stats = data["stats"]
    stats["total_trades"] += 1
    if pnl_pct > 0:
        stats["wins"] += 1
    else:
        stats["losses"] += 1
    stats["total_pnl"] = round(stats.get("total_pnl", 0) + pnl_amount, 2)
    if stats["total_trades"] > 0:
        stats["win_rate"] = round(stats["wins"] / stats["total_trades"] * 100, 1)

    # Portföy değerini gerçekleşen K/Z ile güncelle
    pv = float(stats.get("portfolio_value", config.OTO_PORTFOLIO_VALUE) or config.OTO_PORTFOLIO_VALUE)
    stats["portfolio_value"] = round(pv + pnl_amount, 2)

    # Günlük K/Z takibi (drawdown sigortası için)
    today = now_str("%Y-%m-%d")
    if stats.get("daily_date") != today:
        stats["daily_date"] = today
        stats["daily_pnl"]  = 0.0
    stats["daily_pnl"] = round(float(stats.get("daily_pnl", 0)) + pnl_amount, 2)

    # ── Streak + Expected Value takibi (tam kapatma) ─────────────────────────
    if not is_partial:
        if pnl_pct >= 0:
            stats["consecutive_wins"]   = int(stats.get("consecutive_wins",   0)) + 1
            stats["consecutive_losses"] = 0
        else:
            stats["consecutive_losses"] = int(stats.get("consecutive_losses", 0)) + 1
            stats["consecutive_wins"]   = 0
        stats["max_consec_losses"] = max(
            int(stats.get("max_consec_losses", 0)),
            int(stats.get("consecutive_losses", 0)),
        )
        # Expected Value = WinRate × AvgWin − LossRate × AvgLoss (son 30 işlem)
        recent_h = data["history"][:30]
        _w_pcts = [float(t.get("pnl_pct", 0)) for t in recent_h
                   if float(t.get("pnl_pct", 0)) >= 0
                   and not str(t.get("reason", "")).endswith("_partial")]
        _l_pcts = [abs(float(t.get("pnl_pct", 0))) for t in recent_h
                   if float(t.get("pnl_pct", 0)) < 0
                   and not str(t.get("reason", "")).endswith("_partial")]
        avg_w = round(sum(_w_pcts) / len(_w_pcts), 2) if _w_pcts else 5.0
        avg_l = round(sum(_l_pcts) / len(_l_pcts), 2) if _l_pcts else 3.0
        wr_ev  = stats["wins"] / stats["total_trades"] if stats["total_trades"] > 0 else 0.5
        stats["avg_win_pct"]    = avg_w
        stats["avg_loss_pct"]   = avg_l
        stats["expected_value"] = round(wr_ev * avg_w - (1 - wr_ev) * avg_l, 2)

    if is_partial:
        # Pozisyon devam eder — sadece lot sayısı düşürülür
        remaining = total_qty - qty_closed
        pos["qty"]              = remaining
        pos["cost"]             = round(remaining * float(pos.get("limit_entry", entry) or entry), 2)
        pos["partial_sold"]     = True
        pos["partial_sold_qty"] = int(pos.get("partial_sold_qty", 0)) + qty_closed
        pos["partial_sold_at"]  = now_str()
        pos["partial_sold_px"]  = exit_price
        data["positions"][code] = pos
    else:
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
        brain["stats"]["recent_wins"]    = r_wins
        brain["stats"]["recent_total"]   = r_total
        brain["stats"]["avg_win_pct"]    = round(sum_win / cnt_win,  2) if cnt_win  > 0 else 5.0
        brain["stats"]["avg_loss_pct"]   = round(sum_loss / cnt_loss, 2) if cnt_loss > 0 else 3.0
        brain["stats"]["stats_updated"]  = now_str()
        brain_save(brain)
    except Exception:
        pass

    return pnl_pct


def oto_fetch_live_price(code: str) -> float:
    from .api_client import fetch_live_price
    return fetch_live_price(code)
