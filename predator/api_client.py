"""İdealdata ve Burgan dış API istemcileri."""
from __future__ import annotations
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable, Optional

from . import config
from .http_utils import safe_request
from .observability import log_event, log_exc

_SESSION = requests.Session()
_HEADERS = {
    "User-Agent": "Mozilla/5.0 PREDATOR/35-py",
    "Referer": config.API_REFERER,
    "Accept": "application/json, text/plain, */*",
}


def _safe_decode(content: bytes) -> str:
    """PHP safe_mb_convert karşılığı — UTF-8 → latin1 → cp1254 fallback."""
    if isinstance(content, str):
        return content
    for enc in ("utf-8", "cp1254", "iso-8859-9", "latin-1"):
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def _build_ideal_url(cmd: str, params: dict | None = None) -> str:
    parts = [f"cmd={cmd}"]
    if params:
        for k, v in params.items():
            parts.append(f"{k}={v}")
    parts.append("lang=tr")
    return config.API_BASE_URL + "/" + "?".join(parts)


def _ideal_cmd(cmd: str, params: dict | None = None, timeout: int = 12,
               raw: bool = False) -> Any:
    """PHP tarzı tuhaf URL formatı: /cmd=X?key1=v1?key2=v2?lang=tr

    Standart query string DEĞİL — tüm '?' ayraçlardır. requests bu yapıyı bozar,
    bu yüzden ham URL'i kendimiz inşa ediyoruz.
    raw=True ise decoded text döner (CSV vs).
    """
    url = _build_ideal_url(cmd, params)
    r = safe_request("GET", url, headers=_HEADERS, timeout=timeout,
                     session=_SESSION, retries=3, backoff=0.4,
                     metric_kind="api_ideal")
    if r is None:
        return None
    if r.status_code == 200 and r.content:
        text = _safe_decode(r.content)
        if raw:
            return text
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text
    return None


# Geriye dönük uyum
def ideal_get(path: str, params: Optional[dict] = None, timeout: int = 12) -> Any:
    cmd = path.lstrip("/").replace("cmd=", "")
    return _ideal_cmd(cmd, params, timeout)


def fetch_sirket_detay(code: str) -> Any:
    return _ideal_cmd("SirketDetay", {"symbol": code})


def fetch_sirket_profil(code: str) -> Any:
    return _ideal_cmd("SirketProfil", {"symbol": code})


def fetch_chart2(code: str, periyot: str = "G", bar: int = 220) -> Any:
    """CHART2 — OHLCV. Liste şeklinde döner: [{Date,Open,High,Low,Close,Size,Vol}, ...]"""
    return _ideal_cmd("CHART2", {"symbol": code, "periyot": periyot, "bar": bar}, timeout=20)


def fetch_burgan_kart(code: str) -> Any:
    """Burgan şirket kartı — temel veriler."""
    r = safe_request("GET", config.BURGAN_API_URL,
                     params={"hisseKodu": code}, headers=_HEADERS,
                     timeout=10, session=_SESSION, retries=2, backoff=0.5,
                     metric_kind="api_burgan")
    if r is None or r.status_code != 200:
        return None
    try:
        return r.json()
    except (json.JSONDecodeError, ValueError):
        return None


def fetch_bist_full_list() -> list[dict]:
    """BIST'teki tüm hisselerin listesini çeker. PHP fetchBISTFullList karşılığı.

    PHP'deki gibi Burgan API kök URL'ine GET atar, `symbol_List` döner.
    Üç deneme + allstocks_cache.json fallback.
    """
    import re
    cache_file = config.CACHE_DIR / "predator_bist_full_list.json"
    # 24 saatlik cache
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < 86400:
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached:
                return cached
        except (OSError, json.JSONDecodeError):
            pass

    code_re = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")
    timeouts = [20, 25, 30]
    waits = [0, 2, 4]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": config.API_REFERER,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "Cache-Control": "no-cache",
    }

    for attempt in range(3):
        if waits[attempt] > 0:
            time.sleep(waits[attempt])
        # Bu fonksiyonun kendi retry mantığı zaten var; tek atış yap, retry'siz.
        r = safe_request("GET", config.BURGAN_API_URL, headers=headers,
                         timeout=timeouts[attempt], session=_SESSION,
                         retries=1, metric_kind="api_burgan_list")
        if r is None or r.status_code != 200 or len(r.content) < 100:
            continue
        try:
            data = r.json()
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        items = data.get("symbol_List") or data.get("data") or []
        if not isinstance(items, list) or not items:
            continue
        stocks: list[dict] = []
        seen: set[str] = set()
        for it in items:
            if not isinstance(it, dict):
                continue
            code = (it.get("code") or it.get("Code") or "").strip().upper()
            if not code or not code_re.match(code) or code in seen:
                continue
            seen.add(code)
            stocks.append({"code": code, "name": str(it.get("name") or code)})
        if stocks:
            try:
                cache_file.write_text(json.dumps(stocks, ensure_ascii=False))
            except OSError:
                pass
            return stocks

    # Fallback 1: PHP'nin yazdığı predator_allstocks_cache.json
    try:
        if config.ALLSTOCKS_CACHE.exists():
            data = json.loads(config.ALLSTOCKS_CACHE.read_text(encoding="utf-8"))
            seen: set[str] = set()
            stocks: list[dict] = []
            # Yeni Python şeması (topPicks/allStocks) ya da eski PHP şeması (stocks)
            sources = []
            if isinstance(data, dict):
                if data.get("stocks"): sources.append(data["stocks"])
                if data.get("topPicks"): sources.append(data["topPicks"])
                if data.get("allStocks"): sources.append(data["allStocks"])
            for src in sources:
                if not isinstance(src, list):
                    continue
                for it in src:
                    if not isinstance(it, dict):
                        continue
                    code = str(it.get("code") or it.get("Kod") or "").strip().upper()
                    if not code or not code_re.match(code) or code in seen:
                        continue
                    seen.add(code)
                    stocks.append({"code": code, "name": str(it.get("name") or code)})
            if stocks:
                return stocks
    except (OSError, json.JSONDecodeError):
        pass

    return []


def fetch_live_price(code: str) -> float:
    """Tek hisse için canlı fiyat. Hata durumunda 0.0 döner."""
    data = fetch_sirket_detay(code)
    if not isinstance(data, dict):
        return 0.0
    for key in ("Son", "son", "guncel", "Guncel", "lastPrice", "Last"):
        v = data.get(key)
        if v:
            try:
                return float(str(v).replace(",", ""))
            except (ValueError, TypeError):
                continue
    return 0.0


def fetch_bilanco_rasyo(code: str) -> dict | None:
    """BilancoRasyo CSV → bilanço/rasyo dict.

    PHP runBISTScanTwoPhase Phase 1 birebir parse — Tanim;p1;p2;p3;... formatı.
    """
    raw = _ideal_cmd("BilancoRasyo", {"symbol": code}, timeout=10, raw=True)
    if not isinstance(raw, str) or not raw.strip():
        return None
    rasyo: dict[str, float] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line: continue
        parts = line.split(";")
        if len(parts) < 2: continue
        key = parts[0].strip().lower()
        try:
            val = float((parts[1] or "0").replace(",", ".").strip())
        except (ValueError, TypeError):
            val = 0.0
        rasyo[key] = val
    if not rasyo:
        return None

    def g(*keys: str) -> float:
        for k in keys:
            if k in rasyo: return rasyo[k]
        return 0.0

    return {
        "cariOran":     g("cari oran"),
        "likitOran":    g("likit oran"),
        "nakitOran":    g("nakit oran"),
        "brutKarMarj":  g("brüt kar marjı (%)", "brt kar marj (%)", "brt kar marjı (%)"),
        "netKarMarj":   g("net kar marjı (%)", "net kar marj (%)"),
        "faalKarMarj":  g("faaliyet kar marjı (%)", "faaliyet kar marj (%)"),
        "roa":          g("aktif karlılık marjı (%)", "aktif karllk marj (%)"),
        "roe":          g("özsermaye karlılık marjı (%)", "zsermaye karllk marj (%)",
                          "özsermaye karlllk marjı (%)"),
        "borcOz":       g("borçlar / özsermaye", "borlar / zsermaye"),
        "kaldiraci":    g("kaldıraç oranı", "kaldrç oran"),
        "kvsaBorcOran": g("k.vade borç / toplam borç", "k.vade bor / toplam bor"),
        "stokDevirH":   g("stok devir hızı", "stok devir hz"),
        "alacakDevirH": g("alacak devir hızı", "alacak devir hz"),
        "aktifDevir":   g("aktif devir hızı", "aktif devir hz"),
    }


def fetch_getiri(code: str) -> dict | None:
    """Getiri API → ret1m, ret3m, retYil. PHP Phase 1.7 birebir."""
    j = _ideal_cmd("Getiri", {"symbol": code}, timeout=8)
    if not isinstance(j, list):
        return None
    r1m = r3m = ryil = 0.0
    for row in j:
        if not isinstance(row, dict): continue
        tn = str(row.get("Tanim", "")).strip()
        try:
            yz = float(str(row.get("Yuzde", 0)).replace(",", "."))
        except (ValueError, TypeError):
            yz = 0.0
        if tn == "1 Ay":  r1m  = yz
        elif tn == "3 Ay": r3m  = yz
        elif tn in ("Yl", "Yıl", "Yil"): ryil = yz
    return {"ret1m": r1m, "ret3m": r3m, "retYil": ryil}


def fetch_sirket_sermaye(code: str) -> dict | None:
    """SirketSermaye → recentBedelsiz (son 6 ay), lastTemettu. PHP Phase 1.7 birebir."""
    j = _ideal_cmd("SirketSermaye", {"symbol": code}, timeout=8)
    if not isinstance(j, list):
        return None
    six_months_ago = time.time() - 6 * 30 * 86400
    recent_bedelsiz = False
    last_temettu = 0.0
    import datetime as _dt
    for row in j:
        if not isinstance(row, dict): continue
        ts_str = str(row.get("Tarih", "")).strip()
        ts_val = 0.0
        try:
            ts_val = _dt.datetime.strptime(ts_str, "%d.%m.%Y").timestamp()
        except (ValueError, TypeError):
            pass
        try:
            bed = float(str(row.get("Bedelsiz", 0)).replace(",", "."))
        except (ValueError, TypeError):
            bed = 0.0
        try:
            tem = float(str(row.get("Temettu", 0)).replace(",", "."))
        except (ValueError, TypeError):
            tem = 0.0
        if bed > 0 and ts_val >= six_months_ago:
            recent_bedelsiz = True
        if last_temettu == 0.0 and tem > 0:
            last_temettu = tem
    return {"recentBedelsiz": recent_bedelsiz, "lastTemettu": last_temettu}


def fetch_many(codes: Iterable[str], fetcher: Callable[[str], Any],
               max_workers: int = 20, on_progress: Callable[[int, int], None] | None = None
               ) -> dict[str, Any]:
    """Genel paralel batch — PHP curl_multi_init eşdeğeri.

    fetcher(code) → result. None değerler dahil edilmez.
    """
    codes_list = [c for c in codes if c]
    total = len(codes_list)
    out: dict[str, Any] = {}
    if total == 0:
        return out
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futs = {pool.submit(fetcher, c): c for c in codes_list}
        for fut in as_completed(futs):
            code = futs[fut]
            done += 1
            try:
                res = fut.result()
            except Exception as e:
                log_exc("api", f"fetch_many worker error for {code}", e,
                        code=code, fetcher=getattr(fetcher, "__name__", "?"))
                res = None
            if res is not None:
                out[code] = res
            if on_progress and (done % max(1, total // 30) == 0 or done == total):
                try:
                    on_progress(done, total)
                except Exception as e:
                    log_exc("api", "fetch_many on_progress error", e)
    return out


_SEKTOR_HAM_CACHE: dict[str, str] = {}


def fetch_sirket_sektor_ham(code: str) -> str:
    """PHP fetchSirketSektorHam — SirketProfil'den ham Sektor metnini döner.
    Hafıza içi cache (PHP static $cache eşdeğeri).
    """
    if code in _SEKTOR_HAM_CACHE:
        return _SEKTOR_HAM_CACHE[code]
    j = _ideal_cmd("SirketProfil", {"symbol": code}, timeout=4)
    val = ""
    if isinstance(j, dict) and j.get("Sektor"):
        val = str(j["Sektor"]).strip()
    _SEKTOR_HAM_CACHE[code] = val
    return val
