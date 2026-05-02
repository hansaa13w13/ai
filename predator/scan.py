"""BIST tarama motoru — tüm hisseleri analiz eder ve top picks üretir."""
from __future__ import annotations
import json
import time
import threading
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, indicators as ind, formations, smc as smc_mod
from .levels import find_swing_levels, cluster_levels
from .signal_type import get_signal_tipi
from .api_client import fetch_chart2, fetch_sirket_detay, fetch_burgan_kart, fetch_bist_full_list
from .utils import load_json, save_json, now_str, ScanLock, parse_api_num
from .sectors import get_sector_group
from .scoring import (calculate_ai_score, calculate_hiz_score,
                       calculate_signal_quality, calculate_buy_sell_targets,
                       calculate_consensus, calculate_predator_score)
from .katlama_targets import calculate_katlama_targets
from .ai_think import ai_auto_think
from .brain import brain_load, brain_save, brain_save_snapshot, brain_get_prediction_bonus, neural_ensemble_predict
from .market import detect_market_mode, get_market_mode, save_market_mode
from .signal_history import log_top_picks

_PROGRESS_LOCK = threading.Lock()


def _refresh_score(stock: dict) -> None:
    """v37.4: aiScore değiştikten sonra predatorScore'u yeniden hesapla
    ve `score` alanını her zaman predatorScore'a eşitle.

    Önceki davranış: `_enrich_with_fundamentals`, `_apply_sector_momentum_boost`,
    `_ortak_katlama_analysis` aiScore'a bonus eklerken `score`u aiScore'a
    overwrite ediyordu (~189). `daemon` ısıtmadan sonra `score`u tekrar
    predatorScore'a alıyordu (~350). Bu, kullanıcının gördüğü "iki farklı
    liste" hatasının kök nedenidir. Artık her iki alan da senkron.
    """
    try:
        ai = int(stock.get("aiScore", 0) or 0)
        ai = max(0, min(350, ai))
        stock["aiScore"] = ai
        pred = calculate_predator_score(stock)
        stock["predatorScore"] = round(float(pred), 2)
        stock["score"] = stock["predatorScore"]
    except Exception:
        # Hatada en azından score'u aiScore'a düşür (mevcut davranışa fallback)
        stock["score"] = round(float(stock.get("aiScore", 0) or 0), 2)


def _apply_kap_bonus_parallel(results: list[dict], bonus_fn, max_workers: int = 6) -> None:
    """KAP 'Tipe Dönüşüm' bonusunu dipteki hisseler için paralel uygula.

    Sadece ``pos52wk < 35`` olan hisseler için haber API'sine gider; diğer
    hisseler için bonus çağırma maliyeti ödemeyiz. ``aiScore`` ve cache
    güncellemesi ana thread'de yapılır (race-free).
    """
    candidates = [s for s in results
                  if 0 < float(s.get("pos52wk", 50) or 50) < 35
                  and (s.get("code") or "").upper() not in ("XU100", "XU030", "XBANK")]
    if not candidates:
        return
    futures = {}
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        for s in candidates:
            futures[pool.submit(bonus_fn, s)] = s
        for fut in as_completed(futures):
            s = futures[fut]
            try:
                kb_total, kb_items = fut.result()
            except Exception:
                continue
            old_kb = int(s.get("kapNewsBonus", 0) or 0)
            if kb_total != old_kb:
                delta = kb_total - old_kb
                s["kapNewsBonus"] = kb_total
                s["kapNewsItems"] = kb_items
                s["aiScore"] = max(0, min(350, int(s.get("aiScore", 0) or 0) + delta))


def _apply_bedelsiz_bonus_parallel(results: list[dict], bonus_fn,
                                   max_workers: int = 6) -> None:
    """KAP Bedelsiz Sermaye Artırımı bonusunu TÜM hisseler için paralel uygula.

    Tipe dönüşümün aksine pos52wk filtresi uygulanmaz; bedelsiz duyurusu
    her fiyat seviyesinde yükseliş katalizörüdür.
    """
    candidates = [s for s in results
                  if (s.get("code") or "").upper() not in ("XU100", "XU030", "XBANK")]
    if not candidates:
        return
    futures = {}
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        for s in candidates:
            futures[pool.submit(bonus_fn, s)] = s
        for fut in as_completed(futures):
            s = futures[fut]
            try:
                bed_total, bed_items = fut.result()
            except Exception:
                continue
            if bed_total <= 0:
                continue
            old_bed = int(s.get("kapBedelsizBonus", 0) or 0)
            if bed_total != old_bed:
                delta = bed_total - old_bed
                s["kapBedelsizBonus"] = bed_total
                s["kapBedelsizItems"] = bed_items
                s["aiScore"] = max(0, min(350, int(s.get("aiScore", 0) or 0) + delta))


def _write_progress(pct: int, status: str = "running", err: str = "") -> None:
    with _PROGRESS_LOCK:
        try:
            data = {"pct": pct, "status": status, "ts": int(time.time())}
            if err: data["err"] = err
            config.SCAN_PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
            config.SCAN_PROGRESS_FILE.write_text(json.dumps(data))
        except OSError:
            pass


def _clear_progress() -> None:
    try:
        if config.SCAN_PROGRESS_FILE.exists():
            config.SCAN_PROGRESS_FILE.unlink()
    except OSError:
        pass


def _extract_ohlcv(chart: Any) -> dict | None:
    """CHART2 yanıtını numpy-uyumlu OHLCV formatına dönüştür.

    PHP idealdata formatı: liste — her eleman {Date, Open, High, Low, Close, Size, Vol}
    'Size' = lot adedi, 'Vol' = TL hacmi.
    """
    if not chart:
        return None
    candles = chart
    if isinstance(chart, dict):
        candles = (chart.get("Data") or chart.get("data") or chart.get("candles")
                   or chart.get("ohlcv") or chart.get("kline") or [])
    if not isinstance(candles, list) or len(candles) < 30:
        return None
    h, l, o, c, v = [], [], [], [], []
    for k in candles:
        if isinstance(k, dict):
            o.append(parse_api_num(k.get("Open", k.get("Acilis", k.get("open", k.get("o", 0))))))
            h.append(parse_api_num(k.get("High", k.get("Yuksek", k.get("high", k.get("h", 0))))))
            l.append(parse_api_num(k.get("Low", k.get("Dusuk", k.get("low", k.get("l", 0))))))
            c.append(parse_api_num(k.get("Close", k.get("Kapanis", k.get("close", k.get("c", 0))))))
            # Size = lot, Vol = TL — lot tercih edilir indikatör için
            v.append(parse_api_num(k.get("Size", k.get("Hacim", k.get("volume", k.get("v",
                     k.get("Vol", 0)))))))
        elif isinstance(k, list) and len(k) >= 5:
            o.append(parse_api_num(k[1]))
            h.append(parse_api_num(k[2]))
            l.append(parse_api_num(k[3]))
            c.append(parse_api_num(k[4]))
            v.append(parse_api_num(k[5]) if len(k) > 5 else 0)
    if not c or all(x == 0 for x in c):
        return None
    return {"o": o, "h": h, "l": l, "c": c, "v": v}


def analyze_stock(code: str, mode: str = "bull", chart: Any = None) -> dict | None:
    """Tek hisse için tüm analizi çalıştır.

    chart=None ise CHART2 API'den çekilir; verilirse iki-fazlı tarama gibi
    önceden çekilmiş OHLCV kullanılır (çift API çağrısı yok).
    """
    if chart is None:
        chart = fetch_chart2(code)
    ohlcv = _extract_ohlcv(chart)
    if not ohlcv:
        return None
    o, h, l, c, v = ohlcv["o"], ohlcv["h"], ohlcv["l"], ohlcv["c"], ohlcv["v"]
    if c[-1] <= 0:
        return None

    rsi = ind.rsi(c)
    macd = ind.macd(c)
    bb = ind.bollinger(c)
    atr = ind.atr(h, l, c)
    adx = ind.adx(h, l, c)
    stoch = ind.stoch_rsi(c)              # PHP $tech['stochRsi'] uyumlu
    vwap = ind.vwap(h, l, c, v)
    sar = ind.parabolic_sar(h, l)
    st = ind.supertrend(h, l, c)
    hull = ind.hull_ma(c)
    ichi = ind.ichimoku(h, l, c)
    obv = ind.obv(c, v)
    keltner = ind.keltner(h, l, c)
    trix = ind.trix(c)
    ao = ind.awesome_osc(h, l)
    aroon = ind.aroon(h, l)
    elder = ind.elder_ray(h, c)
    # Temel hareketli ortalamalar — PHP $tech['sma20/50/200']
    sma20  = ind.sma(c, 20)  if len(c) >= 20  else 0.0
    sma50  = ind.sma(c, 50)  if len(c) >= 50  else 0.0
    sma200 = ind.sma(c, 200) if len(c) >= 200 else 0.0
    smc_info = smc_mod.smc_analyze(h, l, o, c, v)
    ofi = smc_mod.order_flow_imbalance(c, v)
    # Formasyonları tech dict'i hazır olduktan sonra hesapla (chart formations tech'e bağımlı)
    forms = []

    # RSI dizisi — single-pass Wilder (O(n) not O(n²))
    rsi_arr = ind.rsi_series(c, period=14, tail=25)
    div_rsi = ind.detect_rsi_divergence(c[-25:], rsi_arr)
    div_macd = ind.detect_macd_divergence(c)

    # PHP v35: Donchian, Pivot, Fibonacci, PVT (birebir port)
    donch = ind.calculate_donchian_breakout(h, l, c)
    piv   = ind.calculate_pivot_points(h, l, c)
    fib   = ind.calculate_fibonacci_levels(h, l)
    pvt_v = ind.calculate_pvt(c, v)
    piv_act = ind.pivot_action(c[-1] if len(c) else 0, piv)
    fib_pos = ind.fib_position(c[-1] if len(c) else 0, fib)

    roc5  = ind.roc(c, 5)
    roc20 = ind.roc(c, 20)
    roc60 = ind.roc(c, 60)
    vol_mom = ind.vol_momentum(v)
    el_sig = ind.elder_signal(h, c)
    trix_val = float(trix.get("val", trix.get("value", 0)) or 0)

    cur = c[-1]

    # EMA 9/21 cross — PHP emaCross.cross birebir
    ema9  = ind.ema(c, 9)
    ema21 = ind.ema(c, 21)
    if len(ema9) >= 2 and len(ema21) >= 2:
        _fast_now  = ema9[-1];  _fast_prev  = ema9[-2]
        _slow_now  = ema21[-1]; _slow_prev  = ema21[-2]
        if _fast_prev <= _slow_prev and _fast_now > _slow_now:
            ema_cross_dir = "golden"
        elif _fast_prev >= _slow_prev and _fast_now < _slow_now:
            ema_cross_dir = "death"
        else:
            ema_cross_dir = "none"
    else:
        ema_cross_dir = "none"

    # BB %B — fiyatın bant içindeki konumu (0=alt, 100=üst)
    _bb_lo = float(bb.get("lower", 0) or 0); _bb_hi = float(bb.get("upper", 0) or 0)
    bb_pct = ((cur - _bb_lo) / (_bb_hi - _bb_lo) * 100) if _bb_hi > _bb_lo else 50.0

    # İchimoku Tenkan/Kijun cross
    _tenk = float(ichi.get("tenkan", 0) or 0); _kij = float(ichi.get("kijun", 0) or 0)
    ichi_tk_cross = "golden" if _tenk > _kij and _tenk > 0 and _kij > 0 else (
                    "death" if _kij > _tenk and _tenk > 0 and _kij > 0 else "none")
    _kumo_top = max(float(ichi.get("spanA", 0) or 0), float(ichi.get("spanB", 0) or 0))
    _kumo_bot = min(float(ichi.get("spanA", 0) or 0), float(ichi.get("spanB", 0) or 0))

    # EMA 9/21 fast-above-slow
    ema_fast_above = bool(len(ema9) and len(ema21) and ema9[-1] > ema21[-1])

    stock = {
        "code": code,
        "guncel": cur,
        "atr14": atr, "atr": atr,
        "rsi": rsi,
        # MACD — hem flat hem nested
        "macd": {"cross": macd["cross"], "hist": macd["hist"],
                 "macd": macd.get("macd", 0), "signal": macd.get("signal", 0)},
        "macdCross": macd["cross"],
        "macdHist": macd["hist"],
        # Bollinger — hem flat hem nested
        "bb": {"upper": _bb_hi, "lower": _bb_lo, "mid": float(bb.get("mid", 0) or 0),
               "squeeze": bb["squeeze"], "pct": bb_pct, "width": float(bb.get("width", 0) or 0)},
        "bbSqueeze": bb["squeeze"],
        "bbPct": bb_pct, "bbLow": _bb_lo, "bbHigh": _bb_hi,
        # ADX
        "adx": {"adx": adx["val"], "dir": adx["dir"],
                "plusDI": adx.get("plusDI", 0), "minusDI": adx.get("minusDI", 0)},
        "adxVal": adx["val"], "adxDir": adx["dir"],
        # Stoch RSI
        "stochRsi": {"k": stoch["k"], "d": stoch["d"]},
        "stochK": stoch["k"], "stochD": stoch["d"],
        # VWAP
        "vwap": float(vwap.get("vwap", 0) or 0),
        "vwapPos": vwap["pos"],
        # SAR
        "sar": {"sar": float(sar.get("sar", 0) or 0), "direction": sar["dir"]},
        "sarVal": float(sar.get("sar", 0) or 0),
        "sarDir": sar["dir"],
        # Supertrend
        "supertrend": {"value": float(st.get("val", 0) or 0), "direction": st["dir"]},
        "supertrendDir": st["dir"],
        "stVal": float(st.get("val", 0) or 0),
        # Hull MA
        "hull": float(hull.get("val", 0) or 0),
        "hullDir": hull["dir"],
        # İchimoku — hem flat hem nested
        "ichimoku": {"signal": ichi["sig"], "tkCross": ichi_tk_cross,
                     "tenkan": _tenk, "kijun": _kij,
                     "spanA": float(ichi.get("spanA", 0) or 0),
                     "spanB": float(ichi.get("spanB", 0) or 0),
                     "kumoTop": _kumo_top, "kumoBot": _kumo_bot},
        "ichiSig": ichi["sig"], "ichiTkCross": ichi_tk_cross,
        "ichiKumoTop": _kumo_top, "ichiKumoBot": _kumo_bot,
        "ichiTenkan": _tenk, "ichiKijun": _kij,
        # OBV/Keltner
        "obvTrend": obv["trend"],
        "keltnerPos": keltner["pos"],
        # TRIX
        "trix": {"value": trix_val, "cross": trix["cross"], "signal": trix.get("signal", "notr")},
        "trixCross": trix["cross"],
        "trixVal": trix_val,
        "trixSig": trix.get("signal", "notr"),
        # Awesome Oscillator
        "awesomeOsc": {"signal": ao["sig"], "cross": ao.get("cross", "none")},
        "awesomeOscSig": ao["sig"],
        "awesomeOscCross": ao.get("cross", "none"),
        # Aroon
        "aroon": {"up": float(aroon.get("up", 50) or 50),
                  "down": float(aroon.get("down", 50) or 50),
                  "osc": aroon["osc"]},
        "aroonOsc": aroon["osc"],
        "aroonUp": float(aroon.get("up", 50) or 50),
        "aroonDown": float(aroon.get("down", 50) or 50),
        # Elder Ray
        "elder": {"bull": elder["bull"], "bear": elder.get("bear", 0), "signal": el_sig},
        "elderBull": elder["bull"],
        "elderSignal": el_sig,
        # Temel hareketli ortalamalar (PHP $tech['sma20/50/200'])
        "sma20": sma20, "sma50": sma50, "sma200": sma200,
        "williamsR": ind.williams_r(h, l, c),
        "cci": ind.cci(h, l, c),
        "mfi": ind.mfi(h, l, c, v),
        "cmf": ind.cmf(h, l, c, v),
        "cmo": ind.chande_mo(c),
        "ultimateOsc": ind.ultimate_osc(h, l, c),
        "smcBias": smc_info["bias"],
        # PHP smcScoreBonus için tam SMC yapısı (orderBlocks, fvg, bos, choch, liquiditySweep)
        "smc": smc_info,
        "ofiSig": ofi,
        "divRsi": div_rsi,
        "divMacd": div_macd,
        "volRatio": ind.vol_ratio(v),
        "volMomentum": vol_mom,
        "pos52wk": ind.pos_52wk(c),
        "fibPos": ind.fib_pos(c),
        "roc5": roc5,
        "roc20": roc20,
        "roc60": roc60,
        "marketMode": mode,
        "formations": forms,
        # EMA 9/21 — hem flat hem nested
        "emaCross": {"cross": ema_cross_dir, "fastAboveSlow": ema_fast_above,
                     "ema9": float(ema9[-1]) if len(ema9) else 0.0,
                     "ema21": float(ema21[-1]) if len(ema21) else 0.0},
        "emaCrossDir": ema_cross_dir,
        "emaFastAboveSlow": ema_fast_above,
        "ema9":  float(ema9[-1])  if len(ema9)  else 0.0,
        "ema21": float(ema21[-1]) if len(ema21) else 0.0,
        "sektor": get_sector_group(code),
        "trend": "yukselis" if c[-1] > sum(c[-20:]) / len(c[-20:]) else "dusus",
        # Donchian — nested + flat
        "donchian": {
            "upper": float(donch.get("upper", 0) or 0),
            "lower": float(donch.get("lower", 0) or 0),
            "breakout": donch.get("breakout", "none") if isinstance(donch, dict) else "none",
        } if isinstance(donch, dict) else donch,
        "pivot": piv,
        "pivotAction": piv_act,
        "fib": fib,
        "pvt": pvt_v,
    }

    # Burgan'dan temel veriler — opsiyonel
    burgan = fetch_burgan_kart(code)
    if isinstance(burgan, dict):
        stock["adil"] = parse_api_num(burgan.get("AdilDeger") or burgan.get("adilDeger") or 0)
        stock["marketCap"] = parse_api_num(burgan.get("PiyasaDegeri") or burgan.get("piyasaDegeri") or 0) / 1e6
    else:
        stock["adil"] = 0.0
        stock["marketCap"] = 0.0

    # Swing levels & formasyonlar (tech dict hazır → chart formations dahil)
    chart_data_for_lv = [{"High": float(h[i]), "Low": float(l[i]), "Close": float(c[i]),
                          "Open": float(o[i]), "Vol": float(v[i])} for i in range(len(c))]
    swing_lv = find_swing_levels(chart_data_for_lv, lookback=5)
    clustered_lv = cluster_levels(swing_lv, tolerance=0.02)
    stock["swingLevels"] = swing_lv
    stock["clusteredLevels"] = clustered_lv

    forms = formations.detect_all(h, l, o, c, v, tech=stock)
    stock["formations"] = forms

    # Skorlama — SQ önce hesaplanmalı; aiScore SQ katkısını içeriyor
    stock["signalQuality"] = calculate_signal_quality(stock)
    stock["aiScore"]       = calculate_ai_score(stock)
    stock["hizScore"]      = calculate_hiz_score(stock)

    # Hedef hesabı (tam PHP portu — clustered levels kullanır)
    targets = calculate_buy_sell_targets(stock, clustered_levels=clustered_lv)
    stock["targets"] = targets
    stock["h1"] = targets["sell1"]; stock["h2"] = targets["sell2"]; stock["h3"] = targets["sell3"]
    stock["stop"] = targets["stop"]; stock["rr"] = targets["rr"]

    # Katlama hedefleri — tüm veri kaynaklarını kullanan gelişmiş H1/H2/H3
    try:
        from .tavan_katlama import load_katlama_archive
        _katlama_arch = load_katlama_archive()
        kat_info = calculate_katlama_targets(
            stock, clustered_levels=clustered_lv, katlama_archive=_katlama_arch
        )
        stock["katlamaInfo"] = kat_info
        # Katlama hedefleri mevcut H1/H2/H3'ten iyiyse güncelle
        if kat_info["h1"] > 0 and kat_info["h1"] > stock["h1"]:
            stock["h1"] = kat_info["h1"]
        if kat_info["h2"] > 0 and kat_info["h2"] > stock["h2"]:
            stock["h2"] = kat_info["h2"]
        if kat_info["h3"] > 0 and kat_info["h3"] > stock["h3"]:
            stock["h3"] = kat_info["h3"]
        stock["katlamaScore"] = kat_info["katlamaScore"]
        stock["katlamaLevel"] = kat_info["katlamaLevel"]
    except Exception as _ke:
        stock["katlamaInfo"] = {}
        stock["katlamaScore"] = 0
        stock["katlamaLevel"] = "NORMAL"

    # predatorScore — PHP birebir (aiScore×0.40 + hizScore×(100/15)×0.28 + expGain×3×0.20 + rrBonus×0.12 + momBonus)
    stock["predatorScore"] = calculate_predator_score(stock)

    # PHP getSignalTipi — GÜÇLÜ AL/AL/NOTR/SAT/GÜÇLÜ SAT
    stock["signalTipi"] = get_signal_tipi(stock["aiScore"], forms, stock)

    # AI thinking — ön-tahmin için brain pred bonusu eklenir
    brain = brain_load()
    stock["predBonus"] = brain_get_prediction_bonus(brain, stock)
    consensus = calculate_consensus(stock)
    stock["consensus"] = consensus
    think = ai_auto_think(stock, consensus, mode)
    stock["autoThinkDecision"] = think["decision"]
    stock["autoThinkConf"] = think["confidence"]
    stock["autoThinkReason"] = think["reasoning"]
    # AI think score_adj'yi aiScore'a ekle ve predatorScore'u yeniden hesapla
    stock["aiScore"] = max(0, min(350, stock["aiScore"] + int(think["score_adj"])))
    stock["predatorScore"] = calculate_predator_score(stock)
    # Uyumluluk: score = predatorScore (PHP tablo görünümü birebir)
    stock["score"] = round(stock["predatorScore"], 2)

    # v43: KAÇIN/SAT sinyalinde yanıltıcı yukarı hedefleri sıfırla.
    # Bu hisseler engine tarafından zaten alınmaz; UI'da da hedef gösterilmemeli.
    if think["decision"] in ("KAÇIN", "SAT", "GÜÇLÜ SAT"):
        stock["h1"] = 0.0; stock["h2"] = 0.0; stock["h3"] = 0.0
        stock["rr"] = 0.0
        _ki = stock.get("katlamaInfo")
        if isinstance(_ki, dict):
            _ki["h1"] = 0.0; _ki["h2"] = 0.0; _ki["h3"] = 0.0
        stock["katlamaScore"] = 0
        stock["katlamaLevel"] = "KAÇIN"

    # Üçlü ağ tahmini
    nn = neural_ensemble_predict(brain, stock)
    stock["nnEnsemble"] = nn

    # Gerçek Beyin tahmini — rb_prob/rb_conf'u pick dict'e ekle
    # portfolio.py ve signal_history.py bu değerleri kullanır
    try:
        from .real_brain import rb_predict, rb_get_status
        _rb_st = rb_get_status(brain)
        if _rb_st.get("ready"):
            _rb_prob, _rb_conf = rb_predict(brain, stock)
            stock["rb_prob"] = round(_rb_prob, 4)
            stock["rb_conf"] = round(_rb_conf, 4)
        else:
            stock["rb_prob"] = 0.5
            stock["rb_conf"] = 0.0
    except Exception:
        stock["rb_prob"] = 0.5
        stock["rb_conf"] = 0.0

    return stock


def run_bist_scan(limit: int = 0, parallel: int = 6) -> dict:
    """Tüm BIST'i tara. Lock alır, progress yazar, allstocks_cache.json'a kaydeder."""
    lock = ScanLock()
    if not lock.acquire():
        return {"status": "locked"}
    _write_progress(1)
    started = time.time()
    try:
        symbols = fetch_bist_full_list()
        if limit > 0:
            symbols = symbols[:limit]
        total = len(symbols)
        if total == 0:
            _write_progress(100, "error", "no_symbols")
            return {"status": "error", "error": "no_symbols"}

        # Önce piyasa modu için cache'den oku
        cached = load_json(config.ALLSTOCKS_CACHE, {})
        prev_picks = cached.get("topPicks", []) if isinstance(cached, dict) else []
        mode = detect_market_mode(prev_picks)

        results: list[dict] = []
        done = 0
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            futs = {pool.submit(_safe_analyze, s["code"], mode): s for s in symbols}
            for f in as_completed(futs):
                done += 1
                pct = min(99, int(done / total * 100))
                if done % max(1, total // 50) == 0 or done == total:
                    _write_progress(pct)
                r = f.result()
                if r is not None:
                    results.append(r)

        # Yanlış sinyal filtresi uygula (PHP filterFalseSignals)
        results = filter_false_signals(results)

        # Uyuyan Mücevher + Erken Yakalama bonuslarını burgan/finData enrichment
        # sonrası yeniden hesapla. analyze_stock sırasında marketCap=0 / sektor=genel
        # olduğu için ilk hesap sıfır dönüyordu (her iki fonksiyon erken exit yapar).
        try:
            from .scoring_extras import (reset_sector_cache, early_catch_bonus,
                                          sleeper_breakdown, kap_tipe_donusum_bonus,
                                          kap_bedelsiz_bonus)
            for s in results:
                sb_total, sb_items = sleeper_breakdown(s)
                old_sb = int(s.get("sleeperBonus", 0) or 0)
                if sb_total != old_sb:
                    delta = sb_total - old_sb
                    s["sleeperBonus"] = sb_total
                    s["sleeperItems"] = sb_items
                    s["aiScore"] = max(0, min(350, int(s.get("aiScore", 0) or 0) + delta))
            # Erken yakalama: önce sektör cache'ini sıfırla — taze sonuçlardan tazelensin.
            reset_sector_cache()
            for s in results:
                ec_total, ec_items = early_catch_bonus(s)
                old_ec = int(s.get("earlyCatchBonus", 0) or 0)
                if ec_total != old_ec:
                    delta = ec_total - old_ec
                    s["earlyCatchBonus"] = ec_total
                    s["earlyCatchItems"] = ec_items
                    s["aiScore"] = max(0, min(350, int(s.get("aiScore", 0) or 0) + delta))
            # KAP "Tipe Dönüşüm" bonusu — sadece dipteki hisseler için (paralel).
            _apply_kap_bonus_parallel(results, kap_tipe_donusum_bonus)
            # KAP "Bedelsiz Sermaye Artırımı" bonusu — tüm hisseler için (paralel).
            _apply_bedelsiz_bonus_parallel(results, kap_bedelsiz_bonus)
        except Exception:
            pass

        # v37.4: Sıralama öncesi tüm bonusları içeren güncel predatorScore'u garantile
        for s in results:
            _refresh_score(s)

        # v37.6: Sıralama — KAÇIN'lar en alta, sonra hedef fiyatı olanlar, sonra skor
        def _sort_key(s: dict):
            is_avoid = (s.get("autoThinkDecision") or "").upper() == "KAÇIN"
            has_target = float(s.get("h1", 0) or 0) > float(s.get("guncel", 0) or 0)
            pred = float(s.get("predatorScore", s.get("aiScore", 0)) or 0)
            return (0 if is_avoid else 1, 1 if has_target else 0, pred)

        results.sort(key=_sort_key, reverse=True)

        # Brain snapshot — tüm sonuçlardan (KAÇIN dahil) öğren
        # v37.9: brain_lock — daemon eğitim ile yarışıp eğitilmiş ağırlıkları silmesin
        from .brain import brain_lock
        with brain_lock():
            brain = brain_load()
            for s in results[:50]:
                try:
                    brain_save_snapshot(brain, s)
                except Exception:
                    pass
            brain_save(brain)

        # v37.6: topPicks listesi sadece KAÇIN OLMAYAN fırsatları içerir
        opportunities = [s for s in results
                         if (s.get("autoThinkDecision") or "").upper() != "KAÇIN"]

        # PHP saveMarketMode — XU100 (varsa) tech alanlarından makro mod yaz
        try:
            xu = next((s for s in results if (s.get("code") or "").upper() == "XU100"), None)
            mode_src = xu or (results[0] if results else {})
            if mode_src:
                _new_mode = save_market_mode(mode_src, code=mode_src.get("code", "XU100"))
                mode = _new_mode or mode
        except Exception:
            pass

        # PHP logSignalHistory — Top picks'i geçmişe kaydet (per-day dedup)
        try:
            log_top_picks(results, market_mode=mode, top_n=20, min_ai_score=100)
        except Exception:
            pass

        cache = {
            "topPicks": opportunities,
            # Tüm hisselerin TAM verisi — AI eğitimi ve on-demand analiz için
            "allStocks": results,
            "marketMode": mode,
            "scanned": total,
            "successful": len(results),
            "opportunities": len(opportunities),
            "duration_sec": round(time.time() - started, 1),
            "updated": now_str(),
        }
        save_json(config.ALLSTOCKS_CACHE, cache)
        _write_progress(100, "done")
        return {"status": "done", "scanned": total, "ok": len(results),
                "marketMode": mode, "duration_sec": cache["duration_sec"]}
    except Exception as e:
        _write_progress(100, "error", str(e))
        return {"status": "error", "error": str(e)}
    finally:
        lock.release()
        # Progress dosyasını birkaç saniye sonra temizlemek daemon için bir döngü daha bekleyebilsin
        threading.Timer(15.0, _clear_progress).start()


def _safe_analyze(code: str, mode: str) -> dict | None:
    try:
        return analyze_stock(code, mode)
    except Exception:
        return None


def filter_false_signals(stocks: list[dict]) -> list[dict]:
    """Yanlış sinyal filtresi — PHP filterFalseSignals birebir.

    Kalitesiz sinyalleri saptar ve puanı düşürür / zayıf listeye taşır.
    """
    if not stocks:
        return []

    # Grafik API toplu hata tespiti: ADX=0 ve formations=[] yüzdesi > %80 ise
    # ADX filtresini devre dışı bırak (veri gelmemiş olabilir)
    zero_adx = sum(1 for s in stocks
                   if float(s.get("adxVal", 0) or 0) < 1 and not s.get("formations"))
    skip_adx_filter = (zero_adx / len(stocks)) > 0.80

    filtered: list[dict] = []
    weak: list[dict] = []

    for stk in stocks:
        rsi    = float(stk.get("rsi", 50) or 50)
        vol    = float(stk.get("volRatio", 1) or 1)
        div    = stk.get("divRsi", "yok")
        ai     = int(stk.get("aiScore", 0) or 0)
        adx    = float(stk.get("adxVal", 0) or 0)
        cmf    = float(stk.get("cmf", 0) or 0)
        mfi    = float(stk.get("mfi", 50) or 50)
        wr     = float(stk.get("williamsR", -50) or -50)
        sk     = float(stk.get("stochK", 50) or 50)
        cci    = float(stk.get("cci", 0) or 0)
        forms  = stk.get("formations") or []
        guncel = float(stk.get("guncel", 0) or 0)
        sell1  = float((stk.get("targets") or {}).get("sell1", stk.get("h1", 0)) or 0)
        st_dir = stk.get("supertrendDir", "notr")
        sar    = stk.get("sarDir", "notr")
        macd   = stk.get("macdCross", "none")

        # Katlama cezası
        if stk.get("katlamis"):
            stk = {**stk, "aiScore": int(round(ai * 0.5))}
            weak.append(stk); continue

        # Ayı RSI diverjansı
        if div == "ayi":
            ai = max(0, ai - 35)
            stk = {**stk, "aiScore": ai}

        # ULTRA FİLTRE 1: Çoklu aşırı alım
        ob_cnt = sum([rsi > 72, sk > 80, mfi > 78, cci > 150, wr > -15])
        if ob_cnt >= 3 and div != "boga":
            stk = {**stk, "aiScore": max(0, int(round(ai * 0.35)))}
            weak.append(stk); continue

        # ULTRA FİLTRE 2: Düşük hacim + yüksek RSI = pump sinyali
        if vol < 0.6 and rsi > 60:
            stk = {**stk, "aiScore": max(0, int(round(ai * 0.4)))}
            weak.append(stk); continue

        # ULTRA FİLTRE 3: Trendsiz hisse
        if not skip_adx_filter and adx < 10 and ai < 50 and not forms:
            weak.append(stk); continue

        # ULTRA FİLTRE 4: Hem Supertrend hem SAR hem MACD ayı
        bear_tech = sum([st_dir == "dusus", sar == "dusus", macd == "death"])
        if bear_tech >= 3 and ai < 80:
            stk = {**stk, "aiScore": max(0, int(round(ai * 0.45)))}
            weak.append(stk); continue

        # CMF çok negatif = kurumsal çıkış sinyali
        if cmf < -0.25:
            penalty = 25 if cmf < -0.40 else 15
            stk = {**stk, "aiScore": max(0, ai - penalty)}

        # Hedef fiyat mevcut fiyatın altındaysa skor yarıla
        if guncel > 0 and sell1 > 0 and sell1 <= guncel:
            stk = {**stk, "aiScore": max(0, int(round(stk.get("aiScore", ai) * 0.5)))}

        filtered.append(stk)

    filtered.sort(key=lambda s: s.get("aiScore", 0), reverse=True)
    weak.sort(key=lambda s: s.get("aiScore", 0), reverse=True)
    return filtered + weak


# ═══════════════════════════════════════════════════════════════════════════
# İKİ FAZLI TARAMA — PHP runBISTScanTwoPhase Python portu
# ═══════════════════════════════════════════════════════════════════════════
from .api_client import (fetch_bilanco_rasyo, fetch_getiri, fetch_sirket_sermaye,
                         fetch_sirket_profil, fetch_many)
from .sectors import piyasa_to_grup, api_sektor_to_intern, get_sector_group, sektor_from_ad
from .utils import calculate_graham


def _enrich_with_fundamentals(stock: dict, fin: dict | None,
                              bilanco: dict | None, getiri: dict | None,
                              sermaye: dict | None,
                              profil_grup: str = "", sektor_intern: str = "",
                              sektor_ham: str = "") -> dict:
    """PHP Phase 3 birebir — finData alanlarını + bonusları stock'a uygula."""
    fin = fin or {}
    bilanco = bilanco or {}
    getiri = getiri or {}
    sermaye = sermaye or {}

    fiy        = parse_api_num(fin.get("SonFiyat") or stock.get("guncel") or 0)
    net_kar    = parse_api_num(fin.get("NetKar"))
    oz_serm    = parse_api_num(fin.get("OzSermaye"))
    ser_adet   = parse_api_num(fin.get("Sermaye"))
    pd_api     = parse_api_num(fin.get("PiyasaDegeri") or fin.get("PiyDeg") or fin.get("PD"))
    fk         = parse_api_num(fin.get("FK"))
    pddd       = parse_api_num(fin.get("PiyDegDefterDeg") or fin.get("PDDD"))
    grup_raw   = str(fin.get("Grup") or "").strip().upper() or (profil_grup or "")
    fark_yz    = parse_api_num(fin.get("FarkYuzde"))
    halkak     = parse_api_num(fin.get("HalkakAciklik"))
    hacim_tl   = parse_api_num(fin.get("Hacim"))
    taban      = parse_api_num(fin.get("Taban"))
    tavan      = parse_api_num(fin.get("Tavan"))
    son4c      = parse_api_num(fin.get("SonDortCeyrek"))

    pg_str = str(fin.get("ParaGiris_Cikis") or "")
    pg_parts = pg_str.split("/") if pg_str else []
    para_giris = parse_api_num(pg_parts[0] if pg_parts else 0)
    para_cikis = parse_api_num(pg_parts[1] if len(pg_parts) > 1 else 0)
    net_para_akis = para_giris - para_cikis

    taban_fark = round((fiy - taban) / fiy * 100, 2) if fiy > 0 and taban > 0 else 0
    tavan_fark = round((tavan - fiy) / fiy * 100, 2) if fiy > 0 and tavan > 0 else 0

    # v31: ROE-ile geliştirilmiş Graham adil değer
    roe_val = float(bilanco.get("roe", 0) or 0)
    adil = calculate_graham(net_kar, oz_serm, ser_adet, roe_val, fiy)

    # Piyasa değeri (M₺)
    if pd_api > 100_000:
        market_cap_m = pd_api / 1_000_000
    elif fiy > 0 and ser_adet > 0:
        market_cap_m = (fiy * ser_adet) / 1_000_000
    else:
        market_cap_m = 0.0

    ret1m  = float(getiri.get("ret1m", 0) or 0)
    ret3m  = float(getiri.get("ret3m", 0) or 0)
    ret_yil= float(getiri.get("retYil", 0) or 0)

    net_kar_mrj  = float(bilanco.get("netKarMarj", 0) or 0)
    cari_oran    = float(bilanco.get("cariOran", 0) or 0)
    roa_val      = float(bilanco.get("roa", 0) or 0)
    brut_kar_mrj = float(bilanco.get("brutKarMarj", 0) or 0)
    borc_oz      = float(bilanco.get("borcOz", 0) or 0)
    likit_oran   = float(bilanco.get("likitOran", 0) or 0)
    kaldiraci    = float(bilanco.get("kaldiraci", 0) or 0)
    kvsa_borc    = float(bilanco.get("kvsaBorcOran", 0) or 0)
    stok_devir   = float(bilanco.get("stokDevirH", 0) or 0)
    faal_kar_mrj = float(bilanco.get("faalKarMarj", 0) or 0)
    nakit_oran   = float(bilanco.get("nakitOran", 0) or 0)
    alacak_devir = float(bilanco.get("alacakDevirH", 0) or 0)
    aktif_devir  = float(bilanco.get("aktifDevir", 0) or 0)
    recent_bedelsiz = bool(sermaye.get("recentBedelsiz", False))
    last_temettu    = float(sermaye.get("lastTemettu", 0) or 0)

    # Stock dict'ine yaz (PHP allStocks[] alanlarıyla aynı isimler)
    stock.update({
        "adil":          round(adil, 2) if adil else stock.get("adil", 0),
        "marketCap":     market_cap_m,
        "fk":            round(fk, 1),
        "pddd":          round(pddd, 2),
        "grup":          grup_raw,
        "sektor":        sektor_intern or stock.get("sektor", ""),
        "sektorHam":     sektor_ham,
        "sermaye":       ser_adet,
        "farkYuzde":     round(fark_yz, 2),
        "halkakAciklik": round(halkak, 2),
        "hacimTL":       hacim_tl,
        "paraGiris":     para_giris,
        "paraCikis":     para_cikis,
        "netParaAkis":   round(net_para_akis, 0),
        "tabanFark":     taban_fark,
        "tavanFark":     tavan_fark,
        "sonDortCeyrek": son4c,
        "ret1m":         round(ret1m, 2),
        "ret3m":         round(ret3m, 2),
        "retYil":        round(ret_yil, 2),
        "netKarMarj":    round(net_kar_mrj, 2),
        "roe":           round(roe_val, 2),
        "roa":           round(roa_val, 2),
        "cariOran":      round(cari_oran, 2),
        "brutKarMarj":   round(brut_kar_mrj, 2),
        "faalKarMarj":   round(faal_kar_mrj, 2),
        "nakitOran":     round(nakit_oran, 2),
        "borcOz":        round(borc_oz, 2),
        "likitOran":     round(likit_oran, 2),
        "kaldiraci":     round(kaldiraci, 2),
        "kvsaBorcOran":  round(kvsa_borc, 2),
        "stokDevirH":    round(stok_devir, 2),
        "alacakDevirH":  round(alacak_devir, 2),
        "aktifDevir":    round(aktif_devir, 2),
        "recentBedelsiz": recent_bedelsiz,
        "lastTemettu":   round(last_temettu, 2),
    })

    # ─── PHP Phase 3 aiScore bonusları (lines 7076-7104) ──────────────
    ai = int(stock.get("aiScore", 0) or 0)
    if   roa_val > 15:  ai = min(350, ai + 4)
    elif roa_val > 8:   ai = min(350, ai + 2)
    elif roa_val < 0:   ai = max(0,   ai - 4)
    if   brut_kar_mrj > 50: ai = min(350, ai + 4)
    elif brut_kar_mrj > 30: ai = min(350, ai + 2)
    elif 0 < brut_kar_mrj < 5: ai = max(0, ai - 3)
    if   ret_yil > 100: ai = min(350, ai + 6)
    elif ret_yil > 50:  ai = min(350, ai + 4)
    elif ret_yil > 20:  ai = min(350, ai + 2)
    elif ret_yil < -30: ai = max(0,   ai - 5)
    if   ret1m > 10:    ai = min(350, ai + 5)
    elif ret1m < -10:   ai = max(0,   ai - 5)
    if   likit_oran > 1.5: ai = min(350, ai + 3)
    elif 0 < likit_oran < 0.5: ai = max(0, ai - 4)
    if   0 < kaldiraci < 0.4: ai = min(350, ai + 3)
    elif kaldiraci > 0.7:     ai = max(0,   ai - 4)
    if   kvsa_borc > 0.7:  ai = max(0, ai - 3)
    if   stok_devir > 15:  ai = min(350, ai + 2)
    if   alacak_devir > 15: ai = min(350, ai + 3)
    elif alacak_devir > 8:  ai = min(350, ai + 1)
    elif 0 < alacak_devir < 3: ai = max(0, ai - 3)
    if   aktif_devir > 2.0: ai = min(350, ai + 3)
    elif aktif_devir > 1.0: ai = min(350, ai + 1)
    if   last_temettu > 5: ai = min(350, ai + 10)
    elif last_temettu > 2: ai = min(350, ai + 5)
    elif last_temettu > 0: ai = min(350, ai + 2)
    # recentBedelsiz: SirketSermaye API'sinden gelen geçmiş dağıtım; puan VERİLMEZ.
    # Puan yalnızca kap_bedelsiz_bonus (başvuru/onay aşaması) tarafından eklenir.
    if net_para_akis > 0 and para_giris > 0:
        ratio = net_para_akis / max(para_giris * 2, 1)
        if   ratio > 0.2:  ai = min(350, ai + 7)
        elif ratio > 0.08: ai = min(350, ai + 3)
    elif net_para_akis < 0 and para_giris > 0:
        cratio = abs(net_para_akis) / max(para_giris * 2, 1)
        if cratio > 0.2:   ai = max(0, ai - 6)
    if   halkak > 60: ai = min(350, ai + 4)
    elif 0 < halkak < 10: ai = max(0, ai - 4)
    if   son4c > 0: ai = min(350, ai + 2)
    elif son4c < 0: ai = max(0, ai - 4)
    if 0 < taban_fark < 3: ai = min(350, ai + 5)

    # ─── Halka Arz (IPO) fiyatı bonusu ────────────────────────────────
    # Cari fiyat halka arz fiyatına yakın/altındaysa skoru artır
    try:
        from .ipo_price import ipo_info
        _ipo = ipo_info(stock.get("code", ""), fiy or stock.get("guncel", 0))
        stock["ipoFiyat"]  = _ipo["ipoFiyat"]
        stock["ipoFark"]   = _ipo["ipoFark"]
        stock["ipoBonus"]  = _ipo["ipoBonus"]
        stock["ipoAltinda"] = _ipo["ipoAltinda"]
        if _ipo["ipoBonus"] > 0:
            ai = min(350, ai + _ipo["ipoBonus"])
    except Exception:
        stock.setdefault("ipoFiyat", 0.0)
        stock.setdefault("ipoFark", 0.0)
        stock.setdefault("ipoBonus", 0)
        stock.setdefault("ipoAltinda", False)

    stock["aiScore"] = ai
    _refresh_score(stock)
    return stock


def _apply_sector_momentum_boost(stocks: list[dict]) -> None:
    """PHP v29 Plan 2.3 — Her sektördeki üst %20'ye +15 aiScore bonusu."""
    by_sector: dict[str, list[float]] = {}
    for s in stocks:
        sek = s.get("sektor") or "genel"
        by_sector.setdefault(sek, []).append(float(s.get("aiScore", 0) or 0))
    thresholds: dict[str, float] = {}
    for sek, scores in by_sector.items():
        if len(scores) < 3: continue
        scores_sorted = sorted(scores, reverse=True)
        top_n = max(1, int((len(scores_sorted) * 0.20) + 0.999))
        thresholds[sek] = scores_sorted[top_n - 1]
    for s in stocks:
        sek = s.get("sektor") or "genel"
        if sek in thresholds and float(s.get("aiScore", 0) or 0) >= thresholds[sek]:
            s["aiScore"] = min(350, int(s.get("aiScore", 0) or 0) + 15)
            _refresh_score(s)


def _normalize_ortak(s: str) -> str:
    tr_from = "İĞÜŞÖÇığüşöçâîû"
    tr_to   = "IGUSOCIGUSOCAIU"
    table = str.maketrans(tr_from, tr_to)
    return (s or "").translate(table).upper().strip()


def _parse_ortaklar(raw_list: list) -> list[dict]:
    """PHP $parseOrtaklar — sadece >=10% pay, küçük/genel isimler hariç."""
    ignored = {"DIGER", "DER", "DGER", "DIER", "DIGER.", "OTHER",
               "HALKA ACIK", "HALKA", "SERBEST"}
    result = []
    if not isinstance(raw_list, list): return result
    for item in raw_list:
        if not isinstance(item, str): continue
        parts = item.split(";")
        if len(parts) < 4: continue
        ad = parts[1].strip() if len(parts) > 1 else ""
        try:
            pct = float(parts[3].strip().replace(".", "").replace(",", "."))
        except (ValueError, TypeError):
            pct = 0.0
        adN = _normalize_ortak(ad)
        if not adN or adN in ignored or len(adN) < 5 or pct < 10:
            continue
        result.append({"ad": ad, "adN": adN, "pct": pct})
    return result


def _ortak_katlama_analysis(stocks: list[dict],
                            ortak_results: dict[str, list],
                            istirakler_results: dict[str, list]) -> None:
    """PHP v29 Ortak Katlaması — büyük referans hisse katladıysa,
    aynı ortaklı küçük hisseye bonus. Yön doğrulamalı (PD kontrolü).
    """
    # Harita 1: ortakAdN → katlayan hisseler
    ortak_katlama_map: dict[str, list[dict]] = {}
    for s in stocks:
        cx = s.get("code", "")
        if not cx: continue
        is_katladi = (s.get("katlamis")
                      or float(s.get("ret3m", 0) or 0) > 40
                      or float(s.get("retYil", 0) or 0) > 60)
        if not is_katladi: continue
        raw = (ortak_results.get(cx, []) or []) + (istirakler_results.get(cx, []) or [])
        seen = set()
        for o in _parse_ortaklar(raw):
            if o["adN"] in seen: continue
            seen.add(o["adN"])
            ortak_katlama_map.setdefault(o["adN"], []).append({
                "code":      cx,
                "name":      s.get("name", cx),
                "retYil":    float(s.get("retYil", 0) or 0),
                "ret3m":     float(s.get("ret3m", 0) or 0),
                "pos52wk":   float(s.get("pos52wk", 0) or 0),
                "ortakAd":   o["ad"],
                "marketCap": float(s.get("marketCap", 0) or 0),
            })

    # Harita 2: tüm hisseler → ortakları (Kural 3)
    ortak_hisse_map: dict[str, list[dict]] = {}
    for s in stocks:
        cx = s.get("code", "")
        if not cx: continue
        raw = (ortak_results.get(cx, []) or []) + (istirakler_results.get(cx, []) or [])
        seen = set()
        for o in _parse_ortaklar(raw):
            if o["adN"] in seen: continue
            seen.add(o["adN"])
            ortak_hisse_map.setdefault(o["adN"], []).append({
                "code": cx, "name": s.get("name", cx),
                "marketCap": float(s.get("marketCap", 0) or 0),
            })

    if not ortak_katlama_map and not ortak_hisse_map:
        return

    for s in stocks:
        cx = s.get("code", "")
        if not cx or float(s.get("guncel", 0) or 0) <= 0: continue
        if (s.get("katlamis")
            or float(s.get("ret3m", 0) or 0) > 40
            or float(s.get("retYil", 0) or 0) > 60
            or float(s.get("pos52wk", 0) or 0) > 75):
            continue

        mc_p = float(s.get("marketCap", 0) or 0)
        raw_p = (ortak_results.get(cx, []) or []) + (istirakler_results.get(cx, []) or [])
        liste_p = _parse_ortaklar(raw_p)
        seen_adN: set[str] = set()
        liste_p = [o for o in liste_p if not (o["adN"] in seen_adN or seen_adN.add(o["adN"]))]

        bulunan = []
        buyuk_iliski = []
        for ortak in liste_p:
            key = ortak["adN"]
            # Kural 1+2: katlama yön kontrolü
            refs = ortak_katlama_map.get(key, [])
            refs_ok = [r for r in refs if r["code"] != cx and (
                mc_p <= 0 or float(r.get("marketCap", 0) or 0) <= 0
                or float(r.get("marketCap", 0) or 0) > mc_p * 1.2)]
            if refs_ok:
                refs_ok.sort(key=lambda r: r["retYil"] + r["ret3m"] * 3, reverse=True)
                best = refs_ok[0]
                bulunan.append({
                    "ortakAd": ortak["ad"], "ortakPct": ortak["pct"],
                    "refCode": best["code"], "refName": best["name"],
                    "refRetYil": best["retYil"], "refRet3m": best["ret3m"],
                    "refPos52wk": best["pos52wk"], "refMcap": best["marketCap"],
                })
            # Kural 3: küçük PD + büyük kardeş
            if 0 < mc_p < 10000:
                for oh in ortak_hisse_map.get(key, []):
                    if oh["code"] == cx: continue
                    ref_mc = float(oh.get("marketCap", 0) or 0)
                    if ref_mc > mc_p * 5:
                        buyuk_iliski.append({
                            "code": oh["code"], "name": oh["name"],
                            "mcap": ref_mc, "ortak": ortak["ad"], "pct": ortak["pct"],
                            "pdOrani": int(round(ref_mc / mc_p)),
                        })

        if bulunan:
            max_ref = bulunan[0]
            ref_getiri = max(max_ref["refRetYil"], max_ref["refRet3m"] * 4)
            if ref_getiri <= 0:
                p52 = max_ref["refPos52wk"]
                ref_getiri = 250 if p52 >= 98 else (120 if p52 >= 90
                              else (70 if p52 >= 80 else 30))
            bonus = 100 if ref_getiri > 200 else (80 if ref_getiri > 100
                    else (60 if ref_getiri > 60 else 40))
            s["aiScore"] = min(350, int(s.get("aiScore", 0) or 0) + bonus)
            _refresh_score(s)
            # UI/filtre için doğrudan alanlar
            s["siblingBonus"] = max(int(s.get("siblingBonus", 0) or 0), bonus)
            s["siblingType"] = "katlama"
            s["siblingRefCode"] = max_ref["refCode"]
            s["siblingRefName"] = max_ref.get("refName", "")
            s["siblingOrtakAd"] = max_ref["ortakAd"]
            s["siblingOrtakPct"] = round(max_ref["ortakPct"], 1)
            s["siblingRefRetYil"] = round(max_ref.get("refRetYil") or 0, 1)
            s["siblingRefRet3m"] = round(max_ref.get("refRet3m") or 0, 1)
            s["siblingRefPos52"] = round(max_ref.get("refPos52wk") or 0, 1)
            ref_mc_n = float(max_ref.get("refMcap") or 0)
            if ref_mc_n > 0 and mc_p > 0:
                s["siblingPdOrani"] = round(ref_mc_n / mc_p, 1)
                s["siblingRefMcap"] = round(ref_mc_n, 0)

            # PHP refLabel: REFCODE (Yıllık %X) | (3A %X) | (52Hf Zirve %X)
            ref_label = max_ref["refCode"]
            if (max_ref.get("refRetYil") or 0) > 0:
                ref_label += f" (Yıllık %{round(max_ref['refRetYil'])})"
            elif (max_ref.get("refRet3m") or 0) > 0:
                ref_label += f" (3A %{round(max_ref['refRet3m'])})"
            elif (max_ref.get("refPos52wk") or 0) > 0:
                ref_label += f" (52Hf Zirve %{round(max_ref['refPos52wk'])})"

            ortak_str = f"{max_ref['ortakAd']} (%{round(max_ref['ortakPct'], 1)})"

            mc_ratio_txt = ""
            ref_mc = float(max_ref.get("refMcap") or 0)
            if ref_mc > 0 and mc_p > 0:
                mc_ratio_txt = f" — referans hisse {round(ref_mc / mc_p)}x daha büyük PD"

            bd = s.get("breakdown") or {}
            items = bd.get("items") or []
            items.append(["🔥",
                f"Büyük Ortak Katlaması: {ortak_str} büyük ortağı {ref_label} katladı"
                f"{mc_ratio_txt} — bu hisse yüksek potansiyel taşır [AI Notu]",
                f"+{bonus}"])
            bd["items"] = items
            bd["aiScore"] = s["aiScore"]
            s["breakdown"] = bd

        if buyuk_iliski:
            buyuk_iliski.sort(key=lambda x: x["mcap"], reverse=True)
            br = buyuk_iliski[0]
            pd_orani = br["pdOrani"]
            buyuk_bonus = (50 if pd_orani >= 100 else
                           (35 if pd_orani >= 30 else
                            (20 if pd_orani >= 10 else
                             (10 if pd_orani >= 5 else 0))))
            if buyuk_bonus > 0:
                s["aiScore"] = min(350, int(s.get("aiScore", 0) or 0) + buyuk_bonus)
                _refresh_score(s)
                # UI/filtre için: küçük PD'li kardeş, büyük abi var
                if int(s.get("siblingBonus", 0) or 0) < buyuk_bonus:
                    s["siblingBonus"] = buyuk_bonus
                if not s.get("siblingType"):
                    s["siblingType"] = "kucuk_kardes"
                if not s.get("siblingRefCode"):
                    s["siblingRefCode"] = br["code"]
                    s["siblingRefName"] = br["name"]
                    s["siblingOrtakAd"] = br["ortak"]
                    s["siblingOrtakPct"] = round(br["pct"], 1)
                    s["siblingRefMcap"] = round(br["mcap"], 0)
                s["siblingPdOrani"] = max(int(s.get("siblingPdOrani", 0) or 0), pd_orani)
                bd = s.get("breakdown") or {}
                items = bd.get("items") or []
                items.append(["⚡",
                    f"Büyük Ortak İlişkisi: {br['ortak']} ortaklığıyla {br['code']} "
                    f"({round(br['mcap'])}M₺) ile aynı sahiplik yapısı — bu hissenin PD'si "
                    f"{pd_orani}x daha düşük, yüksek yakınsama potansiyeli [AI Notu]",
                    f"+{buyuk_bonus}"])
                bd["items"] = items
                bd["aiScore"] = s["aiScore"]
                s["breakdown"] = bd


def run_bist_scan_two_phase(parallel: int = 20, limit: int = 0) -> dict:
    """PHP runBISTScanTwoPhase Python portu.

    AŞAMA 1: SirketDetay + SirketProfil + BilancoRasyo (tüm hisseler, paralel)
    AŞAMA 1.5: SonFiyat>0 olan adayları seç
    AŞAMA 1.7: Getiri + SirketSermaye (sadece adaylar)
    AŞAMA 2: CHART2 (sadece adaylar)
    AŞAMA 3: Tek hisse analizi + sektör momentum + ortak katlama bonusu
    """
    from .api_client import fetch_sirket_detay
    lock = ScanLock()
    if not lock.acquire():
        return {"status": "locked"}
    _write_progress(1, status="running")
    started = time.time()
    try:
        symbols = fetch_bist_full_list()
        if limit > 0:
            symbols = symbols[:limit]
        total = len(symbols)
        if total == 0:
            _write_progress(100, "error", "no_symbols")
            return {"status": "error", "error": "no_symbols"}

        codes = [s["code"] for s in symbols if s.get("code")]
        name_map = {s["code"]: s.get("name", s["code"]) for s in symbols}

        # ── AŞAMA 1 — SirketDetay (tüm hisseler) ──────────────────────
        def _on_p1(done: int, tot: int) -> None:
            pct = max(2, min(20, int(done / max(tot, 1) * 20)))
            _write_progress(pct, status="running")
        detail_results = fetch_many(codes, fetch_sirket_detay, max_workers=parallel,
                                    on_progress=_on_p1)

        # ── AŞAMA 1 — SirketProfil (paralel, sektör + ortak listeleri) ─
        def _on_p1b(done: int, tot: int) -> None:
            pct = max(20, min(35, 20 + int(done / max(tot, 1) * 15)))
            _write_progress(pct, status="running")
        profil_raw = fetch_many(codes, fetch_sirket_profil, max_workers=parallel,
                                on_progress=_on_p1b)

        profil_grup: dict[str, str]   = {}
        sektor_intern_map: dict[str, str] = {}
        sektor_ham_map:    dict[str, str] = {}
        ortak_results:     dict[str, list] = {}
        istirakler_results:dict[str, list] = {}
        for cx, jp in profil_raw.items():
            if not isinstance(jp, dict): continue
            if jp.get("Piyasa"):
                profil_grup[cx] = piyasa_to_grup(str(jp["Piyasa"]))
            if jp.get("Sektor"):
                sektor_intern_map[cx] = api_sektor_to_intern(str(jp["Sektor"]))
                sektor_ham_map[cx]    = str(jp["Sektor"]).strip()
            if isinstance(jp.get("listeholders"), list):
                ortak_results[cx] = jp["listeholders"]
            if isinstance(jp.get("listeholdings"), list):
                istirakler_results[cx] = jp["listeholdings"]

        # ── AŞAMA 1 — BilancoRasyo ────────────────────────────────────
        def _on_p1c(done: int, tot: int) -> None:
            pct = max(35, min(48, 35 + int(done / max(tot, 1) * 13)))
            _write_progress(pct, status="running")
        bilanco_results = fetch_many(codes, fetch_bilanco_rasyo, max_workers=parallel,
                                     on_progress=_on_p1c)

        # ── AŞAMA 1.5 — Adayları belirle (SonFiyat > 0) ──────────────
        candidates: dict[str, dict] = {}
        for cx, fin in detail_results.items():
            if not isinstance(fin, dict): continue
            if parse_api_num(fin.get("SonFiyat")) > 0:
                candidates[cx] = fin

        if not candidates:
            _write_progress(100, "error", "no_candidates")
            return {"status": "error", "error": "no_candidates"}

        # ── AŞAMA 1.7 — Getiri + SirketSermaye (sadece adaylar) ──────
        def _on_p17a(done: int, tot: int) -> None:
            pct = max(48, min(56, 48 + int(done / max(tot, 1) * 8)))
            _write_progress(pct, status="running")
        getiri_results = fetch_many(list(candidates.keys()), fetch_getiri,
                                    max_workers=parallel, on_progress=_on_p17a)

        def _on_p17b(done: int, tot: int) -> None:
            pct = max(56, min(64, 56 + int(done / max(tot, 1) * 8)))
            _write_progress(pct, status="running")
        sermaye_results = fetch_many(list(candidates.keys()), fetch_sirket_sermaye,
                                     max_workers=parallel, on_progress=_on_p17b)

        # ── AŞAMA 2 — CHART2 (sadece adaylar, 220 bar) ───────────────
        def _on_p2(done: int, tot: int) -> None:
            pct = max(64, min(88, 64 + int(done / max(tot, 1) * 24)))
            _write_progress(pct, status="running")
        chart_results = fetch_many(list(candidates.keys()),
                                   lambda c: fetch_chart2(c, "G", 220),
                                   max_workers=parallel, on_progress=_on_p2)

        # ── IPO (Halka Arz) fiyatlarını paralel olarak prefetch et ──
        # Cache'de olmayanlar için aylık (A) chart'tan ilk bar açılış fiyatını çek.
        try:
            from .ipo_price import prefetch as _ipo_prefetch
            _ipo_prefetch(list(candidates.keys()), max_workers=max(2, parallel // 2))
        except Exception:
            pass

        # ── AŞAMA 3 — Analiz + finData enrichment ────────────────────
        # Önce piyasa modu tespiti için cached top picks
        cached = load_json(config.ALLSTOCKS_CACHE, {})
        prev_picks = cached.get("topPicks", []) if isinstance(cached, dict) else []
        mode = detect_market_mode(prev_picks)

        results: list[dict] = []
        cand_total = len(candidates)
        cand_done = 0
        for cx, fin in candidates.items():
            cand_done += 1
            if cand_done % max(1, cand_total // 25) == 0:
                pct = 88 + int(cand_done / max(cand_total, 1) * 10)
                _write_progress(min(98, pct), status="running")
            chart = chart_results.get(cx)
            try:
                stk = analyze_stock(cx, mode, chart=chart)
            except Exception:
                stk = None
            if stk is None:
                continue
            stk["name"] = name_map.get(cx, cx)
            # Sektör tespiti: 1. API ham sektör, 2. şirket adından fallback, 3. kod tablosu
            sek_intern = sektor_intern_map.get(cx)
            if not sek_intern or sek_intern == config.SEKTOR_GENEL:
                ad_fallback = sektor_from_ad(name_map.get(cx, ""))
                if ad_fallback != config.SEKTOR_GENEL:
                    sek_intern = ad_fallback
            if not sek_intern:
                sek_intern = get_sector_group(cx)
            _enrich_with_fundamentals(
                stk, fin,
                bilanco_results.get(cx),
                getiri_results.get(cx),
                sermaye_results.get(cx),
                profil_grup.get(cx, ""),
                sek_intern,
                sektor_ham_map.get(cx, ""),
            )
            results.append(stk)

        # API listesinde olup veri gelmeyen hisseleri en sona ekle
        processed_codes = {s.get("code") for s in results}
        for cx in codes:
            if cx in processed_codes: continue
            results.append({
                "code": cx, "name": name_map.get(cx, cx),
                "guncel": 0, "alPuan": 0, "adil": 0, "trend": "Notr",
                "rsi": 50, "aiScore": 0, "score": 0, "signalQuality": 0,
                "marketMode": mode, "sektor": get_sector_group(cx),
                "marketCap": 0, "katlamis": False, "grup": "",
                "formations": [], "breakdown": {},
            })

        # Sektör momentum boost (PHP v29 Plan 2.3)
        _apply_sector_momentum_boost([s for s in results if float(s.get("guncel", 0) or 0) > 0])

        # Ortak katlama analizi (PHP v29)
        _ortak_katlama_analysis(results, ortak_results, istirakler_results)

        # Uyuyan Mücevher + Erken Yakalama bonuslarını burgan/finData enrichment
        # sonrası yeniden hesapla. analyze_stock sırasında marketCap=0 / sektor=genel
        # olduğu için ilk hesap sıfır dönüyordu (her iki fonksiyon erken exit yapar).
        try:
            from .scoring_extras import (reset_sector_cache, early_catch_bonus,
                                          sleeper_breakdown, kap_tipe_donusum_bonus,
                                          kap_bedelsiz_bonus)
            for s in results:
                sb_total, sb_items = sleeper_breakdown(s)
                old_sb = int(s.get("sleeperBonus", 0) or 0)
                if sb_total != old_sb:
                    delta = sb_total - old_sb
                    s["sleeperBonus"] = sb_total
                    s["sleeperItems"] = sb_items
                    s["aiScore"] = max(0, min(350, int(s.get("aiScore", 0) or 0) + delta))
            # Erken yakalama: önce sektör cache'ini sıfırla — taze sonuçlardan tazelensin.
            reset_sector_cache()
            for s in results:
                ec_total, ec_items = early_catch_bonus(s)
                old_ec = int(s.get("earlyCatchBonus", 0) or 0)
                if ec_total != old_ec:
                    delta = ec_total - old_ec
                    s["earlyCatchBonus"] = ec_total
                    s["earlyCatchItems"] = ec_items
                    s["aiScore"] = max(0, min(350, int(s.get("aiScore", 0) or 0) + delta))
            # KAP "Tipe Dönüşüm" bonusu — sadece dipteki hisseler için (paralel).
            _apply_kap_bonus_parallel(results, kap_tipe_donusum_bonus)
            # KAP "Bedelsiz Sermaye Artırımı" bonusu — tüm hisseler için (paralel).
            _apply_bedelsiz_bonus_parallel(results, kap_bedelsiz_bonus)
        except Exception:
            pass

        # ── Tavan & Katlama Radarı ─────────────────────────────────────
        # Her hisseye tavan/katlama tespiti uygula, NEDEN faktörlerini çıkar,
        # geçmiş DNA arşiviyle benzerlik bul, sıradaki tavan adayını skorla.
        # En güçlü adaylara aiScore bonusu vererek listenin tepesine taşı.
        try:
            from .scoring_extras import tavan_radar_bonus
            from . import tavan_katlama as _tk
            _tk_archive = _tk.load_tavan_archive()  # bir kez yükle
            for s in results:
                if float(s.get("guncel", 0) or 0) <= 0: continue
                tr_total, _tr_items = tavan_radar_bonus(s, archive=_tk_archive)
                old_tr = int(s.get("tavanRadarBonus", 0) or 0)
                if tr_total != old_tr:
                    delta = tr_total - old_tr
                    s["tavanRadarBonus"] = tr_total
                    s["aiScore"] = max(0, min(350, int(s.get("aiScore", 0) or 0) + delta))
            # Bugünün tavan/katlama hisselerini DNA arşivine işle (öğrenme)
            try: _tk.harvest_archives([s for s in results if float(s.get("guncel", 0) or 0) > 0])
            except Exception: pass
        except Exception:
            pass

        # Yanlış sinyal filtresi — sadece fiyat verisi olanlara
        data_stocks   = [s for s in results if float(s.get("guncel", 0) or 0) > 0]
        nodata_stocks = [s for s in results if float(s.get("guncel", 0) or 0) <= 0]
        filtered = filter_false_signals(data_stocks)
        if not filtered and data_stocks:
            data_stocks.sort(key=lambda s: s.get("aiScore", 0), reverse=True)
            filtered = data_stocks
        filtered.extend(nodata_stocks)

        # v37.4: Sıralama öncesi tüm bonusları içeren güncel predatorScore'u garantile
        for s in filtered:
            _refresh_score(s)

        # v37.6: KAÇIN'lar en alta, sonra hedef fiyatı olanlar, sonra predatorScore
        def _sort_key(s: dict):
            is_avoid = (s.get("autoThinkDecision") or "").upper() == "KAÇIN"
            has_target = float(s.get("h1", 0) or 0) > float(s.get("guncel", 0) or 0)
            pred = float(s.get("predatorScore", s.get("aiScore", 0)) or 0)
            return (0 if is_avoid else 1, 1 if has_target else 0, pred)
        filtered.sort(key=_sort_key, reverse=True)

        # v37.6: topPicks sadece KAÇIN OLMAYAN fırsatları içerir
        opportunities = [s for s in filtered
                         if (s.get("autoThinkDecision") or "").upper() != "KAÇIN"]

        # Tavan & Katlama radar verisi — UI panelleri için (3 bölüm)
        try:
            from . import tavan_katlama as _tk_radar
            _tk_radar.build_radar(filtered)
        except Exception:
            pass

        # Brain snapshot
        # v37.9: brain_lock — daemon eğitim ile yarışıp eğitilmiş ağırlıkları silmesin
        from .brain import brain_lock
        with brain_lock():
            brain = brain_load()
            for s in filtered[:50]:
                try: brain_save_snapshot(brain, s)
                except Exception: pass
            brain_save(brain)

        # Market mode kayıt + sinyal geçmişi
        try:
            xu = next((s for s in filtered if (s.get("code") or "").upper() == "XU100"), None)
            mode_src = xu or (filtered[0] if filtered else {})
            if mode_src:
                _new = save_market_mode(mode_src, code=mode_src.get("code", "XU100"))
                mode = _new or mode
        except Exception: pass
        try: log_top_picks(filtered, market_mode=mode, top_n=20, min_ai_score=100)
        except Exception: pass

        cache = {
            "topPicks":     opportunities,
            # Tüm hisselerin TAM verisi — AI eğitimi ve on-demand analiz için
            "allStocks":    filtered,
            "marketMode":   mode,
            "scanned":      total,
            "candidates":   len(candidates),
            "successful":   len([s for s in filtered if float(s.get("guncel", 0) or 0) > 0]),
            "opportunities": len(opportunities),
            "duration_sec": round(time.time() - started, 1),
            "updated":      now_str(),
            "twoPhase":     True,
        }
        save_json(config.ALLSTOCKS_CACHE, cache)
        _write_progress(100, "done")
        return {"status": "done", "scanned": total, "candidates": len(candidates),
                "ok": cache["successful"], "marketMode": mode,
                "duration_sec": cache["duration_sec"]}
    except Exception as e:
        _write_progress(100, "error", str(e))
        return {"status": "error", "error": str(e)}
    finally:
        lock.release()
        threading.Timer(15.0, _clear_progress).start()
