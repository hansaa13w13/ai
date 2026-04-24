"""Monte Carlo simülasyonu ve Kelly Criterion."""
from __future__ import annotations
import math
import numpy as np
from typing import Any
from . import config
from .utils import load_json, save_json, now_str


def monte_carlo_forecast(closes: Any, days: int = 30, simulations: int = 500) -> dict:
    """GBM tabanlı Monte Carlo fiyat tahmini.

    v38 iyileştirmeleri:
      • `confidence` ∈ [0,1] alanı eklendi: kısa geçmiş, sıfır volatilite veya
        anormal-yüksek volatilite güveni düşürür.
      • `low_confidence` bayrağı: skoring ve UI bu sonucu daha az ağırlıklandırabilir.
      • Vektörize edilmiş GBM (Python loop yok) → 5-10x hızlanma.
      • `n_obs` & `sigma_ann` çıktıda raporlanır (şeffaflık).
    """
    c = np.asarray(closes, dtype=float)
    n = int(len(c))
    if n < 30:
        s0 = float(c[-1]) if n else 0.0
        return {"mean": s0, "p25": s0, "p75": s0, "p_up": 0.5, "exp_ret": 0.0,
                "confidence": 0.0, "low_confidence": True, "n_obs": n,
                "sigma_ann": 0.0, "reason": "insufficient_history"}
    window = c[-252:] if n > 252 else c
    log_ret = np.diff(np.log(window))
    mu = float(log_ret.mean())
    sigma = float(log_ret.std())
    s0 = float(c[-1])
    if sigma == 0:
        return {"mean": s0, "p25": s0, "p75": s0, "p_up": 0.5, "exp_ret": 0.0,
                "confidence": 0.0, "low_confidence": True, "n_obs": n,
                "sigma_ann": 0.0, "reason": "zero_volatility"}
    # Vektörize GBM — (simulations, days) Gaussian, kümülatif log getiri
    rng = np.random.default_rng()
    drift = mu - 0.5 * sigma * sigma
    Z = rng.standard_normal((simulations, days))
    log_paths = (drift + sigma * Z).sum(axis=1)
    end_prices = s0 * np.exp(log_paths)

    # Güven skoru: yeterli geçmiş + makul volatilite
    sigma_ann = sigma * math.sqrt(252)
    hist_conf = min(1.0, (n - 30) / 222.0)              # 30..252 → 0..1
    # Yıllık vol %10 ile %120 arası → güven 1.0; uçlarda ceza.
    if   sigma_ann < 0.10: vol_conf = sigma_ann / 0.10
    elif sigma_ann > 1.20: vol_conf = max(0.2, 1.20 / sigma_ann)
    else:                  vol_conf = 1.0
    confidence = round(hist_conf * vol_conf, 3)

    return {
        "mean":     float(end_prices.mean()),
        "p25":      float(np.percentile(end_prices, 25)),
        "p75":      float(np.percentile(end_prices, 75)),
        "p_up":     float((end_prices > s0).mean()),
        "exp_ret":  float((end_prices.mean() - s0) / s0 * 100),
        "confidence":     confidence,
        "low_confidence": confidence < 0.40,
        "n_obs":          n,
        "sigma_ann":      round(sigma_ann, 4),
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
