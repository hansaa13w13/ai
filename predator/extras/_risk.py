"""Monte Carlo risk simülasyonu ve Kelly kriteri."""
from __future__ import annotations

import math

import numpy as np


def run_monte_carlo_risk(entry: float, stop: float, h1: float, h2: float,
                         daily_vol_pct: float, days: int = 10, iters: int = 500) -> dict:
    if entry <= 0 or daily_vol_pct <= 0:
        return {"var95": 0, "var99": 0, "expectedReturn": 0, "probH1": 0, "probStop": 0, "paths": []}
    sigma = daily_vol_pct / 100
    rng = np.random.default_rng()
    finals = []
    hit_h1 = hit_stop = 0
    paths_sample = []
    for it in range(iters):
        price = entry; h1_hit = stop_hit = False
        path = [round(price, 4)]
        for _ in range(days):
            z = rng.standard_normal()
            price = price * math.exp(-0.5 * sigma * sigma + sigma * z)
            if stop > 0 and price <= stop and not h1_hit:
                stop_hit = True; price = stop; break
            if h1   > 0 and price >= h1   and not stop_hit:
                h1_hit   = True; price = h1; break
            if it < 10:
                path.append(round(price, 4))
        if it < 10:
            paths_sample.append(path)
        if h1_hit:   hit_h1 += 1
        if stop_hit: hit_stop += 1
        finals.append(price)
    arr = np.array(finals)
    rets = (arr - entry) / entry * 100
    return {"var95":  round(float(np.percentile(rets, 5)), 2),
            "var99":  round(float(np.percentile(rets, 1)), 2),
            "expectedReturn": round(float(rets.mean()), 2),
            "probH1":  round(hit_h1 / iters * 100, 1),
            "probStop": round(hit_stop / iters * 100, 1),
            "paths":   paths_sample, "iters": iters, "days": days}


def calculate_kelly_criterion(win_rate: float, avg_win_pct: float, avg_loss_pct: float,
                              portfolio_value: float = 100000.0, max_risk_pct: float = 0.02) -> dict:
    if win_rate <= 0 or win_rate >= 1 or avg_win_pct <= 0 or avg_loss_pct <= 0:
        return {"fullKelly": 0, "halfKelly": 0, "positionTL": 0, "positionPct": 0,
                "riskTL": 0, "verdict": "veri_yetersiz", "bRatio": 0}
    p = max(0.01, min(0.99, win_rate)); q = 1 - p
    b = avg_win_pct / avg_loss_pct
    full = (p * b - q) / b
    half = max(0, min(0.25, full / 2))
    risk_frac = max_risk_pct / (avg_loss_pct / 100) if avg_loss_pct > 0 else 0.02
    final = min(half, risk_frac)
    pos_tl = round(portfolio_value * final)
    pos_pct = round(final * 100, 2)
    risk_tl = round(pos_tl * avg_loss_pct / 100)
    if   full <= 0:    verdict = "pozisyon_alma"
    elif half < 0.05:  verdict = "kucuk_pozisyon"
    elif half < 0.15:  verdict = "normal_pozisyon"
    else:              verdict = "buyuk_pozisyon"
    return {"fullKelly": round(full, 4), "halfKelly": round(half, 4),
            "positionTL": pos_tl, "positionPct": pos_pct, "riskTL": risk_tl,
            "verdict": verdict, "bRatio": round(b, 2)}
