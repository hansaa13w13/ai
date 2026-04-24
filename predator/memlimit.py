"""v37.10: Bellek limiti — kernel hard cap + soft monitor.

İki katmanlı koruma:
  1) Hard cap: `resource.setrlimit(RLIMIT_AS, MB)` — tahsis MB'yi aşarsa
     işletim sistemi MemoryError fırlatır (uygulama kontrollü çıkar).
  2) Soft monitor: arka plan thread her 30 sn RSS okur; %80'de gc.collect(),
     %90'da brain snapshot ve oto_log boyutlarını kırpar.
"""
from __future__ import annotations
import os
import gc
import time
import threading
import resource
from pathlib import Path


def apply_hard_limit(mb: int = 512) -> bool:
    """RLIMIT_AS hard cap. Numpy import edilmeden ÖNCE çağırın."""
    try:
        bytes_ = mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (bytes_, bytes_))
        return True
    except (ValueError, OSError):
        return False


def _rss_mb() -> float:
    try:
        with open(f"/proc/{os.getpid()}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1]) / 1024.0
    except OSError:
        pass
    return 0.0


def _trim_caches() -> dict:
    """Bellek baskısı altında brain snapshot + oto log kırp."""
    from . import config
    from .utils import load_json, save_json
    res = {"snapshots_trimmed": 0, "log_trimmed": 0}
    # Brain snapshot — her hisse için son 30 (normal 90)
    try:
        b = load_json(config.AI_BRAIN_FILE, {}) or {}
        snaps = b.get("snapshots") or {}
        before = sum(len(v) for v in snaps.values() if isinstance(v, list))
        for code, lst in list(snaps.items()):
            if isinstance(lst, list) and len(lst) > 30:
                snaps[code] = lst[:30]
        after = sum(len(v) for v in snaps.values() if isinstance(v, list))
        if after < before:
            save_json(config.AI_BRAIN_FILE, b)
            res["snapshots_trimmed"] = before - after
    except Exception:
        pass
    # Oto log — son 200 (normal 500)
    try:
        log = load_json(config.OTO_LOG_FILE, []) or []
        if isinstance(log, list) and len(log) > 200:
            res["log_trimmed"] = len(log) - 200
            save_json(config.OTO_LOG_FILE, log[:200])
    except Exception:
        pass
    return res


def start_soft_monitor(limit_mb: int = 512, interval: int = 30) -> None:
    """Arka plan RSS izleyici. Sınırlara yaklaşınca gc + cache trim yapar."""
    soft_threshold = limit_mb * 0.80
    hard_threshold = limit_mb * 0.90

    def _loop():
        while True:
            try:
                rss = _rss_mb()
                if rss >= hard_threshold:
                    gc.collect()
                    info = _trim_caches()
                    print(f"[memlimit] HIGH rss={rss:.0f}MB/{limit_mb}MB "
                          f"trimmed={info}", flush=True)
                elif rss >= soft_threshold:
                    gc.collect()
            except Exception:
                pass
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name="memlimit_monitor")
    t.start()
