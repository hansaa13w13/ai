"""Brain istatistikleri ve geçmiş örnek arama; backtest istatistikleri."""
from __future__ import annotations

import math

from .. import config
from ..brain import brain_load
from ..utils import load_json


def brain_get_stats() -> dict:
    brain = brain_load()
    total_snaps = total_outcomes = 0
    for snaps in (brain.get("snapshots") or {}).values():
        for s in snaps:
            total_snaps += 1
            if s.get("outcome5") is not None:
                total_outcomes += 1
    form_stats = []
    for name, d in (brain.get("learned_weights", {}).get("formation") or {}).items():
        if d.get("count", 0) < 2: continue
        form_stats.append({"ad": name, "count": d["count"],
                           "win_rate": d.get("win_rate", 0), "avg_ret": d.get("avg_ret", 0),
                           "weight": d.get("weight", 1.0)})
    form_stats.sort(key=lambda x: x["count"], reverse=True)
    ind_stats = []
    for key, d in (brain.get("learned_weights", {}).get("indicator") or {}).items():
        if d.get("count", 0) < 3: continue
        avg = round(d.get("total_ret", 0) / d["count"], 2) if d["count"] > 0 else 0
        ind_stats.append({"key": key, "weight": d.get("weight", 1.0),
                          "count": d["count"], "avg_ret": avg})
    ind_stats.sort(key=lambda x: x["weight"], reverse=True)
    acc = brain.get("prediction_accuracy") or {"toplam": 0, "dogru": 0, "oran": 0.0}
    conf_stats = []
    for key, d in (brain.get("confluence_patterns") or {}).items():
        if d.get("count", 0) < 6: continue
        conf_stats.append({"key": key, "win_rate": d.get("win_rate", 0),
                           "count": d["count"], "avg_ret": d.get("avg_ret", 0),
                           "weight": d.get("weight", 1.0)})
    conf_stats.sort(key=lambda x: x["count"], reverse=True)
    sm_matrix = []
    for key, d in (brain.get("sector_mode_matrix") or {}).items():
        if d.get("count", 0) < 5: continue
        sm_matrix.append({"key": key, "win_rate": d.get("win_rate", 0),
                          "count": d["count"], "avg_ret": d.get("avg_ret", 0)})
    sm_matrix.sort(key=lambda x: x["win_rate"], reverse=True)
    nn = brain.get("neural_net") or {}
    nnb = brain.get("neural_net_beta") or {}
    return {
        "takip_edilen_hisse": len(brain.get("snapshots") or {}),
        "toplam_snapshot": total_snaps,
        "degerlendirilmis": total_outcomes,
        "total_scans": brain.get("total_scans", 0),
        "son_guncelleme": brain.get("last_updated", "Henüz yok"),
        "formasyon_istatistik": form_stats[:10],
        "indikatör_istatistik": ind_stats[:15],
        "sektor_perf": brain.get("sector_perf") or {},
        "version": brain.get("version", 1),
        "pred_toplam": int(acc.get("toplam", 0) or 0),
        "pred_dogru":  int(acc.get("dogru",  0) or 0),
        "pred_oran":   float(acc.get("oran",  0.0) or 0.0),
        "confluence_stats": conf_stats[:5],
        "mode_performance": brain.get("mode_perf_detail") or {},
        "time_patterns":    brain.get("time_patterns")    or {},
        "volatility_learning": brain.get("volatility_learning") or {},
        "sector_mode_matrix":  sm_matrix[:10],
        "alpha_trained":  int(nn.get("trained_samples", 0) or 0),
        "alpha_accuracy": float(nn.get("recent_accuracy", 0.0) or 0.0),
        "alpha_avg_loss": float(nn.get("avg_loss", 1.0) or 1.0),
        "beta_trained":   int(nnb.get("trained_samples", 0) or 0),
        "beta_accuracy":  float(nnb.get("recent_accuracy", 0.0) or 0.0),
        "beta_avg_loss":  float(nnb.get("avg_loss", 1.0) or 1.0),
        "dual_stats":     brain.get("dual_brain_stats") or {},
    }


def brain_find_similar_history(code: str, stock: dict) -> dict | list:
    brain = brain_load()
    snaps = (brain.get("snapshots") or {}).get(code, [])
    if not snaps:
        return []
    rsi_v   = float(stock.get("rsi", 50))
    mode    = stock.get("marketMode", "bull")
    form_names = [f.get("ad") for f in (stock.get("formations") or [])]
    vol_r   = float(stock.get("volRatio", 1))
    trend   = stock.get("trend", "Notr")
    cmf     = float(stock.get("cmf", 0))
    cmf_dir = "pos" if cmf > 0.05 else ("neg" if cmf < -0.05 else "notr")
    sektor  = stock.get("sektor", "")
    similar = []
    for s in snaps:
        if s.get("outcome5") is None: continue
        s_rsi = float(s.get("rsi", 50))
        s_mode = s.get("marketMode", "bull")
        s_forms = s.get("formations", []) or []
        s_vol = float(s.get("volRatio", 1))
        s_trend = s.get("trend", "Notr")
        s_cmf = float(s.get("cmf", 0))
        s_cmf_dir = "pos" if s_cmf > 0.05 else ("neg" if s_cmf < -0.05 else "notr")
        s_sektor = s.get("sektor", "")
        score = 0
        diff = abs(rsi_v - s_rsi)
        if diff < 5: score += 3
        elif diff < 10: score += 2
        elif diff < 18: score += 1
        if s_mode == mode: score += 2
        common = len(set(form_names) & set(s_forms))
        score += min(6, common * 3)
        vd = abs(vol_r - s_vol)
        if vd < 0.3: score += 2
        elif vd < 0.7: score += 1
        if s_trend == trend: score += 2
        if s_cmf_dir == cmf_dir: score += 1
        if sektor and s_sektor == sektor: score += 1
        st_d = stock.get("supertrendDir", "notr")
        hu_d = stock.get("hullDir", "notr")
        smc_b = stock.get("smcBias", "notr")
        if s.get("supertrendDir", "notr") == st_d and st_d != "notr": score += 2
        if s.get("hullDir", "notr") == hu_d and hu_d != "notr": score += 2
        if s.get("smcBias", "notr") == smc_b and smc_b != "notr": score += 2
        if "ofiSig" in s and s["ofiSig"] == stock.get("ofiSig", "notr") and stock.get("ofiSig", "notr") != "notr":
            score += 1
        if "vwapPos" in s and s["vwapPos"] == stock.get("vwapPos", "icinde") and stock.get("vwapPos", "icinde") != "icinde":
            score += 1
        if score >= 5:
            similar.append({"ret": float(s["outcome5"]), "date": s.get("date", ""), "score": score})
    if not similar:
        return []
    similar.sort(key=lambda x: x["score"], reverse=True)
    top = similar[:7]
    rets = [t["ret"] for t in top]
    return {
        "count": len(top),
        "avg_ret": round(sum(rets) / len(rets), 2),
        "win_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 0),
        "samples": top,
    }


def get_backtest_stats() -> dict:
    if not config.SIGNAL_HISTORY_FILE.exists():
        return {"toplam_sinyal": 0}
    hist = load_json(config.SIGNAL_HISTORY_FILE, []) or []
    if not hist:
        return {"toplam_sinyal": 0}
    live_prices = {}
    cache = load_json(config.ALLSTOCKS_CACHE, {}) or {}
    for s in cache.get("stocks", []) or []:
        c = s.get("code"); p = float(s.get("guncel", 0) or 0)
        if c and p > 0: live_prices[c] = p
    temp_results = {}
    for h in hist:
        if h.get("result5") is not None: continue
        code = h.get("code", "")
        if not code or code not in live_prices: continue
        ep = float(h.get("price", 0) or 0)
        if ep <= 0: continue
        temp_results[h.get("date", "") + "|" + code] = round((live_prices[code] - ep) / ep * 100, 2)

    def empty_t(): return {"count": 0, "win": 0, "total_ret": 0.0, "max_ret": -9999, "min_ret": 9999}
    out = {
        "toplam_sinyal": len(hist), "bekleyen": 0,
        "t5": empty_t(), "t10": empty_t(), "t20": empty_t(),
        "by_formation": [], "by_mode": {}, "by_score_tier": {}, "by_sektor": [],
        "best": [], "worst": [], "equity": [], "equity_final": 100.0,
        "equity_gain": 0.0, "sharpe_approx": 0.0,
    }
    by_form, by_mode, by_tier, by_sektor = {}, {}, {}, {}
    t5list, rets5 = [], []
    for h in hist:
        code = h.get("code", "")
        date = (h.get("date") or "")[:10]
        score = int(h.get("aiScore", 0) or 0)
        mode  = h.get("marketMode", "bull")
        tier  = "160+" if score >= 160 else ("120-159" if score >= 120 else ("80-119" if score >= 80 else "<80"))
        sektor = h.get("sektor", "genel")
        live_key = (h.get("date") or "") + "|" + code
        r5 = h.get("result5")
        r5_use = r5 if r5 is not None else temp_results.get(live_key)
        if r5_use is None and h.get("result10") is None and h.get("result20") is None:
            out["bekleyen"] += 1
        for k, field in (("t10", "result10"), ("t20", "result20")):
            v = h.get(field)
            if v is None: continue
            r = float(v)
            o = out[k]; o["count"] += 1
            if r > 0: o["win"] += 1
            o["total_ret"] += r
            if r > o["max_ret"]: o["max_ret"] = r
            if r < o["min_ret"]: o["min_ret"] = r
        if r5_use is not None:
            r = float(r5_use); o = out["t5"]; o["count"] += 1
            if r > 0: o["win"] += 1
            o["total_ret"] += r
            if r > o["max_ret"]: o["max_ret"] = r
            if r < o["min_ret"]: o["min_ret"] = r
            rets5.append(r)
            for form in (h.get("formations") or []):
                if not form: continue
                d = by_form.setdefault(form, {"count": 0, "win": 0, "ret": 0.0})
                d["count"] += 1
                if r > 0: d["win"] += 1
                d["ret"] += r
            d = by_mode.setdefault(mode, {"count": 0, "win": 0, "ret": 0.0})
            d["count"] += 1
            if r > 0: d["win"] += 1
            d["ret"] += r
            d = by_tier.setdefault(tier, {"count": 0, "win": 0, "ret": 0.0})
            d["count"] += 1
            if r > 0: d["win"] += 1
            d["ret"] += r
            d = by_sektor.setdefault(sektor, {"count": 0, "win": 0, "ret": 0.0})
            d["count"] += 1
            if r > 0: d["win"] += 1
            d["ret"] += r
            t5list.append({"code": code, "date": date, "ret": r, "score": score, "mode": mode})
    for k in ("t5", "t10", "t20"):
        c = out[k]["count"]
        out[k]["win_rate"] = round(out[k]["win"] / c * 100, 1) if c > 0 else 0
        out[k]["avg_ret"]  = round(out[k]["total_ret"] / c, 2) if c > 0 else 0
        if out[k]["max_ret"] == -9999: out[k]["max_ret"] = 0
        if out[k]["min_ret"] ==  9999: out[k]["min_ret"] = 0
    if len(rets5) >= 5:
        avg5 = sum(rets5) / len(rets5)
        std = math.sqrt(sum((r - avg5) ** 2 for r in rets5) / len(rets5))
        out["sharpe_approx"] = round(avg5 / std, 2) if std > 0 else 0
    flist = []
    for name, d in by_form.items():
        c = d["count"]
        flist.append({"ad": name, "count": c,
                      "win_rate": round(d["win"] / c * 100, 1) if c > 0 else 0,
                      "avg_ret":  round(d["ret"] / c, 2)        if c > 0 else 0})
    flist.sort(key=lambda x: x["count"], reverse=True)
    out["by_formation"] = flist[:12]
    for m, d in by_mode.items():
        c = d["count"]
        out["by_mode"][m] = {"count": c,
                             "win_rate": round(d["win"] / c * 100, 1) if c > 0 else 0,
                             "avg_ret":  round(d["ret"] / c, 2)        if c > 0 else 0}
    for tier, d in by_tier.items():
        c = d["count"]
        out["by_score_tier"][tier] = {"count": c,
                                      "win_rate": round(d["win"] / c * 100, 1) if c > 0 else 0,
                                      "avg_ret":  round(d["ret"] / c, 2)        if c > 0 else 0}
    seklist = []
    for sek, d in by_sektor.items():
        c = d["count"]
        if c < 2: continue
        seklist.append({"sektor": sek, "count": c,
                        "win_rate": round(d["win"] / c * 100, 1),
                        "avg_ret":  round(d["ret"] / c, 2)})
    seklist.sort(key=lambda x: x["win_rate"], reverse=True)
    out["by_sektor"] = seklist
    if t5list:
        ranked = sorted(t5list, key=lambda x: x["ret"], reverse=True)
        out["best"]  = ranked[:5]
        out["worst"] = sorted(t5list, key=lambda x: x["ret"])[:5]
        chrono = sorted(t5list, key=lambda x: x["date"])
        eq = 100.0; curve = []
        for sig in chrono[-40:]:
            eq = round(eq * (1 + sig["ret"] / 100), 2)
            curve.append({"date": sig["date"], "val": eq, "code": sig["code"], "ret": sig["ret"]})
        out["equity"] = curve
        out["equity_final"] = eq
        out["equity_gain"] = round(eq - 100, 2)
    return out
