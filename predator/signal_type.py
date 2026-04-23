"""PHP getSignalTipi (index.php:10061) birebir port.

aiScore + bearish koşullar → GÜÇLÜ AL / AL / NOTR / SAT / GÜÇLÜ SAT.
"""
from __future__ import annotations


def get_signal_tipi(ai_score: int, formations: list[dict] | None = None,
                    tech: dict | None = None) -> dict:
    """PHP getSignalTipi birebir.

    Returns: {'tip': str, 'renk': str, 'emoji': str}
    """
    formations = formations or []
    tech = tech or {}
    rsi       = float(tech.get("rsi", 50) or 50)
    pos52     = float(tech.get("pos52wk", 50) or 50)
    macd      = tech.get("macd") or {}
    macd_cross = macd.get("cross") if isinstance(macd, dict) else tech.get("macdCross", "none")
    if not macd_cross: macd_cross = tech.get("macdCross", "none")
    sar       = tech.get("sar") or {}
    sar_dir   = sar.get("direction") if isinstance(sar, dict) else tech.get("sarDir", "notr")
    if not sar_dir: sar_dir = tech.get("sarDir", "notr")
    hull_dir  = tech.get("hullDir", "notr")
    adx       = tech.get("adx") or {}
    adx_dir   = adx.get("dir") if isinstance(adx, dict) else tech.get("adxDir", "notr")
    if not adx_dir: adx_dir = tech.get("adxDir", "notr")
    cmf       = float(tech.get("cmf", 0) or 0)

    bear_count = sum(1 for f in formations if (f.get("tip") or "") == "bearish")
    bull_count = sum(1 for f in formations if (f.get("tip") or "") != "bearish")

    strong_bearish = (
        (rsi > 75 and macd_cross == "death")
        or (bear_count >= 2)
        or (rsi > 78 and pos52 > 85 and hull_dir == "dusus")
        or (bear_count >= 1 and cmf < -0.2 and rsi > 65)
    )

    # (strong_bullish PHP'de hesaplansa da kullanılmıyor — birebir korunuyor)
    _strong_bullish = (
        (bull_count >= 2 and rsi < 50 and cmf > 0)
        or (rsi < 30 and macd_cross == "golden")
        or (pos52 < 15 and bull_count >= 1)
    )

    if ai_score >= 155 and not strong_bearish:
        return {"tip": "GÜÇLÜ AL", "renk": "#00ff9d", "emoji": "🚀"}
    if ai_score >= 100 and not strong_bearish:
        return {"tip": "AL",       "renk": "#00f3ff", "emoji": "✅"}
    if ai_score >= 65 and not strong_bearish and bear_count == 0:
        return {"tip": "NOTR",     "renk": "#888888", "emoji": "➡️"}
    if ai_score < 40 or strong_bearish:
        return {"tip": "GÜÇLÜ SAT","renk": "#ff003c", "emoji": "🔴"}
    return {"tip": "SAT",          "renk": "#ff6633", "emoji": "⚠️"}
