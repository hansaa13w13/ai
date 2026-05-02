"""otoEngineMulti — sprint modu pozisyon yöneticisi."""
from __future__ import annotations
from . import config
from .portfolio import (oto_load, oto_save, oto_lock, oto_log, oto_buy_position,
                        oto_close_position, oto_fetch_live_price)
from .ai_think import (ai_driven_min_score, ai_driven_risk_pct,
                       ai_driven_market_bias, ai_driven_max_hold_days)
from .market import get_market_mode
from .telegram import send_tg, send_oto_tg
import time as _time
from datetime import datetime as _dt
from .utils import is_market_open, now_str, count_business_days, now_tr, tg_footer as _tg_footer
from .sectors import get_sector_group


def oto_engine_multi(top_picks: list[dict]) -> None:
    """PHP otoEngineMulti karşılığı — pozisyon yönetimi tek geçişi.
    v37.9: Tüm fonksiyon `oto_lock` ile sarılır — engine içindeki ara save'ler
    ve oto_close_position'un kendi load/save'leri arasında bayat dict yazımı
    olmaz (pozisyon kaybolması/dirilmesi sorunu).
    """
    if not top_picks:
        return

    ai_min_score = ai_driven_min_score()
    ai_risk_pct = ai_driven_risk_pct()
    ai_market_bias = ai_driven_market_bias()

    n = now_tr()
    day_num = n.isoweekday()
    time_min = n.hour * 60 + n.minute
    if not (1 <= day_num <= 5 and 600 <= time_min <= 1075):
        return
    block_new = (time_min < 630 or time_min > 1030)

    with oto_lock():
        _oto_engine_multi_locked(top_picks, ai_min_score, ai_risk_pct,
                                 ai_market_bias, block_new)


def _oto_engine_multi_locked(top_picks: list[dict], ai_min_score: int,
                             ai_risk_pct: float, ai_market_bias: str,
                             block_new: bool) -> None:
    oto = oto_load()
    pick_by_code = {p.get("code"): p for p in top_picks}

    # ── ADIM 1: Mevcut pozisyonları güncelle / çıkış kontrolü ────────────────
    for code in list(oto["positions"].keys()):
        pos = oto["positions"].get(code)
        if not pos:
            continue
        entry = float(pos.get("entry", 0))
        h1 = float(pos.get("h1", 0))
        h2 = float(pos.get("h2", 0))
        h3 = float(pos.get("h3", 0))
        stop = float(pos.get("stop", 0))

        live = 0.0
        if code in pick_by_code:
            live = float(pick_by_code[code].get("guncel", 0) or 0)
        if live <= 0:
            live = oto_fetch_live_price(code)
        if live <= 0:
            continue

        pos["guncel"] = live
        pos["last_check"] = now_str()

        # ── BEKLEYEN (limit emir) kontrolü ───────────────────────────────
        if pos.get("status") == "BEKLEYEN":
            limit_p = float(pos.get("limit_entry", 0) or 0)
            bought_at = pos.get("bought_at", "")
            # 2 iş günü zaman aşımı: yaklaşık 2 × 7.5saat × 3600 = 54000 saniye
            try:
                _age_s = (_time.time() -
                          _dt.strptime(bought_at[:19], "%Y-%m-%d %H:%M:%S").timestamp()
                          ) if bought_at else 999999
            except Exception:
                _age_s = 0

            if limit_p <= 0:
                # Geçersiz limit → anında aç
                pos["status"] = "AÇIK"; pos["entry"] = live
                pos["trail_high"] = live; pos["pnl_pct"] = 0.0
                oto_log(f"LİMİT HEMEN (geçersiz limit): {code} @ {live:.2f}₺", "buy")

            elif live <= limit_p * 1.005:
                # Fiyat limite ulaştı → ÇALIŞTIRILDI
                pos["status"] = "AÇIK"; pos["entry"] = live
                pos["trail_high"] = live; pos["pnl_pct"] = 0.0
                oto_log(f"LİMİT TETİKLENDİ: {code} @ {live:.2f}₺ "
                        f"(hedef:{limit_p:.2f}₺)", "buy")
                send_oto_tg(f"🟡 *OTO — LİMİT TETİKLENDİ!*\n"
                            f"*{code}* belirlenen limite düştü — pozisyon AÇILDI\n"
                            f"💰 Limit: {limit_p:.2f}₺ → Fiyat: {live:.2f}₺\n"
                            f"🎯 H1: {pos.get('h1',0):.2f}₺  "
                            f"Stop: {pos.get('stop',0):.2f}₺{_tg_footer()}")

            elif live >= limit_p * 1.06 or _age_s > 54000:
                # Fiyat %6 yukarı kaçtı VEYA 2 gün geçti → İPTAL
                reason = "limit_kacis" if live >= limit_p * 1.06 else "limit_zaman_asimi"
                oto_save(oto)
                oto_close_position(code, live, reason)
                oto_log(f"LİMİT İPTAL ({reason}): {code} "
                        f"live={live:.2f}₺ limit={limit_p:.2f}₺", "info")
                send_oto_tg(f"⚪ *OTO — LİMİT İPTAL*\n"
                            f"*{code}* {'fiyat kaçtı' if 'kacis' in reason else 'süre doldu'}\n"
                            f"💰 Piyasa: {live:.2f}₺  Limit: {limit_p:.2f}₺{_tg_footer()}")
                oto = oto_load(); continue

            else:
                # Hâlâ bekleniyor — fiyat aralıkta
                pct_diff = (limit_p - live) / live * 100
                oto_log(f"LİMİT BEKLENİYOR: {code} live={live:.2f}₺ "
                        f"limit={limit_p:.2f}₺ (-%{pct_diff:.1f})", "info")
                continue  # çıkış kontrolleri geçilsin, sadece fiyat güncellendi

        if entry > 0 and abs(live - entry) / entry > 0.50:
            continue

        pnl_pct = round((live - entry) / entry * 100, 2) if entry > 0 else 0.0
        pos["pnl_pct"] = pnl_pct

        # AI canlı değerlendirme
        live_pick = pick_by_code.get(code)
        if live_pick:
            cur_dec = live_pick.get("autoThinkDecision", "NÖTR")
            cur_conf = int(live_pick.get("autoThinkConf", 50) or 50)
            pos["ai_decision_live"] = cur_dec
            pos["ai_conf_live"] = cur_conf

            # AI KAÇIN diyorsa erken çık
            if cur_dec == "KAÇIN" and not pos.get("h1_hit") and pnl_pct > -8.0:
                oto_save(oto)
                pnl = oto_close_position(code, live, "ai_kacin")
                send_oto_tg(f"🧠 *AI OTONOM ÇIKIŞ — KAÇIN*\nAI bozulan koşullar nedeniyle *{code}* pozisyonundan çıkış kararı verdi\n"
                            f"💰 Giriş: {entry:.2f}₺ → {live:.2f}₺\n"
                            f"📉 K/Z: *{('+' if pnl >= 0 else '')}{pnl:.2f}%*\n"
                            f"🤖 AI Güven: %{cur_conf}{_tg_footer()}")
                oto_log(f"AI KAÇIN ÇIKIŞ: {code} @ {live:.2f}₺  K/Z:{pnl:.2f}%  Conf:{cur_conf}%", "sell")
                oto = oto_load()
                continue

            # DİKKAT + kâr → stop maliyete
            if cur_dec == "DİKKAT" and pnl_pct > 0.5 and not pos.get("h1_hit"):
                new_stop = max(float(pos.get("stop", 0) or 0), entry)
                if new_stop > float(pos.get("stop", 0) or 0):
                    pos["stop"] = new_stop
                    pos["stpct"] = 0
                    oto_log(f"AI DİKKAT — STOP MALİYETE: {code} stop={new_stop} pnl:{pnl_pct}%", "info")
                    send_oto_tg(f"⚠️ *AI DİKKAT — Stop Maliyete*\n*{code}* için AI dikkat sinyali\nStop: {new_stop:.2f}₺  K/Z:+{pnl_pct}%{_tg_footer()}")

            # ── GERÇEK BEYİN güçlü ayı sinyali — stop sıkıştır veya erken çık
            if live_pick and not pos.get("h1_hit"):
                try:
                    from .real_brain import rb_predict, rb_get_status
                    from .brain import brain_load as _bl
                    _rb_brain = _bl()
                    _rb_st = rb_get_status(_rb_brain)
                    if _rb_st.get("ready") and int(_rb_st.get("n", 0)) >= 50:
                        _rb_p, _rb_c = rb_predict(_rb_brain, live_pick)
                        pos["rb_prob_live"] = round(_rb_p, 4)
                        pos["rb_conf_live"] = round(_rb_c, 4)
                        # Güçlü ayı: prob < 0.30 ve yüksek güven → maliyet üstündeyse çık
                        if _rb_p < 0.30 and _rb_c >= 0.45 and pnl_pct > -5.0 and cur_dec != "KAÇIN":
                            oto_save(oto)
                            pnl = oto_close_position(code, live, "ai_kacin")
                            send_oto_tg(
                                f"🧠 *GERÇEK BEYİN UYARISI — ÇIKIŞ*\n"
                                f"*{code}* için RF+GBM ayı sinyali (%{int(_rb_p*100)} olasılık)\n"
                                f"💰 {entry:.2f}₺ → {live:.2f}₺\n"
                                f"📉 K/Z: *{('+' if pnl >= 0 else '')}{pnl:.2f}%*\n"
                                f"🤖 Güven: %{int(_rb_c*100)}{_tg_footer()}")
                            oto_log(f"RB AYI ÇIKIŞ: {code} rb_prob={_rb_p:.2f} conf={_rb_c:.2f} K/Z:{pnl:.2f}%", "sell")
                            oto = oto_load()
                            continue
                        # Orta ayı: prob < 0.40 ve güven >= 0.50 ve kârda → stop maliyete sıkıştır
                        elif _rb_p < 0.40 and _rb_c >= 0.50 and pnl_pct > 0.3 and not pos.get("breakeven_set"):
                            _be = round(entry * 1.001, 4)
                            if _be > float(pos.get("stop", 0) or 0):
                                pos["stop"] = _be
                                pos["stpct"] = 0
                                pos["breakeven_set"] = True
                                oto_log(f"RB DİKKAT — STOP MALİYETE: {code} rb_prob={_rb_p:.2f}", "info")
                except Exception:
                    pass

        # H3
        if h3 > 0 and live >= h3:
            oto_save(oto)
            pnl = oto_close_position(code, live, "h3_hedef")
            oto_log(f"H3 ÇIKIŞ: {code} @ {live:.2f}₺  K/Z:+{pnl:.2f}%", "sell")
            send_oto_tg(f"🚀 *OTO — H3 HEDEFİ!*\n*{code}* tam hedefe ulaştı\n"
                        f"💰 Giriş: {entry:.2f}₺ → *{live:.2f}₺*\n📈 Kâr: *+{pnl:.2f}%*{_tg_footer()}")
            oto = oto_load(); continue

        # H2
        if h2 > 0 and live >= h2 and not pos.get("h2_hit"):
            pos["h2_hit"] = True
            pos["h2_hit_at"] = now_str()
            if h1 > stop:
                pos["stop"] = h1
                pos["stpct"] = round((live - h1) / live * 100, 1) if live > 0 else 0
            oto_log(f"H2 VURULDU: {code} @ {live:.2f}₺ stop H1'e", "target")
            send_oto_tg(f"🎯 *OTO — H2 HEDEFİ!*\n*{code}* → K/Z:+{pnl_pct:.1f}%\nStop H1 seviyesine: {h1:.2f}₺{_tg_footer()}")

        # H1 — kısmi çıkış (%OTO_H1_PARTIAL_PCT) veya tam çıkış
        if h1 > 0 and live >= h1 and not pos.get("h1_hit"):
            held = count_business_days(pos.get("bought_at", now_str()))
            if config.OTO_H1_AUTO_SELL and not pos.get("partial_sold"):
                total_qty   = int(pos.get("qty", 1))
                partial_pct = getattr(config, "OTO_H1_PARTIAL_PCT", 1.0)
                if partial_pct < 1.0 and total_qty >= 2:
                    # ── Kısmi çıkış: %50 sat, kalan trailing ile devam ──────
                    qty_sell = max(1, int(total_qty * partial_pct))
                    oto_save(oto)
                    pnl = oto_close_position(code, live, "h1_partial",
                                             qty_to_close=qty_sell)
                    oto = oto_load()
                    pos = oto["positions"].get(code)
                    if pos:
                        pos["h1_hit"]      = True
                        pos["h1_hit_at"]   = now_str()
                        pos["h1_hit_px"]   = live
                        pos["trail_active"] = True
                        pos["trail_high"]  = live
                        if entry > stop:
                            pos["stop"] = entry; pos["stpct"] = 0
                        oto_save(oto)
                    oto_log(
                        f"H1 KISMİ: {code} %{int(partial_pct*100)} "
                        f"({qty_sell}/{total_qty} lot) @ {live:.2f}₺ "
                        f"K/Z:+{pnl:.2f}% {held}gün", "sell")
                    send_oto_tg(
                        f"🎯 *H1 KISMİ ÇIKIŞ — %{int(partial_pct*100)} SATILDI*\n"
                        f"*{code}* H1 hedefe ulaştı\n"
                        f"💰 {entry:.2f}₺ → *{live:.2f}₺*\n"
                        f"📈 Kâr: *+{pnl:.2f}%* · {qty_sell}/{total_qty} lot "
                        f"· ⏱ {held} iş günü\n"
                        f"🔄 Kalan {total_qty-qty_sell} lot trailing ile devam"
                        f"{_tg_footer()}")
                    oto = oto_load(); continue
                else:
                    # ── Tam çıkış ──────────────────────────────────────────
                    oto_save(oto)
                    pnl = oto_close_position(code, live, "h1_hedef")
                    oto_log(
                        f"H1 SPRINT: {code} @ {live:.2f}₺ "
                        f"K/Z:+{pnl:.2f}% Süre:{held}gün", "sell")
                    send_oto_tg(
                        f"🎯 *SPRINT — H1 SATILDI!*\n"
                        f"*{code}* hedefe ulaştı — POZİSYON KAPATILDI\n"
                        f"💰 {entry:.2f}₺ → *{live:.2f}₺*\n"
                        f"📈 Kâr: *+{pnl:.2f}%* ⏱ {held} iş günü\n"
                        f"🔄 Yeni fırsat aranıyor...{_tg_footer()}")
                    oto = oto_load(); continue
            elif not config.OTO_H1_AUTO_SELL:
                pos["h1_hit"]      = True
                pos["h1_hit_at"]   = now_str()
                pos["h1_hit_px"]   = live
                pos["trail_active"] = True
                pos["trail_high"]  = live
                if entry > stop:
                    pos["stop"] = entry; pos["stpct"] = 0
                oto_log(f"H1 VURULDU: {code} @ {live:.2f}₺ trailing AÇILDI", "target")

        # AI tutma süresi
        if config.OTO_SPRINT_MODE and not pos.get("h1_hit"):
            ba = pos.get("bought_at", "")
            if ba:
                held = count_business_days(ba)
                max_h = ai_driven_max_hold_days(pos)
                if held >= max_h:
                    oto_save(oto)
                    pnl = oto_close_position(code, live, "zaman_asimi")
                    dec = pos.get("ai_decision_live", "NÖTR")
                    oto_log(f"AI ZAMAN: {code} {held}/{max_h}gün AI:{dec} K/Z:{pnl:.2f}%", "rotate")
                    send_oto_tg(f"⏰ *AI — TUTMA SÜRESİ DOLDU*\n*{code}* AI: *{max_h} iş günü* (AI: {dec})\n"
                                f"📉 K/Z: *{('+' if pnl >= 0 else '')}{pnl:.2f}%*\n"
                                f"🔄 Yeni fırsat aranıyor...{_tg_footer()}")
                    oto = oto_load(); continue

        # ── AUTO BREAK-EVEN: Kâr eşiğini aşınca stop maliyete taşı ─────────
        _be_trig = getattr(config, "OTO_BREAKEVEN_TRIGGER_PCT", 2.0)
        _cur_stop_be = float(pos.get("stop", stop) or stop)
        if (pnl_pct >= _be_trig
                and entry > 0
                and _cur_stop_be < entry * 0.999
                and not pos.get("breakeven_set")
                and not pos.get("h1_hit")):
            _be_stop = round(entry * 1.001, 4)
            pos["stop"] = _be_stop
            pos["stpct"] = round((live - _be_stop) / live * 100, 1) if live > 0 else 0
            pos["breakeven_set"] = True
            oto_log(f"BREAK-EVEN OTOMASYON: {code} stop={_be_stop:.2f}₺ "
                    f"kâr=%{pnl_pct:.1f}≥%{_be_trig:.1f}", "info")
            send_oto_tg(f"🔒 *BREAK-EVEN OTOMATİK*\n"
                        f"*{code}* kâr %{pnl_pct:.1f} eşiği geçti → Stop maliyete taşındı\n"
                        f"📍 Yeni stop: {_be_stop:.2f}₺{_tg_footer()}")

        # ── CHANDELIER MULTI-PHASE TRAILING STOP ─────────────────────────────
        # Faz 1 (açık): ATR × 3.0 — geniş, volatiliteye saygılı
        # Faz 2 (H1 sonrası): ATR × 2.0 — orta, kâr koruyor
        # Faz 3 (H2 sonrası): ATR × 1.5 — sıkı, kâr kilitleniyor
        if pos.get("trail_active"):
            trail_high = max(float(pos.get("trail_high", live)), live)
            pos["trail_high"] = trail_high
            atr_val = float(pos.get("atr14", 0) or 0)
            if atr_val > 0 and live > 0:
                if pos.get("h2_hit"):
                    _ch_mult = getattr(config, "OTO_CHANDELIER_MULT_H2",   1.5)
                elif pos.get("h1_hit"):
                    _ch_mult = getattr(config, "OTO_CHANDELIER_MULT_H1",   2.0)
                else:
                    _ch_mult = getattr(config, "OTO_CHANDELIER_MULT_OPEN", 3.0)
                trail_stop = trail_high - atr_val * _ch_mult
                pos["trail_type"] = f"chandelier_x{_ch_mult}"
            else:
                pnl_now = (live - entry) / entry * 100 if entry > 0 else 0
                trail_pct = 0.025 if pnl_now > 20 else (0.03 if pnl_now > 10 else 0.035)
                trail_stop = trail_high * (1 - trail_pct)
                pos["trail_type"] = "pct"
            cur_stop = float(pos.get("stop", stop) or stop)
            if trail_stop > cur_stop > 0:
                pos["stop"] = round(trail_stop, 4)
                pos["stpct"] = round((live - trail_stop) / live * 100, 1) if live > 0 else 0

        # Stop kontrol
        cur_stop = float(pos.get("stop", stop) or stop)
        if cur_stop > 0 and live <= cur_stop:
            oto_save(oto)
            pnl = oto_close_position(code, live, "stop")
            oto_log(f"STOP: {code} @ {live:.2f}₺ K/Z:{pnl:.2f}%", "stop")
            emoji = "🛑" if pnl < 0 else "✅"
            send_oto_tg(f"{emoji} *OTO — STOP!*\n*{code}* stop seviyesini kırdı\n"
                        f"💰 {entry:.2f}₺ → {live:.2f}₺\n"
                        f"📉 K/Z: *{('+' if pnl >= 0 else '')}{pnl:.2f}%*{_tg_footer()}")
            oto = oto_load(); continue

    oto_save(oto)
    oto = oto_load()

    # ── GÜNLÜK DRAWDOWN SİGORTASI ─────────────────────────────────────────────
    _dd_stats  = oto.get("stats", {})
    _today_str = now_tr().strftime("%Y-%m-%d")
    if _dd_stats.get("daily_date") != _today_str:
        _dd_stats["daily_date"] = _today_str
        _dd_stats["daily_pnl"]  = 0.0
        oto_save(oto)
    _pv      = float(_dd_stats.get("portfolio_value", config.OTO_PORTFOLIO_VALUE) or config.OTO_PORTFOLIO_VALUE)
    _dpnl    = float(_dd_stats.get("daily_pnl", 0))
    _dpct    = (_dpnl / _pv * 100) if _pv > 0 else 0.0
    _dd_lim  = getattr(config, "OTO_DAILY_DD_LIMIT", 3.0)
    if _dpct < -_dd_lim:
        oto_log(
            f"GÜNLÜK DRAWDOWN SİGORTASI: bugün {_dpct:.2f}% < "
            f"-%{_dd_lim:.1f} — yeni giriş DURDURULDU", "warn")
        block_new = True

    # ── KAYIP SERİSİ ADAPTASYONU ─────────────────────────────────────────────
    # Üst üste kayıplar → sistem otomatik defansif moda girer.
    # 2+ kayıp: ai_min_score %25 artar (daha seçici)
    # 3+ kayıp: yeni giriş seans sonuna kadar durdurulur
    _c_losses = int(oto.get("stats", {}).get("consecutive_losses", 0))
    _streak_pause  = getattr(config, "OTO_STREAK_LOSS_PAUSE",  3)
    _streak_strict = getattr(config, "OTO_STREAK_LOSS_STRICT", 2)
    if _c_losses >= _streak_pause and not block_new:
        oto_log(f"KAYIP SERİSİ {_c_losses}× DURDURMA: "
                f"{_c_losses}/{_streak_pause} ardışık kayıp — yeni giriş seansa kadar DURAKLATILDI",
                "warn")
        block_new = True
    elif _c_losses >= _streak_strict:
        _old_min = ai_min_score
        ai_min_score = int(ai_min_score * 1.25)
        oto_log(f"KAYIP SERİSİ {_c_losses}× SIKIŞTIRIM: "
                f"min_score {_old_min}→{ai_min_score} (%25 artı)", "warn")

    # ── ADIM 2: Yeni pozisyon aç ─────────────────────────────────────────────
    open_codes = list(oto["positions"].keys())
    slots = config.OTO_MAX_POSITIONS - len(open_codes)
    added = 0

    if slots > 0 and not block_new:
        cur_mode = get_market_mode()
        for pick in top_picks:
            if added >= slots:
                break
            p_code = pick.get("code", "")
            if not p_code or p_code in open_codes:
                continue
            score = float(pick.get("score", 0) or 0)
            if score < ai_min_score:
                break
            if float(pick.get("rr", 0) or 0) < config.OTO_MIN_RR:
                continue
            if float(pick.get("h1", 0) or 0) <= float(pick.get("guncel", 0) or 0):
                continue
            if float(pick.get("stop", 0) or 0) <= 0:
                continue
            if float(pick.get("volRatio", 1) or 1) < 0.4:
                oto_log(f"HACİM SIFIR: {p_code}", "info"); continue
            if float(pick.get("pos52wk", 50) or 50) > 80 and float(pick.get("rsi", 50) or 50) > 70:
                oto_log(f"AŞIRI ISINMIŞ: {p_code}", "info"); continue

            min_score_mode = ai_min_score
            if cur_mode == "temkinli": min_score_mode = int(ai_min_score * 1.15)
            if cur_mode == "ayi":      min_score_mode = int(ai_min_score * 1.35)
            if ai_market_bias == "bull_bias": min_score_mode = int(min_score_mode * 0.90)
            if ai_market_bias == "bear_bias": min_score_mode = int(min_score_mode * 1.12)
            if score < min_score_mode:
                oto_log(f"AI+MOD FİLTRESİ [{cur_mode}/{ai_market_bias}]: {p_code} {score} < {min_score_mode}", "info")
                continue

            pick_sektor = pick.get("sektor") or get_sector_group(p_code)
            sektor_count = sum(1 for oc in open_codes
                               if (oto["positions"].get(oc, {}).get("sektor") or get_sector_group(oc)) == pick_sektor)
            if sektor_count >= 2:
                oto_log(f"SEKTÖR KORELASYON: {p_code} sektör:{pick_sektor}", "info"); continue

            sq = int(pick.get("signalQuality", 0) or 0)
            if sq < 4:
                oto_log(f"SİNYAL KALİTESİ DÜŞÜK: {p_code} sq={sq}", "info"); continue

            # ── ATR/fiyat volatilite filtresi ─────────────────────────────
            _atr_v = float(pick.get("atr14", 0) or 0)
            _cur_p = float(pick.get("guncel", 0) or 0)
            _max_atr = getattr(config, "OTO_MAX_ATR_PCT", 0.04)
            if _atr_v > 0 and _cur_p > 0 and (_atr_v / _cur_p) > _max_atr:
                oto_log(
                    f"VOLATİLİTE FİLTRESİ: {p_code} "
                    f"ATR/fiyat=%{_atr_v/_cur_p*100:.1f} > %{_max_atr*100:.0f}", "info")
                continue

            # ── RSI momentum filtresi ─────────────────────────────────────
            _rsi_v   = float(pick.get("rsi", 50) or 50)
            _min_rsi = getattr(config, "OTO_MIN_MOMENTUM_RSI", 35)
            if _rsi_v < _min_rsi:
                oto_log(
                    f"MOMENTUM FİLTRESİ: {p_code} RSI={_rsi_v:.0f} < {_min_rsi}", "info")
                continue

            ai_dec = pick.get("autoThinkDecision", "NÖTR")
            ai_conf = int(pick.get("autoThinkConf", 50) or 50)
            if ai_dec not in ("GÜÇLÜ AL", "AL"):
                oto_log(f"AI REDDETTİ: {p_code} AI={ai_dec} Güven={ai_conf}%", "info"); continue
            if ai_conf < 45 and score < ai_min_score * 1.20:
                oto_log(f"AI DÜŞÜK GÜVEN: {p_code} Güven={ai_conf}%", "info"); continue

            # ── HACİM DİFERANSİYEL FİLTRE ────────────────────────────────
            # "AL" kararı daha yüksek hacim onayı gerektirir;
            # "GÜÇLÜ AL" kendi momentum'u ile daha gevşek hacim kabul edilir.
            _vol_r = float(pick.get("volRatio", 1) or 1)
            _min_vol = (getattr(config, "OTO_MIN_VOL_RATIO_GUCLU", 0.85)
                        if ai_dec == "GÜÇLÜ AL"
                        else getattr(config, "OTO_MIN_VOL_RATIO_AL", 1.05))
            if _vol_r < _min_vol:
                oto_log(f"HACİM REDDEDİLDİ [{ai_dec}]: {p_code} "
                        f"vol={_vol_r:.2f} < {_min_vol:.2f}", "info"); continue

            # ── CONVİCTİON SKOR KAPISI: score × (ai_conf/100) ≥ eşik ────
            # Yüksek skor + düşük güven = zayıf entry; düşük skor + yüksek
            # güven = da zayıf entry. İkisini birlikte değerlendirir.
            _conviction = score * (ai_conf / 100.0)
            _conv_min   = getattr(config, "OTO_CONVICTION_MIN", 62)
            if _conviction < _conv_min:
                oto_log(f"CONVİCTİON KAPISI: {p_code} "
                        f"skor={score}×%{ai_conf}={_conviction:.0f}<{_conv_min}", "info"); continue

            if oto_buy_position(pick):
                oto = oto_load()
                open_codes = list(oto["positions"].keys())
                added += 1
                cur = float(pick.get("guncel", 0) or 0)
                new_pos = oto["positions"].get(p_code, {})
                is_pending = new_pos.get("status") == "BEKLEYEN"
                lmt = float(new_pos.get("limit_entry", cur) or cur)
                lmt_src = new_pos.get("limit_src", "")
                discount = (cur - lmt) / cur * 100 if cur > 0 else 0
                if is_pending:
                    send_oto_tg(
                        f"🟠 *OTO — LİMİT EMİR OLUŞTURULDU*\n"
                        f"*{p_code}* için limit emir bekleniyor\n"
                        f"💰 Piyasa: {cur:.2f}₺ → Limit: {lmt:.2f}₺ (-%{discount:.1f}, {lmt_src})\n"
                        f"📊 Skor: *{int(score)}*  RR: *{pick.get('rr', 0)}*\n"
                        f"🤖 AI: *{ai_dec}* Güven %{ai_conf}\n"
                        f"🎯 H1: {pick.get('h1', 0):.2f}₺  Stop: {pick.get('stop', 0):.2f}₺{_tg_footer()}")
                else:
                    send_oto_tg(
                        f"🟢 *OTO — AÇILDI!*\n*{p_code}* @ {cur:.2f}₺\n"
                        f"📊 Skor: *{int(score)}*  RR: *{pick.get('rr', 0)}*\n"
                        f"🤖 AI: *{ai_dec}* Güven %{ai_conf}\n"
                        f"🎯 H1: {pick.get('h1', 0):.2f}₺  Stop: {pick.get('stop', 0):.2f}₺{_tg_footer()}")
                oto_log(f"AI ONAY ALINDI: {p_code} @ {cur:.2f}₺ Skor:{int(score)} SQ:{sq} AI:{ai_dec}(%{ai_conf})", "buy")
    elif block_new and slots > 0:
        oto_log(f"SEANS FİLTRESİ: yeni pozisyon yok (saat:{time_min})", "info")

    # ── ADIM 3: Sprint Rotasyon — zayıf pozisyonu daha iyi bir fırsatla değiştir ──
    oto = oto_load()
    if oto["positions"] and not block_new:
        worst_code = None
        worst_score = float("inf")
        worst_hiz = float("inf")

        for code, pos in oto["positions"].items():
            pos_score = int(pos.get("score", 0) or 0)
            pos_hiz = int(pos.get("hizScore", 0) or 0)
            pnl_pct = float(pos.get("pnl_pct", 0) or 0)
            if pos.get("h1_hit"):
                continue
            if pnl_pct >= config.OTO_ROTATION_PNL * 2:
                continue
            if pnl_pct < -(config.OTO_ROTATION_PNL * 4):
                continue
            if pos_score < worst_score:
                worst_score = pos_score
                worst_hiz = pos_hiz
                worst_code = code

        if worst_code is not None:
            open_codes3 = list(oto["positions"].keys())
            for pick in top_picks:
                p_code = pick.get("code", "")
                if not p_code or p_code in open_codes3:
                    continue
                new_score = int(pick.get("score", 0) or 0)
                new_hiz = int(pick.get("hizScore", 0) or 0)
                if new_score < ai_min_score:
                    break
                if float(pick.get("rr", 0) or 0) < config.OTO_MIN_RR:
                    continue
                if float(pick.get("h1", 0) or 0) <= float(pick.get("guncel", 0) or 0):
                    continue
                sq_rot = int(pick.get("signalQuality", 0) or 0)
                if sq_rot < 4:
                    continue
                rot_ai_dec = pick.get("autoThinkDecision", "NÖTR")
                rot_ai_conf = int(pick.get("autoThinkConf", 50) or 50)
                if rot_ai_dec not in ("GÜÇLÜ AL", "AL"):
                    oto_log(f"ROTASYON AI REDDETTİ: {p_code} AI={rot_ai_dec}", "info")
                    continue

                score_diff = new_score - worst_score
                hiz_diff = new_hiz - worst_hiz
                rot_base = config.OTO_ROTATION_SCORE
                if rot_ai_dec == "GÜÇLÜ AL": rot_base = int(rot_base * 0.70)
                if ai_market_bias == "bear_bias": rot_base = int(rot_base * 1.30)
                if ai_market_bias == "bull_bias": rot_base = int(rot_base * 0.85)

                should_rotate = (score_diff >= rot_base) or (
                    hiz_diff >= 4 and new_score >= ai_min_score and rot_ai_dec == "GÜÇLÜ AL"
                )

                if should_rotate:
                    cur_price = oto_fetch_live_price(worst_code)
                    if cur_price <= 0:
                        break
                    worst_pos = oto["positions"].get(worst_code, {})
                    pnl = oto_close_position(worst_code, cur_price, "rotasyon")
                    held_d = count_business_days(worst_pos.get("bought_at", now_str()))
                    oto_log(f"AI ROTASYON: {worst_code}(S:{worst_score}) → {p_code}(S:{new_score} AI:{rot_ai_dec} %{rot_ai_conf})  K/Z:{pnl:.2f}%  {held_d}gün", "rotate")
                    oto_buy_position(pick)
                    send_oto_tg(
                        f"⚡ *AI OTONOM ROTASYON*\n"
                        f"Çıkış: *{worst_code}* ({held_d} iş günü) K/Z:{('+' if pnl >= 0 else '')}{pnl:.2f}%\n"
                        f"Giriş: *{p_code}*  AI:{new_score}  Hz:{new_hiz}/15  SQ:{sq_rot}\n"
                        f"🤖 AI: *{rot_ai_dec}*  Güven: %{rot_ai_conf}\n"
                        f"Skor farkı: {('+' if score_diff >= 0 else '')}{score_diff}  Hız farkı: {('+' if hiz_diff >= 0 else '')}{hiz_diff}{_tg_footer()}"
                    )
                    break

    # ── ADIM 4: Periyodik OTO PORTFÖY ÖZET bildirimi devre dışı ─────────────
    # Kullanıcı isteği üzerine kaldırıldı (v37.x): tek pinli PREDATOR PANOSU
    # yeterli olduğundan ek özet mesajı artık gönderilmiyor. Pano canlı kalır,
    # bu blok grupta tekrar eden gürültü oluşturmasın diye no-op bırakıldı.
    return
