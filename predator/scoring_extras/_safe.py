"""Tip-güvenli sayı/dize dönüşüm yardımcıları."""

from __future__ import annotations

from typing import Any


def _safe_num(v: Any, default: float = 0.0) -> float:
    """Dict/None/str gelse bile güvenli sayı döndürür (dict ise value/k/score arar)."""
    if v is None:
        return float(default)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        for key in ("value", "val", "k", "score", "v"):
            if key in v:
                try:
                    return float(v[key])
                except (TypeError, ValueError):
                    pass
        return float(default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _safe_str(v: Any, default: str) -> str:
    if v is None:
        return default
    if isinstance(v, dict):
        for key in ("dir", "cross", "trend", "signal", "value"):
            if key in v and isinstance(v[key], str):
                return v[key]
        return default
    return str(v) if not isinstance(v, str) else v
