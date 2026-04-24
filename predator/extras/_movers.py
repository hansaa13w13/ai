"""Benzer hareket motoru: teknik fingerprint ve saf fiyat (cosine) eşleştirme."""
from __future__ import annotations

import math
import time

from .. import config
from ._chart_io import _read_json_cache, _write_json_cache


def _stock_fingerprint(s: dict) -> dict:
    forms = sorted([f.get("ad") for f in (s.get("formations") or []) if f.get("ad")])
    return {
        "ret1m": float(s.get("ret1m", 0) or 0),
        "ret3m": float(s.get("ret3m", 0) or 0),
        "retYil": float(s.get("retYil", 0) or 0),
        "rsi": float(s.get("rsi", 50) or 50),
        "aiScore": int(s.get("aiScore", 0) or 0),
        "macd": str(s.get("macdCross", "") or ""),
        "sar":  str(s.get("sarDir", "")    or ""),
        "bb":   bool(s.get("bbSqueeze")),
        "adx":  float(s.get("adxVal", 0) or 0),
        "pos52wk": float(s.get("pos52wk", 50) or 50),
        "vol":  float(s.get("volRatio", 1) or 1),
        "forms": forms,
        "sektor": str(s.get("sektor", "") or ""),
        "cap": float(s.get("marketCap", 0) or 0),
    }


def _movement_similarity(a: dict, b: dict) -> int:
    score = 0
    rd = abs(a["rsi"] - b["rsi"])
    if rd < 5: score += 20
    elif rd < 10: score += 12
    elif rd < 20: score += 5
    if a["macd"] and a["macd"] == b["macd"]: score += 15
    if a["sar"]  and a["sar"]  == b["sar"]:  score += 10
    if a["bb"] and b["bb"]: score += 8
    if a["adx"] >= 20 and b["adx"] >= 20:
        ad = abs(a["adx"] - b["adx"])
        if ad < 5: score += 10
        elif ad < 15: score += 5
    wd = abs(a["pos52wk"] - b["pos52wk"])
    if wd < 10: score += 12
    elif wd < 20: score += 6
    if a["forms"] and b["forms"]:
        common = len(set(a["forms"]) & set(b["forms"]))
        score += min(20, common * 7)
    if a["sektor"] and a["sektor"] == b["sektor"]: score += 5
    return min(100, score)


def find_similar_movers(all_stocks: list[dict]) -> dict:
    cache = config.CACHE_DIR / "predator_compare_cache.json"
    cached = _read_json_cache(cache, 900)
    if cached and cached.get("groups"):
        return cached
    leaders, candidates = {}, {}
    for s in all_stocks:
        code = s.get("code")
        if not code: continue
        fp = _stock_fingerprint(s)
        price = float(s.get("guncel", 0) or 0)
        kat = bool(s.get("katlamis"))
        if kat or fp["ret3m"] > 40 or fp["retYil"] > 80:
            leaders[code] = {"stock": s, "fp": fp, "price": price}
        elif price > 0 and price < 150 and int(s.get("aiScore", 0) or 0) >= 30 and not kat:
            candidates[code] = {"stock": s, "fp": fp, "price": price}
    groups = []
    for cc, cd in candidates.items():
        cfp = cd["fp"]; matched = []
        for lc, ld in leaders.items():
            sim = _movement_similarity(cfp, ld["fp"])
            if sim >= 30:
                matched.append({"code": lc, "sim": sim, "ret3m": ld["fp"]["ret3m"],
                                "retYil": ld["fp"]["retYil"], "price": ld["price"],
                                "sektor": ld["fp"]["sektor"], "katlamis": bool(ld["stock"].get("katlamis"))})
        if not matched: continue
        matched.sort(key=lambda x: x["sim"], reverse=True)
        top = matched[:3]
        avg = round(sum(t["sim"] for t in top) / len(top))
        if avg < 30: continue
        s = cd["stock"]
        groups.append({
            "code": cc, "name": s.get("name", cc), "price": cd["price"],
            "aiScore": int(s.get("aiScore", 0) or 0), "rsi": round(cfp["rsi"], 1),
            "ret1m": cfp["ret1m"], "ret3m": cfp["ret3m"], "retYil": cfp["retYil"],
            "cap": cfp["cap"], "sektor": cfp["sektor"], "macd": cfp["macd"],
            "sar": cfp["sar"], "pos52wk": cfp["pos52wk"], "forms": cfp["forms"][:3],
            "leaders": top, "avgSim": avg,
            "formations": (s.get("formations") or [])[:3],
            "signalTipi": s.get("signalTipi", {"tip": "NOTR", "renk": "#888", "emoji": "→"}),
            "h1": float((s.get("targets") or {}).get("sell1", s.get("h1", 0)) or 0),
            "stop": float((s.get("targets") or {}).get("stop", s.get("stop", 0)) or 0),
            "rr": float(s.get("rr1", 0) or 0),
            "signalQuality": int(s.get("signalQuality", 0) or 0),
        })
    groups.sort(key=lambda g: g["avgSim"] * 0.5 + min(100, g["aiScore"] / 3.5) * 0.3 + max(0, 40 - g["pos52wk"]) * 0.5,
                reverse=True)
    result = {"ts": int(time.time()), "leader_count": len(leaders),
              "candidate_count": len(candidates), "groups": groups[:25]}
    _write_json_cache(cache, result)
    return result


def _price_mov_vec(s: dict) -> dict:
    def norm(v: float, cap: float) -> float:
        if cap <= 0: return 0.0
        return max(-1.0, min(1.0, v / cap))
    roc5  = float(s.get("roc5", 0) or 0); roc20 = float(s.get("roc20", 0) or 0)
    ret1m = float(s.get("ret1m", 0) or 0); ret3m = float(s.get("ret3m", 0) or 0)
    retY  = float(s.get("retYil", 0) or 0); fark = float(s.get("farkYuzde", 0) or 0)
    volR  = min(5.0, float(s.get("volRatio", 1) or 1))
    volM  = float(s.get("volMomentum", 100) or 100)
    pos52 = float(s.get("pos52wk", 50) or 50)
    atr14 = float(s.get("atr14", 0) or 0)
    g = max(0.001, float(s.get("guncel", 1) or 1))
    return {"roc5": norm(roc5, 20.0), "roc20": norm(roc20, 40.0),
            "ret1m": norm(ret1m, 60.0), "ret3m": norm(ret3m, 120.0),
            "retYil": norm(retY, 200.0), "fark": norm(fark, 8.0),
            "volR": norm(volR - 1, 4.0), "volM": norm(volM - 100, 100.0),
            "pos52": norm(pos52 - 50, 50.0), "atrRel": norm(atr14 / g * 100, 5.0)}


def _cosine_sim_pm(a: dict, b: dict) -> float:
    keys = a.keys()
    dot = magA = magB = 0.0
    for k in keys:
        av = float(a.get(k, 0)); bv = float(b.get(k, 0))
        dot += av * bv; magA += av * av; magB += bv * bv
    magA = math.sqrt(magA); magB = math.sqrt(magB)
    if magA < 1e-9 or magB < 1e-9: return 50.0
    return round((dot / (magA * magB) + 1.0) / 2.0 * 100.0, 1)


def find_price_only_movers(all_stocks: list[dict]) -> dict:
    cache = config.CACHE_DIR / "predator_price_compare_cache.json"
    cached = _read_json_cache(cache, 900)
    if cached and cached.get("groups"):
        return cached
    leaders, candidates = {}, {}
    for s in all_stocks:
        code = s.get("code")
        if not code: continue
        price = float(s.get("guncel", 0) or 0)
        ret3m = float(s.get("ret3m", 0) or 0)
        retY  = float(s.get("retYil", 0) or 0)
        kat = bool(s.get("katlamis"))
        roc5  = float(s.get("roc5", 0) or 0)
        roc20 = float(s.get("roc20", 0) or 0)
        cap = float(s.get("marketCap", 0) or 0)
        vec = _price_mov_vec(s)
        if kat or ret3m > 35 or retY > 70:
            leaders[code] = {"vec": vec, "ret3m": ret3m, "retYil": retY, "price": price,
                             "katlamis": kat, "code": code, "name": s.get("name", code),
                             "sektor": s.get("sektor", ""), "cap": cap, "roc5": roc5, "roc20": roc20}
        elif price > 0 and price < 120 and not kat and (roc5 > -5 or roc20 > 0):
            candidates[code] = {"vec": vec, "ret3m": ret3m, "retYil": retY, "price": price,
                                "code": code, "name": s.get("name", code),
                                "sektor": s.get("sektor", ""), "cap": cap,
                                "roc5": roc5, "roc20": roc20,
                                "aiScore": int(s.get("aiScore", 0) or 0),
                                "rsi": float(s.get("rsi", 50) or 50),
                                "pos52wk": float(s.get("pos52wk", 50) or 50),
                                "farkYuzde": float(s.get("farkYuzde", 0) or 0),
                                "volRatio": float(s.get("volRatio", 1) or 1),
                                "formations": (s.get("formations") or [])[:3],
                                "signalTipi": s.get("signalTipi", {"tip": "NOTR", "renk": "#888", "emoji": ""}),
                                "targets": s.get("targets", {}),
                                "rr": float(s.get("rr1", 0) or 0),
                                "signalQuality": int(s.get("signalQuality", 0) or 0)}
    groups = []
    for cc, cd in candidates.items():
        matched = []
        for lc, ld in leaders.items():
            sim = _cosine_sim_pm(cd["vec"], ld["vec"])
            if sim >= 72:
                ldr_mov = abs(ld["ret3m"]) + abs(ld["retYil"]) * 0.3
                cnd_mov = abs(cd["ret3m"]) + abs(cd["retYil"]) * 0.3
                ratio = cnd_mov / ldr_mov if ldr_mov > 0 else 1
                if ratio < 0.65:
                    matched.append({"code": lc, "sim": sim, "ret3m": ld["ret3m"], "retYil": ld["retYil"],
                                    "roc5": ld["roc5"], "roc20": ld["roc20"], "katlamis": ld["katlamis"],
                                    "price": ld["price"], "sektor": ld["sektor"], "name": ld["name"],
                                    "lagRatio": round((1 - ratio) * 100)})
        if not matched: continue
        matched.sort(key=lambda x: x["sim"], reverse=True)
        top = matched[:3]
        avg_sim = round(sum(t["sim"] for t in top) / len(top), 1)
        max_lag = max(t["lagRatio"] for t in top)
        opp = avg_sim * 0.4 + max_lag * 0.3 + min(100, cd["aiScore"] / 3.5) * 0.2 + max(0, 50 - cd["pos52wk"]) * 0.5
        groups.append({**{k: cd[k] for k in ("code", "name", "price", "aiScore", "rsi", "roc5", "roc20",
                                              "ret3m", "retYil", "farkYuzde", "volRatio", "pos52wk",
                                              "cap", "sektor", "formations", "signalTipi", "rr",
                                              "signalQuality", "targets")},
                       "leaders": top, "avgSim": avg_sim, "maxLag": max_lag,
                       "oppScore": round(opp, 1)})
    groups.sort(key=lambda g: g["oppScore"], reverse=True)
    result = {"ts": int(time.time()), "leader_count": len(leaders),
              "candidate_count": len(candidates), "groups": groups[:30],
              "method": "price_cosine"}
    _write_json_cache(cache, result)
    return result
