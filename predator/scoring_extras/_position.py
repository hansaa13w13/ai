"""Pozisyon güveni ve brain×backtest fusion (Predator IQ)."""

from __future__ import annotations


def get_unified_position_confidence(code: str, pos: dict, brain_data: dict, bt_stats: dict) -> dict:
    """PHP getUnifiedPositionConfidence birebir."""
    signals = []
    total = max_s = 0
    bt_wr5 = float(((bt_stats.get("t5") or {}).get("win_rate")) or 0)
    bt_cnt = int(((bt_stats.get("t5") or {}).get("count")) or 0)
    if bt_cnt >= 3:
        max_s += 30
        contrib = round(bt_wr5 / 100 * 30)
        total += contrib
        signals.append({"label": "Backtest WR(5g)", "val": f"%{bt_wr5}",
                        "color": "#00ff9d" if bt_wr5 >= 60 else ("#ffea00" if bt_wr5 >= 50 else "#ff003c")})
    acc = brain_data.get("prediction_accuracy") or {}
    pred_oran = float(acc.get("oran") or 0)
    pred_top = int(acc.get("toplam") or 0)
    if pred_top >= 5:
        max_s += 25
        contrib = round(pred_oran / 100 * 25)
        total += contrib
        signals.append({"label": "Brain Doğruluk", "val": f"%{pred_oran}",
                        "color": "#bc13fe" if pred_oran >= 60 else ("#ffea00" if pred_oran >= 50 else "#ff003c")})
    pnl = float(pos.get("pnl_pct") or 0)
    max_s += 20
    if pnl > 3:
        total += 20
        signals.append({"label": "K/Z Trend", "val": f"+{round(pnl,1)}%", "color": "#00ff9d"})
    elif pnl > 0:
        total += 12
        signals.append({"label": "K/Z Trend", "val": f"+{round(pnl,1)}%", "color": "#ffea00"})
    elif pnl > -3:
        total += 6
        signals.append({"label": "K/Z Trend", "val": f"{round(pnl,1)}%", "color": "#ff9900"})
    else:
        signals.append({"label": "K/Z Trend", "val": f"{round(pnl,1)}%", "color": "#ff003c"})
    sc_entry = int(pos.get("score") or 0)
    max_s += 15
    if sc_entry >= 200:
        total += 15
        signals.append({"label": "Giriş Skoru", "val": sc_entry, "color": "#00ff9d"})
    elif sc_entry >= 130:
        total += 10
        signals.append({"label": "Giriş Skoru", "val": sc_entry, "color": "#ffea00"})
    else:
        total += 5
        signals.append({"label": "Giriş Skoru", "val": sc_entry, "color": "#ff9900"})
    snaps = ((brain_data.get("snapshots") or {}).get(code)) or []
    eligible = [s for s in snaps if s.get("outcome5") is not None]
    wins = [s for s in eligible if float(s.get("outcome5") or 0) > 0]
    if eligible:
        snap_wr = round(len(wins) / len(eligible) * 100)
        max_s += 10
        total += round(snap_wr / 100 * 10)
        signals.append({"label": "Hisse Geçmişi", "val": f"%{snap_wr}({len(eligible)})",
                        "color": "#00ff9d" if snap_wr >= 60 else ("#ffea00" if snap_wr >= 50 else "#ff003c")})
    pct = min(100, round(total / max_s * 100)) if max_s > 0 else 0
    return {"pct": pct, "signals": signals}


def get_brain_backtest_fusion(brain_stats: dict, bt_stats: dict) -> dict:
    """PHP getBrainBacktestFusion birebir."""
    bt_wr5  = float(((bt_stats.get("t5") or {}).get("win_rate")) or 0)
    bt_avg5 = float(((bt_stats.get("t5") or {}).get("avg_ret")) or 0)
    bt_cnt5 = int(((bt_stats.get("t5") or {}).get("count")) or 0)
    pred_oran = float(brain_stats.get("pred_oran") or 0)
    pred_total = int(brain_stats.get("pred_toplam") or 0)
    iq = 0
    iq_parts = []
    if bt_cnt5 >= 3:
        bt_score = min(40, round(bt_wr5 * 0.4))
        iq += bt_score
        iq_parts.append(["Backtest", bt_score, 40, "#00f3ff"])
    if pred_total >= 5:
        brain_score = min(35, round(pred_oran * 0.35))
        iq += brain_score
        iq_parts.append(["Brain Doğruluk", brain_score, 35, "#bc13fe"])
    form_count = len(brain_stats.get("formasyon_istatistik") or [])
    form_score = min(15, form_count * 2)
    iq += form_score
    iq_parts.append(["Formasyon", form_score, 15, "#ffea00"])
    sekt_count = len(brain_stats.get("sektor_perf") or [])
    sekt_score = min(15, sekt_count)
    iq += sekt_score
    iq_parts.append(["Sektör", sekt_score, 15, "#00ff9d"])
    iq_color = "#00ff9d" if iq >= 70 else ("#ffea00" if iq >= 50 else ("#ff9900" if iq >= 30 else "#555"))
    return {
        "iq": iq, "iq_color": iq_color, "iq_parts": iq_parts,
        "bt_wr5": bt_wr5, "bt_avg5": bt_avg5, "bt_cnt5": bt_cnt5,
        "pred_oran": pred_oran, "pred_total": pred_total,
    }
