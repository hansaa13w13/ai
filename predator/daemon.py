"""CLI daemon: BIST otomatik tarayıcı/eğitici/oto-trader.

v38.1 değişiklikler:
  • SIGTERM/SIGINT için graceful shutdown — `_STOP` event tüm döngülerde
    yoklanır; Render restart'ında 3 saniyeden kısa sürede temiz iniş yapılır.
  • Startup'ta `config.validate_secrets()` çağrılır; eksik token loglanır.
"""
from __future__ import annotations
import signal
import threading
import time
import argparse
import json
from . import config
from .utils import load_json, save_json, now_str, now_tr
from .scan import run_bist_scan, run_bist_scan_two_phase
from .engine import oto_engine_multi
from .extras import warm_smc_cache
from .brain import (brain_load, brain_save, brain_lock, neural_train_epochs,
                    neural_bootstrap, neural_negative_bootstrap,
                    brain_update_outcomes)
from .cache_backup import (backup_cache_to_telegram,
                           restore_cache_from_telegram, cache_is_empty)
from .observability import log_event, log_exc

# v38.1: Tüm uzun döngüler bu Event'i yoklar; SIGTERM/SIGINT alınca True olur.
_STOP = threading.Event()


def _install_signal_handlers() -> None:
    """SIGTERM (Render container kill) ve SIGINT (Ctrl+C) için handler kur."""
    def _handler(signum, frame):
        sname = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        if not _STOP.is_set():
            print(f"[daemon] {sname} alındı — graceful shutdown başladı", flush=True)
            log_event("daemon", f"{sname} received — graceful shutdown",
                      level="warn", signal=sname)
            _STOP.set()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            # Bazı ortamlarda (ör. Flask reloader child) signal kurulamaz
            pass


def _interruptible_sleep(seconds: float) -> bool:
    """`seconds` kadar bekle ama _STOP setlenirse erken dön. True = stop edildi."""
    return _STOP.wait(timeout=max(0.0, float(seconds)))


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
        # Top pick'ler için SMC/MC/Kelly/Weekly/Gap/Harmonik paketini önceden hesapla
        # → kullanıcı modal açtığında her şey hazır, tıklama → 0 gecikme.
        try:
            warm_n = min(50, len(picks))
            if warm_n:
                _save_status({"status": "warming", "scan_count": scan_count,
                              "msg": f"Detaylı analiz hazırlanıyor ({warm_n} hisse)..."})
                t0 = time.time()
                wr = warm_smc_cache(picks[:warm_n], max_workers=6)
                _log(f"🧠 Detaylı paket önbelleklendi: {wr.get('ok',0)}/{wr.get('total',0)} "
                     f"({round(time.time()-t0,1)}sn)", "warm")
                # v37.1: harmonik & SMC eklendi → yeniden skorla, picks'i güncelle
                try:
                    from .scoring import calculate_ai_score, calculate_predator_score
                    from .scan import _refresh_score
                    for p in picks[:warm_n]:
                        if p.get("harmonics") or p.get("smcFull"):
                            p["aiScore"] = calculate_ai_score(p)
                            # v37.4: predatorScore + score senkron, tek noktadan
                            _refresh_score(p)
                    picks[:warm_n] = sorted(picks[:warm_n], key=lambda x: x.get("score", 0), reverse=True)
                    cache["topPicks"] = picks
                    save_json(config.ALLSTOCKS_CACHE, cache)
                    _log("♻️ Skorlar harmonik+tam SMC ile güncellendi", "warm")
                except Exception as _e:
                    _log(f"Yeniden skorlama hatası: {_e}", "warn")
        except Exception as e:
            _log(f"Önbellekleme hatası: {e}", "warn")
        # Olgunlaşan snapshot'lardan gerçek-getiri eğitimi (wins/losses + tahmin doğruluğu)
        _update_outcomes(scan_count)
        _save_status({"status": "idle", "scan_count": scan_count,
                      "last_scan": now_str("%H:%M:%S"), "msg": "Tarama tamamlandı"})
        # Render.com gibi efemer disklerde cache kaybına karşı yedek (throttled).
        _maybe_backup_to_tg()
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
        # v37.4: Brain RMW kilidi — eş zamanlı kullanıcı eğitimi ile çakışmayı engeller
        with brain_lock():
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
                                  tg_pin_loop, tg_deletion_worker,
                                  closing_summary_loop)
        from .tg_cleanup import cleanup_loop as tg_cleanup_loop
        threading.Thread(target=tg_listener_loop, daemon=True,
                         name="predator-tg-listener").start()
        threading.Thread(target=daily_summary_loop, daemon=True,
                         name="predator-tg-daily").start()
        threading.Thread(target=closing_summary_loop, daemon=True,
                         name="predator-tg-closing").start()
        threading.Thread(target=tg_pin_loop, daemon=True,
                         name="predator-tg-pin").start()
        threading.Thread(target=tg_deletion_worker, daemon=True,
                         name="predator-tg-delete").start()
        # Akıllı mesaj temizleme — her 10dk'da track tablosunu süpürür
        threading.Thread(target=tg_cleanup_loop, kwargs={"interval_sec": 600},
                         daemon=True,
                         name="predator-tg-cleanup").start()
        _log("TG dinleyici/günlük özet/kapanış özeti/pin pano/silme/akıllı temizlik aktif",
             "start")
    except Exception as e:
        _log(f"TG thread başlatma hatası: {e}", "error")


def _heartbeat_loop(state: dict) -> None:
    """UI kapalıyken bile daemon'un hayatta olduğunu workflow loglarında
    gösteren bağımsız kalp atışı thread'i. Her 60sn'de bir satır basar."""
    HEARTBEAT_INT = 60
    while not _STOP.is_set():
        try:
            now_ts = time.time()
            uptime_min = int((now_ts - state.get("start_time", now_ts)) / 60)
            is_open = _market_open()
            mkt = "açık" if is_open else "kapalı"
            scan_count = state.get("scan_count", 0)
            phase = state.get("phase", "init")
            last_scan_ts = state.get("last_scan", 0)
            interval = (config.DAEMON_INT_MARKET if is_open
                        else config.DAEMON_INT_CLOSED)
            next_in = (max(0, int(interval - (now_ts - last_scan_ts)))
                       if last_scan_ts else 0)
            print(f"[{now_str('%H:%M:%S')}] [heartbeat] 💓 daemon canlı | "
                  f"faz={phase} | tarama={scan_count} | borsa={mkt} | "
                  f"sonraki={next_in}sn | uptime={uptime_min}dk", flush=True)
        except Exception as e:
            log_exc("heartbeat", "hata", e)
        if _interruptible_sleep(HEARTBEAT_INT):
            return


def _update_outcomes(scan_count: int) -> None:
    """Tarama sonrası: snapshot'lara güncel fiyatları uygula → 3/7/14/21 gün
    olgunlaşan örneklerden gerçek getiri ile sinir ağlarını eğit ve
    `prediction_accuracy` (tahmin doğruluğu) sayacını ilerlet."""
    try:
        cache = load_json(config.ALLSTOCKS_CACHE, {}) or {}
        all_stocks = (cache.get("allStocks") or cache.get("stocks")
                      or cache.get("topPicks") or [])
        if not isinstance(all_stocks, list) or not all_stocks:
            return
        prices: dict[str, float] = {}
        for s in all_stocks:
            code = (str(s.get("code") or "")).strip().upper()
            price = float(s.get("guncel", 0) or 0)
            if code and price > 0:
                prices[code] = price
        if not prices:
            return
        keys = ("neural_net", "neural_net_beta", "neural_net_gamma")
        with brain_lock():
            brain = brain_load()
            before = sum(int((brain.get(k) or {}).get("wins", 0)) +
                         int((brain.get(k) or {}).get("losses", 0)) for k in keys)
            pa_before = int((brain.get("prediction_accuracy") or {}).get("toplam", 0))
            brain_update_outcomes(brain, prices)
            after = sum(int((brain.get(k) or {}).get("wins", 0)) +
                        int((brain.get(k) or {}).get("losses", 0)) for k in keys)
            pa_after = int((brain.get("prediction_accuracy") or {}).get("toplam", 0))
            brain_save(brain)
        delta_train = after - before
        delta_pa = pa_after - pa_before
        if delta_train > 0 or delta_pa > 0:
            pa = brain.get("prediction_accuracy") or {}
            _log(f"📊 Outcomes: +{delta_train} gerçek eğitim örneği, "
                 f"+{delta_pa} tahmin doğruluğu örneği "
                 f"(toplam {pa.get('toplam', 0)} · %{pa.get('oran', 0)} doğru)",
                 "outcomes")
        # PHP signal_history paralel sistemi de güncel kalsın
        try:
            from .scoring_extras import update_signal_outcomes
            update_signal_outcomes(all_stocks)
        except Exception:
            pass
    except Exception as e:
        _log(f"Outcomes güncelleme hatası: {e}", "error")


def _maybe_restore_from_tg() -> None:
    """Cache boşsa (örn. Render.com fresh deploy / disk silme), yedeği geri yükle.

    Strateji:
    - Önce kalite kontrollü `cache_is_empty()` ile gerçekten boş mu diye bak.
    - Boşsa çok aşamalı `restore_cache_from_telegram()` dene (pin → /tmp → tracked).
    - Ağ hatalarına karşı 3 deneme, üstel bekleme (2s / 4s / 8s).
    """
    if not cache_is_empty():
        return
    _log("Cache boş/küçük — Telegram yedekten geri yükleme başlıyor...", "restore")
    MAX_TRIES = 3
    for attempt in range(1, MAX_TRIES + 1):
        try:
            r = restore_cache_from_telegram()
        except Exception as e:
            _log(f"Geri yükleme istisnası #{attempt}/{MAX_TRIES}: {e}", "error")
            r = {"ok": False, "error": str(e)}
        if r.get("ok"):
            strat = r.get("strategy", "?")
            _log(
                f"✅ Cache geri yüklendi (deneme #{attempt}, strateji={strat}): "
                f"{r.get('restored', 0)} dosya · {r.get('size_kb', 0)} KB "
                f"({r.get('filename', '?')})", "restore")
            return
        err = r.get("error", "unknown")
        if attempt < MAX_TRIES:
            wait = 2 ** attempt
            _log(f"Geri yükleme #{attempt}/{MAX_TRIES} başarısız: {err} — "
                 f"{wait}sn bekleyip yeniden deneniyor...", "warn")
            time.sleep(wait)
        else:
            _log(f"Tüm {MAX_TRIES} deneme başarısız. Son hata: {err} — "
                 f"ilk taramada cache yeniden oluşturulacak.", "warn")


def _maybe_backup_to_tg() -> None:
    """No-op: cache yedeği artık birleşik pinli mesaj üzerinden yapılıyor.

    `tg_pin_loop` her 60sn'de `_ensure_pinned_board` → `update_unified_panel`
    çağırır; orada 30dk'lık BACKUP_INTERVAL_SEC ile yeni şifreli `.bin` upload
    edilir, eskileri silinir. Burada ayrıca yedek almıyoruz (mükerrer mesaj
    olmasın).
    """
    return


def run_daemon() -> None:
    _install_signal_handlers()
    log_event("daemon", "starting", level="info")
    # v38.1: Eksik secret'leri startup'ta logla (TG no-op'a düşer ama görünür olur)
    try:
        config.validate_secrets()
    except Exception as e:
        log_exc("daemon", "validate_secrets fail", e)
    # ── ÖNEMLİ: Cache restore HER ŞEYDEN ÖNCE yapılmalı ───────────────────
    # Aksi halde aşağıdaki `_log(...)` çağrısı `cache/predator_auto_log.json`
    # (CRITICAL_FILES içinde) dosyasını oluşturur, `cache_is_empty()` False
    # döner ve Telegram pinli yedek geri yüklenmeden taze taramaya başlanır.
    _maybe_restore_from_tg()
    _log("🚀 PREDATOR Oto-Pilot daemon başlatıldı (Python sürümü)", "start")

    # Real Brain önyükleme: mevcut outcome-etiketli snapshot'lardan rb_samples doldur.
    # Brain her restart'ta in-memory model sıfırlanır; bu satır geçmişi hemen geri yükler.
    try:
        from .real_brain import rb_bootstrap_from_snapshots as _rb_boot
        with brain_lock():
            _rb_brain = brain_load()
            _rb_n_before = len(_rb_brain.get("rb_samples") or [])
            _added = _rb_boot(_rb_brain)
            if _added > 0:
                brain_save(_rb_brain)
                _log(f"🧠 Real Brain önyüklendi: +{_added} örnek "
                     f"(toplam {_rb_n_before + _added})", "start")
    except Exception as _rb_e:
        _log(f"Real Brain önyükleme hatası: {_rb_e}", "warn")

    _clear_stale_locks()
    _start_tg_threads()
    _save_status({"status": "starting", "msg": "Daemon başlatılıyor...", "scan_count": 0})
    state = {"last_scan": 0, "last_train": 0, "scan_count": 0,
             "start_time": time.time(), "phase": "ilk-tarama"}

    # Bağımsız kalp atışı thread'i — UI kapalıyken bile workflow logunda
    # daemon'un her dakika "canlı" sinyali görünür olur.
    threading.Thread(target=_heartbeat_loop, args=(state,),
                     daemon=True, name="predator-heartbeat").start()

    # İlk tarama
    if not _STOP.is_set():
        state["scan_count"] = _scan_and_engine(state["scan_count"])
        state["last_scan"] = time.time()
        state["phase"] = "ilk-eğitim"
    if not _STOP.is_set():
        _train(state)
        state["phase"] = "döngü"

    while not _STOP.is_set():
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
            state["phase"] = "tarama"
            state["scan_count"] = _scan_and_engine(state["scan_count"])
            state["last_scan"] = time.time()
            if _STOP.is_set():
                break
            state["phase"] = "eğitim"
            _train(state)
            state["phase"] = "bekleme"
        else:
            # 15sn bekle ama erken çıkışa duyarlı
            if _interruptible_sleep(15):
                break

    # ── Graceful shutdown: kilitleri bırak, status'u temiz bırak
    _log("Daemon kapatılıyor (graceful)...", "stop")
    log_event("daemon", "shutdown complete", level="info",
              uptime_sec=int(time.time() - state["start_time"]),
              total_scans=state.get("scan_count", 0))
    try:
        _save_status({"status": "stopped", "msg": "Daemon kapandı (graceful)",
                      "scan_count": state.get("scan_count", 0)})
    except Exception:
        pass
    try:
        if config.SCAN_LOCK_FILE.exists():
            config.SCAN_LOCK_FILE.unlink()
    except OSError:
        pass


def main() -> None:
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
