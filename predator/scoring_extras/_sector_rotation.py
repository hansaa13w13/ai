"""Sektör rotasyon takibi — Erken Yakalama Bonusu.

Mantık: Sektör henüz yükselişe geçmemişken (yatay/aşağı), tek bir hisse
52 hafta dibinde ve sessizce birikim sinyalleri veriyorsa, bu hisse o
sektör rotasyonunun ilk dalgasını yakalama potansiyeline sahiptir.

Yatırımcı avantajı: Sektör hareketlenmeden önce binmek.

PHP karşılığı: yok (Python tarafında yeni eklenen özellik).
"""
from __future__ import annotations

from typing import Any

from .. import config
from ..utils import load_json


_SECTOR_CACHE: dict | None = None


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def get_sector_metrics() -> dict[str, dict]:
    """Sektör başına toplu metrikleri döndür (cache).

    Dönüş:
        {
            "BANKA": {"count": 12, "avg_roc20": -2.1, "avg_roc5": -0.5,
                      "avg_rsi": 41, "avg_pos52": 28, "rising_pct": 33,
                      "rotation": "uyuyor"},
            ...
        }

    Rotation etiketleri:
        - "patliyor"   → avg_roc20 > 8       (zaten geç)
        - "isiniyor"   → 3 < avg_roc20 ≤ 8   (orta)
        - "uyaniyor"   → 0 < avg_roc20 ≤ 3   (erken)
        - "uyuyor"     → -3 ≤ avg_roc20 ≤ 0  (en erken — ALTIN AN)
        - "dusuyor"    → avg_roc20 < -3      (kapitülasyon — fırsat veya tuzak)
    """
    global _SECTOR_CACHE
    if _SECTOR_CACHE is not None:
        return _SECTOR_CACHE

    data = load_json(config.ALLSTOCKS_CACHE, {}) or {}
    stocks = data.get("allStocks") or data.get("topPicks") or data.get("stocks") or []
    if not isinstance(stocks, list) or not stocks:
        _SECTOR_CACHE = {}
        return _SECTOR_CACHE

    groups: dict[str, list] = {}
    for s in stocks:
        sek = (s.get("sektor") or "genel").strip()
        if not sek:
            continue
        groups.setdefault(sek, []).append(s)

    out: dict[str, dict] = {}
    for sek, lst in groups.items():
        n = len(lst)
        if n < 2:
            continue
        roc20s = [_f(x.get("roc20")) for x in lst]
        roc5s = [_f(x.get("roc5")) for x in lst]
        rsis = [_f(x.get("rsi"), 50) for x in lst]
        pos52s = [_f(x.get("pos52wk"), 50) for x in lst]
        rising = sum(1 for x in lst if _f(x.get("gunlukDegisim")) > 0)
        avg_roc20 = sum(roc20s) / n
        avg_roc5 = sum(roc5s) / n
        avg_rsi = sum(rsis) / n
        avg_pos52 = sum(pos52s) / n
        rising_pct = round(rising / n * 100, 1)

        if avg_roc20 > 8:
            rot = "patliyor"
        elif avg_roc20 > 3:
            rot = "isiniyor"
        elif avg_roc20 > 0:
            rot = "uyaniyor"
        elif avg_roc20 >= -3:
            rot = "uyuyor"
        else:
            rot = "dusuyor"

        out[sek] = {
            "count": n,
            "avg_roc20": round(avg_roc20, 2),
            "avg_roc5": round(avg_roc5, 2),
            "avg_rsi": round(avg_rsi, 1),
            "avg_pos52": round(avg_pos52, 1),
            "rising_pct": rising_pct,
            "rotation": rot,
        }

    _SECTOR_CACHE = out
    return out


def early_catch_bonus(stock: dict) -> tuple[int, list[tuple[str, str, int]]]:
    """Erken yakalama bonusu — sektör uyurken dipteki hisseyi ödüllendir.

    Dönüş:
        (toplam_puan, [(emoji, açıklama, puan), ...])

    Kapılar (FOMO koruması):
        - Hisse zaten katlamış / pos52 > 50 / roc20 > 15 → 0
        - Sektör verisi yoksa veya sektör grubu < 2 hisse → 0
    """
    items: list[tuple[str, str, int]] = []

    if stock.get("katlamis"):
        return 0, items
    pos52 = _f(stock.get("pos52wk"), 50)
    roc20 = _f(stock.get("roc20"))
    if pos52 > 50 or roc20 > 15:
        return 0, items

    sek = (stock.get("sektor") or "").strip()
    if not sek or sek == "genel":
        return 0, items

    metrics = get_sector_metrics()
    sm = metrics.get(sek)
    if not sm:
        return 0, items

    rot = sm.get("rotation", "")
    s_roc20 = float(sm.get("avg_roc20", 0))
    s_pos52 = float(sm.get("avg_pos52", 50))
    s_rising = float(sm.get("rising_pct", 50))

    # ── Senaryo 1: Sektör çakılmış + hisse tabanda → KAPITÜLASYON FIRSATI
    if rot == "dusuyor" and pos52 < 15 and roc20 > -10:
        items.append((
            "🎣",
            f"Sektör çakılmış (avg %{s_roc20}) ama hisse dipte tutunuyor — kapitülasyon fırsatı",
            18,
        ))
    # ── Senaryo 2: Sektör uyuyor + hisse dipte → EN GÜÇLÜ ERKEN YAKALAMA
    elif rot == "uyuyor" and pos52 < 15:
        items.append((
            "🐣",
            f"Sektör uyuyor (avg %{s_roc20}) + hisse 52H tabanında — erken yakalama altın anı",
            16,
        ))
    elif rot == "uyuyor" and pos52 < 25:
        items.append((
            "🐣",
            f"Sektör uyuyor (avg %{s_roc20}) + hisse alt çeyrekte — erken yakalama",
            11,
        ))
    # ── Senaryo 3: Sektör uyanıyor + hisse hala dipte → İLK DALGADA BIN
    elif rot == "uyaniyor" and pos52 < 20:
        items.append((
            "🌅",
            f"Sektör uyanıyor (avg %{s_roc20}) + hisse hala dipte — ilk dalga",
            13,
        ))
    elif rot == "uyaniyor" and pos52 < 30:
        items.append((
            "🌅",
            f"Sektör uyanıyor (avg %{s_roc20}) + hisse alt çeyrekte",
            7,
        ))

    # ── Bonus: Sektörün geneli de dipte ise (ortak taban) → ek +4
    if s_pos52 < 30 and items:
        items.append((
            "🪨",
            f"Sektör geneli de tabanda (sektör avg pos52 %{round(s_pos52)})",
            4,
        ))

    # ── Bonus: Sessiz akıllı para sızıyorken sektör henüz hareketsiz → ek +5
    quiet_score = 0
    if _f(stock.get("cmf")) > 0.05:
        quiet_score += 1
    if stock.get("obvTrend") == "artis":
        quiet_score += 1
    if _f(stock.get("netParaAkis")) > 0:
        quiet_score += 1
    if quiet_score >= 2 and rot in ("uyuyor", "uyaniyor", "dusuyor") and items:
        items.append((
            "🤐",
            "Sektör hareketsizken bu hissede sessiz akıllı para sızması",
            5,
        ))

    # ── Tuzak filtresi: Sektör boğa breadth çok düşükse (< 25% rising) → ½ ceza yok
    # (yalnızca pozitif bonusları zaten yukarıda kapıladık)

    total = sum(p for _, _, p in items)
    return total, items


def reset_sector_cache() -> None:
    """Tarama sonunda cache'i sıfırla — bir sonraki ekran yenilemesinde
    güncel verilerle yeniden hesaplansın."""
    global _SECTOR_CACHE
    _SECTOR_CACHE = None
