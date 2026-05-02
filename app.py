"""BIST PREDATOR v35 — Flask uygulaması.

Tüm `?action=` uç noktaları PHP sürümüyle uyumludur.
"""
from __future__ import annotations
import os

# v37.10: Bellek limiti — numpy/flask import edilmeden ÖNCE uygula.
# Varsayılan: 512 MB hedef + soft monitor (RSS izler, %80'de gc, %90'da trim).
# Hard cap (RLIMIT_AS) opsiyoneldir: PREDATOR_MEM_HARD=1
_MEM_MB = int(os.environ.get("PREDATOR_MEM_MB", "512") or "512")
from predator.memlimit import apply_hard_limit, start_soft_monitor
_HARD_OK = False
if os.environ.get("PREDATOR_MEM_HARD") == "1":
    # Hard cap: fiziksel + sanal toplam tahsisi MB ile sınırlar.
    # Numpy lazy mmap'leri yüzünden 512 MB AS dar gelebilir → bu mod opsiyonel.
    _HARD_OK = apply_hard_limit(_MEM_MB * 2)  # AS, RSS'in ~2x'i kadar gevşek

import json
from pathlib import Path
import time
import threading
import warnings
from flask import Flask, request, jsonify, render_template, send_from_directory, make_response

# v38.1: Artık verify=True kullanıyoruz; bu uyarı bastırması güvenlik
# regresyonunu maskelerdi → kaldırıldı.

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


def _early_restore_if_needed() -> None:
    """Flask modülleri yüklendikten hemen sonra cache boşsa TG yedeğini geri yükle.

    Bu fonksiyon daemon Timer'dan ÖNCE çalışır. Böylece:
    - Daemon thread başlamadan önce restore tamamlanır (race condition yok)
    - Hiçbir HTTP isteği küçük stub dosyaları oluşturamaz ve restore'u
      yanlışlıkla skip ettiremez
    - Render.com redeploy → disk silme senaryosunda güvenilir çalışır
    """
    try:
        from predator.cache_backup import cache_is_empty, restore_cache_from_telegram
        if not cache_is_empty():
            return
        print("[PREDATOR] Startup: cache boş/küçük — Telegram yedekten geri yükleniyor...",
              flush=True)
        MAX_TRIES = 3
        for attempt in range(1, MAX_TRIES + 1):
            try:
                r = restore_cache_from_telegram()
            except Exception as e:
                r = {"ok": False, "error": str(e)}
            if r.get("ok"):
                print(
                    f"[PREDATOR] Startup restore OK (#{attempt}, "
                    f"strateji={r.get('strategy', '?')}): "
                    f"{r.get('restored', 0)} dosya, {r.get('size_kb', 0)} KB",
                    flush=True)
                return
            print(f"[PREDATOR] Startup restore #{attempt} başarısız: {r.get('error')}",
                  flush=True)
            if attempt < MAX_TRIES:
                import time as _t; _t.sleep(2 ** attempt)
    except Exception as e:
        print(f"[PREDATOR] Startup restore hatası: {e}", flush=True)


# Cache restore: daemon timer'dan ÖNCE, senkron çalışır (race condition yok)
_early_restore_if_needed()
# Sunucu tam ayağa kalktıktan sonra daemon başlat
threading.Timer(5.0, _start_daemon_thread).start()


# ── UI ────────────────────────────────────────────────────────────────────
def _asset_ver() -> str:
    """static/app.js mtime → cache-buster."""
    try:
        import os
        return str(int(os.path.getmtime(os.path.join(app.static_folder, "app.js"))))
    except Exception:
        import time
        return str(int(time.time()))


@app.route("/")
def index():
    resp = make_response(render_template("index.html", asset_ver=_asset_ver()))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


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


def _yo_penalize(picks: list) -> list:
    """Yatırım Ortaklığı hisselerine -100 puan cezasını cache'den okurken uygula.

    Ceza scan sırasında da uygulanır; ancak eski (restart öncesi) cache verisi
    için okuma anında da garantilenmesi gerekir.
    """
    for s in picks:
        name_u = str(s.get("name") or "").upper()
        sham_u = str(s.get("sektorHam") or "").upper()
        if not ("YATIRIM ORTAKL" in name_u or "YATIRIM ORTAKL" in sham_u):
            continue
        if s.get("_yo_penalized"):
            continue
        for key in ("score", "predatorScore", "aiScore"):
            v = s.get(key)
            if v is not None:
                s[key] = round(float(v) - 100, 2)
        s["_yo_penalized"] = True
    return picks


def act_top_picks():
    cache = load_json(config.ALLSTOCKS_CACHE, {})
    # v37.8: Taranan TÜM hisseler (KAÇIN dahil) skor sırasına göre dönsün.
    picks = cache.get("allStocks") or cache.get("topPicks") or []
    if not isinstance(picks, list):
        picks = []
    picks = _yo_penalize(picks)
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
    oto_logs  = load_json(config.OTO_LOG_FILE,  [])
    auto_logs = load_json(config.AUTO_LOG_FILE, [])
    if not isinstance(oto_logs,  list): oto_logs  = []
    if not isinstance(auto_logs, list): auto_logs = []
    for e in oto_logs:
        e.setdefault("source", "oto")
        if "type" not in e and "kind" in e:
            e["type"] = e["kind"]
    for e in auto_logs:
        e.setdefault("source", "daemon")
        if "type" not in e and "kind" in e:
            e["type"] = e["kind"]
        elif "type" not in e:
            e["type"] = "info"
    merged = sorted(oto_logs + auto_logs,
                    key=lambda x: float(x.get("ts") or 0),
                    reverse=True)
    return _json({"log": merged[:200]})


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


def act_stock_health():
    """Açık pozisyonların (veya verilen codes listesinin) canlı API sağlığını raporlar.

    Tespitler:
      • dead       → API yanıt vermiyor (delist / kod değişmiş)
      • renamed    → API'deki Tanim, BIST listesindeki ad ile uyuşmuyor
      • stale      → Fark=0 + Hacim yok + OncHafta boş → işlem yok
      • no_price   → SonFiyat boş/0
      • ok         → Canlı fiyat geliyor, ad uyuşuyor
    """
    from predator.api_client import fetch_sirket_detay
    codes_param = (request.values.get("codes") or "").strip().upper()
    if codes_param:
        codes = [c.strip() for c in codes_param.split(",") if c.strip()]
    else:
        codes = list(oto_load()["positions"].keys())

    bist_list = load_json(config.CACHE_DIR / "predator_bist_full_list.json", [])
    bist_names = {s.get("code", "").upper(): str(s.get("name") or "")
                  for s in bist_list if isinstance(s, dict)}

    _TR = {"Ç":"C","Ğ":"G","İ":"I","I":"I","Ö":"O","Ş":"S","Ü":"U"}
    # Şirket ünvanlarındaki yapısal/biçimsel parçalar — eşleşmeden önce atılır
    _STOP = {"VE","A.Ş.","AŞ","AS","T.A.Ş.","TAŞ","TAS","A.O.","AO","SAN.","SAN",
             "TIC.","TIC","TICARET","SANAYI","A","Ş","HOLDİNG","HOLDING",
             "FABRIKALARI","FABRIKASI","YATIRIM","YATIRIMLAR","YATIRIMLARI",
             "GRUP","GRUBU","ENERJI","ENERJ","TURIZM","INŞAAT","INSAAT"}

    def _tokens(s: str) -> set:
        """Türkçe harfleri normalize edip kelimelere böler, stopword'leri atar."""
        s = (s or "").upper()
        s = "".join(_TR.get(c, c) for c in s)
        s = "".join(c if c.isalnum() else " " for c in s)
        toks = {t for t in s.split() if len(t) > 1 and t not in _STOP}
        return toks

    report = []
    for code in codes:
        d = fetch_sirket_detay(code)
        item = {"code": code, "status": "ok", "issues": []}
        if not isinstance(d, dict):
            item["status"] = "dead"
            item["issues"].append("API yanıt vermiyor — kod silinmiş veya değişmiş olabilir")
            item["bist_name"] = bist_names.get(code, "")
            report.append(item)
            continue

        tanim = str(d.get("Tanim") or "").strip()
        son = str(d.get("SonFiyat") or "").strip()
        fark = str(d.get("Fark") or "").strip()
        hacim = str(d.get("Hacim") or "").strip()
        onc_hafta = str(d.get("OncHafta") or "").strip()

        try:
            price_f = float(son.replace(",", ".")) if son else 0.0
        except (ValueError, TypeError):
            price_f = 0.0
        try:
            fark_f = float(fark.replace(",", ".")) if fark else 0.0
        except (ValueError, TypeError):
            fark_f = 0.0
        try:
            hacim_f = float(hacim.replace(",", "")) if hacim else 0.0
        except (ValueError, TypeError):
            hacim_f = 0.0

        item["api_tanim"] = tanim
        item["bist_name"] = bist_names.get(code, "")
        item["price"] = price_f
        item["fark"] = fark_f
        item["hacim"] = hacim_f

        if price_f <= 0:
            item["status"] = "no_price"
            item["issues"].append("SonFiyat boş/sıfır")
        if fark_f == 0 and hacim_f == 0 and not onc_hafta:
            item["status"] = "stale" if item["status"] == "ok" else item["status"]
            item["issues"].append("İşlem yok (Fark=0, Hacim=0, geçmiş veri boş) — gözaltı/halt olabilir")

        bist_name = bist_names.get(code, "")
        if tanim and bist_name:
            t1, t2 = _tokens(tanim), _tokens(bist_name)
            if t1 and t2:
                # Küçük olan, büyük olanın alt kümesi mi? (ör. {METRO,HOLDING} ⊆ {...})
                same = t1.issubset(t2) or t2.issubset(t1)
                if not same:
                    # Yine de tokenların >=%50'si örtüşüyorsa aynı şirket say
                    overlap = len(t1 & t2)
                    smaller = min(len(t1), len(t2))
                    if smaller and overlap / smaller < 0.5:
                        item["status"] = "renamed" if item["status"] == "ok" else item["status"]
                        item["issues"].append(
                            f"Şirket adı değişmiş — BIST listesi: '{bist_name}' / API: '{tanim}'")

        report.append(item)

    # Sorunlu kodlar için halef (successor) önerisi ekle
    if request.values.get("with_successor", "1") not in ("0", "false", "no"):
        from predator.symbol_aliases import detect_successor, get_active_symbol
        for r in report:
            if r["status"] in ("dead", "renamed", "stale"):
                # Önce kayıtlı alias var mı?
                active = get_active_symbol(r["code"])
                if active and active != r["code"]:
                    r["successor"] = {"new": active, "source": "alias_cache",
                                      "registered": True}
                    continue
                try:
                    sx = detect_successor(r["code"], bist_list=bist_list)
                except Exception:
                    sx = None
                if sx and sx.get("new"):
                    r["successor"] = {"new": sx["new"],
                                      "tanim": sx.get("tanim", ""),
                                      "reason": sx.get("reason", ""),
                                      "source": "auto_detect",
                                      "registered": False,
                                      "migrate_url":
                                          f"/?action=migrate_position"
                                          f"&old={r['code']}&new={sx['new']}"
                                          f"&confirm=1"}
                elif sx:
                    r["successor"] = {"new": None,
                                      "reason": sx.get("reason", "")}

    summary = {
        "total": len(report),
        "ok": sum(1 for r in report if r["status"] == "ok"),
        "renamed": sum(1 for r in report if r["status"] == "renamed"),
        "stale": sum(1 for r in report if r["status"] == "stale"),
        "no_price": sum(1 for r in report if r["status"] == "no_price"),
        "dead": sum(1 for r in report if r["status"] == "dead"),
        "with_successor": sum(1 for r in report
                              if r.get("successor", {}).get("new")),
    }
    return _json({"ok": True, "summary": summary, "report": report,
                  "ts": now_str()})


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
    delta_net = brain.get("neural_net_delta") or {}
    delta_trained = int(delta_net.get("trained_samples", 0) or 0)

    # ── Gerçek Beyin durumu ───────────────────────────────────────────────
    rb_status: dict = {}
    try:
        from predator.real_brain import rb_get_status, rb_top_features
        rb_status = rb_get_status(brain)
        rb_status["top_features"] = rb_top_features(brain, 5)
    except Exception:
        rb_status = {"ready": False, "n": 0, "min_n": 30, "accuracy": None,
                     "win_rate": 0.0, "top_features": []}

    return _json({
        "alpha": neural_get_stats(brain.get("neural_net")),
        "beta":  neural_get_stats(brain.get("neural_net_beta")),
        "gamma": neural_get_stats(brain.get("neural_net_gamma")),
        "delta": {
            "trained": delta_trained,
            "ready": delta_trained >= 20,
            "accuracy": float(delta_net.get("recent_accuracy", 0) or 0),
            "avg_loss": float(delta_net.get("avg_loss", 1.0) or 1.0),
            "wins": int(delta_net.get("wins", 0)),
            "losses": int(delta_net.get("losses", 0)),
            "arch": "32→24→12→6→1 (meta-stacking)",
            "last_trained": delta_net.get("last_trained", ""),
        },
        "real_brain": rb_status,
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
    candles = extras.fetch_chart2_candles(code, periyot="G", bar=250)
    out_candles = [{"o": round(c["Open"], 4), "h": round(c["High"], 4),
                    "l": round(c["Low"], 4),  "c": round(c["Close"], 4),
                    "v": round(c["Vol"]),     "t": c["Date"]} for c in candles[-220:]]
    tgts = {"h1": 0, "h2": 0, "h3": 0, "stop": 0, "entry": 0, "limit_entry": 0}
    if pos:
        tgts.update({"entry": float(pos.get("entry", 0) or 0),
                     "limit_entry": float(pos.get("limit_entry", 0) or 0),
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
        "posStatus": pos.get("status", "AÇIK") if pos else None,
        "pnl": round(float(pos.get("pnl_pct", 0) or 0), 2) if pos else None,
        "autoThinkDecision": (stock_info or {}).get("autoThinkDecision", (pos or {}).get("ai_decision", "—")),
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


def act_kap_tipe_test():
    """KAP 'Tipe Dönüşüm' bonusunu canlı dene.

    Örnek: /?action=kap_tipe_test&code=YIGIT&pos52=8
    Eğer pos52 verilmezse 5 (dipteki test) varsayılır.
    """
    code = _get_code(loose=True)
    if not code:
        return _json({"ok": False, "err": "Geçersiz kod"})
    try:
        pos52 = float(request.values.get("pos52", 5) or 5)
    except (TypeError, ValueError):
        pos52 = 5.0
    from predator.scoring_extras import (kap_tipe_donusum_bonus,
                                         reset_kap_news_cache)
    reset_kap_news_cache()  # her test çağrısında taze veri
    fake_stock = {"code": code.upper(), "pos52wk": pos52}
    total, items = kap_tipe_donusum_bonus(fake_stock)
    return _json({
        "ok": True,
        "code": code.upper(),
        "pos52wk": pos52,
        "kapNewsBonus": total,
        "kapNewsItems": [{"emoji": e, "msg": m, "puan": p} for e, m, p in items],
        "haber_ornek": (extras.fetch_news(code, 15) or {}).get("haberler", [])[:5],
    })


def act_kap_tipe_watchlist():
    """KAP 'Tipe Dönüşüm' watchlist — son N gün içinde duyuru olan TÜM hisseler.

    Sonuç ``pos52wk`` artan sıralı (52h dipteki hisseler en üstte). Sonuç
    15 dakika cache'lenir; ``?refresh=1`` ile zorla yeniden hesaplanır.

    Örnek: /?action=kap_tipe_watchlist&days=30
    """
    try:
        days = int(request.values.get("days", 364) or 364)
    except (TypeError, ValueError):
        days = 364
    days = max(1, min(364, days))   # 52 hafta tavanı
    force = (request.values.get("refresh") in ("1", "true", "yes"))

    cache = load_json(config.ALLSTOCKS_CACHE, {})
    picks = cache.get("allStocks") or cache.get("topPicks") or []
    if not isinstance(picks, list):
        picks = []

    from predator.scoring_extras import kap_tipe_watchlist
    out = kap_tipe_watchlist(picks, window_days=days, max_workers=8, force=force)
    out["lastScan"] = cache.get("updated", "")
    return _json(out)


def act_tavan_radar():
    """Tavan & Katlama Radarı — 3 bölümlü görüntü.

    Döner:
      - currentlyTavan: bugün tavan vuran/yakın hisseler (sebepleriyle)
      - katlamalar: 2X+ katlamış hisseler (geçmiş başarı, sebepleriyle)
      - nextCandidates: AI tahmininin sıradaki tavan adayları
                       (DNA cosine similarity + heuristik skor)
      - summary: özet sayılar

    Cache file (build_radar tarafından her tarama sonu yazılır):
      cache/predator_tavan_radar_cache.json
    """
    from predator import tavan_katlama as _tk
    radar = _tk.load_radar_cached()
    cache = load_json(config.ALLSTOCKS_CACHE, {})
    radar["lastScan"] = cache.get("updated", "")
    return _json(radar)


def act_tavan_compare():
    """Belirli bir hisse için detaylı tavan analizi + en benzer geçmiş kalıplar.

    Örnek: /?action=tavan_compare&code=AKBNK
    """
    code = _get_code()
    if not code:
        return _json({"ok": False, "err": "Geçersiz kod"})
    cache = load_json(config.ALLSTOCKS_CACHE, {})
    picks = cache.get("allStocks") or cache.get("topPicks") or []
    stock = next((s for s in picks if (s.get("code") or "").upper() == code), None)
    if not stock:
        return _json({"ok": False, "err": f"{code} taramada yok"})
    from predator import tavan_katlama as _tk
    arc_t = _tk.load_tavan_archive()
    arc_k = _tk.load_katlama_archive()
    res = _tk.apply_tavan_katlama(dict(stock), ohlc=None,
                                   archive=arc_t + arc_k)
    return _json({
        "ok":      True,
        "code":    code,
        "name":    stock.get("name", code),
        "guncel":  stock.get("guncel", 0),
        "sektor":  stock.get("sektor", ""),
        "marketCap": stock.get("marketCap", 0),
        "tavan":   res["tavan"],
        "katlama": res["katlama"],
        "next":    res["next"],
        "reasons": res["reasons"],
        "bonus":   res["bonus"],
        "archiveSize": {
            "tavan":   len(arc_t),
            "katlama": len(arc_k),
        },
    })


def act_gundem():
    return _json(extras.fetch_gundem())


def act_force_duels():
    """v39: Mevcut snapshot'ları ZORLA olgunlaştır → düelloyu hemen başlat.

    Kullanım: /?action=force_duels
    Tüm 1+ günlük snapshot'lara güncel fiyatlardan getiri hesaplar, outcome5'i
    set eder, Triple Brain düellosu çalıştırır.

    Kullanıcı 7 günlük olgunlaşmayı beklemek istemediğinde manuel tetiklemek için.
    """
    from predator import brain as _b
    cache = load_json(config.ALLSTOCKS_CACHE, {})
    picks = cache.get("allStocks") or cache.get("topPicks") or []
    prices = {(s.get("code") or "").upper(): float(s.get("guncel", 0) or 0)
              for s in picks if float(s.get("guncel", 0) or 0) > 0}
    if not prices:
        return _json({"ok": False, "err": "Cache'te güncel fiyat yok — önce tarama yapın"})
    brain = _b.brain_load()
    before = (brain.get("dual_brain_stats") or {}).get("total_duels", 0)
    before_acc = (brain.get("prediction_accuracy") or {}).get("dogru", 0)
    before_total = (brain.get("prediction_accuracy") or {}).get("toplam", 0)
    _b.brain_update_outcomes(brain, prices)
    _b.brain_save(brain)
    after = (brain.get("dual_brain_stats") or {}).get("total_duels", 0)
    after_acc = (brain.get("prediction_accuracy") or {}).get("dogru", 0)
    after_total = (brain.get("prediction_accuracy") or {}).get("toplam", 0)
    return _json({
        "ok":              True,
        "duels_before":    before,
        "duels_after":     after,
        "new_duels":       after - before,
        "predictions_added": after_total - before_total,
        "accuracy_pct":    round(after_acc / max(after_total, 1) * 100, 1),
        "champion":        (brain.get("dual_brain_stats") or {}).get("current_champion", "tie"),
        "stocks_priced":   len(prices),
    })


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


def act_cache_backup():
    """Birleşik pinli mesajı yenile (yedek + portföy panosu) — force=1 ise
    aralık beklemeden yeni şifreli dosya yükler."""
    from predator.cache_backup import update_unified_panel
    from predator.tg_listener import _build_position_board
    force = (request.values.get("force") or "").lower() in ("1", "true", "yes")
    try:
        text = _build_position_board()
    except Exception as e:
        text = f"📊 PREDATOR — yedek\n_pano üretilemedi: {e}_"
    return _json(update_unified_panel(text, force_new_doc=force))


def act_cache_restore():
    """Pinli mesajdaki en son cache yedeğini geri yükle."""
    from predator.cache_backup import restore_cache_from_telegram
    overwrite = (request.values.get("overwrite") or "1").lower() not in ("0", "false", "no")
    return _json(restore_cache_from_telegram(overwrite=overwrite))


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


def act_sleeper_stats():
    """Uyuyan Mücevher etiketli sinyallerin gerçek getirisi."""
    return _json({"ok": True, "stats": _sx.sleeper_performance_stats()})


def act_sector_rotation():
    """Sektör başına toplu rotasyon metrikleri (avg roc20, pos52, etc.)."""
    return _json({"ok": True, "sectors": _sx.get_sector_metrics()})


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
        fiyat = float(s.get("guncel") or 0)
        adil  = float(s.get("adil") or 0)
        mcap  = float(s.get("marketCap") or 0)
        ai_s  = int(s.get("aiScore") or 0)
        al_p  = int(s.get("alPuani") or 0)
        sq    = int(s.get("signalQuality") or 0)
        sektor = s.get("sektor") or ""
        forms  = s.get("formations") or []
        tech_bd = {
            "rsi": s.get("rsi"),
            "macd": {"cross": s.get("macdCross"), "hist": s.get("macdHist")},
            "divergence": {"rsi": s.get("divRsi"), "macd": s.get("divMacd")},
            "stochRsi": {"k": s.get("stochK"), "d": s.get("stochD")},
            "ichimoku": {"signal": s.get("ichiSig"), "tkCross": s.get("ichiTk")},
            "sar": {"direction": s.get("sarDir")},
            "bb": {"pct": s.get("bbPct"), "squeeze": s.get("bbSqueeze")},
            "williamsR": s.get("williamsR"),
            "cmf": s.get("cmf"), "mfi": s.get("mfi"),
            "adx": {"adx": s.get("adxVal"), "dir": s.get("adxDir")},
            "supertrend": {"direction": s.get("supertrendDir"), "value": s.get("supertrendVal")},
            "emaCross": {"cross": s.get("emaCrossDir"), "fastAboveSlow": s.get("emaFastAbove")},
            "trix": {"cross": s.get("trixCross"), "signal": s.get("trixSig")},
            "cmo": s.get("cmo"),
            "awesomeOsc": {"cross": s.get("aoCross"), "signal": s.get("aoSig")},
            "hullDir": s.get("hullDir"),
            "elder": {"signal": s.get("elderSig")},
            "ultimateOsc": s.get("uo"), "pvt": s.get("pvt"),
            "pos52wk": s.get("pos52wk"), "volRatio": s.get("volRatio"),
        }
        fin_bd = {
            "NetKar": s.get("netKar"), "FK": s.get("fk"),
            "PiyDegDefterDeg": s.get("pddd"), "roe": s.get("roe"),
            "netKarMarj": s.get("netKarMarj"), "faalKarMarj": s.get("faalKarMarj"),
            "cariOran": s.get("cariOran"), "borcOz": s.get("borcOz"),
            "lastTemettu": s.get("lastTemettu"), "recentBedelsiz": s.get("recentBedelsiz"),
            "brutKarMarj": s.get("brutKarMarj"), "roa": s.get("roa"),
            "ret3m": s.get("ret3m"),
        }
        base_bd = _sx.build_ai_breakdown(fiyat, adil, tech_bd, fin_bd, forms, mcap, ai_s, al_p, sektor, sq) or {}
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


# ── v38.1: Observability HTTP action'ları ────────────────────────────────
def act_health():
    """Sağlık özeti — son 60sn/5dk hata sayısı + uptime."""
    from predator.observability import get_health
    h = get_health()
    daemon_st = load_json(config.AUTO_STATUS_FILE, {})
    h["daemon_status"] = daemon_st.get("status", "unknown")
    h["daemon_phase"] = daemon_st.get("phase")
    return _json(h)


def act_metrics():
    """Tüm sayaç/gauge/histogram'lar — JSON formatında."""
    from predator.observability import get_metrics
    return _json(get_metrics())


def act_errors():
    """Son N hata kayıt (varsayılan 50). ?limit=N ile özelleştir."""
    from predator.observability import get_recent_errors
    try:
        limit = int(request.args.get("limit", "50") or 50)
    except (TypeError, ValueError):
        limit = 50
    return _json({"errors": get_recent_errors(limit=max(1, min(200, limit))),
                  "as_of": now_str()})


def act_triple_brain():
    """Dörtlü Beyin istatistikleri — Alpha/Beta/Gamma/Delta özeti."""
    brain = brain_load()
    ds = brain.get("dual_brain_stats") or {}
    nets = {}
    for label, key in (("alpha", "neural_net"), ("beta", "neural_net_beta"),
                       ("gamma", "neural_net_gamma"), ("delta", "neural_net_delta")):
        net = brain.get(key) or {}
        nets[label] = {
            "wins": int(net.get("wins", 0)),
            "losses": int(net.get("losses", 0)),
            "trained_samples": int(net.get("trained_samples", 0)),
            "recent_accuracy": float(net.get("recent_accuracy", 0) or 0),
            "ready": int(net.get("trained_samples", 0)) >= 20,
        }
    return _json({"dual_brain_stats": ds, "nets": nets, "as_of": now_str()})


def act_kap_news_status():
    """KAP 'Tipe Dönüşüm' cache durumu — disk persistence teşhisi."""
    from predator.scoring_extras._kap_news import get_cache_status
    return _json({"ok": True, "ts": now_str(), **get_cache_status()})


def act_tg_cleanup_status():
    """TG akıllı mesaj yöneticisi durumu — track sayısı, aktif pin vs."""
    from predator import tg_cleanup, config as _cfg
    s = tg_cleanup.status(chat_id=_cfg.TG_CHAT_ID)
    return _json({"ok": True, "ts": now_str(), **s})


def act_tg_sweep():
    """TG mesaj track tablosunu süpür: TTL aşımı + aktif olmayan
    yedek/pano mesajları silinir.

    Parametreler:
      ?dry=1 → sadece raporla, silme.
    """
    from predator import tg_cleanup, config as _cfg
    if not _cfg.TG_CHAT_ID:
        return _json({"error": "telegram_config_missing"}, 400)
    dry = request.values.get("dry") in ("1", "true", "yes")
    r = tg_cleanup.sweep(_cfg.TG_CHAT_ID, dry=dry)
    return _json({**r, "ts": now_str()})


def act_tg_nuke_range():
    """Agresif temizlik — verilen ID aralığındaki bot mesajlarını sil.

    Track dosyası kayıpsa eski mesajları süpürmek için kullanılır.
    Aktif pin atlanır. Var olmayan/sahipsiz ID'lere DELETE sessizce
    başarısız olur (zararsız).

    Parametreler:
      ?start=<id>&end=<id>[&step=1][&max=500]
    """
    from predator import tg_cleanup, config as _cfg
    if not _cfg.TG_CHAT_ID:
        return _json({"error": "telegram_config_missing"}, 400)
    try:
        start = int(request.values.get("start") or 0)
        end = int(request.values.get("end") or 0)
        step = int(request.values.get("step") or 1)
        mx = int(request.values.get("max") or 500)
    except (ValueError, TypeError):
        return _json({"error": "invalid_params"}, 400)
    if start < 1 or end < start:
        return _json({"error": "invalid_range",
                      "hint": "?start=N&end=M (M>=N) gerekli"}, 400)
    r = tg_cleanup.nuke_range(_cfg.TG_CHAT_ID, start, end,
                              step=step, max_calls=mx)
    return _json({**r, "ts": now_str()})


def act_tg_reconcile():
    """TG pin state'i ile gerçek pinli mesaj arasında uyum kur."""
    from predator import tg_cleanup, config as _cfg
    if not _cfg.TG_CHAT_ID:
        return _json({"error": "telegram_config_missing"}, 400)
    r = tg_cleanup.reconcile(_cfg.TG_CHAT_ID)
    return _json({"ok": True, **r, "ts": now_str()})


def act_tg_nuke_my_messages():
    """Aktif pinin gerisindeki ID aralığında bota ait TÜM eski mesajları sil.

    `editMessageReplyMarkup` ile sahiplik probu yapılır; kullanıcı mesajları
    dokunulmaz. Sadece pinli güncel PREDATOR PANOSU + en son şifreli yedek doc
    grupta kalır.

    Parametreler:
      ?scan_back=500 (varsayılan) — pinden geriye kaç ID taranacak
      ?max=500                    — en fazla kaç silme yapılacak
      ?pause=0.05                 — her probe arası bekleme (sn)
    """
    from predator import tg_cleanup, config as _cfg
    if not _cfg.TG_CHAT_ID:
        return _json({"error": "telegram_config_missing"}, 400)
    try:
        scan_back = int(request.values.get("scan_back") or 500)
        mx = int(request.values.get("max") or 500)
        pause = float(request.values.get("pause") or 0.05)
    except (ValueError, TypeError):
        return _json({"error": "invalid_params"}, 400)
    r = tg_cleanup.nuke_my_messages(_cfg.TG_CHAT_ID,
                                    scan_back=max(1, scan_back),
                                    max_deletes=max(1, mx),
                                    pause_sec=max(0.0, pause))
    return _json({**r, "ts": now_str()})


def act_aliases_list():
    """Kayıtlı sembol takma adları (eski → yeni kod)."""
    from predator.symbol_aliases import all_aliases
    al = all_aliases()
    return _json({"ok": True, "count": len(al), "aliases": al,
                  "ts": now_str()})


def act_detect_aliases():
    """Açık pozisyonlar (veya verilen codes) için stale kodları tarayıp
    yeni kod adayı bulur. Bulduklarını kaydeder (default) veya sadece raporlar
    (?dry=1).
    """
    from predator.symbol_aliases import detect_successor, register_alias
    codes_param = (request.values.get("codes") or "").strip().upper()
    if codes_param:
        codes = [c.strip() for c in codes_param.split(",") if c.strip()]
    else:
        codes = list(oto_load()["positions"].keys())
    dry = request.values.get("dry") in ("1", "true", "yes")
    bist_list = load_json(config.CACHE_DIR / "predator_bist_full_list.json", [])

    results = []
    for code in codes:
        try:
            r = detect_successor(code, bist_list=bist_list)
        except Exception as e:
            results.append({"old": code, "error": str(e)})
            continue
        if r is None:
            results.append({"old": code, "status": "fresh"})
            continue
        if r.get("new"):
            if not dry:
                register_alias(r["old"], r["new"],
                               reason=r.get("reason") or "auto-detect")
            results.append({"old": r["old"], "new": r["new"],
                            "tanim": r.get("tanim", ""),
                            "reason": r.get("reason", ""),
                            "status": "registered" if not dry else "proposed"})
        else:
            results.append({"old": r["old"], "new": None,
                            "reason": r.get("reason", ""),
                            "status": "dead"})
    return _json({"ok": True, "ts": now_str(), "dry": dry,
                  "scanned": len(codes), "results": results})


def act_migrate_position():
    """Portföydeki bir pozisyonu eski koddan yeni koda taşır.

    Parametre: ?old=METUR&new=BLUME
    Davranış:
      • Eski kod altındaki pozisyon kaydı, yeni kod altına taşınır.
      • Pozisyon meta bilgileri korunur (qty, entry, vs.) — fiyat/oran
        değişimi yapılmaz; kullanıcı manuel doğrulamalı.
      • Sembol takma adı (alias) da kaydedilir.
      • ?confirm=1 olmadan dry-run rapor verir.
    """
    from predator.symbol_aliases import register_alias
    old = (request.values.get("old") or "").strip().upper()
    new = (request.values.get("new") or "").strip().upper()
    confirm = request.values.get("confirm") in ("1", "true", "yes")
    if not old or not new:
        return _json({"error": "missing_params",
                      "hint": "old=ESKI&new=YENI gerekli"}, 400)
    if old == new:
        return _json({"error": "same_code"}, 400)

    oto = oto_load()
    positions = oto.get("positions") or {}
    if old not in positions:
        return _json({"error": "old_not_in_portfolio", "old": old}, 404)
    if new in positions:
        return _json({"error": "new_already_in_portfolio", "new": new,
                      "hint": "Çakışma — önce mevcut yeni kodu kapatın"}, 409)

    pos = dict(positions[old])
    pos["code"] = new
    pos["migrated_from"] = old
    pos["migrated_at"] = now_str()

    plan = {
        "old": old,
        "new": new,
        "qty": pos.get("qty"),
        "entry": pos.get("entry"),
        "buy_price": pos.get("buy_price"),
        "note": "Yeni kodda fiyat farklı olabilir — entry/qty manuel "
                "doğrulanmalı. Migration sonrası canlı fiyat ile P&L hesabı "
                "çarpık görünebilir.",
    }

    if not confirm:
        return _json({"ok": True, "dry": True, "plan": plan,
                      "hint": "&confirm=1 ile uygulayın"})

    # Uygula
    new_positions = {}
    for k, v in positions.items():
        if k == old:
            continue
        new_positions[k] = v
    new_positions[new] = pos
    oto["positions"] = new_positions
    oto_save(oto)

    register_alias(old, new, reason="manual_migrate")
    try:
        oto_log(f"[migrate] {old} → {new} (qty={pos.get('qty')}, "
                f"entry={pos.get('entry')})")
    except Exception:
        pass

    return _json({"ok": True, "dry": False, "applied": True, "plan": plan,
                  "ts": now_str()})


# ── Katlama Hedefleri — tüm verileri kullanan gelişmiş H1/H2/H3 ──────────────

def act_katlama_hedefleri():
    """Tek hisse için tüm verileri kullanarak katlama H1/H2/H3 hesapla.

    Örnek: /?action=katlama_hedefleri&code=AKBNK
    """
    code = _get_code()
    if not code:
        return _json({"ok": False, "err": "Geçersiz sembol"}, 400)
    cache = load_json(config.ALLSTOCKS_CACHE, {})
    picks = cache.get("allStocks") or cache.get("topPicks") or []
    stock = next((s for s in picks if (s.get("code") or "").upper() == code), None)
    if not stock:
        return _json({"ok": False, "err": f"{code} taramada bulunamadı"}, 404)

    from predator.katlama_targets import calculate_katlama_targets
    from predator.tavan_katlama import load_katlama_archive
    arc = load_katlama_archive()
    info = calculate_katlama_targets(
        dict(stock),
        clustered_levels=stock.get("clusteredLevels"),
        katlama_archive=arc,
    )
    return _json({
        "ok":      True,
        "code":    code,
        "name":    stock.get("name", code),
        "guncel":  stock.get("guncel", 0),
        "sektor":  stock.get("sektor", ""),
        "aiScore": stock.get("aiScore", 0),
        "predatorScore": stock.get("predatorScore") or stock.get("score", 0),
        "katlamaInfo": info,
        "archiveSize": len(arc),
    })


def act_katlama_radar_v2():
    """Tüm hisseleri tüm verileri kullanarak katlama potansiyeline göre sırala.

    Parametreler:
      min_score  (int, default 25) — minimum katlamaScore eşiği
      top_n      (int, default 50) — kaç hisse dönsün
      level      (str, opsiyonel)  — filtre: "2X"|"3X"|"5X"
      sector     (str, opsiyonel)  — sektör filtresi

    Örnek: /?action=katlama_radar_v2&min_score=40&top_n=20
    """
    try:
        min_score = int(request.values.get("min_score", 25) or 25)
        top_n     = int(request.values.get("top_n", 50) or 50)
    except (ValueError, TypeError):
        min_score, top_n = 25, 50

    level_filter  = (request.values.get("level") or "").strip().upper()
    sector_filter = (request.values.get("sector") or "").strip().lower()

    cache = load_json(config.ALLSTOCKS_CACHE, {})
    picks = cache.get("allStocks") or cache.get("topPicks") or []
    if not picks:
        return _json({"ok": False, "err": "Cache boş — önce tarama yapın"})

    from predator.katlama_targets import katlama_radar
    from predator.tavan_katlama import load_katlama_archive
    arc = load_katlama_archive()

    result = katlama_radar(picks, min_score=min_score, top_n=top_n * 3, katlama_archive=arc)

    # İsteğe bağlı filtreler
    if level_filter:
        result = [r for r in result if r["katlamaInfo"].get("katlamaLevel") == level_filter]
    if sector_filter:
        result = [r for r in result if sector_filter in str(r.get("sektor", "")).lower()]

    result = result[:top_n]

    # Özet
    summary = {
        "total":    len(result),
        "5X":       sum(1 for r in result if r["katlamaInfo"].get("katlamaLevel") == "5X"),
        "3X":       sum(1 for r in result if r["katlamaInfo"].get("katlamaLevel") == "3X"),
        "2X":       sum(1 for r in result if r["katlamaInfo"].get("katlamaLevel") == "2X"),
        "1.5X":     sum(1 for r in result if r["katlamaInfo"].get("katlamaLevel") == "1.5X"),
        "NORMAL":   sum(1 for r in result if r["katlamaInfo"].get("katlamaLevel") == "NORMAL"),
        "archiveSize": len(arc),
        "scanned":  len(picks),
        "updated":  cache.get("updated", ""),
    }
    return _json({"ok": True, "summary": summary, "radar": result, "ts": now_str()})


def act_trade_history():
    """Son işlemler, istatistikler ve portföy değeri."""
    from predator.portfolio import oto_load as _oto_load
    oto  = _oto_load()
    hist = oto.get("history", [])[:50]
    st   = oto.get("stats", {})
    pv   = float(st.get("portfolio_value", config.OTO_PORTFOLIO_VALUE) or config.OTO_PORTFOLIO_VALUE)
    return _json({
        "ok": True,
        "history": hist,
        "stats": {
            "total_trades":    int(st.get("total_trades", 0)),
            "wins":            int(st.get("wins", 0)),
            "losses":          int(st.get("losses", 0)),
            "win_rate":        float(st.get("win_rate", 0)),
            "total_pnl":       float(st.get("total_pnl", 0)),
            "portfolio_value": pv,
            "daily_pnl":       float(st.get("daily_pnl", 0)),
            "daily_date":      st.get("daily_date", ""),
        },
    })


_ACTIONS = {
    "ping": act_ping,
    "health": act_health,
    "metrics": act_metrics,
    "errors": act_errors,
    "triple_brain": act_triple_brain,
    "duel_stats": act_triple_brain,
    "bist_scan": act_bist_scan,
    "bist_scan_two_phase": act_bist_scan_two_phase,
    "bist_scan_2p": act_bist_scan_two_phase,
    "scan_progress": act_scan_progress,
    "top_picks": act_top_picks,
    "sleeper_stats": act_sleeper_stats,
    "sector_rotation": act_sector_rotation,
    "oto_status": act_oto_status,
    "oto_log": act_oto_log,
    "oto_engine_run": act_oto_engine_run,
    "oto_close": act_oto_close,
    "oto_close_all": act_oto_close_all,
    "oto_prices": act_oto_prices,
    "stock_health": act_stock_health,
    "kap_news_status": act_kap_news_status,
    "tg_cleanup_status": act_tg_cleanup_status,
    "tg_sweep": act_tg_sweep,
    "tg_nuke_range": act_tg_nuke_range,
    "tg_nuke_my_messages": act_tg_nuke_my_messages,
    "tg_reconcile": act_tg_reconcile,
    "aliases_list": act_aliases_list,
    "detect_aliases": act_detect_aliases,
    "migrate_position": act_migrate_position,
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
    "cache_backup": act_cache_backup,
    "cache_restore": act_cache_restore,
    # ── Yeni eklenen action'lar (PHP birebir) ─────────────────────────
    "chart_data": act_chart_data,
    "brain_stats": act_brain_stats,
    "backtest_stats": act_backtest_stats,
    "brain_similar": act_brain_similar,
    "chart_compare": act_chart_compare,
    "haber_firma": act_haber_firma,
    "kap_tipe_test": act_kap_tipe_test,
    "kap_tipe_watchlist": act_kap_tipe_watchlist,
    # Tavan & Katlama Radarı
    "tavan_radar": act_tavan_radar,
    "tavan_compare": act_tavan_compare,
    # Katlama Hedefleri (tüm veri kaynaklı gelişmiş H1/H2/H3)
    "katlama_hedefleri": act_katlama_hedefleri,
    "katlama_radar_v2":  act_katlama_radar_v2,
    "force_duels": act_force_duels,
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
    "trade_history": act_trade_history,
}


if __name__ == "__main__":
    # v37.10: Bellek izleyici (soft monitor) — gerçek sınıra yaklaşınca
    # gc + brain snapshot/log trim yapar.
    start_soft_monitor(_MEM_MB, interval=30)
    print(f"[memlimit] limit={_MEM_MB}MB hard_cap={'ok' if _HARD_OK else 'soft-only'}",
          flush=True)
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
