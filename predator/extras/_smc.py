"""SMC (Smart Money Concepts) ve harmonik formasyon analizi."""
from __future__ import annotations


def calculate_smc(chart_data: list[dict], lookback: int = 100) -> dict:
    n = len(chart_data)
    if n < 20:
        return {"orderBlocks": [], "fvg": [], "liquiditySweep": {"bullish": False, "bearish": False, "strength": 0},
                "bos": "none", "choch": False, "bias": "notr", "bosStrength": 0}

    sl = chart_data[-min(lookback, n):]
    sn = len(sl)
    last_close = float(sl[-1].get("Close", 0))

    obs = []
    for i in range(2, sn - 2):
        cur, nxt = sl[i], sl[i + 1]
        nn = sl[i + 2] if i + 2 < sn else nxt
        cO = float(cur.get("Open", cur.get("Close", 0)))
        cC = float(cur.get("Close", 0))
        cH = float(cur.get("High", cC))
        cL = float(cur.get("Low",  cC))
        nO = float(nxt.get("Open", nxt.get("Close", 0)))
        nC = float(nxt.get("Close", 0))
        nnC = float(nn.get("Close", nC))
        if cC <= 0 or nC <= 0:
            continue
        if (cH - cL) < 0.0001:
            continue
        impulse = abs(nC - nO)
        imp_pct = (impulse / nO * 100) if nO > 0 else 0
        if cC < cO and nC > nO and imp_pct >= 1.5 and nnC > nC:
            obs.append({"type": "bullish", "top": round(cO, 4), "bot": round(cL, 4),
                        "mid": round((cO + cL) / 2, 4), "idx": i,
                        "date": str(cur.get("Date", "")), "strength": round(min(100, imp_pct * 15), 1),
                        "mitigated": False})
        if cC > cO and nC < nO and imp_pct >= 1.5 and nnC < nC:
            obs.append({"type": "bearish", "top": round(cH, 4), "bot": round(cO, 4),
                        "mid": round((cH + cO) / 2, 4), "idx": i,
                        "date": str(cur.get("Date", "")), "strength": round(min(100, imp_pct * 15), 1),
                        "mitigated": False})
    for ob in obs:
        if ob["type"] == "bullish" and last_close < ob["bot"]:
            ob["mitigated"] = True
        elif ob["type"] == "bearish" and last_close > ob["top"]:
            ob["mitigated"] = True
    active_obs = [ob for ob in obs if not ob["mitigated"]][-6:]

    fvgs = []
    for i in range(sn - 2):
        b1, b3 = sl[i], sl[i + 2]
        h1 = float(b1.get("High", b1.get("Close", 0)))
        l1 = float(b1.get("Low",  b1.get("Close", 0)))
        h3 = float(b3.get("High", b3.get("Close", 0)))
        l3 = float(b3.get("Low",  b3.get("Close", 0)))
        if h1 <= 0 or l3 <= 0:
            continue
        if l3 > h1:
            gap_pct = (l3 - h1) / h1 * 100 if h1 > 0 else 0
            if gap_pct >= 0.3:
                fvgs.append({"type": "bullish", "top": round(l3, 4), "bot": round(h1, 4),
                             "mid": round((l3 + h1) / 2, 4), "idx": i, "gapPct": round(gap_pct, 2),
                             "filled": last_close < (l3 + h1) / 2})
        if h3 < l1:
            gap_pct = (l1 - h3) / l1 * 100 if l1 > 0 else 0
            if gap_pct >= 0.3:
                fvgs.append({"type": "bearish", "top": round(l1, 4), "bot": round(h3, 4),
                             "mid": round((l1 + h3) / 2, 4), "idx": i, "gapPct": round(gap_pct, 2),
                             "filled": last_close > (l1 + h3) / 2})
    recent_fvgs = fvgs[-8:]

    sweep = {"bullish": False, "bearish": False, "strength": 0}
    if sn >= 22:
        ref = sl[-21:-1]
        last_bar = sl[-1]
        ref_low  = min(float(b.get("Low", b.get("Close", 9999999))) for b in ref)
        ref_high = max(float(b.get("High", b.get("Close", 0))) for b in ref)
        last_low  = float(last_bar.get("Low", last_close))
        last_high = float(last_bar.get("High", last_close))
        if last_low < ref_low and last_close > ref_low:
            depth = (ref_low - last_low) / max(ref_low, 0.001) * 100
            sweep = {"bullish": True, "bearish": False, "strength": round(min(100, depth * 20), 1)}
        elif last_high > ref_high and last_close < ref_high:
            height = (last_high - ref_high) / max(ref_high, 0.001) * 100
            sweep = {"bullish": False, "bearish": True, "strength": round(min(100, height * 20), 1)}

    swing_highs, swing_lows, sw = [], [], 3
    for i in range(sw, sn - sw):
        h = float(sl[i].get("High", sl[i].get("Close", 0)))
        l = float(sl[i].get("Low",  sl[i].get("Close", 9999999)))
        is_h = is_l = True
        for j in range(i - sw, i + sw + 1):
            if j == i:
                continue
            if float(sl[j].get("High", sl[j].get("Close", 0))) > h:
                is_h = False
            if float(sl[j].get("Low", sl[j].get("Close", 9999999))) < l:
                is_l = False
        if is_h:
            swing_highs.append({"price": h, "idx": i})
        if is_l:
            swing_lows.append({"price": l, "idx": i})

    bos, choch, bos_strength = "none", False, 0
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        sh_last, sh_prev = swing_highs[-1], swing_highs[-2]
        sl_last, sl_prev = swing_lows[-1], swing_lows[-2]
        higher_h = sh_last["price"] > sh_prev["price"]
        higher_l = sl_last["price"] > sl_prev["price"]
        lower_h  = sh_last["price"] < sh_prev["price"]
        lower_l  = sl_last["price"] < sl_prev["price"]
        if higher_h and higher_l:
            bos = "bullish_bos" if last_close > sh_last["price"] else "bullish"
            bos_strength = round((sh_last["price"] - sh_prev["price"]) / sh_prev["price"] * 100, 2) if sh_prev["price"] > 0 else 0
        elif lower_h and lower_l:
            bos = "bearish_bos" if last_close < sl_last["price"] else "bearish"
            bos_strength = round((sl_prev["price"] - sl_last["price"]) / sl_prev["price"] * 100, 2) if sl_prev["price"] > 0 else 0
        choch = (higher_h and lower_l) or (lower_h and higher_l)

    bull = bear = 0
    for ob in active_obs:
        if ob["type"] == "bullish" and abs(last_close - ob["mid"]) / max(ob["mid"], 0.001) < 0.05:
            bull += 1
        if ob["type"] == "bearish" and abs(last_close - ob["mid"]) / max(ob["mid"], 0.001) < 0.05:
            bear += 1
    for f in recent_fvgs:
        if not f["filled"]:
            if f["type"] == "bullish" and last_close > f["bot"]:
                bull += 1
            if f["type"] == "bearish" and last_close < f["top"]:
                bear += 1
    if sweep["bullish"]: bull += 2
    if sweep["bearish"]: bear += 2
    if bos.startswith("bullish"): bull += 2
    if bos.startswith("bearish"): bear += 2
    bias = "bullish" if bull > bear else ("bearish" if bear > bull else "notr")

    return {"orderBlocks": active_obs, "fvg": recent_fvgs, "liquiditySweep": sweep,
            "bos": bos, "choch": choch, "bias": bias, "bosStrength": bos_strength,
            "swingHighs": swing_highs[-3:], "swingLows": swing_lows[-3:]}


def detect_harmonic_patterns(chart_data: list[dict], lookback: int = 80) -> list[dict]:
    n = len(chart_data)
    if n < 15:
        return []
    sl = chart_data[-min(lookback, n):]
    highs = [float(b.get("High", b.get("Close", 0))) for b in sl]
    lows  = [float(b.get("Low",  b.get("Close", 0))) for b in sl]
    sn = len(sl)
    pivots = []
    sw2 = 2
    for i in range(sw2, sn - sw2):
        h, l = highs[i], lows[i]
        is_h = is_l = True
        for j in range(i - sw2, i + sw2 + 1):
            if j == i:
                continue
            if highs[j] > h: is_h = False
            if lows[j]  < l: is_l = False
        if is_h: pivots.append({"type": "H", "price": h, "idx": i})
        if is_l: pivots.append({"type": "L", "price": l, "idx": i})
    if len(pivots) < 5:
        return []

    def fib(a: float, b: float, r: float) -> float: return a + (b - a) * r
    def ratio(m1: float, m2: float) -> float: return abs(m2 / m1) if m1 != 0 else 0
    def within(v: float, lo: float, hi: float) -> bool: return lo <= v <= hi

    patterns = []
    recent = pivots[-10:]
    for xi in range(len(recent) - 4):
        X, A, B, C, D = recent[xi:xi + 5]
        if X["type"] == A["type"] or A["type"] == B["type"] or B["type"] == C["type"] or C["type"] == D["type"]:
            continue
        XA = abs(A["price"] - X["price"]); AB = abs(B["price"] - A["price"])
        BC = abs(C["price"] - B["price"]); CD = abs(D["price"] - C["price"])
        if XA < 0.001 or AB < 0.001 or BC < 0.001:
            continue
        AB_XA = ratio(XA, AB); BC_AB = ratio(AB, BC); CD_BC = ratio(BC, CD)
        AD_XA = abs(D["price"] - A["price"]) / XA if XA > 0 else 0
        is_bull = (X["type"] == "H")
        if within(AB_XA, 0.55, 0.68) and within(BC_AB, 0.35, 0.9) and within(CD_BC, 1.2, 1.7) and within(AD_XA, 0.72, 0.83):
            prz = fib(X["price"], A["price"], 0.786)
            patterns.append({"name": "Gartley", "type": "bullish" if is_bull else "bearish",
                             "X": X["price"], "A": A["price"], "B": B["price"], "C": C["price"], "D": D["price"],
                             "prz": round(prz, 4), "confidence": round(80 - abs(AB_XA - 0.618) * 100, 1),
                             "stopBeyond": round(X["price"] * (0.98 if is_bull else 1.02), 4)})
        elif within(AB_XA, 0.35, 0.52) and within(BC_AB, 0.35, 0.9) and within(CD_BC, 1.6, 2.7) and within(AD_XA, 0.82, 0.95):
            prz = fib(X["price"], A["price"], 0.886)
            patterns.append({"name": "Bat", "type": "bullish" if is_bull else "bearish",
                             "X": X["price"], "A": A["price"], "B": B["price"], "C": C["price"], "D": D["price"],
                             "prz": round(prz, 4), "confidence": round(78 - abs(AB_XA - 0.45) * 80, 1),
                             "stopBeyond": round(X["price"] * (0.977 if is_bull else 1.023), 4)})
        elif within(AB_XA, 0.35, 0.63) and within(BC_AB, 0.35, 0.9) and within(CD_BC, 2.5, 3.7) and within(AD_XA, 1.5, 1.74):
            prz = fib(X["price"], A["price"], 1.618)
            patterns.append({"name": "Crab", "type": "bullish" if is_bull else "bearish",
                             "X": X["price"], "A": A["price"], "B": B["price"], "C": C["price"], "D": D["price"],
                             "prz": round(prz, 4), "confidence": round(76 - abs(CD_BC - 3.14) * 15, 1),
                             "stopBeyond": round(X["price"] * (0.975 if is_bull else 1.025), 4)})
        elif within(AB_XA, 0.72, 0.83) and within(BC_AB, 0.35, 0.9) and within(CD_BC, 1.6, 2.7) and within(AD_XA, 1.2, 1.65):
            prz = fib(X["price"], A["price"], 1.272)
            patterns.append({"name": "Butterfly", "type": "bullish" if is_bull else "bearish",
                             "X": X["price"], "A": A["price"], "B": B["price"], "C": C["price"], "D": D["price"],
                             "prz": round(prz, 4), "confidence": round(74 - abs(AB_XA - 0.786) * 80, 1),
                             "stopBeyond": round(X["price"] * (0.98 if is_bull else 1.02), 4)})
        elif within(AB_XA, 0.35, 0.63) and within(BC_AB, 1.2, 1.45):
            XC = abs(C["price"] - X["price"])
            CD_XC = CD / XC if XC > 0 else 0
            if within(CD_XC, 0.72, 0.83):
                prz = fib(X["price"], C["price"], 0.786)
                patterns.append({"name": "Cypher", "type": "bullish" if is_bull else "bearish",
                                 "X": X["price"], "A": A["price"], "B": B["price"], "C": C["price"], "D": D["price"],
                                 "prz": round(prz, 4), "confidence": round(72 - abs(CD_XC - 0.786) * 80, 1),
                                 "stopBeyond": round(X["price"] * (0.975 if is_bull else 1.025), 4)})
    patterns.sort(key=lambda p: p["confidence"], reverse=True)
    return patterns[:3]
