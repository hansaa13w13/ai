"""PHP findSwingLevels (10541) + clusterLevels (10552) birebir port.

S/R seviyelerini pivot tarama + ±2% klasterleme ile çıkarır.
"""
from __future__ import annotations
from typing import Sequence


def find_swing_levels(chart_data: Sequence[dict], lookback: int = 5) -> list[dict]:
    """Pivot tepe/dip taraması.
    Her bar için lookback±lookback penceresinde mutlak max/min ise pivot kabul edilir.
    Returns: [{'price': float, 'type': 'sup'|'res'}, ...]
    """
    levels: list[dict] = []
    n = len(chart_data)
    if n <= 2 * lookback:
        return levels
    for i in range(lookback, n - lookback):
        bar = chart_data[i]
        high = float(bar.get("High", bar.get("Close", 0)) or 0)
        low  = float(bar.get("Low",  bar.get("Close", 0)) or 0)

        is_high = True
        for j in range(i - lookback, i + lookback + 1):
            if j == i: continue
            o = chart_data[j]
            v = float(o.get("High", o.get("Close", 0)) or 0)
            if v > high:
                is_high = False; break
        if is_high and high > 0:
            levels.append({"price": high, "type": "res"})

        is_low = True
        for j in range(i - lookback, i + lookback + 1):
            if j == i: continue
            o = chart_data[j]
            v = float(o.get("Low", o.get("Close", 999_999)) or 999_999)
            if v < low:
                is_low = False; break
        if is_low and low > 0:
            levels.append({"price": low, "type": "sup"})
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
