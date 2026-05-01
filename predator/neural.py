"""Dörtlü sinir ağı (Alpha/Beta/Gamma + Delta meta-beyin) — numpy tabanlı.

Mimari:
  Alpha: 26→32→16→8→1,  LeakyReLU, Adam, λ=0.00008  (uzun vadeli)
  Beta : 26→16→8→4→1,   LeakyReLU, Adam, λ=0.0015   (kısa vadeli)
  Gamma: 26→20→10→5→1,  LeakyReLU, Adam, λ=0.0010   (orta vadeli)
  Delta: 32→24→12→6→1,  LeakyReLU, Adam, λ=0.0005   (meta-stacking)
         Girdi: 3 tahmin + 3 güven + 26 ham özellik = 32

Tüm ağırlıklar JSON-serializable list yapısında saklanır
(eski PHP cache dosyalarıyla aynı format).
"""
from __future__ import annotations
import math
import random
import time
import numpy as np
from typing import Any

ARCHITECTURES = {
    "alpha": {"layers": [29, 32, 16, 8, 1], "lambda": 0.00008,
              "label": "29→32(LReLU)→16(LReLU)→8(LReLU)→1(Sigmoid)|Adam|v41"},
    "beta":  {"layers": [29, 16, 8, 4, 1],  "lambda": 0.0015,
              "label": "29→16(LReLU)→8(LReLU)→4(LReLU)→1(Sigmoid)|Adam|v41"},
    "gamma": {"layers": [29, 20, 10, 5, 1], "lambda": 0.0010,
              "label": "29→20(LReLU)→10(LReLU)→5(LReLU)→1(Sigmoid)|Adam|v41"},
    "delta": {"layers": [35, 24, 12, 6, 1], "lambda": 0.0005,
              "label": "35→24(LReLU)→12(LReLU)→6(LReLU)→1(Sigmoid)|Adam|meta-v41"},
}

# v41: Feature vektörü boyutu (alpha/beta/gamma için 26 → 29)
FEATURE_DIM = 29
FEATURE_DIM_DELTA = 35  # 6 meta + 29 ham

LR = 0.001
LEAK = 0.01
ADAM_B1 = 0.9
ADAM_B2 = 0.999
ADAM_EPS = 1e-8
GRAD_CLIP = 5.0          # v37.3: gradient clipping (gradient patlamalarını engeller)
LR_DECAY_EVERY = 2000    # her N adımda lr *= LR_DECAY_GAMMA
LR_DECAY_GAMMA = 0.85
LR_MIN = 1e-5


def _xavier(fan_in: int, fan_out: int) -> list[list[float]]:
    """He/Xavier init."""
    s = math.sqrt(2.0 / fan_in)
    return [[random.gauss(0, s) for _ in range(fan_out)] for _ in range(fan_in)]


def init_weights(arch: str = "alpha") -> dict:
    layers = ARCHITECTURES[arch]["layers"]
    return {
        "W": [_xavier(layers[i], layers[i + 1]) for i in range(len(layers) - 1)],
        "b": [[0.0] * layers[i + 1] for i in range(len(layers) - 1)],
        "arch": arch,
    }


def init_adam(weights: dict) -> dict:
    return {
        "t": 0,
        "mW": [[[0.0] * len(row) for row in W] for W in weights["W"]],
        "vW": [[[0.0] * len(row) for row in W] for W in weights["W"]],
        "mb": [[0.0] * len(b) for b in weights["b"]],
        "vb": [[0.0] * len(b) for b in weights["b"]],
    }


# v38: Eksik özellik tanılaması — son 50 snapshot'ta hangi anahtarlar boş kaldı?
# Modül seviyesinde global, küçük ring buffer; predict/train_step her seferinde
# güncel kalır. neural_get_stats üzerinden UI'ya raporlanır.
_MISSING_FEATURE_COUNTS: dict[str, int] = {}
_MISSING_FEATURE_TOTAL: int = 0


def _track_missing(k: str) -> None:
    global _MISSING_FEATURE_TOTAL
    _MISSING_FEATURE_COUNTS[k] = _MISSING_FEATURE_COUNTS.get(k, 0) + 1
    _MISSING_FEATURE_TOTAL += 1
    # Pencereyi büyütme: tek anahtar 200'ü geçerse hepsini yarıya indir (üstel azaltma)
    if _MISSING_FEATURE_COUNTS[k] > 200:
        for kk in list(_MISSING_FEATURE_COUNTS.keys()):
            _MISSING_FEATURE_COUNTS[kk] = _MISSING_FEATURE_COUNTS[kk] // 2
        _MISSING_FEATURE_TOTAL = sum(_MISSING_FEATURE_COUNTS.values())


def get_missing_feature_report() -> dict:
    """En sık eksik kalan 5 özellik + toplam eksik sayısı (UI/log için)."""
    top = sorted(_MISSING_FEATURE_COUNTS.items(), key=lambda x: x[1], reverse=True)[:5]
    return {"total_missing": _MISSING_FEATURE_TOTAL,
            "top_missing": [{"feature": k, "count": v} for k, v in top]}


def features(snap: dict) -> list[float]:
    """29 özelliklik öznitelik vektörü — v41: stochK, stochD, elderBull eklendi.

    v37.2: tanh-tabanlı yumuşak ölçek (tanh(x/k) → ekstrem değerlerde satürasyon).
    v38: Eksik özellik sayacı → `get_missing_feature_report()` ile tanılama.
    v41: 3 yeni özellik → 26'dan 29'a genişleme. Eski 26-özellikli ağırlıklar
         brain_load() tarafından otomatik sıfırlanır (boy uyumsuzluğu durumunda).

    Özellik sırası (26 eski + 3 yeni):
      0:rsi  1:pos52wk  2:volRatio  3:macdCross  4:sarDir  5:ichiSig
      6:divRsi  7:bbSqueeze  8:cmf  9:mfi  10:adxVal  11:smcBias
      12:ofiSig  13:supertrendDir  14:hullDir  15:emaCrossDir  16:trixCross
      17:cmo  18:awesomeOscSig  19:keltnerPos  20:ultimateOsc  21:cci
      22:vwapPos  23:aroonOsc  24:williamsR  25:marketMode
      26:stochK [YENİ]  27:stochD [YENİ]  28:elderBull [YENİ]
    """
    def f(k, default=0.0):
        if k not in snap:
            _track_missing(k)
            return float(default)
        v = snap[k]
        if v is None or (isinstance(v, str) and not v.strip()):
            _track_missing(k)
            return float(default)
        try:
            return float(v)
        except (TypeError, ValueError):
            _track_missing(k)
            return float(default)
    th = math.tanh
    macd = snap.get("macdCross", "none")
    sar = snap.get("sarDir", "notr")
    ichi = snap.get("ichiSig", "notr")
    div = snap.get("divRsi", "yok")
    smc = snap.get("smcBias", "notr")
    ofi = snap.get("ofiSig", "notr")
    st = snap.get("supertrendDir", "notr")
    hull = snap.get("hullDir", "notr")
    emac = snap.get("emaCrossDir", "none")
    trix = snap.get("trixCross", "none")
    ao = snap.get("awesomeOscSig", "notr")
    kel = snap.get("keltnerPos", "notr")
    vwap = snap.get("vwapPos", "icinde")
    mode = snap.get("marketMode", "bull")

    return [
        (f("rsi", 50) - 50.0) / 30.0,                    # 0  RSI ~[-1.7, +1.7]
        (f("pos52wk", 50) - 50.0) / 35.0,                # 1  52H'ya merkezli
        th(f("volRatio", 1) / 2.5),                       # 2  smooth saturation
        1.0 if macd == "golden" else (-1.0 if macd == "death" else 0.0),  # 3
        1.0 if sar == "yukselis" else (-1.0 if sar == "dusus" else 0.0),  # 4
        1.0 if ichi == "ustunde" else (-1.0 if ichi == "altinda" else 0.0),  # 5
        1.0 if div == "boga" else (-1.0 if div == "ayi" else 0.0),         # 6
        1.0 if snap.get("bbSqueeze") else 0.0,            # 7
        th(f("cmf", 0) * 3.0),                            # 8  CMF keskinleştir
        (f("mfi", 50) - 50.0) / 30.0,                    # 9  MFI merkezli
        th(f("adxVal", 0) / 30.0),                        # 10 ADX
        1.0 if smc == "bullish" else (-1.0 if smc == "bearish" else 0.0),  # 11
        1.0 if ofi == "guclu_alis" else (0.5 if ofi == "alis" else         # 12
            (-1.0 if ofi == "guclu_satis" else (-0.5 if ofi == "satis" else 0.0))),
        1.0 if st == "yukselis" else (-1.0 if st == "dusus" else 0.0),    # 13
        1.0 if hull == "yukselis" else (-1.0 if hull == "dusus" else 0.0), # 14
        1.0 if emac == "golden" else (-1.0 if emac == "death" else 0.0),   # 15
        1.0 if trix == "bullish" else (-1.0 if trix == "bearish" else 0.0),# 16
        th(f("cmo", 0) / 40.0),                           # 17 CMO ±100
        1.0 if ao == "yukselis" else (-1.0 if ao == "dusus" else 0.0),    # 18
        1.0 if kel == "ust_bant" else (-1.0 if kel == "alt_bant" else 0.0),# 19
        (f("ultimateOsc", 50) - 50.0) / 25.0,            # 20 UO merkezli
        th(f("cci", 0) / 120.0),                          # 21 ±200 smooth
        1.0 if vwap == "ust2" else (0.5 if vwap == "ust1" else             # 22
            (-1.0 if vwap == "alt2" else (-0.5 if vwap == "alt1" else 0.0))),
        th(f("aroonOsc", 0) / 60.0),                      # 23 ±100 smooth
        (f("williamsR", -50) + 50.0) / 30.0,              # 24 -100..0 merkezli
        1.0 if mode == "bull" else (-1.0 if mode == "ayi" else 0.0),       # 25
        # ── v41: 3 yeni özellik ─────────────────────────────────────────────
        (f("stochK", 50) - 50.0) / 30.0,                 # 26 StochRSI %K
        (f("stochD", 50) - 50.0) / 30.0,                 # 27 StochRSI %D
        th(f("elderBull", 0) / 0.03),                     # 28 Elder Ray (fiyat-normalize)
    ]


def _to_np(weights: dict) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Hem yeni Python şeması (W:[...], b:[...]) hem de PHP şeması (w1,b1,w2,b2,...) destekli.

    v41: Eski 26-özellikli ağırlıkları tespit eder → ValueError fırlatır → çağıran
    (brain_load) bunu yakalar ve ağı sıfırlar. Silinme yerine migration yapılır.
    """
    if "W" in weights and "b" in weights:
        Ws = [np.array(W, dtype=float) for W in weights["W"]]
        bs = [np.array(b, dtype=float) for b in weights["b"]]
    else:
        # PHP şeması: w1, b1, w2, b2, ...
        Ws, bs = [], []
        i = 1
        while f"w{i}" in weights:
            Ws.append(np.array(weights[f"w{i}"], dtype=float))
            bs.append(np.array(weights[f"b{i}"], dtype=float))
            i += 1
        if not Ws:
            raise KeyError("weights neither has 'W' nor 'w1'")
        # PHP'de w1 boyutu (out, in) olabilir; bizim forward (in, out) bekliyor.
        if Ws[0].shape[0] not in (FEATURE_DIM, FEATURE_DIM - 1, 26) and \
           Ws[0].shape[1] in (FEATURE_DIM, 26):
            Ws = [W.T for W in Ws]

    # v41: Eski 26-özellik mimarisi → ValueError → brain_load yeniden başlatır.
    if Ws and Ws[0].shape[0] == 26:
        raise ValueError("feature_dim_mismatch:26→29")
    return Ws, bs


def _from_np(Ws, bs, php_style: bool = True) -> dict:
    """PHP uyumluluğu için varsayılan olarak w1,b1,w2,... şeması."""
    if not php_style:
        return {"W": [W.tolist() for W in Ws], "b": [b.tolist() for b in bs]}
    out = {}
    for i, (W, b) in enumerate(zip(Ws, bs), start=1):
        out[f"w{i}"] = W.tolist()
        out[f"b{i}"] = b.tolist()
    return out


def forward(weights: dict, x: list[float]) -> tuple[float, list[np.ndarray]]:
    Ws, bs = _to_np(weights)
    a = np.array(x, dtype=float)
    activations = [a]
    L = len(Ws)
    for i, (W, b) in enumerate(zip(Ws, bs)):
        z = a @ W + b
        if i == L - 1:
            a = 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))   # sigmoid
        else:
            a = np.where(z > 0, z, LEAK * z)                  # leaky relu
        activations.append(a)
    return float(activations[-1][0]), activations


def predict(net: dict, snap: dict) -> float:
    """0..1 arası ham tahmin — yüksek = boğa beklentisi.

    v38: Hata ayrıntısını net['last_predict_error']'a yazar; çağıran 0.5 yerine
    bilinçli karar verebilir. Eskiden sessiz 0.5 hata gizliyordu.
    """
    if not net or "weights" not in net:
        return 0.5
    try:
        x = features(snap)
        y, _ = forward(net["weights"], x)
        # NaN/Inf koruması
        if not math.isfinite(y):
            net["last_predict_error"] = "non_finite_output"
            return 0.5
        return y
    except Exception as e:
        net["last_predict_error"] = f"{type(e).__name__}: {e}"
        return 0.5


def predict_calibrated(net: dict, snap: dict) -> tuple[float, float]:
    """Kalibre edilmiş tahmin (prob, confidence).

    v38: Ham sigmoid çıktısı genellikle ekstremlere yapışır (under-/overconfident).
    Burada 'temperature scaling' uygulanır — ağın güveni veriden öğrenilir:
      • avg_loss yüksek (>0.20) → tahminler az güvenilir → temperature artır (yumuşat)
      • recent_accuracy düşük (<55) → temperature artır
      • Yeterli eğitim örneği yok (<30) → güven düşür
    confidence ∈ [0,1]: ensemble bonus çarpanlarında kullanmaya uygun.
    """
    if not net or "weights" not in net:
        return (0.5, 0.0)
    p = predict(net, snap)
    trained = int(net.get("trained_samples", 0) or 0)
    avg_loss = float(net.get("avg_loss", 1.0) or 1.0)
    rec_acc = float(net.get("recent_accuracy", 50.0) or 50.0)

    # Sıcaklık (T): 1.0 = nötr; T>1 olasılıkları 0.5'e doğru çeker.
    # Loss & doğruluk kötüleştikçe T büyür.
    T = 1.0
    if avg_loss > 0.10: T += min(2.0, (avg_loss - 0.10) * 8.0)
    if rec_acc < 55.0:  T += min(1.5, (55.0 - rec_acc) / 25.0)
    if trained < 30:    T += min(1.0, (30 - trained) / 30.0)
    T = max(1.0, min(4.5, T))

    # Logit'e dönüştür, T ile böl, geri sigmoid.
    p_clip = min(0.9999, max(0.0001, p))
    logit = math.log(p_clip / (1 - p_clip))
    p_cal = 1.0 / (1.0 + math.exp(-logit / T))

    # Confidence: yeterli veri + iyi doğruluk + düşük loss
    dat = min(1.0, trained / 50.0)
    acc = min(1.0, max(0.0, (rec_acc - 40.0) / 60.0))
    los = max(0.0, 1.0 - min(1.0, avg_loss))
    conf = round(0.45 * dat + 0.35 * acc + 0.20 * los, 3)
    return (p_cal, conf)


def _adaptive_lr(net: dict, base_lr: float) -> float:
    """v37.3 + v38: Adam adım sayısı + ReduceLROnPlateau hibridi.

    - Her N adımda üstel decay (mevcut davranış korundu)
    - Loss EMA son 200 adımda düşmediyse ek 0.5x indirim (plateau)
    """
    t = int((net.get("optimizer") or {}).get("t", 0))
    decays = t // LR_DECAY_EVERY
    lr = base_lr * (LR_DECAY_GAMMA ** decays)
    # Plato kontrolü: net['plateau_factor'] 0..1 arası, eğitim sırasında güncellenir
    pf = float(net.get("plateau_factor", 1.0) or 1.0)
    lr *= max(0.1, min(1.0, pf))
    return max(LR_MIN, lr)


def _clip_grad(g: "np.ndarray", max_norm: float = GRAD_CLIP) -> "np.ndarray":
    """Global L2-norm gradient clipping."""
    n = float(np.linalg.norm(g))
    if n > max_norm and n > 0:
        return g * (max_norm / n)
    return g


def train_step(net: dict, snap: dict, target: float,
               lr: float = LR, sample_weight: float = 1.0) -> float:
    """Tek bir SGD+Adam adımı. PHP neuralTrainOnOutcome karşılığı.

    v37.3 iyileştirmeleri:
      • sample_weight: zor/azınlık örneklere daha güçlü gradyan (focal-benzeri)
      • Gradient clipping (||g|| <= GRAD_CLIP) → patlamayı engeller
      • Adaptif LR (Adam adım sayısına göre üstel decay)
      • Loss EMA + adam_steps güvenli artırım

    Returns: bu örnekteki MSE loss.
    """
    lr = _adaptive_lr(net, lr)
    if "weights" not in net:
        arch = net.get("arch_name", "alpha")
        net["weights"] = init_weights(arch)
        net["optimizer"] = init_adam(net["weights"])

    arch_name = net["weights"].get("arch", "alpha")
    lam = ARCHITECTURES[arch_name]["lambda"]

    Ws, bs = _to_np(net["weights"])
    L = len(Ws)
    x = np.array(features(snap), dtype=float)

    # Forward
    activations = [x]
    zs = []
    a = x
    for i, (W, b) in enumerate(zip(Ws, bs)):
        z = a @ W + b
        zs.append(z)
        if i == L - 1:
            a = 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))
        else:
            a = np.where(z > 0, z, LEAK * z)
        activations.append(a)

    y = activations[-1][0]
    target = max(0.0, min(1.0, float(target)))
    sw = max(0.1, min(5.0, float(sample_weight)))
    loss = (y - target) ** 2

    # Backward — sample_weight ile çarpılmış delta (focal benzeri)
    grads_W = [None] * L
    grads_b = [None] * L
    delta = (a - target) * (a * (1 - a)) * sw  # sigmoid' * MSE' * w
    for i in range(L - 1, -1, -1):
        a_prev = activations[i]
        gW = np.outer(a_prev, delta) + lam * Ws[i]
        gb = delta.copy()
        # v37.3: Gradient clipping (katman bazlı)
        grads_W[i] = _clip_grad(gW)
        grads_b[i] = _clip_grad(gb)
        if i > 0:
            z_prev = zs[i - 1]
            d_act = np.where(z_prev > 0, 1.0, LEAK)
            delta = (delta @ Ws[i].T) * d_act

    # Adam — ağırlıklar W/b formatındaysa optimizer sıfırla
    opt = net.get("optimizer") or {}
    if "mW" not in opt:
        # Ağırlıkları önce W/b formatına normalize et
        if "W" not in net.get("weights", {}):
            try:
                _Ws, _bs = _to_np(net.get("weights", {}))
                _arch = net.get("weights", {}).get("arch", net.get("arch_name", "alpha"))
                net["weights"] = {"W": [_W.tolist() for _W in _Ws],
                                  "b": [_b.tolist() for _b in _bs], "arch": _arch}
                Ws, bs = [np.array(w, dtype=float) for w in net["weights"]["W"]], \
                         [np.array(b, dtype=float) for b in net["weights"]["b"]]
            except Exception:
                _arch = net.get("arch_name", "alpha")
                net["weights"] = init_weights(_arch)
                Ws = [np.array(w, dtype=float) for w in net["weights"]["W"]]
                bs = [np.array(b, dtype=float) for b in net["weights"]["b"]]
        opt = init_adam(net["weights"])
    opt["t"] = int(opt.get("t", 0)) + 1
    t = opt["t"]
    bc1 = 1 - ADAM_B1 ** t
    bc2 = 1 - ADAM_B2 ** t

    mWs = [np.array(m, dtype=float) for m in opt["mW"]]
    vWs = [np.array(v, dtype=float) for v in opt["vW"]]
    mbs = [np.array(m, dtype=float) for m in opt["mb"]]
    vbs = [np.array(v, dtype=float) for v in opt["vb"]]

    for i in range(L):
        mWs[i] = ADAM_B1 * mWs[i] + (1 - ADAM_B1) * grads_W[i]
        vWs[i] = ADAM_B2 * vWs[i] + (1 - ADAM_B2) * (grads_W[i] ** 2)
        mh = mWs[i] / bc1
        vh = vWs[i] / bc2
        Ws[i] = Ws[i] - lr * mh / (np.sqrt(vh) + ADAM_EPS)

        mbs[i] = ADAM_B1 * mbs[i] + (1 - ADAM_B1) * grads_b[i]
        vbs[i] = ADAM_B2 * vbs[i] + (1 - ADAM_B2) * (grads_b[i] ** 2)
        mhb = mbs[i] / bc1
        vhb = vbs[i] / bc2
        bs[i] = bs[i] - lr * mhb / (np.sqrt(vhb) + ADAM_EPS)

    net["weights"] = {"W": [W.tolist() for W in Ws],
                      "b": [b.tolist() for b in bs],
                      "arch": arch_name}
    net["optimizer"] = {
        "t": t,
        "mW": [m.tolist() for m in mWs], "vW": [v.tolist() for v in vWs],
        "mb": [m.tolist() for m in mbs], "vb": [v.tolist() for v in vbs],
    }
    net["trained_samples"] = int(net.get("trained_samples", 0)) + 1
    new_avg = 0.95 * float(net.get("avg_loss", 1.0)) + 0.05 * loss
    net["avg_loss"] = round(new_avg, 6)
    net["last_trained"] = time.strftime("%Y-%m-%d %H:%M:%S")

    # v38: ReduceLROnPlateau — son 200 adımdaki en iyi loss takip edilir.
    # Plato (200 adımdır iyileşme yok) → plateau_factor 0.5x'e düşer.
    # Her 600 adımda factor sıfırlanır → ağ kurtulma şansına sahip.
    best = float(net.get("best_loss", 1.0) or 1.0)
    bs = int(net.get("best_loss_step", 0) or 0)
    if new_avg < best - 1e-5:
        net["best_loss"] = round(new_avg, 6)
        net["best_loss_step"] = t
        # İyileşme var → plateau_factor'ı tedrici geri yükselt
        cur = float(net.get("plateau_factor", 1.0) or 1.0)
        net["plateau_factor"] = round(min(1.0, cur + 0.05), 3)
    elif (t - bs) >= 200:
        cur = float(net.get("plateau_factor", 1.0) or 1.0)
        net["plateau_factor"] = round(max(0.1, cur * 0.5), 3)
        net["best_loss_step"] = t  # cooldown başlasın
    if (t % 600) == 0 and t > 0:
        net["plateau_factor"] = 1.0
        net["best_loss"] = round(new_avg, 6)
        net["best_loss_step"] = t
    return float(loss)


def train_on_outcome(net: dict, snap: dict, ret: float,
                     lr_mult: float = 1.0) -> float:
    """Sonuç getirisinden hedef üret ve eğit.

    v37.2: tanh tabanlı risk-ayarlı hedef. ret/15 üzerinden satüre olur.
    v37.3 iyileştirmeleri:
      • Sınıf dengesi: kazanan/kaybeden oranına göre sample_weight (azınlığı yukseltir)
      • Zor örnek bonus: tahmin yanlışsa weight 1.5x (focal-benzeri)
      • Yüksek mutlak getiri (|ret|>10) güçlü sinyal → +25% weight
    v38.1: `lr_mult` — Triple Brain düellosunda kayıp ağa cezalı eğitim için
      learning rate çarpanı (örn. 2.2). Varsayılan 1.0 → davranış değişmez.
    """
    target = 0.5 + 0.45 * math.tanh(ret / 15.0)
    target = max(0.05, min(0.95, target))
    win = ret > 0
    if win:
        net["wins"] = int(net.get("wins", 0)) + 1
    else:
        net["losses"] = int(net.get("losses", 0)) + 1

    # Sınıf dengesi ağırlığı: azınlık sınıfına daha fazla ağırlık
    wins = int(net.get("wins", 0))
    losses = int(net.get("losses", 0))
    total = wins + losses
    sample_w = 1.0
    if total >= 20:
        if win and wins > 0:
            sample_w = max(0.5, min(2.0, (total / 2.0) / wins))
        elif (not win) and losses > 0:
            sample_w = max(0.5, min(2.0, (total / 2.0) / losses))

    # Eğitimden ÖNCE mevcut tahmin doğruluğunu izle — recent_accuracy EMA
    was_correct = True
    if "weights" in net:
        try:
            x = features(snap)
            prob, _ = forward(net["weights"], x)
            predicted_bull = prob >= 0.5
            was_correct = (predicted_bull == win)
            alpha = 0.10
            old_acc = float(net.get("recent_accuracy", 50.0) or 50.0)
            new_acc = old_acc * (1 - alpha) + (100.0 if was_correct else 0.0) * alpha
            net["recent_accuracy"] = round(new_acc, 2)
        except Exception:
            pass

    # Hard sample bonus + güçlü sinyal bonus
    if not was_correct:
        sample_w *= 1.5
    if abs(ret) >= 10.0:
        sample_w *= 1.25
    sample_w = max(0.3, min(3.0, sample_w))

    # v38.1: Düello cezası lr_mult ile uygulanır
    eff_lr = LR * max(0.1, min(5.0, float(lr_mult)))
    return train_step(net, snap, target, lr=eff_lr, sample_weight=sample_w)


def neural_get_stats(net: dict | None) -> dict:
    if not net:
        return {"ready": False, "trained": 0}
    trained = int(net.get("trained_samples", 0))
    wins = int(net.get("wins", 0))
    losses = int(net.get("losses", 0))
    return {
        # v38: 'ready' eşiği 5'ten 20'ye çıktı — 5 örnekle skor bonusu vermek
        # ağa güven oluşturmadan kullanıcıya yanlış sinyal verirdi.
        "ready": trained >= 20,
        "trained": trained,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / max(1, wins + losses) * 100, 1),
        "avg_loss": float(net.get("avg_loss", 1.0)),
        "accuracy": float(net.get("recent_accuracy", 0.0)),
        "arch": net.get("arch", ARCHITECTURES["alpha"]["label"]),
        "optimizer": "Adam",
        "adam_steps": int((net.get("optimizer") or {}).get("t", 0)),
        "last_trained": net.get("last_trained", ""),
        "bootstrap": bool(net.get("bootstrap", False)),
        # v38: tanılama alanları
        "best_loss": float(net.get("best_loss", 1.0)),
        "plateau_factor": float(net.get("plateau_factor", 1.0)),
        "last_predict_error": net.get("last_predict_error", ""),
        "missing_features": get_missing_feature_report(),
    }


def make_net(arch: str = "alpha") -> dict:
    w = init_weights(arch)
    o = init_adam(w)
    return {
        "weights": w, "optimizer": o,
        "arch_name": arch,
        "arch": ARCHITECTURES[arch]["label"],
        "trained_samples": 0, "wins": 0, "losses": 0,
        "avg_loss": 1.0, "recent_accuracy": 0.0,
        "loss_history": [], "accuracy_history": [],
        "last_trained": "", "bootstrap": False,
    }


# ── Delta Meta-Beyin ──────────────────────────────────────────────────────────

def features_delta(snap: dict,
                   p_alpha: float, conf_alpha: float,
                   p_beta: float, conf_beta: float,
                   p_gamma: float, conf_gamma: float) -> list[float]:
    """Delta meta-beyin için 35 boyutlu girdi vektörü (v41: 32→35).

    İlk 6 eleman: Alpha/Beta/Gamma tahminleri + güven skorları (meta-bilgi).
    Son 29 eleman: Ham teknik özellikler (features() ile aynı — v41 genişlemesi dahil).
    Delta, bu bilgiyi birleştirerek A/B/G'nin optimal ağırlığını öğrenir.
    """
    raw = features(snap)
    meta = [
        p_alpha * 2.0 - 1.0,    # [0,1] → [-1,+1]
        p_beta  * 2.0 - 1.0,
        p_gamma * 2.0 - 1.0,
        conf_alpha * 2.0 - 1.0,
        conf_beta  * 2.0 - 1.0,
        conf_gamma * 2.0 - 1.0,
    ]
    return meta + raw


def predict_delta(delta_net: dict, snap: dict,
                  p_alpha: float, conf_alpha: float,
                  p_beta: float, conf_beta: float,
                  p_gamma: float, conf_gamma: float) -> tuple[float, float]:
    """Delta meta-tahmin: (prob 0..1, calibrated_conf 0..1).

    Delta en az 20 örnek gördüyse devreye girer.
    Yeterli eğitim yoksa (0.5, 0.0) döner — ensemble bunu yok sayar.
    """
    if not delta_net or "weights" not in delta_net:
        return (0.5, 0.0)
    trained = int(delta_net.get("trained_samples", 0) or 0)
    if trained < 20:
        return (0.5, 0.0)
    try:
        x = features_delta(snap, p_alpha, conf_alpha, p_beta, conf_beta, p_gamma, conf_gamma)
        y, _ = forward(delta_net["weights"], x)
        if not math.isfinite(y):
            return (0.5, 0.0)
        avg_loss = float(delta_net.get("avg_loss", 1.0) or 1.0)
        rec_acc  = float(delta_net.get("recent_accuracy", 50.0) or 50.0)
        T = 1.0
        if avg_loss > 0.10: T += min(2.0, (avg_loss - 0.10) * 8.0)
        if rec_acc  < 55.0: T += min(1.5, (55.0 - rec_acc) / 25.0)
        T = max(1.0, min(4.5, T))
        p_clip = min(0.9999, max(0.0001, y))
        logit  = math.log(p_clip / (1 - p_clip))
        p_cal  = 1.0 / (1.0 + math.exp(-logit / T))
        dat  = min(1.0, trained / 50.0)
        acc  = min(1.0, max(0.0, (rec_acc - 40.0) / 60.0))
        los  = max(0.0, 1.0 - min(1.0, avg_loss))
        conf = round(0.45 * dat + 0.35 * acc + 0.20 * los, 3)
        return (p_cal, conf)
    except Exception:
        return (0.5, 0.0)


def train_delta_on_outcome(delta_net: dict, snap: dict,
                           p_alpha: float, conf_alpha: float,
                           p_beta: float, conf_beta: float,
                           p_gamma: float, conf_gamma: float,
                           ret: float) -> float:
    """Delta meta-beynini bir gerçek sonuçla eğit.

    Girdi: o anki A/B/G tahminleri + snap özellikleri.
    Hedef: tanh tabanlı risk-ayarlı (train_on_outcome ile aynı yöntem).
    """
    target = 0.5 + 0.45 * math.tanh(ret / 15.0)
    target = max(0.05, min(0.95, target))
    win = ret > 0
    if win:
        delta_net["wins"]   = int(delta_net.get("wins", 0)) + 1
    else:
        delta_net["losses"] = int(delta_net.get("losses", 0)) + 1

    wins   = int(delta_net.get("wins", 0))
    losses = int(delta_net.get("losses", 0))
    total  = wins + losses
    sample_w = 1.0
    if total >= 20:
        if win and wins > 0:
            sample_w = max(0.5, min(2.0, (total / 2.0) / wins))
        elif (not win) and losses > 0:
            sample_w = max(0.5, min(2.0, (total / 2.0) / losses))

    was_correct = True
    if "weights" in delta_net:
        try:
            x = features_delta(snap, p_alpha, conf_alpha,
                               p_beta, conf_beta, p_gamma, conf_gamma)
            prob, _ = forward(delta_net["weights"], x)
            was_correct = (prob >= 0.5) == win
            old_acc = float(delta_net.get("recent_accuracy", 50.0) or 50.0)
            new_acc = old_acc * 0.90 + (100.0 if was_correct else 0.0) * 0.10
            delta_net["recent_accuracy"] = round(new_acc, 2)
        except Exception:
            pass

    if not was_correct:
        sample_w *= 1.5
    if abs(ret) >= 10.0:
        sample_w *= 1.25
    sample_w = max(0.3, min(3.0, sample_w))

    lr = _adaptive_lr(delta_net, LR)
    if "weights" not in delta_net:
        delta_net["weights"]   = init_weights("delta")
        delta_net["optimizer"] = init_adam(delta_net["weights"])

    lam = ARCHITECTURES["delta"]["lambda"]
    Ws, bs = _to_np(delta_net["weights"])
    L = len(Ws)
    x_np = np.array(features_delta(snap, p_alpha, conf_alpha,
                                   p_beta, conf_beta, p_gamma, conf_gamma), dtype=float)
    activations = [x_np]
    zs = []
    a = x_np
    for i, (W, b) in enumerate(zip(Ws, bs)):
        z = a @ W + b
        zs.append(z)
        a = 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50))) if i == L - 1 \
            else np.where(z > 0, z, LEAK * z)
        activations.append(a)

    y = activations[-1][0]
    loss = (y - target) ** 2
    grads_W = [None] * L
    grads_b = [None] * L
    delta_arr = (a - target) * (a * (1 - a)) * sample_w
    for i in range(L - 1, -1, -1):
        a_prev = activations[i]
        gW = np.outer(a_prev, delta_arr) + lam * Ws[i]
        gb = delta_arr.copy()
        grads_W[i] = _clip_grad(gW)
        grads_b[i] = _clip_grad(gb)
        if i > 0:
            z_prev = zs[i - 1]
            d_act  = np.where(z_prev > 0, 1.0, LEAK)
            delta_arr = (delta_arr @ Ws[i].T) * d_act

    opt = delta_net.get("optimizer") or {}
    if "mW" not in opt:
        delta_net["weights"]   = {"W": [W.tolist() for W in Ws],
                                  "b": [b.tolist() for b in bs], "arch": "delta"}
        Ws = [np.array(w, dtype=float) for w in delta_net["weights"]["W"]]
        bs = [np.array(b, dtype=float) for b in delta_net["weights"]["b"]]
        opt = init_adam(delta_net["weights"])

    opt["t"] = int(opt.get("t", 0)) + 1
    t  = opt["t"]
    bc1 = 1 - ADAM_B1 ** t
    bc2 = 1 - ADAM_B2 ** t
    mWs = [np.array(m, dtype=float) for m in opt["mW"]]
    vWs = [np.array(v, dtype=float) for v in opt["vW"]]
    mbs = [np.array(m, dtype=float) for m in opt["mb"]]
    vbs = [np.array(v, dtype=float) for v in opt["vb"]]

    for i in range(L):
        mWs[i] = ADAM_B1 * mWs[i] + (1 - ADAM_B1) * grads_W[i]
        vWs[i] = ADAM_B2 * vWs[i] + (1 - ADAM_B2) * (grads_W[i] ** 2)
        mh = mWs[i] / bc1;  vh = vWs[i] / bc2
        Ws[i] -= lr * mh / (np.sqrt(vh) + ADAM_EPS)
        mbs[i] = ADAM_B1 * mbs[i] + (1 - ADAM_B1) * grads_b[i]
        vbs[i] = ADAM_B2 * vbs[i] + (1 - ADAM_B2) * (grads_b[i] ** 2)
        mhb = mbs[i] / bc1; vhb = vbs[i] / bc2
        bs[i] -= lr * mhb / (np.sqrt(vhb) + ADAM_EPS)

    delta_net["weights"]   = {"W": [W.tolist() for W in Ws],
                              "b": [b.tolist() for b in bs], "arch": "delta"}
    delta_net["optimizer"] = {
        "t": t,
        "mW": [m.tolist() for m in mWs], "vW": [v.tolist() for v in vWs],
        "mb": [m.tolist() for m in mbs], "vb": [v.tolist() for v in vbs],
    }
    delta_net["trained_samples"] = int(delta_net.get("trained_samples", 0)) + 1
    new_avg = 0.95 * float(delta_net.get("avg_loss", 1.0)) + 0.05 * loss
    delta_net["avg_loss"]    = round(new_avg, 6)
    delta_net["last_trained"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return float(loss)
