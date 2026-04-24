"""BIST PREDATOR v35 — Flask uygulaması.

Tüm `?action=` uç noktaları PHP sürümüyle uyumludur.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import time
import threading
import warnings
from flask import Flask, request, jsonify, render_template, send_from_directory

# SSL uyarılarını sustur
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from predator import config
from predator.utils import load_json, save_json, now_str
from predator.scan import run_bist_scan, run_bist_scan_two_phase
from predator.engine import oto_engine_multi
from predator.brain import brain_load, neural_ensemble_predict
from predator.neural import neural_get_stats
from predator.portfolio import oto_load, oto_save, oto_close_position, oto_log, oto_buy_position
from predator.market import get_market_mode
from predator.telegram import send_tg
from predator.api_client import fetch_live_price
from predator import extras
import re

app = Flask(__name__, static_folder="static", template_folder="templates")


def _save_port():
    """Replit proxy için aktif portu yaz."""
    try:
        port = os.environ.get("PORT") or "5000"
        config.SERVER_PORT_FILE.write_text(str(port))
    except OSError:
        pass


_save_port()


# ── Daemon otomatik başlatma ──────────────────────────────────────────────────
_DAEMON_LOCK_FILE = Path("/tmp") / "predator_daemon.lock"
_daemon_started = False


def _start_daemon_thread():
    """Oto-pilot daemon'ı arka planda başlat (tek sefer)."""
    global _daemon_started
    if _daemon_started:
        return
    # Çoklu worker / reload senaryosunda dosya kilidiyle ikinci başlatmayı engelle
    try:
        my_pid = os.getpid()
        if _DAEMON_LOCK_FILE.exists():
            try:
                old_pid = int(_DAEMON_LOCK_FILE.read_text().strip() or "0")
                if old_pid > 0 and old_pid != my_pid:
                    try:
                        os.kill(old_pid, 0)  # canlı mı?
                        print(f"[PREDATOR] Daemon zaten çalışıyor (pid={old_pid}); bu süreçte başlatılmadı.", flush=True)
                        _daemon_started = True
                        return
                    except OSError:
                        pass  # eski pid ölmüş, devam et
            except Exception:
                pass
        _DAEMON_LOCK_FILE.write_text(str(my_pid))
    except Exception as e:
        print(f"[PREDATOR] Daemon kilit hatası: {e}", flush=True)

    try:
        from predator.daemon import run_daemon
        t = threading.Thread(target=run_daemon, daemon=True, name="predator-daemon")
        t.start()
        _daemon_started = True
        print(f"[PREDATOR] Oto-pilot daemon arka planda başlatıldı (pid={os.getpid()}). 7/24 modda.", flush=True)
    except Exception as e:
        print(f"[PREDATOR] Daemon başlatma hatası: {e}", flush=True)


# Sunucu tam ayağa kalktıktan sonra daemon başlat
threading.Timer(5.0, _start_daemon_thread).start()


# ── UI ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/static/<path:p>")
def static_files(p):
    return send_from_directory(app.static_folder, p)


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


# ── JSON yardımcı ─────────────────────────────────────────────────────────
def _json(data, status: int = 200):
    resp = jsonify(data)
    resp.status_code = status
    return resp


# ── ?action=... router ────────────────────────────────────────────────────
@app.route("/action", methods=["GET", "POST"])
@app.route("/api/<action>", methods=["GET", "POST"])
def api_action(action: str | None = None):
    action = action or (request.values.get("action") or "").strip()
    handler = _ACTIONS.get(action)
    if not handler:
        return _json({"error": "unknown_action", "action": action}, 404)
    try:
        return handler()
    except Exception as e:
        return _json({"error": "internal", "msg": str(e)}, 500)


# ── Tek action router (?action=...) ───────────────────────────────────────
@app.before_request
def _action_dispatch():
    """PHP'deki `index.php?action=...` uyumluluğu için kök URL üzerinde dispatch."""
    if request.path == "/" and request.values.get("action"):
        act = request.values.get("action").strip()
        h = _ACTIONS.get(act)
        if h:
            try:
                return h()
            except Exception as e:
                return _json({"error": "internal", "msg": str(e)}, 500)


# ── Action implementasyonları ─────────────────────────────────────────────
def act_ping():
    return _json({"status": "ok", "time": now_str(), "version": "35.0-py",
                  "market_open": get_market_mode()})


def _scan_lock_busy() -> bool:
    """Lock dosyası var ve TTL süresi dolmadıysa True. Eski/bayat lock'u temizler."""
    p = config.SCAN_LOCK_FILE
    if not p.exists():
        return False
    try:
        age = time.time() - p.stat().st_mtime
        if age >= config.SCAN_LOCK_TTL:
            try: p.unlink()
            except OSError: pass
            return False
        return True
    except OSError:
        return False


def act_bist_scan():
    """BIST tarama — varsayılan: PHP runBISTScanTwoPhase ile birebir uyumlu
    iki fazlı tarama. `legacy=1` ile eski tek-fazlı taramaya geçilebilir.
    """
    legacy   = request.values.get("legacy") == "1"
    parallel = int(request.values.get("parallel", 20))
    limit    = int(request.values.get("limit", 0))
    target   = run_bist_scan if legacy else run_bist_scan_two_phase
    kwargs   = {} if legacy else {"parallel": parallel, "limit": limit}
    if request.values.get("_async") == "1" or request.values.get("_cron"):
        if _scan_lock_busy():
            return _json({"status": "already_running"})
        threading.Thread(target=target, kwargs=kwargs, daemon=True).start()
        return _json({"status": "started", "mode": "legacy" if legacy else "two_phase"})
    res = target(**kwargs)
    return _json(res)


def act_bist_scan_two_phase():
    """Açık iki-fazlı tarama uç noktası (varsayılan da artık iki-fazlı)."""
    parallel = int(request.values.get("parallel", 20))
    limit    = int(request.values.get("limit", 0))
    if request.values.get("_async") == "1" or request.values.get("_cron"):
        if _scan_lock_busy():
            return _json({"status": "already_running"})
        threading.Thread(target=run_bist_scan_two_phase,
                         kwargs={"parallel": parallel, "limit": limit},
                         daemon=True).start()
        return _json({"status": "started", "mode": "two_phase"})
    res = run_bist_scan_two_phase(parallel=parallel, limit=limit)
    return _json(res)


def act_scan_progress():
    if config.SCAN_PROGRESS_FILE.exists():
        try:
            data = json.loads(config.SCAN_PROGRESS_FILE.read_text())
            # Bayat 'running' durumunu otomatik temizle (90sn güncellenmemişse)
            if isinstance(data, dict) and data.get("status") == "running":
                ts = int(data.get("ts", 0))
                if ts and (time.time() - ts) > 90:
                    data = {"status": "idle", "pct": 0, "ts": int(time.time()), "stale_cleared": True}
                    try:
                        config.SCAN_PROGRESS_FILE.write_text(json.dumps(data))
                    except OSError:
                        pass
            return _json(data)
        except (OSError, json.JSONDecodeError):
            pass
    return _json({"status": "idle", "pct": 0})


def act_top_picks():
    cache = load_json(config.ALLSTOCKS_CACHE, {})
    # v37.8: Taranan TÜM hisseler (KAÇIN dahil) skor sırasına göre dönsün.
    picks = cache.get("allStocks") or cache.get("topPicks") or []
    if not isinstance(picks, list):
        picks = []
    picks = sorted(
        picks,
        key=lambda s: float(s.get("score", s.get("predatorScore", s.get("aiScore", 0))) or 0),
        reverse=True,
    )
    n = int(request.values.get("n", 0) or 0)
    sliced = picks if n <= 0 else picks[:n]
    return _json({
        "picks": sliced,
        "marketMode": cache.get("marketMode", "bull"),
        "updated": cache.get("updated", ""),
        "scanned": cache.get("scanned", 0),
        "ok": cache.get("successful", 0),
        "opportunities": cache.get("opportunities", 0),
        "total": len(picks),
    })


def act_oto_status():
    oto = oto_load()
    return _json({
        "positions": oto["positions"],
        "history": oto["history"][:25],
        "stats": oto["stats"],
        "last_updated": oto.get("last_updated"),
    })


def act_oto_log():
    return _json({"log": load_json(config.OTO_LOG_FILE, [])[:200]})


def act_oto_engine_run():
    cache = load_json(config.ALLSTOCKS_CACHE, {})
    picks = cache.get("topPicks", []) if isinstance(cache, dict) else []
    if not picks:
        return _json({"status": "no_picks"})
    oto_engine_multi(picks)
    return _json({"status": "done", "considered": len(picks)})


def act_oto_close():
    code = (request.values.get("code") or "").strip().upper()
    if not code:
        return _json({"error": "missing_code"}, 400)
    oto = oto_load()
    pos = oto["positions"].get(code)
    if not pos:
        return _json({"error": "no_position"}, 404)
    live = float(request.values.get("price", 0) or 0)
    if live <= 0:
        live = fetch_live_price(code) or float(pos.get("guncel", 0) or 0)
    pnl = oto_close_position(code, live, request.values.get("reason", "manuel"))
    oto_log(f"MANUEL KAPATMA: {code} @ {live:.2f}₺ K/Z:{pnl:.2f}%", "manual")
    from predator.telegram import send_oto_tg
    from predator.utils import tg_footer
    send_oto_tg(f"💼 *OTO — MANUEL SATIŞ*\n*{code}* kapatıldı\n💰 Fiyat: {live:.2f}₺\nK/Z: *{('+' if pnl >= 0 else '')}{pnl:.2f}%*{tg_footer()}")
    return _json({"status": "closed", "code": code, "exit": live, "pnl_pct": pnl})


def act_oto_close_all():
    """Tüm açık pozisyonları manuel kapat."""
    oto = oto_load()
    codes = list(oto["positions"].keys())
    if not codes:
        return _json({"status": "no_positions"})
    results = []
    for code in codes:
        pos = oto_load()["positions"].get(code)
        if not pos:
            continue
        price = fetch_live_price(code)
        if price <= 0:
            price = float(pos.get("guncel", pos.get("entry", 0)) or 0)
        pnl = oto_close_position(code, price, "manuel_hepsi")
        oto_log(f"MANUEL TÜMÜ KAPAT: {code} @ {price:.2f}₺ K/Z:{pnl:.2f}%", "sell")
        results.append({"code": code, "price": price, "pnl_pct": pnl})
    from predator.telegram import send_oto_tg
    from predator.utils import tg_footer
    send_oto_tg(f"💼 *OTO — TÜM POZİSYONLAR KAPATILDI*\n{len(results)} pozisyon manuel kapatıldı{tg_footer()}")
    return _json({"status": "done", "closed": results})


def act_oto_prices():
    """Tüm açık pozisyonlar için canlı fiyat al."""
    oto = oto_load()
    updated = {}
    for code, pos in oto["positions"].items():
        price = fetch_live_price(code)
        if price <= 0:
            price = float(pos.get("guncel", 0) or 0)
        entry = float(pos.get("entry", 0))
        pnl_pct = round((price - entry) / entry * 100, 2) if entry > 0 else 0.0
        h1 = float(pos.get("h1", 0) or 0)
        h2 = float(pos.get("h2", 0) or 0)
        h3 = float(pos.get("h3", 0) or 0)
        stop = float(pos.get("stop", 0) or 0)
        alert = None
        if h3 > 0 and price >= h3: alert = "h3"
        elif h2 > 0 and price >= h2 and not pos.get("h2_hit"): alert = "h2"
        elif h1 > 0 and price >= h1 and not pos.get("h1_hit"): alert = "h1"
        elif stop > 0 and price <= stop: alert = "stop"
        h1_bar = min(100, max(0, round((price - entry) / (h1 - entry) * 100))) if (h1 > entry and h1 > 0) else 0
        if price > 0:
            pos["guncel"] = price
            pos["pnl_pct"] = pnl_pct
            pos["last_check"] = now_str()
        updated[code] = {
            "price": price, "pnl_pct": pnl_pct,
            "h1_hit": bool(pos.get("h1_hit")), "h2_hit": bool(pos.get("h2_hit")),
            "stop": stop, "h1bar": h1_bar, "alert": alert, "last_chk": now_str("%H:%M:%S"),
        }
    oto_save(oto)
    return _json({"ok": True, "positions": updated, "ts": now_str("%H:%M:%S")})


def act_oto_manual_add():
    """Manuel hisse ekle."""
    body = request.get_json(silent=True) or {}
    code = (body.get("code") or request.values.get("code") or "").strip().upper()
    if not code:
        return _json({"error": "missing_code"}, 400)
    cache = load_json(config.ALLSTOCKS_CACHE, {})
    picks = cache.get("topPicks", []) if isinstance(cache, dict) else []
    pick = next((p for p in picks if p.get("code") == code), None)
    if not pick:
        return _json({"error": "stock_not_in_cache", "code": code}, 404)
    ok = oto_buy_position(pick)
    if ok:
        from predator.telegram import send_oto_tg
        from predator.utils import tg_footer
        send_oto_tg(f"✅ *OTO — MANUEL EKLEME*\n*{code}* portföye eklendi\n💰 @ {float(pick.get('guncel', 0)):.2f}₺{tg_footer()}")
    return _json({"status": "added" if ok else "failed", "code": code})


def act_oto_tg_summary():
    """Manuel Telegram portföy özeti gönder."""
    oto = oto_load()
    if not oto["positions"]:
        return _json({"status": "no_positions"})
    from predator.telegram import send_oto_tg
    from predator.utils import tg_footer
    msg = f"📊 *OTO PORTFÖY ÖZET*\n{len(oto['positions'])}/{config.OTO_MAX_POSITIONS} POZİSYON\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    total_pnl = 0.0
    for code, pos in oto["positions"].items():
        pnl = float(pos.get("pnl_pct", 0) or 0)
        total_pnl += pnl
        sign = "+" if pnl >= 0 else ""
        h1_hit = "✅" if pos.get("h1_hit") else ""
        msg += f"*{code}* {sign}{pnl:.1f}% {h1_hit}  H1:{float(pos.get('h1', 0)):.2f}₺\n"
    avg = round(total_pnl / len(oto["positions"]), 2)
    stats = oto.get("stats", {})
    t = stats.get("total_trades", 0)
    wr = round(stats.get("wins", 0) / t * 100, 1) if t > 0 else 0
    msg += f"\nOrt. K/Z: *{('+' if avg >= 0 else '')}{avg}%*\n"
    msg += f"Tarihsel: {t} işlem · %{wr} kazanma{tg_footer()}"
    sent = send_oto_tg(msg)
    return _json({"status": "sent" if sent else "dedup_skip"})


def act_daily_summary():
    """Manuel olarak günlük özet gönder. force=1 ise gün-içi tekrar göndermeye izin verir."""
    from predator.tg_listener import send_daily_summary, _build_daily_summary
    force = (request.values.get("force", "0") in ("1", "true", "yes"))
    preview = (request.values.get("preview", "0") in ("1", "true", "yes"))
    if preview:
        return _json({"ok": True, "preview": _build_daily_summary()})
    sent = send_daily_summary(force=force)
    return _json({"ok": True, "status": "sent" if sent else "skipped_already_sent_today"})


def act_pin_board_now():
    """Pinned canlı portföy panosunu hemen güncelle/oluştur."""
    from predator.tg_listener import _ensure_pinned_board, _build_position_board
    preview = (request.values.get("preview", "0") in ("1", "true", "yes"))
    if preview:
        return _json({"ok": True, "preview": _build_position_board()})
    try:
        _ensure_pinned_board(config.TG_CHAT_ID)
        return _json({"ok": True, "status": "pinned_or_updated"})
    except Exception as e:
        return _json({"ok": False, "error": str(e)}, 500)


def act_tg_test_report():
    """Belirtilen kod için T-komutu raporunun aynısını üretir (Telegram'a göndermeden gösterir)."""
    code = _get_code()
    if not code:
        return _json({"ok": False, "error": "code gerekli"}, 400)
    from predator.tg_listener import _build_stock_report
    return _json({"ok": True, "code": code, "report": _build_stock_report(code)})


def act_neural_stats():
    brain = brain_load()
    return _json({
        "alpha": neural_get_stats(brain.get("neural_net")),
        "beta":  neural_get_stats(brain.get("neural_net_beta")),
        "gamma": neural_get_stats(brain.get("neural_net_gamma")),
        "snapshots": sum(len(v) for v in brain.get("snapshots", {}).values()),
        "stocks_tracked": len(brain.get("snapshots", {})),
        "prediction_accuracy": brain.get("prediction_accuracy", {}),
    })


def act_neural_predict():
    code = (request.values.get("code") or "").strip().upper()
    if not code:
        return _json({"error": "missing_code"}, 400)
    cache = load_json(config.ALLSTOCKS_CACHE, {})
    picks = cache.get("topPicks", []) if isinstance(cache, dict) else []
    pick = next((p for p in picks if p.get("code") == code), None)
    if not pick:
        return _json({"error": "stock_not_in_cache"}, 404)
    brain = brain_load()
    return _json(neural_ensemble_predict(brain, pick))


def act_market_mode():
    return _json({"mode": get_market_mode()})


def act_send_tg():
    msg = request.values.get("msg", "")
    if not msg:
        return _json({"error": "missing_msg"}, 400)
    return _json({"sent": send_tg(msg)})


def act_daemon_status():
    st = load_json(config.AUTO_STATUS_FILE, {}) or {}
    if not isinstance(st, dict):
        st = {}
    log = load_json(config.AUTO_LOG_FILE, [])
    if not isinstance(log, list):
        log = []
    # Daemon canlı mı? Son status güncellemesi 60sn içindeyse "alive" kabul et.
    ts = int(st.get("ts", 0) or 0)
    alive = bool(ts) and (time.time() - ts) < 60
    out = dict(st)  # scan_count, next_scan_in, last_scan, msg, market_open, ... düzleştirilmiş
    out["alive"] = alive
    out["status"] = st
    out["state"] = st.get("status", "unknown")
    out["log"] = log[:30]
    return _json(out)


_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")
_CODE_RE_LOOSE = re.compile(r"^[A-Z0-9]{2,7}$")


def _get_code(loose: bool = False) -> str:
    code = (request.values.get("code") or "").strip().upper()
    if not code:
        return ""
    rx = _CODE_RE_LOOSE if loose else _CODE_RE
    return code if rx.match(code) else ""


def _allstocks() -> dict:
    return load_json(config.ALLSTOCKS_CACHE, {}) or {}


def _stock_from_cache(code: str) -> dict | None:
    cache = _allstocks()
    code = (code or "").upper()
    for key in ("topPicks", "stocks", "allStocks"):
        for s in (cache.get(key) or []):
            if (s.get("code") or "").upper() == code:
                return s
    return None


# ── chart_data ────────────────────────────────────────────────────────────
def act_chart_data():
    code = _get_code()
    if not code:
        return _json({"ok": False, "err": "Geçersiz sembol"})
    stock_info = _stock_from_cache(code)
    oto = oto_load()
    pos = oto["positions"].get(code)
    candles = extras.fetch_chart2_candles(code, periyot="G", bar=220)
    out_candles = [{"o": round(c["Open"], 4), "h": round(c["High"], 4),
                    "l": round(c["Low"], 4),  "c": round(c["Close"], 4),
                    "v": round(c["Vol"]),     "t": c["Date"]} for c in candles[-120:]]
    tgts = {"h1": 0, "h2": 0, "h3": 0, "stop": 0, "entry": 0}
    if pos:
        tgts.update({"entry": float(pos.get("entry", 0) or 0),
                     "h1": float(pos.get("h1", 0) or 0),
                     "h2": float(pos.get("h2", 0) or 0),
                     "h3": float(pos.get("h3", 0) or 0),
                     "stop": float(pos.get("stop", 0) or 0)})
    elif stock_info:
        t = stock_info.get("targets", {}) or {}
        tgts["h1"]   = float(t.get("sell1", 0) or 0)
        tgts["h2"]   = float(t.get("sell2", 0) or 0)
        tgts["h3"]   = float(t.get("sell3", 0) or 0)
        tgts["stop"] = float(t.get("stop", 0) or 0)
    sig_def = {"tip": "NOTR", "renk": "#888888", "emoji": "➡️"}
    return _json({
        "ok": True, "code": code,
        "name": (stock_info or pos or {}).get("name", code) if (stock_info or pos) else code,
        "candles": out_candles, "targets": tgts,
        "formations": (stock_info or pos or {}).get("formations", []) if (stock_info or pos) else [],
        "aiScore": (stock_info or {}).get("aiScore", (pos or {}).get("score", 0)),
        "rsi": round(float((stock_info or {}).get("rsi", 50) or 50), 1) if stock_info else 50,
        "trend": (stock_info or {}).get("trend", "Notr"),
        "signalTipi": (stock_info or {}).get("signalTipi", sig_def),
        "sektorHam": (stock_info or {}).get("sektorHam", ""),
        "inPortfolio": pos is not None,
        "pnl": round(float(pos.get("pnl_pct", 0) or 0), 2) if pos else None,
    })


def act_brain_stats():
    return _json({"ok": True, "stats": extras.brain_get_stats()})


def act_backtest_stats():
    return _json({"ok": True, "stats": extras.get_backtest_stats()})


def act_brain_similar():
    code = _get_code()
    if not code:
        return _json({"ok": False, "err": "Geçersiz sembol"})
    stock = _stock_from_cache(code) or {}
    similar = extras.brain_find_similar_history(code, stock) if stock else []
    return _json({"ok": True, "code": code, "similar": similar})


def act_chart_compare():
    cache = _allstocks()
    all_st = cache.get("stocks", []) or cache.get("topPicks", []) or []
    if not all_st:
        return _json({"ok": False, "err": "Cache bos"})
    if request.values.get("refresh"):
        for fn in ("predator_compare_cache.json", "predator_price_compare_cache.json"):
            p = config.CACHE_DIR / fn
            if p.exists():
                try: p.unlink()
                except OSError: pass
    return _json({"ok": True,
                  "data": extras.find_similar_movers(all_st),
                  "price_data": extras.find_price_only_movers(all_st)})


def act_haber_firma():
    code = _get_code(loose=True)
    if not code:
        return _json({"ok": False, "err": "Geçersiz kod"})
    adet = max(3, min(30, int(request.values.get("adet", 5) or 5)))
    return _json(extras.fetch_news(code, adet))


def act_gundem():
    return _json(extras.fetch_gundem())


def act_bilanco_detay():
    code = _get_code(loose=True)
    if not code:
        return _json({"ok": False, "err": "Geçersiz kod"})
    return _json(extras.fetch_bilanco(code))


def act_smclevels():
    code = _get_code()
    if not code:
        return _json({"ok": False, "err": "Geçersiz sembol"})
    cache_file = config.CACHE_DIR / f"predator_smc_{code}.json"
    cached = extras._read_json_cache(cache_file, 900)
    if cached:
        return _json(cached)
    # Önbellek yok → tek seferlik anında hesapla (daemon henüz ısıtmamış olabilir)
    try:
        out = extras.compute_smc_pack(code, _stock_from_cache(code))
        if out and out.get("ok"):
            return _json(out)
    except Exception as e:
        return _json({"ok": False, "err": f"hesaplama hatası: {e}"})
    candles = extras.fetch_chart2_candles(code, periyot="G", bar=150)
    if len(candles) < 20:
        return _json({"ok": False, "err": "Veri yetersiz"})
    smc_r  = extras.calculate_smc(candles, 100)
    vp_r   = extras.calculate_volume_profile(candles, 40)
    vwap_r = extras.calculate_vwap_bands(candles)
    avwap_r = extras.calculate_avwap_strategies(candles, 120)
    gap_r  = extras.detect_gap_analysis(candles)
    ofi_r  = extras.calculate_ofi_full(candles, 20)
    harm_r = extras.detect_harmonic_patterns(candles, 80)
    av_r   = extras.calculate_adaptive_volatility(candles, 20)
    last = candles[-1]; entry = float(last.get("Close", 0))
    atr_v = extras.calculate_atr_chart(candles)
    daily_vol = (atr_v / entry * 100) if entry > 0 else 1.5
    stock_entry = _stock_from_cache(code) or {}
    tgts = stock_entry.get("targets", {}) or {}
    stop = float(tgts.get("stop", entry * 0.95) or (entry * 0.95))
    h1   = float(tgts.get("sell1", entry * 1.08) or (entry * 1.08))
    h2   = float(tgts.get("sell2", entry * 1.15) or (entry * 1.15))
    mc_raw = extras.run_monte_carlo_risk(entry, stop, h1, h2, daily_vol, 10, 500)
    _exp = float(mc_raw.get("expectedReturn", 0) or 0)
    _p95 = float(mc_raw.get("var95", 0) or 0)
    _p99 = float(mc_raw.get("var99", 0) or 0)
    _ph1 = float(mc_raw.get("probH1", 0) or 0)
    _pst = float(mc_raw.get("probStop", 0) or 0)
    _std = max(0.01, abs(_exp - _p95) / 1.65) if _p95 != 0 else max(0.01, daily_vol)
    mc_r = dict(mc_raw)
    mc_r.update({
        "win_prob": _ph1,
        "h2_prob": round(max(0.0, _ph1 * 0.55), 1),
        "stop_prob": _pst,
        "median_ret": _exp,
        "ev": round(_exp, 2),
        "p95": round(_exp + 1.65 * _std, 2),
        "p5": _p95,
        "sharpe": round(_exp / _std, 2) if _std > 0 else 0,
    })
    bt = extras.get_backtest_stats()
    bt10 = bt.get("t10", {}) if isinstance(bt, dict) else {}
    win = float(bt10.get("win_rate", 55) or 55) / 100
    avg_w = abs(float(bt10.get("avg_gain", 7) or 7))
    avg_l = abs(float(bt10.get("avg_loss", -3.5) or -3.5))
    kelly = extras.calculate_kelly_criterion(win, max(0.1, avg_w), max(0.1, avg_l),
                                             config.OTO_PORTFOLIO_VALUE, config.OTO_MAX_RISK_PCT)
    if isinstance(kelly, dict):
        kelly.setdefault("kelly_frac", kelly.get("halfKelly", 0))
        kelly.setdefault("position_size", kelly.get("positionTL", 0))
        kelly.setdefault("max_risk_tl", kelly.get("riskTL", 0))
        _pos = float(kelly.get("position_size") or 0)
        kelly.setdefault("lots_100", round(_pos / 100) if _pos else 0)
    weekly = extras.get_weekly_signal(code)
    out = {"ok": True, "code": code, "smc": smc_r, "volProfile": vp_r,
           "vwapBands": vwap_r, "avwap": avwap_r, "gapAnalysis": gap_r, "ofi": ofi_r,
           "harmonics": harm_r, "adaptiveVol": av_r, "monteCarlo": mc_r,
           "kelly": kelly, "weeklySignal": weekly, "atr": round(atr_v, 4),
           "dailyVol": round(daily_vol, 2), "timestamp": now_str()}
    extras._write_json_cache(cache_file, out)
    return _json(out)


def act_multi_tf():
    code = _get_code()
    if not code:
        return _json({"ok": False, "err": "Geçersiz sembol"})
    weekly = extras.get_weekly_signal(code)
    daily = _stock_from_cache(code) or {}
    daily_score = int(daily.get("aiScore", daily.get("alPuan", 0)) or 0)
    bonus = extras.mtf_confluence_score({"techScore": daily_score}, weekly)
    return _json({"ok": True, "code": code, "weekly": weekly,
                  "dailyScore": daily_score, "confluenceBonus": bonus,
                  "finalScore": min(350, daily_score + bonus)})


def act_monte_carlo():
    code = _get_code()
    entry = float(request.values.get("entry", 0) or 0)
    stop  = float(request.values.get("stop", 0) or 0)
    h1    = float(request.values.get("h1", 0) or 0)
    h2    = float(request.values.get("h2", 0) or 0)
    vol   = float(request.values.get("vol", 1.5) or 1.5)
    iters = min(2000, max(100, int(request.values.get("iters", 500) or 500)))
    if entry <= 0:
        return _json({"ok": False, "err": "Geçersiz giriş fiyatı"})
    return _json({"ok": True, "code": code,
                  "result": extras.run_monte_carlo_risk(entry, stop, h1, h2, vol, 10, iters)})


def act_avwap():
    code = _get_code()
    if not code:
        return _json({"ok": False, "err": "Geçersiz sembol"})
    lookback = max(20, min(500, int(request.values.get("lookback", 120) or 120)))
    bar = max(lookback + 30, 150)
    cache_file = config.CACHE_DIR / f"predator_avwap_{code}_{lookback}.json"
    cached = extras._read_json_cache(cache_file, 900)
    if cached:
        return _json(cached)
    candles = extras.fetch_chart2_candles(code, periyot="G", bar=bar)
    if len(candles) < 20:
        return _json({"ok": False, "err": "Veri yetersiz"})
    res = extras.calculate_avwap_strategies(candles, lookback)
    out = {"ok": True, "code": code, "avwap": res, "ts": now_str()}
    extras._write_json_cache(cache_file, out)
    return _json(out)


def act_volume_profile():
    code = _get_code()
    if not code:
        return _json({"ok": False, "err": "Geçersiz sembol"})
    cache_file = config.CACHE_DIR / f"predator_vp_{code}.json"
    cached = extras._read_json_cache(cache_file, 1800)
    if cached:
        return _json(cached)
    candles = extras.fetch_chart2_candles(code, periyot="G", bar=100)
    if len(candles) < 10:
        return _json({"ok": False, "err": "Veri yetersiz"})
    out = {"ok": True, "code": code,
           "volProfile":  extras.calculate_volume_profile(candles, 40),
           "vwapBands":   extras.calculate_vwap_bands(candles),
           "adaptiveVol": extras.calculate_adaptive_volatility(candles, 20),
           "ts": now_str()}
    extras._write_json_cache(cache_file, out)
    return _json(out)


def act_kelly_size():
    win = float(request.values.get("win", 55) or 55) / 100
    avg_w = float(request.values.get("avgwin", 7) or 7)
    avg_l = float(request.values.get("avgloss", 3.5) or 3.5)
    portfolio = float(request.values.get("portfolio", config.OTO_PORTFOLIO_VALUE) or config.OTO_PORTFOLIO_VALUE)
    max_risk = float(request.values.get("maxrisk", config.OTO_MAX_RISK_PCT * 100) or (config.OTO_MAX_RISK_PCT * 100)) / 100
    bt = extras.get_backtest_stats()
    bt10 = bt.get("t10", {}) if isinstance(bt, dict) else {}
    real_win = float(bt10.get("win_rate", win * 100) or (win * 100)) / 100
    real_g = abs(float(bt10.get("avg_gain", avg_w) or avg_w))
    real_l = abs(float(bt10.get("avg_loss", avg_l) or avg_l))
    kelly = extras.calculate_kelly_criterion(real_win, max(0.1, real_g),
                                             max(0.1, real_l), portfolio, max_risk)
    return _json({"ok": True, "kelly": kelly, "winRate": round(real_win * 100, 1),
                  "avgWin": real_g, "avgLoss": real_l})


def act_cache_flush():
    """Tüm geçici cache dosyalarını siler. Kalıcı portföy/brain dosyalarına dokunmaz."""
    keep_prefixes = ("predator_oto_", "predator_ai_brain", "predator_signal_history",
                     "predator_auto_", "predator_tg_dedup")
    deleted = []
    skipped = 0
    target_kind = (request.values.get("kind") or "").strip().lower()
    for p in config.CACHE_DIR.glob("predator_*.json"):
        name = p.name
        # Kalıcı dosyaları koru (kind=all dahi olsa)
        if any(name.startswith(k) for k in keep_prefixes):
            skipped += 1
            continue
        if target_kind and target_kind not in name:
            continue
        try:
            p.unlink()
            deleted.append(name)
        except OSError:
            pass
    # haber_*.json ve compare cache'leri de sil
    for p in config.CACHE_DIR.glob("haber_*.json"):
        try:
            p.unlink()
            deleted.append(p.name)
        except OSError:
            pass
    return _json({"ok": True, "deleted": len(deleted), "skipped": skipped,
                  "files": deleted[:50]})


def act_brain_state():
    brain = brain_load()
    return _json({
        "snapshots_total": sum(len(v) for v in brain.get("snapshots", {}).values()),
        "stocks_tracked": len(brain.get("snapshots", {})),
        "learned_formations": len(brain.get("learned_weights", {}).get("formation", {})),
        "learned_indicators": len(brain.get("learned_weights", {}).get("indicator", {})),
        "sector_perf": brain.get("sector_perf", {}),
        "prediction_accuracy": brain.get("prediction_accuracy", {}),
        "stats": brain.get("stats", {}),
        "last_updated": brain.get("last_updated", ""),
    })


# ═════════════════════════════════════════════════════════════════════════
# ── v36: Eksik PHP fonksiyonları için action katmanı (scoring_extras)
# ═════════════════════════════════════════════════════════════════════════
from predator import scoring_extras as _sx


def act_ai_performance():
    return _json({"ok": True, "stats": _sx.ai_performance_stats()})


def act_update_outcomes():
    cache = _allstocks()
    stocks = cache.get("stocks") or cache.get("topPicks") or []
    if not isinstance(stocks, list):
        stocks = []
    changed = _sx.update_signal_outcomes(stocks)
    return _json({"ok": True, "changed": bool(changed), "stocks": len(stocks)})


def act_confidence_score():
    code = _get_code()
    s = (_stock_from_cache(code) if code else None) or {}
    sq = int(request.args.get("sq", s.get("signalQuality", 0) or 0))
    ai = int(request.args.get("ai", s.get("aiScore", 0) or 0))
    mode = request.args.get("mode", "")
    extra = {
        "predBonus": int(request.args.get("predBonus", s.get("predBonus", 0) or 0)),
        "consensus": float(request.args.get("consensus", 0) or 0),
        "triple_brain_cons": int(request.args.get("tbc", 0) or 0),
    }
    pct = _sx.calculate_confidence_score(sq, ai, mode, extra)
    return _json({"ok": True, "code": code, "confidence": pct,
                  "signalQuality": sq, "aiScore": ai, "extra": extra})


def act_calibration():
    return _json({"ok": True, "suggestions": _sx.get_calibration_suggestions()})


def act_market_breadth():
    _sx.reset_breadth_cache()  # her istekte taze hesapla
    b = _sx.get_market_breadth()
    return _json({"ok": True, "breadth": b})


def act_radar_membership():
    code = _get_code()
    if not code:
        return _json({"ok": False, "error": "code gerekli"}, 400)
    _sx.reset_radar_caches()
    return _json({"ok": True, "code": code, "radar": _sx.get_radar_membership(code)})


def act_consensus_score():
    code = _get_code()
    if not code:
        return _json({"ok": False, "error": "code gerekli"}, 400)
    s = _stock_from_cache(code) or {}
    if not s:
        return _json({"ok": False, "error": "hisse bulunamadı"}, 404)
    fin = {
        "FK": s.get("fk"), "PiyDegDefterDeg": s.get("pddd"), "ROE": s.get("roe"),
    }
    cons = _sx.calculate_consensus_score(s, fin)
    return _json({"ok": True, "code": code, "consensus": cons})


def act_ai_reasoning():
    code = _get_code()
    if not code:
        return _json({"ok": False, "error": "code gerekli"}, 400)
    s = _stock_from_cache(code) or {}
    if not s:
        return _json({"ok": False, "error": "hisse bulunamadı"}, 404)
    cons = _sx.calculate_consensus_score(s, {
        "FK": s.get("fk"), "PiyDegDefterDeg": s.get("pddd"), "ROE": s.get("roe"),
    })
    return _json({"ok": True, "code": code,
                  "reasoning": _sx.get_ai_reasoning(s, cons),
                  "consensus": cons.get("consensus")})


def act_brain_confluence_bonus():
    code = _get_code()
    if not code:
        return _json({"ok": False, "error": "code gerekli"}, 400)
    s = _stock_from_cache(code) or {}
    return _json({
        "ok": True, "code": code,
        "key": _sx.get_confluence_key(s),
        "confluence_bonus": _sx.brain_get_confluence_bonus(s),
        "time_bonus": _sx.brain_get_time_bonus(),
    })


def act_unified_position_confidence():
    code = _get_code()
    if not code:
        return _json({"ok": False, "error": "code gerekli"}, 400)
    portfolio = oto_load() or {}
    pos = (portfolio.get("positions") or {}).get(code) or {}
    if not pos:
        return _json({"ok": False, "error": "pozisyon yok"}, 404)
    brain = brain_load()
    from predator.extras import get_backtest_stats as _gbs
    bt = _gbs() or {}
    return _json({
        "ok": True, "code": code,
        "confidence": _sx.get_unified_position_confidence(code, pos, brain, bt),
    })


def act_brain_backtest_fusion():
    from predator.extras import brain_get_stats as _bgs, get_backtest_stats as _gbs
    return _json({
        "ok": True,
        "fusion": _sx.get_brain_backtest_fusion(_bgs() or {}, _gbs() or {}),
    })


def act_ai_breakdown():
    code = _get_code()
    if not code:
        return _json({"ok": False, "error": "code gerekli"}, 400)
    s = _stock_from_cache(code) or {}
    if not s:
        return _json({"ok": False, "error": "hisse bulunamadı"}, 404)
    fiyat = float(s.get("guncel") or 0)
    adil = float(s.get("adil") or 0)
    mcap = float(s.get("marketCap") or 0)
    ai_s = int(s.get("aiScore") or 0)
    al_p = int(s.get("alPuani") or 0)
    sq = int(s.get("signalQuality") or 0)
    sektor = s.get("sektor") or ""
    forms = s.get("formations") or []
    # Tech sözlüğü PHP buildAIBreakdown'ın beklediği yapıda hazırlanır:
    tech = {
        "rsi": s.get("rsi"),
        "macd": {"cross": s.get("macdCross"), "hist": s.get("macdHist")},
        "divergence": {"rsi": s.get("divRsi"), "macd": s.get("divMacd")},
        "stochRsi": {"k": s.get("stochK"), "d": s.get("stochD")},
        "ichimoku": {"signal": s.get("ichiSig"), "tkCross": s.get("ichiTk")},
        "sar": {"direction": s.get("sarDir")},
        "bb": {"pct": s.get("bbPct"), "squeeze": s.get("bbSqueeze")},
        "williamsR": s.get("williamsR"),
        "cmf": s.get("cmf"),
        "mfi": s.get("mfi"),
        "adx": {"adx": s.get("adxVal"), "dir": s.get("adxDir")},
        "supertrend": {"direction": s.get("supertrendDir"), "value": s.get("supertrendVal")},
        "emaCross": {"cross": s.get("emaCrossDir"), "fastAboveSlow": s.get("emaFastAbove")},
        "trix": {"cross": s.get("trixCross"), "signal": s.get("trixSig")},
        "cmo": s.get("cmo"),
        "awesomeOsc": {"cross": s.get("aoCross"), "signal": s.get("aoSig")},
        "hullDir": s.get("hullDir"),
        "elder": {"signal": s.get("elderSig")},
        "ultimateOsc": s.get("uo"),
        "pvt": s.get("pvt"),
        "pos52wk": s.get("pos52wk"),
        "volRatio": s.get("volRatio"),
    }
    fin = {
        "NetKar": s.get("netKar"),
        "FK": s.get("fk"),
        "PiyDegDefterDeg": s.get("pddd"),
        "roe": s.get("roe"),
        "netKarMarj": s.get("netKarMarj"),
        "faalKarMarj": s.get("faalKarMarj"),
        "cariOran": s.get("cariOran"),
        "borcOz": s.get("borcOz"),
        "lastTemettu": s.get("lastTemettu"),
        "recentBedelsiz": s.get("recentBedelsiz"),
        "brutKarMarj":   s.get("brutKarMarj"),
        "roa":           s.get("roa"),
        "ret3m":         s.get("ret3m"),
        "nakitOran":     s.get("nakitOran"),
        "likitOran":     s.get("likitOran"),
        "kaldiraci":     s.get("kaldiraci"),
        "stokDevirH":    s.get("stokDevirH"),
        "alacakDevirH":  s.get("alacakDevirH"),
        "aktifDevir":    s.get("aktifDevir"),
        "kvsaBorcOran":  s.get("kvsaBorcOran"),
        "netParaAkis":   s.get("netParaAkis"),
        "paraGiris":     s.get("paraGiris"),
        "halkakAciklik": s.get("halkakAciklik"),
        "sonDortCeyrek": s.get("sonDortCeyrek"),
        "tabanFark":     s.get("tabanFark"),
    }
    bd = _sx.build_ai_breakdown(fiyat, adil, tech, fin, forms, mcap, ai_s, al_p, sektor, sq)
    if isinstance(bd, dict):
        bd.setdefault("fundamental", fin)
        bd.setdefault("fin", fin)
        bd.setdefault("formations", forms)
    return _json({"ok": True, "code": code, "breakdown": bd})


def act_ai_explain():
    """v37.3: Tam AI karar şeffaflık paneli — her fazın puan kırılımı."""
    code = _get_code()
    if not code:
        return _json({"ok": False, "error": "code gerekli"}, 400)
    s = _stock_from_cache(code) or {}
    if not s:
        return _json({"ok": False, "error": "hisse bulunamadı"}, 404)
    # Önce baz breakdown'ı al (build_ai_breakdown'a delege)
    try:
        from flask import g
        with app.test_request_context(f"/?action=ai_breakdown&code={code}"):
            bd_resp = act_ai_breakdown()
            import json as _j
            bd_payload = _j.loads(bd_resp.get_data(as_text=True))
            base_bd = bd_payload.get("breakdown") or {}
    except Exception:
        base_bd = {}
    from predator.explain import build_full_ai_explain
    explain = build_full_ai_explain(s, base_bd)
    return _json({"ok": True, "code": code, "explain": explain})


def act_dual_brain_transfer():
    code = _get_code()
    if not code:
        return _json({"ok": False, "error": "code gerekli"}, 400)
    ret = float(request.args.get("ret", 0) or 0)
    loser = request.args.get("loser", "tie")
    s = _stock_from_cache(code) or {"code": code}
    brain = brain_load()
    _sx.dual_brain_knowledge_transfer(brain, s, ret, loser)
    from predator.brain import brain_save as _bs
    _bs(brain)
    return _json({"ok": True, "code": code, "loser": loser, "ret": ret,
                  "dual_brain_stats": brain.get("dual_brain_stats", {})})


_ACTIONS = {
    "ping": act_ping,
    "bist_scan": act_bist_scan,
    "bist_scan_two_phase": act_bist_scan_two_phase,
    "bist_scan_2p": act_bist_scan_two_phase,
    "scan_progress": act_scan_progress,
    "top_picks": act_top_picks,
    "oto_status": act_oto_status,
    "oto_log": act_oto_log,
    "oto_engine_run": act_oto_engine_run,
    "oto_close": act_oto_close,
    "oto_close_all": act_oto_close_all,
    "oto_prices": act_oto_prices,
    "oto_manual_add": act_oto_manual_add,
    "oto_tg_summary": act_oto_tg_summary,
    "daily_summary": act_daily_summary,
    "tg_test_report": act_tg_test_report,
    "pin_board_now": act_pin_board_now,
    "neural_stats": act_neural_stats,
    "neural_predict": act_neural_predict,
    "market_mode": act_market_mode,
    "send_tg": act_send_tg,
    "daemon_status": act_daemon_status,
    "brain_state": act_brain_state,
    "cache_flush": act_cache_flush,
    # ── Yeni eklenen action'lar (PHP birebir) ─────────────────────────
    "chart_data": act_chart_data,
    "brain_stats": act_brain_stats,
    "backtest_stats": act_backtest_stats,
    "brain_similar": act_brain_similar,
    "chart_compare": act_chart_compare,
    "haber_firma": act_haber_firma,
    "gundem": act_gundem,
    "bilanco_detay": act_bilanco_detay,
    "smclevels": act_smclevels,
    "multi_tf": act_multi_tf,
    "monte_carlo": act_monte_carlo,
    "volume_profile": act_volume_profile,
    "avwap": act_avwap,
    "avwap_strategies": act_avwap,
    "kelly_size": act_kelly_size,
    # ── v36: Eksik PHP fonksiyonları (skorlama / radar / güven) ────────
    "ai_performance": act_ai_performance,
    "update_outcomes": act_update_outcomes,
    "confidence_score": act_confidence_score,
    "calibration": act_calibration,
    "market_breadth": act_market_breadth,
    "radar_membership": act_radar_membership,
    "consensus_score": act_consensus_score,
    "ai_reasoning": act_ai_reasoning,
    "brain_confluence_bonus": act_brain_confluence_bonus,
    "unified_position_confidence": act_unified_position_confidence,
    "brain_backtest_fusion": act_brain_backtest_fusion,
    "ai_breakdown": act_ai_breakdown,
    "ai_explain": lambda: act_ai_explain(),
    "dual_brain_transfer": act_dual_brain_transfer,
    # ── PHP isim alias'ları ────────────────────────────────────────────
    "oto_close_position": act_oto_close,
    "oto_close_all_manual": act_oto_close_all,
    "oto_add_manual": act_oto_manual_add,
    "scan_status": act_scan_progress,
    "auto_status": act_daemon_status,
    "neural_status": act_neural_stats,
}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
