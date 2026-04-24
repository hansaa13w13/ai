"""Yapılandırılmış log + metrik + hata halkası.

PREDATOR'ın merkezi gözlemlenebilirlik katmanı. `print()` yerine bu modülü
kullan: zaman damgalı, structured (kind/level/fields) loglar üretir, son N
hatayı bellekte tutar, sayaçlar (metrics) yönetir.

Kullanım:
    from predator.observability import log_event, log_exc, metric_inc, get_health
    log_event("scan", "Tarama başladı", level="info", scan_count=12)
    try: ...
    except Exception as e: log_exc("scan", "tarama çöktü", e)
    metric_inc("scans_total")
    metric_observe("scan_duration_sec", 42.7)

HTTP üzerinden ?action=health / ?action=metrics / ?action=errors ile okunur.
"""
from __future__ import annotations
import json
import sys
import time
import threading
import traceback
from collections import deque
from typing import Any

_LOCK = threading.RLock()
_ERROR_RING: deque[dict[str, Any]] = deque(maxlen=200)
_EVENT_RING: deque[dict[str, Any]] = deque(maxlen=500)
_COUNTERS: dict[str, int] = {}
_GAUGES: dict[str, float] = {}
_HISTOGRAMS: dict[str, dict[str, float]] = {}  # min/max/sum/count/last

_LEVEL_PRIORITY = {"debug": 10, "info": 20, "warn": 30, "error": 40, "critical": 50}


def _now() -> float:
    return time.time()


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def log_event(kind: str, msg: str, level: str = "info", **fields: Any) -> None:
    """Structured log → stdout + ring buffer.

    kind: 'scan', 'brain', 'tg', 'engine', 'api', ... — alan filtreleme için.
    """
    rec = {
        "ts": _ts(),
        "epoch": _now(),
        "kind": kind,
        "level": level,
        "msg": msg,
    }
    if fields:
        rec.update(fields)
    line = f"[{rec['ts']}] [{level:<5}] [{kind}] {msg}"
    if fields:
        try:
            extra = " ".join(f"{k}={_short(v)}" for k, v in fields.items())
            line += f"  {extra}"
        except Exception:
            pass
    print(line, flush=True)
    with _LOCK:
        _EVENT_RING.append(rec)
        if level in ("error", "critical"):
            _ERROR_RING.append(rec)
            metric_inc(f"errors_total.{kind}")


def log_exc(kind: str, msg: str, exc: BaseException | None = None,
            level: str = "error", **fields: Any) -> None:
    """Exception log — kısa stack trace + kind/fields ile ring'e."""
    if exc is None:
        exc = sys.exc_info()[1]
    err_type = type(exc).__name__ if exc else "UnknownError"
    err_msg = str(exc) if exc else ""
    fields = dict(fields)
    fields["err_type"] = err_type
    fields["err_msg"] = err_msg[:200]
    if exc is not None:
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        fields["traceback"] = "".join(tb)[-2000:]
    log_event(kind, msg, level=level, **fields)


def _short(v: Any) -> str:
    s = str(v)
    return s if len(s) <= 80 else s[:77] + "..."


# ── Metrics ─────────────────────────────────────────────────────────────────
def metric_inc(name: str, n: int = 1) -> None:
    with _LOCK:
        _COUNTERS[name] = int(_COUNTERS.get(name, 0)) + int(n)


def metric_set(name: str, value: float) -> None:
    with _LOCK:
        _GAUGES[name] = float(value)


def metric_observe(name: str, value: float) -> None:
    """Histogram benzeri özet (min/max/sum/count/last). Tam histogram değil."""
    v = float(value)
    with _LOCK:
        h = _HISTOGRAMS.setdefault(name, {"min": v, "max": v, "sum": 0.0,
                                          "count": 0, "last": v})
        h["min"] = min(h["min"], v)
        h["max"] = max(h["max"], v)
        h["sum"] += v
        h["count"] += 1
        h["last"] = v


def get_metrics() -> dict[str, Any]:
    with _LOCK:
        hist = {k: {**v, "avg": (v["sum"] / v["count"]) if v["count"] else 0.0}
                for k, v in _HISTOGRAMS.items()}
        return {
            "counters": dict(_COUNTERS),
            "gauges": dict(_GAUGES),
            "histograms": hist,
            "uptime_sec": int(_now() - _START_TS),
            "as_of": _ts(),
        }


def get_recent_errors(limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK:
        return list(_ERROR_RING)[-limit:]


def get_recent_events(limit: int = 100, kind: str | None = None,
                      min_level: str = "info") -> list[dict[str, Any]]:
    min_p = _LEVEL_PRIORITY.get(min_level, 20)
    with _LOCK:
        items = list(_EVENT_RING)
    out = []
    for ev in reversed(items):
        if kind and ev.get("kind") != kind:
            continue
        if _LEVEL_PRIORITY.get(ev.get("level", "info"), 0) < min_p:
            continue
        out.append(ev)
        if len(out) >= limit:
            break
    return list(reversed(out))


def clear_errors() -> int:
    with _LOCK:
        n = len(_ERROR_RING)
        _ERROR_RING.clear()
        return n


def get_health() -> dict[str, Any]:
    """Hızlı sağlık özeti — UI / monitoring için."""
    with _LOCK:
        recent_err_60s = sum(1 for e in _ERROR_RING
                             if (_now() - float(e.get("epoch", 0))) < 60)
        recent_err_5m = sum(1 for e in _ERROR_RING
                            if (_now() - float(e.get("epoch", 0))) < 300)
    return {
        "ok": recent_err_60s == 0,
        "errors_last_60s": recent_err_60s,
        "errors_last_5m": recent_err_5m,
        "errors_total": int(_COUNTERS.get("errors_total", 0)) + sum(
            v for k, v in _COUNTERS.items() if k.startswith("errors_total.")
        ),
        "uptime_sec": int(_now() - _START_TS),
        "as_of": _ts(),
    }


_START_TS = _now()
