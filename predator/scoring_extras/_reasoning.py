"""AI sebep (reasoning) Türkçe metni."""

from __future__ import annotations


def get_ai_reasoning(stock: dict, consensus: dict) -> str:
    """PHP getAIReasoning birebir."""
    rsi = float(stock.get("rsi") or 50)
    macd = stock.get("macdCross") or "none"
    sar = stock.get("sarDir") or "notr"
    vol = float(stock.get("volRatio") or 1)
    pos52 = float(stock.get("pos52wk") or 50)
    cmf = float(stock.get("cmf") or 0)
    adx_v = float(stock.get("adxVal") or 0)
    forms = stock.get("formations") or []
    adil = float(stock.get("adil") or 0)
    guncel = float(stock.get("guncel") or 0)
    cap = float(stock.get("marketCap") or 0)
    agree_bull = consensus.get("agree_bull") or 0
    sim = consensus.get("sim_history") or {}
    reasons: list[str] = []
    if rsi < 20:    reasons.append(f"RSI aşırı satım bölgesinde ({round(rsi,1)}) — güçlü toparlanma potansiyeli")
    elif rsi < 30:  reasons.append(f"RSI satım bölgesinde ({round(rsi,1)}) — dip oluşumu sinyali")
    if macd == "golden": reasons.append("MACD altın kesişimi gerçekleşti — yükseliş trendi onaylandı")
    if sar == "yukselis": reasons.append("Parabolik SAR yükseliş yönüne döndü — fiyat üstünde destek var")
    if vol >= 2.5:  reasons.append(f"Olağanüstü hacim artışı ({round(vol,1)}x) — akıllı para girişi")
    elif vol >= 1.5: reasons.append(f"Ortalamanın üzerinde hacim ({round(vol,1)}x) — alıcı ilgisi var")
    if pos52 < 10:  reasons.append(f"52 haftalık dibin yakınında ({round(pos52,1)}%) — çift dip fırsatı")
    elif pos52 < 20: reasons.append(f"52 haftalık dibe yakın ({round(pos52,1)}%) — değer alımı bölgesi")
    if cmf > 0.15:  reasons.append(f"Para akışı endeksi pozitif (CMF: +{round(cmf,2)}) — kurumsal alım")
    if adx_v >= 25: reasons.append(f"ADX {round(adx_v,1)} — trend güçlü, yön yukarı")
    bull_form_names = []
    for f in forms:
        if (f.get("tip") or "") != "bearish":
            bull_form_names.append(f"{f.get('emoji','')} {f.get('ad','')}")
    if bull_form_names:
        reasons.append("Formasyon(lar): " + ", ".join(bull_form_names[:3]))
    if adil > 0 and guncel > 0 and adil > guncel * 1.2:
        pot = round((adil - guncel) / guncel * 100, 1)
        reasons.append(f"Graham adil değeri mevcut fiyatın %{pot} üzerinde — temel potansiyel güçlü")
    if agree_bull >= 6:
        reasons.append(f"7 bağımsız sistemden {agree_bull} tanesi AL oyu verdi — güçlü uyum")
    elif agree_bull >= 5:
        reasons.append(f"7 sistemden {agree_bull} tanesi AL tarafında — iyi konsensüs")
    if isinstance(sim, dict) and (sim.get("count") or 0) >= 3:
        reasons.append(f"Benzer geçmiş durumlarda {sim.get('win_rate')}% başarı oranı, ort. %{sim.get('avg_ret')} getiri ({sim.get('count')} örnek)")
    if cap and cap < 500:
        reasons.append(f"Mikro-cap ({round(cap)}M₺) — yüksek hareket potansiyeli")
    elif cap and cap < 2000:
        reasons.append(f"Küçük-cap ({round(cap)}M₺) — kurumsal hareket öncesi fırsat")
    if (consensus.get("conf_bonus") or 0) >= 10:
        reasons.append("Bu sinyal kombinasyonu geçmişte yüksek başarı gösterdi")
    if (consensus.get("time_bonus") or 0) >= 5:
        reasons.append("Haftanın bu günü tarihsel olarak olumlu")
    if not reasons:
        reasons.append("Teknik göstergeler alım bölgesine işaret ediyor · AI skor eşiğini aştı")
    return " · ".join(reasons[:5])
