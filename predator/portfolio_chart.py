"""Portföydeki açık pozisyon için grafik üreticisi.

Açık pozisyon varsa ilk hissenin son ~120 günlük mum verisini çeker ve
fiyat eğrisinin üzerine GİRİŞ / H1 / H2 / H3 / STOP seviyelerini çizer.
Üretilen JPG byte'ları `cache_backup` tarafından şifreli yedeğin kapak
resmi olarak kullanılır.
"""
from __future__ import annotations

import io
import time
from pathlib import Path
from typing import Any

from .observability import log_event

_CACHE_TTL = 600
_CACHE_BYTES: bytes = b""
_CACHE_TS: float = 0.0
_CACHE_KEY: tuple = ()

_W, _H = 1280, 720
_MARGIN_L = 110
_MARGIN_R = 220
_MARGIN_T = 110
_MARGIN_B = 70

_BG = (10, 14, 22)
_GRID = (38, 46, 60)
_AXIS = (120, 130, 145)
_TEXT = (220, 228, 240)
_TITLE = (255, 255, 255)
_PRICE_LINE = (90, 200, 255)
_PRICE_FILL = (90, 200, 255, 40)
_GREEN = (0, 220, 130)
_GREEN_SOFT = (0, 200, 120)
_YELLOW = (250, 200, 50)
_RED = (255, 90, 90)
_BLUE = (120, 170, 255)
_BADGE_BG = (24, 32, 46)


def _font(size: int):
    from PIL import ImageFont  # geç içe-aktarma
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _font_regular(size: int):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _select_position() -> dict | None:
    """Açık pozisyonlardan birini seç — pnl_pct mutlak değeri en büyük olan
    yoksa ilk eklenen."""
    try:
        from .portfolio import oto_load
        oto = oto_load()
    except Exception as e:
        log_event("portfolio_chart", f"oto_load failed: {e}", level="warn")
        return None
    positions = oto.get("positions", {}) or {}
    if not positions:
        return None
    items = list(positions.values())
    items.sort(key=lambda p: abs(float(p.get("pnl_pct", 0) or 0)), reverse=True)
    return items[0]


def _fetch_candles(code: str, bars: int = 120) -> list[dict]:
    try:
        from .extras._chart_io import fetch_chart2_candles
        candles = fetch_chart2_candles(code, periyot="G", bar=bars + 20)
    except Exception as e:
        log_event("portfolio_chart",
                  f"fetch_chart2_candles failed: {e}", level="warn", code=code)
        return []
    if not candles:
        return []
    return candles[-bars:]


def _format_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.0f}".replace(",", ".")
    if p >= 100:
        return f"{p:.1f}"
    return f"{p:.2f}"


def _draw_chart(pos: dict, candles: list[dict]) -> bytes:
    from PIL import Image, ImageDraw

    code = str(pos.get("code", "?"))
    entry = float(pos.get("entry", 0) or 0)
    cur = float(pos.get("guncel", entry) or entry)
    h1 = float(pos.get("h1", 0) or 0)
    h2 = float(pos.get("h2", 0) or 0)
    h3 = float(pos.get("h3", 0) or 0)
    stop = float(pos.get("stop", 0) or 0)
    ai = str(pos.get("ai_decision_live") or pos.get("ai_decision") or "").strip()
    ai_conf = int(pos.get("ai_conf_live", pos.get("ai_conf", 0)) or 0)
    pnl = float(pos.get("pnl_pct", 0) or 0)

    closes = [float(b.get("Close", 0) or 0) for b in candles if b.get("Close")]
    highs = [float(b.get("High", 0) or 0) for b in candles if b.get("High")]
    lows = [float(b.get("Low", 0) or 0) for b in candles if b.get("Low")]
    if not closes:
        closes = [entry, cur]
        highs = closes[:]
        lows = closes[:]

    levels = [v for v in (entry, cur, h1, h2, h3, stop) if v > 0]
    pmin = min(min(lows), min(levels)) * 0.985
    pmax = max(max(highs), max(levels)) * 1.015
    if pmax <= pmin:
        pmax = pmin + 1.0

    img = Image.new("RGB", (_W, _H), _BG)
    draw = ImageDraw.Draw(img, "RGBA")

    # Üst başlık şeridi
    draw.rectangle((0, 0, _W, 70), fill=(16, 22, 34))
    f_title = _font(34)
    f_sub = _font_regular(18)
    f_med = _font(20)
    f_small = _font_regular(15)
    f_badge = _font(16)

    sign = "+" if pnl >= 0 else ""
    pnl_color = _GREEN if pnl >= 0 else _RED
    title = f"PREDATOR · {code}"
    draw.text((28, 18), title, font=f_title, fill=_TITLE)
    sub = f"Giriş {_format_price(entry)}₺   →   Şu an {_format_price(cur)}₺"
    draw.text((28, 56), sub, font=f_sub, fill=_TEXT)
    pnl_txt = f"{sign}{pnl:.2f}%"
    bbox = draw.textbbox((0, 0), pnl_txt, font=f_title)
    pw = bbox[2] - bbox[0]
    draw.text((_W - 28 - pw, 18), pnl_txt, font=f_title, fill=pnl_color)
    if ai:
        ai_line = f"AI: {ai}" + (f" · %{ai_conf}" if ai_conf else "")
        bbox2 = draw.textbbox((0, 0), ai_line, font=f_sub)
        pw2 = bbox2[2] - bbox2[0]
        draw.text((_W - 28 - pw2, 56), ai_line, font=f_sub, fill=_BLUE)

    # Grafik alanı sınırları
    x0, y0 = _MARGIN_L, _MARGIN_T
    x1, y1 = _W - _MARGIN_R, _H - _MARGIN_B

    def y_for(p: float) -> float:
        return y1 - (p - pmin) / (pmax - pmin) * (y1 - y0)

    # Grid + sol Y ekseni etiketleri
    draw.rectangle((x0, y0, x1, y1), outline=_AXIS, width=1)
    n_grid = 6
    for i in range(n_grid + 1):
        gy = y0 + (y1 - y0) * i / n_grid
        draw.line((x0, gy, x1, gy), fill=_GRID, width=1)
        price = pmax - (pmax - pmin) * i / n_grid
        draw.text((10, gy - 9), _format_price(price) + "₺",
                  font=f_small, fill=_AXIS)

    # Fiyat eğrisi (close line) — alttan dolgu
    n = len(closes)
    if n >= 2:
        step = (x1 - x0) / max(1, n - 1)
        pts = [(x0 + i * step, y_for(closes[i])) for i in range(n)]
        # Dolgu poligonu
        poly = pts + [(x1, y1), (x0, y1)]
        draw.polygon(poly, fill=_PRICE_FILL)
        # Çizgi
        draw.line(pts, fill=_PRICE_LINE, width=3)
        # Son nokta
        lx, ly = pts[-1]
        draw.ellipse((lx - 6, ly - 6, lx + 6, ly + 6),
                     fill=_PRICE_LINE, outline=_TITLE, width=2)

    # Hedef/stop çizgileri + sağda etiket
    rows: list[tuple[str, float, tuple, str]] = []
    if h3 > 0: rows.append(("H3", h3, _GREEN, "🎯"))
    if h2 > 0: rows.append(("H2", h2, _GREEN_SOFT, "🎯"))
    if h1 > 0: rows.append(("H1", h1, _YELLOW, "🎯"))
    if entry > 0: rows.append(("GİRİŞ", entry, _BLUE, "•"))
    if stop > 0: rows.append(("STOP", stop, _RED, "🛑"))

    legend_x = x1 + 16
    used_y: list[float] = []
    for label, price, color, _icon in rows:
        if not (pmin <= price <= pmax):
            continue
        ly = y_for(price)
        # Çizgi (kesikli)
        dash = 14
        gap = 8
        cx = x0
        while cx < x1:
            cxe = min(cx + dash, x1)
            draw.line((cx, ly, cxe, ly), fill=color, width=2)
            cx = cxe + gap
        # Sol fiyat etiketi rozeti
        ptxt = _format_price(price) + "₺"
        bb = draw.textbbox((0, 0), ptxt, font=f_badge)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        rx0, ry0 = x0 - tw - 16, ly - th / 2 - 4
        rx1, ry1 = x0 - 4, ly + th / 2 + 4
        draw.rectangle((rx0, ry0, rx1, ry1), fill=color)
        draw.text((rx0 + 6, ry0 + 2), ptxt, font=f_badge, fill=(10, 14, 22))
        # Sağda büyük etiket — çakışmayı az çok ayır
        ty = ly - 10
        for uy in used_y:
            if abs(ty - uy) < 22:
                ty = uy + 22
        used_y.append(ty)
        pct = ((price - cur) / cur * 100) if cur > 0 else 0.0
        sign = "+" if pct >= 0 else ""
        legend_txt = f"{label} {ptxt}"
        sub_txt = f"{sign}{pct:.1f}%"
        draw.text((legend_x, ty), legend_txt, font=f_med, fill=color)
        draw.text((legend_x, ty + 22), sub_txt, font=f_small, fill=_TEXT)

    # Alt bar: tarih aralığı + zaman damgası
    draw.rectangle((0, _H - 28, _W, _H), fill=(16, 22, 34))
    if candles:
        d0 = str(candles[0].get("Date", ""))[:10]
        d1 = str(candles[-1].get("Date", ""))[:10]
        date_txt = f"{d0}  →  {d1}   ·   {len(candles)} bar"
    else:
        date_txt = "veri yok"
    ts_txt = time.strftime("Üretildi: %d.%m.%Y %H:%M", time.localtime())
    draw.text((20, _H - 22), date_txt, font=f_small, fill=_AXIS)
    bb = draw.textbbox((0, 0), ts_txt, font=f_small)
    draw.text((_W - 20 - (bb[2] - bb[0]), _H - 22),
              ts_txt, font=f_small, fill=_AXIS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()


def _fallback_jpg() -> bytes:
    """Pozisyon yok / kütüphane yok — eski statik kapak."""
    p = Path(__file__).parent / "assets" / "cover.jpg"
    try:
        return p.read_bytes()
    except OSError:
        # Asgari geçerli minimal JPG
        return (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01"
                b"\x00\x01\x00\x00\xff\xdb\x00C\x00" + b"\x08" * 64 +
                b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
                b"\xff\xc4\x00\x14\x00\x01" + b"\x00" * 15 + b"\x09"
                b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfa\xff\xd9")


def render_cover_jpg() -> bytes:
    """Açık pozisyondaki hisse için grafik JPG'si üret. Hata olursa
    statik kapak resmine geri düşer. 10 dakikalık in-memory cache."""
    global _CACHE_BYTES, _CACHE_TS, _CACHE_KEY
    pos = _select_position()
    if not pos:
        return _fallback_jpg()
    key = (str(pos.get("code")),
           round(float(pos.get("guncel", 0) or 0), 4),
           round(float(pos.get("h1", 0) or 0), 4),
           round(float(pos.get("stop", 0) or 0), 4))
    now = time.time()
    if (_CACHE_BYTES and key == _CACHE_KEY
            and (now - _CACHE_TS) < _CACHE_TTL):
        return _CACHE_BYTES
    try:
        candles = _fetch_candles(str(pos.get("code", "")))
        jpg = _draw_chart(pos, candles)
        _CACHE_BYTES, _CACHE_TS, _CACHE_KEY = jpg, now, key
        log_event("portfolio_chart",
                  f"rendered chart for {pos.get('code')}",
                  level="info", bars=len(candles), kb=len(jpg) // 1024)
        return jpg
    except Exception as e:
        log_event("portfolio_chart", f"render failed: {e}", level="warn")
        return _fallback_jpg()
