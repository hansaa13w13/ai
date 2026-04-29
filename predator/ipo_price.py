"""Halka Arz fiyatı (IPO) cache + skor bonusu.

Her hisse için ilk listelenme fiyatını CHART2 aylık verisinden çeker
(ilk barın açılışı). IPO fiyatı zamanla değişmediği için kalıcı diskte
cache'lenir; ikinci taramada API çağrısı yapılmaz.

Skor bonusu: cari fiyat IPO fiyatının altına/yakın oldukça artar.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Iterable

from . import config
from .api_client import fetch_chart2

_IPO_CACHE_FILE = config.CACHE_DIR / "predator_ipo_prices.json"
_LOCK = threading.Lock()
_MEM: dict | None = None


def _load() -> dict:
    global _MEM
    if _MEM is not None:
        return _MEM
    try:
        if _IPO_CACHE_FILE.exists():
            _MEM = json.loads(_IPO_CACHE_FILE.read_text(encoding="utf-8")) or {}
        else:
            _MEM = {}
    except (OSError, json.JSONDecodeError):
        _MEM = {}
    return _MEM


def _save() -> None:
    if _MEM is None:
        return
    try:
        _IPO_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _IPO_CACHE_FILE.write_text(json.dumps(_MEM, ensure_ascii=False))
    except OSError:
        pass


def _extract_first_price(chart) -> float:
    """CHART2 yanıtından en eski (ilk) bar'ın açılış/kapanış fiyatını döndür."""
    if not chart:
        return 0.0
    candles = chart
    if isinstance(chart, dict):
        candles = (chart.get("Data") or chart.get("data")
                   or chart.get("candles") or chart.get("ohlcv") or [])
    if not isinstance(candles, list) or not candles:
        return 0.0
    first = candles[0]
    if isinstance(first, dict):
        for key in ("Open", "Acilis", "open", "o",
                    "Close", "Kapanis", "close", "c"):
            v = first.get(key)
            try:
                f = float(str(v).replace(",", ".")) if v not in (None, "") else 0.0
            except (ValueError, TypeError):
                f = 0.0
            if f > 0:
                return f
    elif isinstance(first, list) and len(first) >= 5:
        for idx in (1, 4):  # open, close
            try:
                f = float(str(first[idx]).replace(",", "."))
                if f > 0:
                    return f
            except (ValueError, TypeError, IndexError):
                pass
    return 0.0


def get_ipo_price(code: str, *, force: bool = False) -> float:
    """Tek hisse IPO fiyatı — disk cache'inden, yoksa API'den çek."""
    code = (code or "").strip().upper()
    if not code:
        return 0.0
    with _LOCK:
        cache = _load()
        if not force and code in cache:
            v = cache[code]
            if isinstance(v, dict):
                return float(v.get("ipo", 0) or 0)
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0
    # API'den çek (aylık, 360 bar = ~30 yıl)
    try:
        chart = fetch_chart2(code, "A", 360)
    except Exception:
        chart = None
    price = _extract_first_price(chart)
    with _LOCK:
        cache = _load()
        cache[code] = {"ipo": round(price, 4), "ts": int(time.time())}
        _save()
    return price


def prefetch(codes: Iterable[str], max_workers: int = 6) -> None:
    """Cache'de olmayanları paralel olarak doldur. Mevcutları atla."""
    from concurrent.futures import ThreadPoolExecutor
    cache = _load()
    missing = [c.strip().upper() for c in codes
               if c and c.strip().upper() not in cache]
    if not missing:
        return
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        list(pool.map(lambda c: get_ipo_price(c), missing))


def ipo_bonus(cur_price: float, ipo_price: float) -> int:
    """IPO fiyatına göre aiScore bonusu (max +100).

    - Cari fiyat IPO'nun ne kadar altındaysa o kadar fazla puan verir.
    - %5 yakınında: +20, eşit/altında: +40, -%25: +65, -%50 ve aşağı: +100.
    - IPO üzerindeyse 0.
    """
    try:
        ipo = float(ipo_price or 0)
        cur = float(cur_price or 0)
    except (ValueError, TypeError):
        return 0
    if ipo <= 0 or cur <= 0:
        return 0
    diff_pct = (cur - ipo) / ipo * 100.0  # negatif = IPO altında
    if diff_pct <= -50: return 100
    if diff_pct <= -35: return 85
    if diff_pct <= -25: return 65
    if diff_pct <= -10: return 50
    if diff_pct <=   0: return 40   # IPO eşit veya altında
    if diff_pct <=   5: return 20   # IPO'ya çok yakın (%5 üstü)
    return 0


def ipo_info(code: str, cur_price: float) -> dict:
    """Cari fiyat ve IPO fiyatına göre tüm IPO meta bilgisini döndürür."""
    ipo = get_ipo_price(code)
    if ipo <= 0:
        return {"ipoFiyat": 0.0, "ipoFark": 0.0, "ipoBonus": 0, "ipoAltinda": False}
    try:
        cur = float(cur_price or 0)
    except (ValueError, TypeError):
        cur = 0.0
    diff_pct = (cur - ipo) / ipo * 100.0 if cur > 0 else 0.0
    bonus = ipo_bonus(cur, ipo)
    return {
        "ipoFiyat": round(ipo, 4),
        "ipoFark": round(diff_pct, 2),
        "ipoBonus": bonus,
        "ipoAltinda": diff_pct <= 5,  # %5 yakın veya altı = "halka arz fiyatına yakın/altında"
    }
