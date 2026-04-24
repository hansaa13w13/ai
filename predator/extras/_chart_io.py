"""CHART2 → mum listesi, JSON cache yardımcıları, ATR ve idealdata text yardımcısı."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .. import config
from ..api_client import fetch_chart2
from ..indicators import atr as ind_atr
from ..utils import parse_api_num


def fetch_chart2_candles(code: str, periyot: str = "G", bar: int = 220) -> list[dict]:
    raw = fetch_chart2(code, periyot=periyot, bar=bar)
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for b in raw:
        if not isinstance(b, dict):
            continue
        o = parse_api_num(b.get("Open", b.get("Acilis", 0)))
        h = parse_api_num(b.get("High", b.get("Yuksek", 0)))
        l = parse_api_num(b.get("Low",  b.get("Dusuk",  0)))
        c = parse_api_num(b.get("Close", b.get("Kapanis", 0)))
        v = parse_api_num(b.get("Vol", b.get("Volume", b.get("Hacim", 0))))
        t = str(b.get("Date", b.get("Tarih", "")))
        if c <= 0 or h <= 0 or l <= 0:
            continue
        if o <= 0:
            o = c
        out.append({"Open": o, "High": max(h, o, c),
                    "Low": min(l, o, c) if l > 0 else min(o, c),
                    "Close": c, "Vol": v, "Date": t})
    return out


def _read_json_cache(path: Path, ttl: int) -> Any:
    try:
        if path.exists() and (time.time() - path.stat().st_mtime) < ttl:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _write_json_cache(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def calculate_atr_chart(chart_data: list[dict], period: int = 14) -> float:
    if len(chart_data) < period + 1:
        return 0.0
    H = [b.get("High", b.get("Close", 0)) for b in chart_data]
    L = [b.get("Low",  b.get("Close", 0)) for b in chart_data]
    C = [b.get("Close", 0) for b in chart_data]
    return float(ind_atr(H, L, C, period))


def _ideal_text(suffix: str, timeout: int = 10) -> str:
    """idealdata API'den ham metin yanıt al (PHP'deki garip ?ayraç biçimi)."""
    from ..http_utils import safe_request
    url = f"{config.API_BASE_URL}/cmd={suffix}?lang=tr"
    r = safe_request("GET", url,
                     headers={"Referer": config.API_REFERER,
                              "User-Agent": "Mozilla/5.0"},
                     timeout=timeout, retries=2, backoff=0.5,
                     metric_kind="api_ideal_text")
    if r is None or r.status_code != 200 or not r.content:
        return ""
    try:
        return r.content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return r.content.decode("iso-8859-9")
        except UnicodeDecodeError:
            return r.text
