"""Predictive warm cache: top picks için tam analiz paketi (SMC/MC/Kelly/Weekly/...)."""
from __future__ import annotations

from .. import config
from ..utils import load_json, now_str
from ._chart_io import _write_json_cache, calculate_atr_chart, fetch_chart2_candles
from ._brain_stats import get_backtest_stats
from ._mtf import get_weekly_signal
from ._risk import calculate_kelly_criterion, run_monte_carlo_risk
from ._smc import calculate_smc, detect_harmonic_patterns
from ._volume import (
    calculate_adaptive_volatility,
    calculate_avwap_strategies,
    calculate_ofi_full,
    calculate_volume_profile,
    calculate_vwap_bands,
    detect_gap_analysis,
)


def compute_smc_pack(code: str, stock_entry: dict | None = None) -> dict:
    """act_smclevels ile aynı çıktı şemasını üretir; UI'dan bağımsız çağrılabilir."""
    code = (code or "").upper()
    if not code:
        return {"ok": False, "err": "Geçersiz sembol"}
    candles = fetch_chart2_candles(code, periyot="G", bar=150)
    if len(candles) < 20:
        return {"ok": False, "err": "Veri yetersiz"}
    smc_r   = calculate_smc(candles, 100)
    vp_r    = calculate_volume_profile(candles, 40)
    vwap_r  = calculate_vwap_bands(candles)
    avwap_r = calculate_avwap_strategies(candles, 120)
    gap_r   = detect_gap_analysis(candles)
    ofi_r   = calculate_ofi_full(candles, 20)
    harm_r  = detect_harmonic_patterns(candles, 80)
    av_r    = calculate_adaptive_volatility(candles, 20)
    last    = candles[-1]
    entry   = float(last.get("Close", 0))
    atr_v   = calculate_atr_chart(candles)
    daily_vol = (atr_v / entry * 100) if entry > 0 else 1.5

    if stock_entry is None:
        all_cache = load_json(config.ALLSTOCKS_CACHE, {}) or {}
        for key in ("topPicks", "stocks", "allStocks"):
            for s in (all_cache.get(key) or []):
                if (s.get("code") or "").upper() == code:
                    stock_entry = s; break
            if stock_entry: break
    stock_entry = stock_entry or {}
    tgts = stock_entry.get("targets", {}) or {}
    stop = float(tgts.get("stop",  entry * 0.95) or (entry * 0.95))
    h1   = float(tgts.get("sell1", entry * 1.08) or (entry * 1.08))
    h2   = float(tgts.get("sell2", entry * 1.15) or (entry * 1.15))

    mc_raw = run_monte_carlo_risk(entry, stop, h1, h2, daily_vol, 10, 500)
    _exp = float(mc_raw.get("expectedReturn", 0) or 0)
    _p95 = float(mc_raw.get("var95", 0) or 0)
    _ph1 = float(mc_raw.get("probH1", 0) or 0)
    _pst = float(mc_raw.get("probStop", 0) or 0)
    _std = max(0.01, abs(_exp - _p95) / 1.65) if _p95 != 0 else max(0.01, daily_vol)
    mc_r = dict(mc_raw); mc_r.update({
        "win_prob": _ph1,
        "h2_prob":  round(max(0.0, _ph1 * 0.55), 1),
        "stop_prob": _pst,
        "median_ret": _exp,
        "ev":        round(_exp, 2),
        "p95":       round(_exp + 1.65 * _std, 2),
        "p5":        _p95,
        "sharpe":    round(_exp / _std, 2) if _std > 0 else 0,
    })

    bt = get_backtest_stats(); bt10 = bt.get("t10", {}) if isinstance(bt, dict) else {}
    win   = float(bt10.get("win_rate", 55) or 55) / 100
    avg_w = abs(float(bt10.get("avg_gain", 7) or 7))
    avg_l = abs(float(bt10.get("avg_loss", -3.5) or -3.5))
    kelly = calculate_kelly_criterion(win, max(0.1, avg_w), max(0.1, avg_l),
                                      config.OTO_PORTFOLIO_VALUE, config.OTO_MAX_RISK_PCT)
    if isinstance(kelly, dict):
        kelly.setdefault("kelly_frac",   kelly.get("halfKelly", 0))
        kelly.setdefault("position_size", kelly.get("positionTL", 0))
        kelly.setdefault("max_risk_tl",  kelly.get("riskTL", 0))
        _pos = float(kelly.get("position_size") or 0)
        kelly.setdefault("lots_100", round(_pos / 100) if _pos else 0)

    weekly = get_weekly_signal(code)
    out = {
        "ok": True, "code": code, "smc": smc_r, "volProfile": vp_r,
        "vwapBands": vwap_r, "avwap": avwap_r, "gapAnalysis": gap_r, "ofi": ofi_r,
        "harmonics": harm_r, "adaptiveVol": av_r, "monteCarlo": mc_r,
        "kelly": kelly, "weeklySignal": weekly, "atr": round(atr_v, 4),
        "dailyVol": round(daily_vol, 2), "timestamp": now_str(),
    }
    cache_file = config.CACHE_DIR / f"predator_smc_{code}.json"
    _write_json_cache(cache_file, out)
    return out


def warm_smc_cache(picks: list[dict], max_workers: int = 6,
                   on_progress=None) -> dict:
    """Top pick listesindeki her hisse için tam analiz paketini önceden hesapla.

    Daemon tarama bittikten sonra çağırır → kullanıcı modal açtığında her şey hazır.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if not isinstance(picks, list) or not picks:
        return {"ok": 0, "err": 0, "total": 0}
    items = [(p.get("code") or "").upper() for p in picks if p.get("code")]
    items = [c for c in items if c]
    by_code = {(p.get("code") or "").upper(): p for p in picks if p.get("code")}
    ok = err = 0
    total = len(items)

    def _one(c: str) -> tuple[str, bool]:
        try:
            res = compute_smc_pack(c, by_code.get(c))
            ok_flag = bool(res and res.get("ok"))
            if ok_flag:
                pk = by_code.get(c)
                if isinstance(pk, dict):
                    if isinstance(res.get("harmonics"), list):
                        pk["harmonics"] = res["harmonics"]
                    if isinstance(res.get("smc"), dict):
                        pk["smcFull"] = res["smc"]
            return c, ok_flag
        except Exception:
            return c, False

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_one, c): c for c in items}
        done = 0
        for f in as_completed(futs):
            done += 1
            try:
                _, success = f.result()
                if success: ok += 1
                else:       err += 1
            except Exception:
                err += 1
            if on_progress:
                try: on_progress(done, total)
                except Exception: pass
    return {"ok": ok, "err": err, "total": total}
