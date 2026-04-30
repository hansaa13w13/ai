"""Tavan & Katlama Radar bonus wrapper for scoring pipeline.

`tavan_katlama` modülünü scan.py içinden çağırarak aiScore bonusu üretir.
"""
from __future__ import annotations

from .. import tavan_katlama as tk


def tavan_radar_bonus(stock: dict, archive: list[dict] | None = None) -> tuple[int, dict]:
    """Bir hisseye tavan/katlama analizini uygula ve bonus döndür.

    Yan etki: stock dict tavan/katlama alanlarıyla zenginleştirilir.
    """
    res = tk.apply_tavan_katlama(stock, ohlc=None, archive=archive)
    items = {
        "tavan":   res["tavan"],
        "katlama": res["katlama"],
        "next":    res["next"],
        "reasons": res["reasons"][:5],
    }
    return int(res["bonus"]), items


__all__ = ["tavan_radar_bonus"]
