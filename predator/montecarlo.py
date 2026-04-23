"""Monte Carlo simülasyonu ve Kelly Criterion."""
from __future__ import annotations
import numpy as np
from typing import Any
from . import config
from .utils import load_json, save_json, now_str


def monte_carlo_forecast(closes: Any, days: int = 30, simulations: int = 500) -> dict:
    """GBM tabanlı Monte Carlo fiyat tahmini."""
    c = np.asarray(closes, dtype=float)
    if len(c) < 30:
        return {"mean": 0.0, "p25": 0.0, "p75": 0.0, "p_up": 0.5, "exp_ret": 0.0}
    log_ret = np.diff(np.log(c[-252:] if len(c) > 252 else c))
    mu = log_ret.mean()
    sigma = log_ret.std()
    if sigma == 0:
        return {"mean": float(c[-1]), "p25": float(c[-1]), "p75": float(c[-1]),
                "p_up": 0.5, "exp_ret": 0.0}
    s0 = c[-1]
    rng = np.random.default_rng()
    end_prices = []
    for _ in range(simulations):
        path = s0
        for _ in range(days):
            path *= np.exp((mu - 0.5 * sigma * sigma) + sigma * rng.standard_normal())
        end_prices.append(path)
    end_prices = np.array(end_prices)
    return {
        "mean": float(end_prices.mean()),
        "p25": float(np.percentile(end_prices, 25)),
        "p75": float(np.percentile(end_prices, 75)),
        "p_up": float((end_prices > s0).mean()),
        "exp_ret": float((end_prices.mean() - s0) / s0 * 100),
    }


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Half-Kelly fraksiyonu (0..0.25)."""
    if avg_loss <= 0 or win_rate <= 0:
        return 0.0
    b = avg_win / avg_loss
    k = (win_rate * b - (1 - win_rate)) / b
    return max(0.0, min(0.25, k * 0.5))


def log_kelly(symbol: str, fraction: float, win_rate: float) -> None:
    logs = load_json(config.KELLY_LOG_FILE, [])
    if not isinstance(logs, list): logs = []
    logs.insert(0, {"time": now_str(), "code": symbol,
                    "fraction": round(fraction, 4), "win_rate": round(win_rate, 4)})
    if len(logs) > 200:
        logs = logs[:200]
    save_json(config.KELLY_LOG_FILE, logs)
