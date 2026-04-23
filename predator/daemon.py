"""CLI daemon: BIST otomatik tarayıcı/eğitici/oto-trader."""
from __future__ import annotations
import time
import argparse
import json
import requests
from . import config
from .utils import load_json, save_json, now_str, now_tr
from .scan import run_bist_scan, run_bist_scan_two_phase
from .engine import oto_engine_multi
from .brain import (brain_load, brain_save, neural_train_epochs,
                    neural_bootstrap, neural_negative_bootstrap)


def _save_status(d: dict) -> None:
    d["ts"] = int(time.time()); d["timestamp"] = now_str()
    save_json(config.AUTO_STATUS_FILE, d)


def _log(msg: str, kind: str = "info") -> None:
    logs = load_json(config.AUTO_LOG_FILE, [])
    if not isinstance(logs, list): logs = []
    logs.insert(0, {"time": now_str("%H:%M:%S"), "msg": msg, "type": kind})
    if len(logs) > 50: logs = logs[:50]
    save_json(config.AUTO_LOG_FILE, logs)
    print(f"[{now_str('%H:%M:%S')}] [{kind}] {msg}", flush=True)


def _market_open() -> bool:
    n = now_tr()
    if n.isoweekday() > 5: return False
    m = n.hour * 60 + n.minute
    return config.DAEMON_MARKET_FROM <= m <= config.DAEMON_MARKET_TO


def _scan_and_engine(scan_count: int) -> int:
    _log("Tarama başlatılıyor...", "scan")
    _save_status({"status": "scan_starting", "scan_count": scan_count, "msg": "Tarama..."})
    try:
        r = run_bist_scan_two_phase()
    except Exception as e:
        _log(f"Tarama hatası: {e}", "error")
        return scan_count
    if r.get("status") == "done":
        scan_count += 1
        _log(f"✅ Tarama #{scan_count} tamamlandı ({r.get('ok', 0)}/{r.get('scanned', 0)} hisse, {r.get('duration_sec', 0)}sn)", "scan")
        # Oto-trade engine
        cache = load_json(config.ALLSTOCKS_CACHE, {})
        picks = cache.get("topPicks", []) if isinstance(cache, dict) else []
        try:
            oto_engine_multi(picks)
        except Exception as e:
            _log(f"Engine hatası: {e}", "error")
        _save_status({"status": "idle", "scan_count": scan_count,
                      "last_scan": now_str("%H:%M:%S"), "msg": "Tarama tamamlandı"})
    elif r.get("status") == "locked":
        _log("Tarama kilidi mevcut — bekleniyor", "warn")
    else:
        _log(f"Tarama başarısız: {r.get('error', 'unknown')}", "error")
    return scan_count


def _train(state: dict) -> None:
    if time.time() - state.get("last_train", 0) < config.DAEMON_TRAIN_INT:
        return
    _log("AI eğitimi başlatılıyor...", "train")
    try:
        brain = brain_load()
        cache = load_json(config.ALLSTOCKS_CACHE, {}) or {}
        # İlk açılışta klasik bootstrap
        if int(brain.get("neural_net", {}).get("trained_samples", 0)) < 10:
            picks = cache.get("topPicks", []) if isinstance(cache, dict) else []
            n = neural_bootstrap(brain, picks)
            _log(f"Bootstrap: {n} sentetik örnek", "train")
        # Negatif örnek eğitimi (allStocks tam veriden)
        all_stocks = cache.get("allStocks") or []
        if all_stocks:
            neg = neural_negative_bootstrap(brain, all_stocks, epochs=2)
            _log(f"Negatif eğitim: +{neg.get('positive',0)} / -{neg.get('negative',0)} "
                 f"× {neg.get('epochs',0)} epoch", "train")
        neural_train_epochs(brain, epochs=3)
        brain_save(brain)
        state["last_train"] = time.time()
        _log("✅ AI eğitim tamamlandı", "train")
    except Exception as e:
        _log(f"Eğitim hatası: {e}", "error")


def _clear_stale_locks() -> None:
    """Daemon her başlatıldığında bayat kilit/progress dosyalarını temizler."""
    try:
        if config.SCAN_LOCK_FILE.exists():
            age = time.time() - config.SCAN_LOCK_FILE.stat().st_mtime
            config.SCAN_LOCK_FILE.unlink()
            _log(f"Bayat tarama kilidi temizlendi (yaş {int(age)}sn)", "warn")
    except OSError:
        pass
    try:
        if config.SCAN_PROGRESS_FILE.exists():
            save_json(config.SCAN_PROGRESS_FILE, {"status": "idle", "pct": 0, "ts": int(time.time())})
    except Exception:
        pass


def _start_tg_threads() -> None:
    """Telegram dinleyici + günlük özet zamanlayıcı thread'lerini başlat."""
    import threading
    try:
        from .tg_listener import (tg_listener_loop, daily_summary_loop,
                                  tg_pin_loop, tg_deletion_worker)
        threading.Thread(target=tg_listener_loop, daemon=True,
                         name="predator-tg-listener").start()
        threading.Thread(target=daily_summary_loop, daemon=True,
                         name="predator-tg-daily").start()
        threading.Thread(target=tg_pin_loop, daemon=True,
                         name="predator-tg-pin").start()
        threading.Thread(target=tg_deletion_worker, daemon=True,
                         name="predator-tg-delete").start()
        _log("TG dinleyici/günlük özet/pin pano/silme işçisi aktif", "start")
    except Exception as e:
        _log(f"TG thread başlatma hatası: {e}", "error")


def run_daemon() -> None:
    _log("🚀 PREDATOR Oto-Pilot daemon başlatıldı (Python sürümü)", "start")
    _clear_stale_locks()
    _start_tg_threads()
    _save_status({"status": "starting", "msg": "Daemon başlatılıyor...", "scan_count": 0})
    state = {"last_scan": 0, "last_train": 0, "scan_count": 0, "start_time": time.time()}
    # İlk tarama
    state["scan_count"] = _scan_and_engine(state["scan_count"])
    state["last_scan"] = time.time()
    _train(state)

    while True:
        is_open = _market_open()
        interval = config.DAEMON_INT_MARKET if is_open else config.DAEMON_INT_CLOSED
        since = time.time() - state["last_scan"]
        next_in = max(0, int(interval - since))
        _save_status({
            "status": "idle",
            "market_open": is_open,
            "scan_count": state["scan_count"],
            "last_scan_ts": int(state["last_scan"]),
            "last_scan": time.strftime("%H:%M:%S", time.localtime(state["last_scan"])) if state["last_scan"] else None,
            "next_scan_in": next_in,
            "uptime_sec": int(time.time() - state["start_time"]),
            "msg": (f"Borsa açık — sonraki tarama {next_in}sn" if is_open
                    else f"Borsa kapalı — sonraki tarama {next_in}sn"),
        })
        if since >= interval:
            state["scan_count"] = _scan_and_engine(state["scan_count"])
            state["last_scan"] = time.time()
            _train(state)
        else:
            time.sleep(15)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true", help="Sürekli çalışan oto-pilot modunu başlat")
    ap.add_argument("--scan-once", action="store_true", help="Tek tarama yap ve çık")
    args = ap.parse_args()
    if args.scan_once:
        r = run_bist_scan_two_phase()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return
    if args.daemon:
        run_daemon()
        return
    ap.print_help()


if __name__ == "__main__":
    main()
