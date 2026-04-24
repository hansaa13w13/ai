"""Radar (compare/price) cache yükleme ve üyelik."""

from __future__ import annotations

from .. import config
from ..utils import load_json


_CMP_MAP_CACHE: dict | None = None
_PRC_MAP_CACHE: dict | None = None


def _load_radar_maps() -> None:
    global _CMP_MAP_CACHE, _PRC_MAP_CACHE
    if _CMP_MAP_CACHE is None:
        _CMP_MAP_CACHE = {}
        d = load_json(config.CACHE_DIR / "predator_compare_cache.json", {}) or {}
        for g in (d.get("groups") or []):
            if g.get("code"):
                _CMP_MAP_CACHE[g["code"]] = int(g.get("avgSim") or 0)
    if _PRC_MAP_CACHE is None:
        _PRC_MAP_CACHE = {}
        d = load_json(config.CACHE_DIR / "predator_price_compare_cache.json", {}) or {}
        for g in (d.get("groups") or []):
            if g.get("code"):
                _PRC_MAP_CACHE[g["code"]] = float(g.get("oppScore") or 0)


def get_radar_membership(code: str) -> dict:
    """PHP getRadarMembership birebir."""
    _load_radar_maps()
    cmp_sim = (_CMP_MAP_CACHE or {}).get(code, 0)
    prc_opp = (_PRC_MAP_CACHE or {}).get(code, 0.0)
    return {
        "inCmp":  cmp_sim >= 60,
        "cmpSim": cmp_sim,
        "inPrc":  prc_opp >= 45,
        "prcOpp": prc_opp,
    }


def reset_radar_caches() -> None:
    global _CMP_MAP_CACHE, _PRC_MAP_CACHE
    _CMP_MAP_CACHE = None
    _PRC_MAP_CACHE = None
