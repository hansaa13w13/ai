"""KAP 'Borsada İşlem Gören Tipe Dönüşüm' Bonusu — dipteki hisseler.

KAP (Kamuyu Aydınlatma Platformu) üzerinde Merkez Kayıt Kuruluşu (MKK)
tarafından yayımlanan ``Borsada İşlem Gören Tipe Dönüşüm Duyurusu``
hisselerin pay tipinin değiştiğini (örn. nama → hamiline) gösterir.
Bu nadir görülen bir olaydır ve genellikle pay likiditesi ile yatırımcı
ilgisini artırarak rebound katalizörü oluşturur.

Bu modül:
  • SADECE "tipe dönüşüm" / "tip değişikliği" / "pay tipi" / "pay grubu
    dönüşümü" geçen KAP haberlerini puanlar.
  • Kısıtlama, BISTECH genel duyurusu, devre kesici gibi diğer haberleri
    PUANA DAHİL ETMEZ.
  • Sadece ``pos52wk < 35`` olan dipteki hisselere uygulanır.

Test:
    /?action=kap_tipe_test&code=YIGIT
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

# ── Cache ────────────────────────────────────────────────────────────────────
_CACHE: dict[str, tuple[float, int, list[tuple[str, str, int]]]] = {}
_CACHE_TTL = 1800  # 30 dakika
_CACHE_LOCK = threading.Lock()

# ── Watchlist cache (UI panel) ───────────────────────────────────────────────
_WATCHLIST_CACHE: dict[str, Any] = {"ts": 0.0, "window": 0, "data": []}
_WATCHLIST_TTL = 900   # 15 dakika
_WATCHLIST_LOCK = threading.Lock()

# ── Disk persistence (v37.11) ────────────────────────────────────────────────
# Cache restart sonrası kayboluyordu → tipe dönüşüm bonusu sıfırdan hesaplanmak
# zorundaydı, bu da skoru gecikmeli olarak yansıtıyordu. Artık kalıcı.
_PERSIST_DEBOUNCE = 3.0
_LAST_PERSIST_TS = {"cache": 0.0, "watchlist": 0.0}
_HYDRATED = False


def _cache_path():
    from .. import config
    return config.CACHE_DIR / "predator_kap_news_cache.json"


def _watchlist_path():
    from .. import config
    return config.CACHE_DIR / "predator_kap_watchlist.json"


def _hydrate() -> None:
    global _HYDRATED
    if _HYDRATED:
        return
    try:
        p = _cache_path()
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                now = time.time()
                with _CACHE_LOCK:
                    for code, ent in raw.items():
                        if not isinstance(ent, list) or len(ent) < 3:
                            continue
                        ts, total, items = ent[0], ent[1], ent[2]
                        if not isinstance(ts, (int, float)):
                            continue
                        # 4 saatten eski kayıtları atla — yine de cache_ttl
                        # geçince fonksiyon kendi tazeleyecek.
                        if (now - float(ts)) > (_CACHE_TTL * 8):
                            continue
                        try:
                            items_t = [(str(a), str(b), int(c))
                                       for a, b, c in items]
                        except (TypeError, ValueError):
                            continue
                        _CACHE[str(code).upper()] = (
                            float(ts), int(total), items_t)
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    try:
        p = _watchlist_path()
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("data"), list):
                with _WATCHLIST_LOCK:
                    _WATCHLIST_CACHE["ts"] = float(raw.get("ts") or 0)
                    _WATCHLIST_CACHE["window"] = int(raw.get("window") or 0)
                    _WATCHLIST_CACHE["scanned"] = int(raw.get("scanned") or 0)
                    _WATCHLIST_CACHE["data"] = list(raw["data"])
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    _HYDRATED = True


def _persist_cache(force: bool = False) -> None:
    now = time.time()
    if not force and (now - _LAST_PERSIST_TS["cache"]) < _PERSIST_DEBOUNCE:
        return
    try:
        with _CACHE_LOCK:
            data = {k: [v[0], v[1], [list(it) for it in v[2]]]
                    for k, v in _CACHE.items()}
        p = _cache_path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
        # Forced yazımlar debounce penceresini sıfırlamaz — sıradaki gerçek
        # populate yazımı geçebilsin (örn. reset → hemen sonra YIGIT cache'i).
        if not force:
            _LAST_PERSIST_TS["cache"] = now
    except OSError:
        pass


def _persist_watchlist(force: bool = False) -> None:
    now = time.time()
    if not force and (now - _LAST_PERSIST_TS["watchlist"]) < _PERSIST_DEBOUNCE:
        return
    try:
        with _WATCHLIST_LOCK:
            data = {
                "ts": float(_WATCHLIST_CACHE.get("ts") or 0),
                "window": int(_WATCHLIST_CACHE.get("window") or 0),
                "scanned": int(_WATCHLIST_CACHE.get("scanned") or 0),
                "data": list(_WATCHLIST_CACHE.get("data") or []),
            }
        p = _watchlist_path()
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
        if not force:
            _LAST_PERSIST_TS["watchlist"] = now
    except OSError:
        pass


def get_cache_status() -> dict:
    """Teşhis amaçlı: cache durum bilgisi."""
    _hydrate()
    with _CACHE_LOCK:
        per_stock = len(_CACHE)
        positives = sum(1 for v in _CACHE.values() if v[1] > 0)
    with _WATCHLIST_LOCK:
        wl_count = len(_WATCHLIST_CACHE.get("data") or [])
        wl_ts = float(_WATCHLIST_CACHE.get("ts") or 0)
    return {
        "perStockEntries": per_stock,
        "perStockWithBonus": positives,
        "watchlistMatches": wl_count,
        "watchlistTs": int(wl_ts),
        "watchlistAgeSec": int(time.time() - wl_ts) if wl_ts else None,
        "cacheTtlSec": _CACHE_TTL,
        "watchlistTtlSec": _WATCHLIST_TTL,
        "files": {
            "perStock": str(_cache_path()),
            "watchlist": str(_watchlist_path()),
            "perStockExists": _cache_path().exists(),
            "watchlistExists": _watchlist_path().exists(),
        },
    }


# ── Anahtar kelime kalıpları ─────────────────────────────────────────────────
# SADECE "tipe dönüşüm" — başka hiçbir KAP haberi puana dahil değildir.
# MKK / Borsa İstanbul terminolojisi: "Borsada İşlem Gören Tipe Dönüşüm"
_PATTERNS_TIPE_DONUSUM = [
    re.compile(r"borsada\s*işlem\s*gören\s*tipe\s*dönüş", re.IGNORECASE),
    re.compile(r"tipe\s*dönüş",       re.IGNORECASE),  # genel form
    re.compile(r"tip\s*değişikli",    re.IGNORECASE),  # "tip değişikliği"
    re.compile(r"pay\s*tipi\s*değiş", re.IGNORECASE),  # "pay tipi değişikliği"
    re.compile(r"pay\s*grubu\s*dönüş", re.IGNORECASE),
    re.compile(r"nama\s*yazılı.+hamiline",  re.IGNORECASE),  # nama → hamiline
    re.compile(r"hamiline.+nama\s*yazılı",  re.IGNORECASE),  # hamiline → nama
]

# ── Bedelsiz sermaye artırımı kalıpları ──────────────────────────────────────
# KAP'ta yayımlanan "Bedelsiz Sermaye Artırımı" ve "Rüçhan Hakkı" duyuruları
# hisse başına bedava pay alımı anlamına gelir → güçlü yükseliş katalizörü.
_PATTERNS_BEDELSIZ = [
    re.compile(r"bedelsiz\s*sermaye\s*artır",   re.IGNORECASE),
    re.compile(r"bedelsiz\s*hisse",             re.IGNORECASE),
    re.compile(r"bedelsiz\s*pay",               re.IGNORECASE),
    re.compile(r"ücretsiz\s*sermaye\s*artır",   re.IGNORECASE),
    re.compile(r"iç\s*kaynaklardan\s*sermaye",  re.IGNORECASE),
    re.compile(r"iç\s*kaynak.*sermaye\s*artır", re.IGNORECASE),
    re.compile(r"sermaye\s*artır.*bedelsiz",    re.IGNORECASE),
    re.compile(r"bedelsiz\s*oran",              re.IGNORECASE),
    re.compile(r"rüçhan\s*hakkı\s*kullan",      re.IGNORECASE),
    re.compile(r"rüçhan.*bedelsiz",             re.IGNORECASE),
]

# ── Bedelsiz GERÇEKLEŞMİŞ (tamamlanmış) kalıpları ────────────────────────────
# Bu kalıplar haber başlığında eşleşirse bedelsiz ZATEN GERÇEKLEŞMIŞ demektir;
# bekleyen bir katalizör olmadığından puan VERİLMEZ.
_PATTERNS_BEDELSIZ_DONE = [
    re.compile(r"tescil\s+edildi",                       re.IGNORECASE),
    re.compile(r"tescil\s+tamamland",                    re.IGNORECASE),
    re.compile(r"sermaye\s+artı[sş]ı.*tescil",           re.IGNORECASE),
    re.compile(r"tescil.*sermaye\s+artı",                re.IGNORECASE),
    re.compile(r"bedelsiz.*dağıtıldı",                   re.IGNORECASE),
    re.compile(r"dağıtım.*tamamland",                    re.IGNORECASE),
    re.compile(r"pay.*dağıtıldı",                        re.IGNORECASE),
    re.compile(r"hak.*kullanım.*tamamland",              re.IGNORECASE),
    re.compile(r"hak\s+kullanımı\s+tamamland",           re.IGNORECASE),
    re.compile(r"bedelsiz.*hesaba\s+aktarıldı",          re.IGNORECASE),
    re.compile(r"hesaba\s+aktarıldı.*bedelsiz",          re.IGNORECASE),
    re.compile(r"artırım\s+gerçekle[sş]ti",              re.IGNORECASE),
    re.compile(r"sermaye\s+artı[sş]ı\s+gerçekle[sş]ti", re.IGNORECASE),
    re.compile(r"kullanım\s+süresi.*sona",               re.IGNORECASE),
    re.compile(r"rüçhan.*tamamland",                     re.IGNORECASE),
]

# ── Bedelsiz BAŞVURU / ONAY (henüz gerçekleşmemiş) kalıpları ─────────────────
# Bu kalıplar eşleşirse bedelsiz BAŞVURU veya ONAY aşamasındadır → puan VERİLİR.
_PATTERNS_BEDELSIZ_PENDING = [
    re.compile(r"spk.*başvur",                           re.IGNORECASE),
    re.compile(r"başvur.*spk",                           re.IGNORECASE),
    re.compile(r"başvurusu\s+yapıldı",                   re.IGNORECASE),
    re.compile(r"başvurdu",                              re.IGNORECASE),
    re.compile(r"yönetim\s+kurulu.*bedelsiz",            re.IGNORECASE),
    re.compile(r"bedelsiz.*yönetim\s+kurulu",            re.IGNORECASE),
    re.compile(r"yk.*bedelsiz",                          re.IGNORECASE),
    re.compile(r"bedelsiz.*yk",                          re.IGNORECASE),
    re.compile(r"spk.*onay",                             re.IGNORECASE),
    re.compile(r"onay.*spk",                             re.IGNORECASE),
    re.compile(r"kurul\s+onayı",                         re.IGNORECASE),
    re.compile(r"izahname",                              re.IGNORECASE),
    re.compile(r"tescil\s+başvuru",                      re.IGNORECASE),
    re.compile(r"hak\s+kullanım\s+tarih",               re.IGNORECASE),  # tarih duyurusu = yaklaşıyor ama bitmedi
    re.compile(r"rüçhan.*hak\s+kullanım\s+tarih",       re.IGNORECASE),
]

# Bedelsiz cache (tipe dönüşümden ayrı)
_BED_CACHE: dict[str, tuple[float, int, list]] = {}
_BED_CACHE_TTL = 1800
_BED_CACHE_LOCK = threading.Lock()


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _symbol_match(sembol: str, code: str) -> bool:
    """KAP haberinin 'sembol' alanı virgüllü liste. Hisse gerçekten
    listede mi, kontrol et."""
    if not sembol:
        return True
    parts = [p.strip().upper() for p in sembol.split(",")]
    return code.upper() in parts


def kap_tipe_donusum_bonus(stock: dict) -> tuple[int, list[tuple[str, str, int]]]:
    """Dipteki hisseler için KAP 'Tipe Dönüşüm' bonusu.

    Mantık (kullanıcı kuralı):
        • Hisse TÜM ZAMAN dibinde (pos52wk ≤ 35) olmalı
          (artık pencere 52 hafta değil; tüm geçmiş fiyat verisi kullanılır)
        • KAP'ta son 52 hafta içinde "Borsada İşlem Gören Tipe Dönüşüm
          Duyurusu" çıkmış olmalı
        Bu iki şart sağlanırsa **olay yaşına bakılmaksızın** sabit base
        puan verilir; yalnızca dip derinliğine göre çarpanla artar.

    Puanlama:
        base = 80  (sabit — yaş önemli değil)
        çarpan: pos52<10 → ×1.30, pos52<20 → ×1.15, pos52<35 → ×1.0
        tavan = +100

    Dönüş:
        (toplam_puan, [(emoji, açıklama, puan), ...])
    """
    items: list[tuple[str, str, int]] = []
    code = (stock.get("code") or stock.get("symbol") or "").upper()
    if not code or code in ("XU100", "XU030", "XBANK"):
        return 0, items

    pos52 = _f(stock.get("pos52wk"), 50)
    # Sadece dipteki hisseler
    if pos52 > 35:
        return 0, items

    _hydrate()
    # Cache kontrol
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(code)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1], list(cached[2])

    # Haberleri çek (geniş set — fetch_news kendi içinde 50 cache'liyor)
    try:
        from ..extras._news import fetch_news
        data = fetch_news(code, adet=50) or {}
    except Exception:
        return 0, items

    haberler = data.get("haberler") or []
    if not haberler:
        with _CACHE_LOCK:
            _CACHE[code] = (now, 0, [])
        _persist_cache()
        return 0, items

    today = datetime.now()
    best_age:    float | None = None
    best_baslik: str = ""

    for h in haberler:
        baslik = (h.get("baslik") or "").strip()
        if not baslik:
            continue
        if not _symbol_match(h.get("sembol") or "", code):
            continue
        # Tipe dönüşüm deseni eşleşiyor mu?
        if not any(p.search(baslik) for p in _PATTERNS_TIPE_DONUSUM):
            continue
        dt = _parse_date(h.get("tarih") or "")
        if dt is None:
            continue
        age_d = (today - dt).total_seconds() / 86400.0
        # 52 hafta (364 gün) penceresi — daha eski haberleri yoksay
        if age_d < 0 or age_d > 364:
            continue
        if best_age is None or age_d < best_age:
            best_age = age_d
            best_baslik = baslik

    if best_age is None:
        with _CACHE_LOCK:
            _CACHE[code] = (now, 0, [])
        _persist_cache()
        return 0, items

    # ── Puanlama: SABİT base — yaş skor üzerinde etkili değil ────────────
    base = 80

    # Başlık örneğini kısalt
    snippet = best_baslik
    if len(snippet) > 110:
        snippet = snippet[:107] + "…"

    items.append(("📜",
                  f"KAP 'Tipe Dönüşüm' duyurusu var: {snippet}",
                  base))

    # ── Dip derinliği çarpanı ─────────────────────────────────────────────
    if pos52 < 10:
        mult = 1.30
        items.append(("📉", f"Tüm zaman derin dip (%{round(pos52)}) — bonus x1.30", 0))
    elif pos52 < 20:
        mult = 1.15
        items.append(("📉", f"Tüm zaman dip bölgesi (%{round(pos52)}) — bonus x1.15", 0))
    else:
        mult = 1.0

    total = int(round(base * mult))
    total = max(0, min(100, total))  # tavan +100 puan

    with _CACHE_LOCK:
        _CACHE[code] = (now, total, items)
    _persist_cache()
    return total, items


def reset_kap_news_cache() -> None:
    """Cache'i sıfırla — taze haberlerden tekrar hesaplansın (disk + bellek)."""
    with _CACHE_LOCK:
        _CACHE.clear()
    with _BED_CACHE_LOCK:
        _BED_CACHE.clear()
    with _WATCHLIST_LOCK:
        _WATCHLIST_CACHE["ts"] = 0.0
        _WATCHLIST_CACHE["data"] = []
    _persist_cache(force=True)
    _persist_watchlist(force=True)


def kap_bedelsiz_bonus(stock: dict) -> tuple[int, list[tuple[str, str, int]]]:
    """KAP'ta yayımlanan bedelsiz sermaye artırımı duyurusu için puan.

    Mantık (kullanıcı kuralı):
        • Sadece BAŞVURU veya ONAY aşamasındaki bedelsizler puan alır.
        • Bedelsiz ZATEN GERÇEKLEŞMIŞSE (tescil/dağıtım/hesaba aktarıldı) → 0 puan.
        • Kural: En son ilgili KAP haberi "gerçekleşmiş" kalıbıyla eşleşiyorsa puan yok.
          En son ilgili haber "başvuru/onay" kalıbıyla eşleşiyorsa puan verilir.
        • Son 365 gün içinde taranan haberler değerlendirilir.
        • Yaş etkisi (başvuru tarihine göre): 0-30 gün → ×1.30, 30-90 gün → ×1.10,
          90-365 gün → ×1.0

    Puanlama:
        base = 55  (yaşa göre çarpan)
        tavan = +70 puan

    Dönüş:
        (toplam_puan, [(emoji, açıklama, puan), ...])
    """
    items: list[tuple[str, str, int]] = []
    code = (stock.get("code") or stock.get("symbol") or "").upper()
    if not code or code in ("XU100", "XU030", "XBANK"):
        return 0, items

    now = time.time()
    with _BED_CACHE_LOCK:
        cached = _BED_CACHE.get(code)
    if cached and (now - cached[0]) < _BED_CACHE_TTL:
        return cached[1], list(cached[2])

    try:
        from ..extras._news import fetch_news
        data = fetch_news(code, adet=50) or {}
    except Exception:
        return 0, items

    haberler = data.get("haberler") or []
    if not haberler:
        with _BED_CACHE_LOCK:
            _BED_CACHE[code] = (now, 0, [])
        return 0, items

    today = datetime.now()

    # En son "gerçekleşmiş" ve "başvuru/onay" haberlerini ayrı ayrı bul
    latest_done_age:    float | None = None
    latest_done_baslik: str = ""
    latest_pend_age:    float | None = None
    latest_pend_baslik: str = ""

    for h in haberler:
        baslik = (h.get("baslik") or "").strip()
        if not baslik:
            continue
        if not _symbol_match(h.get("sembol") or "", code):
            continue
        # Önce genel bedelsiz kalıbıyla eşleşmeli
        if not any(p.search(baslik) for p in _PATTERNS_BEDELSIZ):
            continue
        dt = _parse_date(h.get("tarih") or "")
        if dt is None:
            continue
        age_d = (today - dt).total_seconds() / 86400.0
        if age_d < 0 or age_d > 365:
            continue

        is_done    = any(p.search(baslik) for p in _PATTERNS_BEDELSIZ_DONE)
        is_pending = any(p.search(baslik) for p in _PATTERNS_BEDELSIZ_PENDING)

        if is_done:
            if latest_done_age is None or age_d < latest_done_age:
                latest_done_age    = age_d
                latest_done_baslik = baslik
        elif is_pending:
            # Açıkça "done" değilse ve "pending" kalıbıyla eşleşiyorsa
            if latest_pend_age is None or age_d < latest_pend_age:
                latest_pend_age    = age_d
                latest_pend_baslik = baslik
        else:
            # Ne done ne pending → genel bedelsiz haberi; pending gibi işle
            if latest_pend_age is None or age_d < latest_pend_age:
                latest_pend_age    = age_d
                latest_pend_baslik = baslik

    # Hiç eşleşme yoksa 0
    if latest_done_age is None and latest_pend_age is None:
        with _BED_CACHE_LOCK:
            _BED_CACHE[code] = (now, 0, [])
        return 0, items

    # En son gerçekleşmiş, en son başvurudan daha YENİYSE → bedelsiz tamamlanmış, puan yok
    if latest_done_age is not None:
        if latest_pend_age is None or latest_done_age <= latest_pend_age:
            # done haberi daha yeni (veya pending hiç yok) → gerçekleşmiş
            snip = latest_done_baslik[:100] + "…" if len(latest_done_baslik) > 103 else latest_done_baslik
            items.append(("✅", f"Bedelsiz zaten gerçekleşmiş ({int(latest_done_age)}g önce): {snip}", 0))
            with _BED_CACHE_LOCK:
                _BED_CACHE[code] = (now, 0, items)
            return 0, items

    # Başvuru/onay aşamasında → puan ver
    best_age    = latest_pend_age
    best_baslik = latest_pend_baslik

    base = 55
    snippet = best_baslik[:107] + "…" if len(best_baslik) > 110 else best_baslik
    stage = "başvuru" if any(p.search(best_baslik) for p in _PATTERNS_BEDELSIZ_PENDING) else "bekleniyor"
    items.append(("📋", f"KAP Bedelsiz {stage}: {snippet}", base))

    if best_age < 30:
        mult = 1.30
        items.append(("🔥", f"Taze bedelsiz {stage} ({int(best_age)} gün önce) — bonus x1.30", 0))
    elif best_age < 90:
        mult = 1.10
        items.append(("📅", f"Yakın bedelsiz {stage} ({int(best_age)} gün önce) — bonus x1.10", 0))
    else:
        mult = 1.0

    total = int(round(base * mult))
    total = max(0, min(70, total))

    with _BED_CACHE_LOCK:
        _BED_CACHE[code] = (now, total, items)
    return total, items


def _scan_one_for_event(stock: dict, window_days: int) -> dict | None:
    """Tek bir hisse için 'Tipe Dönüşüm' KAP olayını ``window_days`` içinde ara.

    Eşleşirse hisse meta + olay bilgilerini içeren dict döner; yoksa ``None``.
    Bu fonksiyon ``kap_tipe_donusum_bonus``tan farklı olarak ``pos52wk`` filtresi
    UYGULAMAZ — watchlist tüm hisseleri kapsar.
    """
    code = (stock.get("code") or stock.get("symbol") or "").upper()
    if not code or code in ("XU100", "XU030", "XBANK"):
        return None
    try:
        from ..extras._news import fetch_news
        data = fetch_news(code, adet=50) or {}
    except Exception:
        return None
    haberler = data.get("haberler") or []
    if not haberler:
        return None
    today = datetime.now()
    best_age: float | None = None
    best_baslik = ""
    best_link = ""
    best_tarih = ""
    for h in haberler:
        baslik = (h.get("baslik") or "").strip()
        if not baslik:
            continue
        if not _symbol_match(h.get("sembol") or "", code):
            continue
        if not any(p.search(baslik) for p in _PATTERNS_TIPE_DONUSUM):
            continue
        dt = _parse_date(h.get("tarih") or "")
        if dt is None:
            continue
        age_d = (today - dt).total_seconds() / 86400.0
        if age_d < 0 or age_d > window_days:
            continue
        if best_age is None or age_d < best_age:
            best_age = age_d
            best_baslik = baslik
            best_link = (h.get("link") or "").strip()
            best_tarih = (h.get("tarih") or "").strip()
    if best_age is None:
        return None
    return {
        "code": code,
        "pos52wk": _f(stock.get("pos52wk"), 0.0),
        "guncel": _f(stock.get("guncel"), 0.0),
        "score": _f(stock.get("score", stock.get("predatorScore", 0)), 0.0),
        "sektor": (stock.get("sektor") or stock.get("sector") or "").strip() or "—",
        "ageDays": round(float(best_age), 1),
        "baslik": best_baslik,
        "link": best_link,
        "tarih": best_tarih,
    }


def kap_tipe_watchlist(stocks: list[dict],
                       window_days: int = 30,
                       max_workers: int = 8,
                       force: bool = False) -> dict:
    """KAP 'Tipe Dönüşüm' duyurusu olan tüm hisseleri ``window_days`` içinde tara.

    Sonuç ``pos52wk`` (52 haftalık pozisyon) artan sıralı döner — yani 52 haftalık
    dipte olanlar en üstte. 15 dakika cache'lenir; ``force=True`` ile yeniden
    hesaplanır.

    Dönüş şeması:
        {
          "ok": True,
          "ts": <unix_ts>,
          "ageSec": <hesaplamadan beri saniye>,
          "windowDays": <window>,
          "scanned": <taranan hisse sayısı>,
          "matched": <eşleşen hisse sayısı>,
          "items": [
            {code, pos52wk, guncel, score, sektor, ageDays, baslik, link, tarih},
            ...
          ]
        }
    """
    _hydrate()
    now = time.time()
    with _WATCHLIST_LOCK:
        cached = dict(_WATCHLIST_CACHE)
    if (not force
            and cached.get("data")
            and cached.get("window") == window_days
            and (now - float(cached.get("ts") or 0)) < _WATCHLIST_TTL):
        return {
            "ok": True,
            "ts": int(cached["ts"]),
            "ageSec": int(now - float(cached["ts"])),
            "windowDays": window_days,
            "scanned": int(cached.get("scanned") or 0),
            "matched": len(cached["data"]),
            "items": list(cached["data"]),
            "fromCache": True,
        }

    if not stocks:
        return {
            "ok": True,
            "ts": int(now),
            "ageSec": 0,
            "windowDays": window_days,
            "scanned": 0,
            "matched": 0,
            "items": [],
            "fromCache": False,
        }

    matches: list[dict] = []
    futures = {}
    workers = max(1, min(16, int(max_workers)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for s in stocks:
            futures[pool.submit(_scan_one_for_event, s, window_days)] = s
        for fut in as_completed(futures):
            try:
                hit = fut.result()
            except Exception:
                hit = None
            if hit is not None:
                matches.append(hit)

    matches.sort(key=lambda r: (float(r.get("pos52wk", 0) or 0),
                                float(r.get("ageDays", 999) or 999)))

    with _WATCHLIST_LOCK:
        _WATCHLIST_CACHE["ts"] = now
        _WATCHLIST_CACHE["window"] = window_days
        _WATCHLIST_CACHE["scanned"] = len(stocks)
        _WATCHLIST_CACHE["data"] = matches
    _persist_watchlist(force=True)

    return {
        "ok": True,
        "ts": int(now),
        "ageSec": 0,
        "windowDays": window_days,
        "scanned": len(stocks),
        "matched": len(matches),
        "items": matches,
        "fromCache": False,
    }
