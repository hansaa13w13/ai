"""PHP findSwingLevels (10541) + clusterLevels (10552) birebir port.

S/R seviyelerini pivot tarama + ±2% klasterleme ile çıkarır.

v43: find_swing_levels O(n²) iç döngü kaldırıldı — sliding_window_view ile
tamamen vektörize edildi. clusterLevels O(n) kalıyor (inherently sequential).
"""
from __future__ import annotations
import numpy as np
from typing import Sequence


def find_swing_levels(chart_data: Sequence[dict], lookback: int = 5) -> list[dict]:
    """Pivot tepe/dip taraması — vectorized O(n) with sliding_window_view.

    Her bar için [i-lookback .. i+lookback] penceresinde mutlak max/min ise pivot.
    Returns: [{'price': float, 'type': 'sup'|'res'}, ...]
    """
    n = len(chart_data)
    w = 2 * lookback + 1
    if n < w:
        return []

    highs = np.array([float(b.get("High", b.get("Close", 0)) or 0) for b in chart_data])
    lows  = np.array([float(b.get("Low",  b.get("Close", 0)) or 0) for b in chart_data])

    win_H = np.lib.stride_tricks.sliding_window_view(highs, w)
    win_L = np.lib.stride_tricks.sliding_window_view(lows,  w)

    center = lookback  # center index inside each window
    center_H = win_H[:, center]
    center_L = win_L[:, center]

    is_res = (center_H == win_H.max(axis=1)) & (center_H > 0)
    is_sup = (center_L == win_L.min(axis=1)) & (center_L > 0)

    levels: list[dict] = []
    for idx in np.where(is_res)[0]:
        levels.append({"price": float(highs[idx + lookback]), "type": "res"})
    for idx in np.where(is_sup)[0]:
        levels.append({"price": float(lows[idx + lookback]), "type": "sup"})
    return levels


def cluster_levels(levels: list[dict], tolerance: float = 0.02) -> list[dict]:
    """±tolerance bandında pivotları birleştir, en güçlü 8'i döndür.
    Returns: [{'price': avg, 'type': 'sup'|'res', 'strength': int}]
    """
    if not levels:
        return []
    sorted_lv = sorted(levels, key=lambda x: x["price"])
    clusters: list[list[dict]] = []
    curr: list[dict] = [sorted_lv[0]]
    for lv in sorted_lv[1:]:
        anchor = curr[0]["price"]
        if abs(lv["price"] - anchor) / max(anchor, 0.001) < tolerance:
            curr.append(lv)
        else:
            clusters.append(curr)
            curr = [lv]
    clusters.append(curr)

    out: list[dict] = []
    for cl in clusters:
        if len(cl) < 2:
            continue
        avg = sum(x["price"] for x in cl) / len(cl)
        types = [x["type"] for x in cl]
        sup_cnt = sum(1 for t in types if t == "sup")
        out.append({
            "price": avg,
            "type": "sup" if sup_cnt >= len(cl) / 2 else "res",
            "strength": len(cl),
        })
    out.sort(key=lambda x: x["strength"], reverse=True)
    return out[:8]
