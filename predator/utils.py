"""Yardımcı fonksiyonlar — sayı parse, JSON I/O, tarih, dosya kilidi."""
from __future__ import annotations
import json
import os
import time
import math
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import pytz

from . import config

_TZ = pytz.timezone(config.TIMEZONE)
_FILE_LOCK = threading.RLock()


def now_tr() -> datetime:
    return datetime.now(_TZ)


def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return now_tr().strftime(fmt)


def today_str() -> str:
    return now_tr().strftime("%Y-%m-%d")


def parse_api_num(val: Any) -> float:
    """PHP'deki parseApiNum birebir karşılığı."""
    if val is None or val == "" or val is False:
        return 0.0
    if isinstance(val, (int, float)):
        try:
            f = float(val)
            return 0.0 if math.isnan(f) or math.isinf(f) else f
        except Exception:
            return 0.0
    s = str(val).replace(",", "").replace(" ", "").replace("\xa0", "")
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def load_json(path: Path | str, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default if default is not None else {}
    try:
        with _FILE_LOCK:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def _json_default(o: Any) -> Any:
    """numpy ve diğer custom tipleri JSON-uyumlu yap."""
    try:
        import numpy as np
        if isinstance(o, (np.bool_,)): return bool(o)
        if isinstance(o, (np.integer,)): return int(o)
        if isinstance(o, (np.floating,)): return float(o)
        if isinstance(o, (np.ndarray,)): return o.tolist()
    except ImportError:
        pass
    if hasattr(o, "tolist"): return o.tolist()
    if hasattr(o, "isoformat"): return o.isoformat()
    return str(o)


def save_json(path: Path | str, data: Any) -> bool:
    p = Path(path)
    try:
        with _FILE_LOCK:
            tmp = p.with_suffix(p.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"),
                          default=_json_default)
            os.replace(tmp, p)
        return True
    except OSError:
        return False


def file_age(path: Path | str) -> float:
    p = Path(path)
    if not p.exists():
        return float("inf")
    return time.time() - p.stat().st_mtime


def tg_footer() -> str:
    return f"\n_PREDATOR v35 · {now_tr().strftime('%d.%m.%Y %H:%M')}_"


def is_market_open() -> bool:
    n = now_tr()
    if n.weekday() > 4:
        return False
    minutes = n.hour * 60 + n.minute
    return 600 <= minutes <= 1075  # 10:00 – 17:55


def count_business_days(date_str: str) -> int:
    """PHP countBusinessDays karşılığı — verilen tarihten bugüne iş günü sayısı.
    v37.4: TR zaman dilimi kullanılır (eskiden naif `datetime.now()` idi —
    UTC sunucularda gece yarısı dilimi yanlış sayardı).
    """
    try:
        if " " in date_str:
            d = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        else:
            d = datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return 0
    days = 0
    cur = d.date()
    end = now_tr().date()
    while cur < end:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


# ── Basit dosya kilidi (tarama için) ──────────────────────────────────────
class ScanLock:
    def __init__(self, path: Path = config.SCAN_LOCK_FILE, ttl: int = config.SCAN_LOCK_TTL):
        self.path = Path(path)
        self.ttl = ttl

    def acquire(self) -> bool:
        if self.path.exists():
            age = time.time() - self.path.stat().st_mtime
            if age < self.ttl:
                return False
            try:
                self.path.unlink()
            except OSError:
                pass
        try:
            self.path.write_text(str(int(time.time())))
            return True
        except OSError:
            return False

    def release(self):
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("scan_lock_busy")
        return self

    def __exit__(self, *exc):
        self.release()


# ── PHP'den taşınan yardımcılar ───────────────────────────────────────────
def quantile(arr, q: float) -> float:
    """PHP `quantile($arr,$q)` birebir karşılığı — sıralı dizide doğrusal interpolasyon."""
    if not arr:
        return 0.0
    a = sorted(float(x) for x in arr)
    n = len(a)
    idx = q * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return a[n - 1]
    return a[lo] + (idx - lo) * (a[hi] - a[lo])


def calculate_graham(net_kar: float, oz_sermaye: float, sermaye: float,
                     roe: float = 0.0, fiyat: float = 0.0) -> float:
    """PHP calculateGraham birebir karşılığı.

    Klasik Graham formülü + ROE'ye dayalı büyüme çarpanı + güvenlik sınırları.
    Negatif kâr durumunda BVPS bazlı muhafazakâr taban döndürür.
    """
    import math
    if oz_sermaye <= 0 or sermaye <= 0:
        return 0.0
    bvps = oz_sermaye / sermaye
    # Negatif kar → defter değerinin %40'ı (tasfiye tabanı)
    if net_kar <= 0:
        return max(0.0, bvps * 0.4)
    eps = net_kar / sermaye
    # ROE × plowback (0.6) ile sürdürülebilir büyüme — max %15
    g = min(roe * 0.006, 0.15) if roe > 0 else 0.0
    val = 22.5 * eps * bvps
    if val <= 0:
        return 0.0
    graham = math.sqrt(val) * (1.0 + g)
    # Üst sınır: fiyatın 3x'i ; alt sınır: BVPS'nin 0.4x'i
    if fiyat > 0:
        graham = min(graham, fiyat * 3.0)
    graham = max(graham, bvps * 0.4)
    return round(graham, 4)


def safe_str_decode(raw) -> str:
    """PHP safe_mb_convert benzeri — bytes/garbled string'i UTF-8'e dönüştür."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        for enc in ("utf-8", "windows-1254", "iso-8859-9", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")
    return str(raw)
