"""Haber, gündem, bilanço dış API yardımcıları (idealdata)."""
from __future__ import annotations

import time

from .. import config
from ._chart_io import _ideal_text, _read_json_cache, _write_json_cache


def fetch_news(code: str, adet: int = 5) -> dict:
    cache = config.CACHE_DIR / f"haber_{code.upper()}.json"
    cached = _read_json_cache(cache, 1800)
    if cached and len(cached.get("haberler") or []) >= min(50, adet):
        return cached
    # API'den her zaman geniş set (50) alınır; cache tüm seti tutar, çağrı
    # tarafına ``adet`` kadarı kesilip döner. Bu, bonus modüllerinin (örn.
    # KAP "Tipe Dönüşüm" — son 90 günde olabilir) geçmişi görmesini sağlar.
    raw = _ideal_text(f"HaberFirmaBasliklar?adet=50?symbol={code.upper()}", timeout=8)
    haberler = []
    if raw:
        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        if lines:
            lines = lines[1:]
        for line in lines:
            p = line.split("|", 5)
            if len(p) < 5: continue
            haberler.append({
                "id": p[0].strip(), "tarih": p[1].strip(),
                "kategori": p[2].strip(), "link": p[3].strip(),
                "sembol": p[4].strip(),
                "baslik": p[5].strip() if len(p) > 5 else ""
            })
    # Cache: tam set (50). Çağrı tarafına: adet kadarı.
    full = {"ok": True, "code": code.upper(), "haberler": haberler[:50]}
    _write_json_cache(cache, full)
    out = dict(full)
    out["haberler"] = haberler[:max(3, min(50, adet))]
    return out


def fetch_gundem() -> dict:
    cache = config.CACHE_DIR / "predator_gundem.json"
    cached = _read_json_cache(cache, 3600)
    if cached: return cached
    raw = _ideal_text("Gundem", timeout=10)
    events = []
    if raw:
        try:
            from xml.etree import ElementTree as ET
            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                raw2 = raw.encode("latin1", errors="ignore").decode("iso-8859-9", errors="ignore")
                root = ET.fromstring(raw2)
            for d in root.iter("data"):
                events.append({
                    "tarih": (d.findtext("tarih") or "").strip(),
                    "saat":  (d.findtext("saat")  or "").strip(),
                    "ulke":  (d.findtext("ulke")  or "").strip(),
                    "onem":  (d.findtext("onem")  or "").strip(),
                    "veri":  (d.findtext("veri")  or "").strip(),
                    "beklenti": (d.findtext("beklenti") or "").strip(),
                    "onceki": (d.findtext("onceki") or "").strip(),
                })
        except Exception:
            pass
    out = {"ok": True, "events": events, "ts": int(time.time())}
    _write_json_cache(cache, out)
    return out


def fetch_bilanco(code: str) -> dict:
    cache = config.CACHE_DIR / f"bilanco_{code.upper()}.json"
    cached = _read_json_cache(cache, 86400)
    if cached: return cached
    raw = _ideal_text(f"BilancoDetay?symbol={code.upper()}?konsolide=0", timeout=10)
    rows = []
    if raw:
        lines = [ln for ln in raw.split("\n") if ln.strip()]
        if lines:
            header = [h.strip() for h in lines[0].split(";")]
            for ln in lines[1:]:
                cols = ln.split(";")
                rows.append({header[i]: (cols[i].strip() if i < len(cols) else "")
                             for i in range(len(header))})
    out = {"ok": True, "code": code.upper(), "rows": rows}
    _write_json_cache(cache, out)
    return out
