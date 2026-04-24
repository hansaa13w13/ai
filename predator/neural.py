"""Üçlü sinir ağı (Alpha/Beta/Gamma) — numpy tabanlı.

Mimari:
  Alpha: 26→32→16→8→1, LeakyReLU, Adam, λ=0.00008
  Beta : 26→16→8→4→1,  LeakyReLU, Adam, λ=0.0015
  Gamma: 26→20→10→5→1, LeakyReLU, Adam, λ=0.0010

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
    "alpha": {"layers": [26, 32, 16, 8, 1], "lambda": 0.00008,
              "label": "26→32(LReLU)→16(LReLU)→8(LReLU)→1(Sigmoid)|Adam|v35"},
    "beta":  {"layers": [26, 16, 8, 4, 1],  "lambda": 0.0015,
              "label": "26→16(LReLU)→8(LReLU)→4(LReLU)→1(Sigmoid)|Adam|v35"},
    "gamma": {"layers": [26, 20, 10, 5, 1], "lambda": 0.0010,
              "label": "26→20(LReLU)→10(LReLU)→5(LReLU)→1(Sigmoid)|Adam|v35"},
}

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


def features(snap: dict) -> list[float]:
    """26 özelliklik öznitelik vektörü — v37.2: tanh-tabanlı yumuşak ölçek.

    Eski: volRatio/5 → ekstrem hacimde 1.0'a yapışıyordu, ADX 100'e bölme zayıftı.
    Yeni: tanh(x/k) → ekstrem değerlerde yumuşak satürasyon, NN gradyanı kaybolmaz.
    Vector boyutu (26) ve sıra korunuyor → eski brain ağırlıkları geçerli kalır.
    """
    def f(k, default=0.0):
        v = snap.get(k, default)
        try:
            return float(v) if v is not None else float(default)
        except (TypeError, ValueError):
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
        (f("rsi", 50) - 50.0) / 30.0,                    # ~[-1.7, +1.7]
        (f("pos52wk", 50) - 50.0) / 35.0,                # 52H'ya merkezli
        th(f("volRatio", 1) / 2.5),                       # smooth saturation
        1.0 if macd == "golden" else (-1.0 if macd == "death" else 0.0),
        1.0 if sar == "yukselis" else (-1.0 if sar == "dusus" else 0.0),
        1.0 if ichi == "ustunde" else (-1.0 if ichi == "altinda" else 0.0),
        1.0 if div == "boga" else (-1.0 if div == "ayi" else 0.0),
        1.0 if snap.get("bbSqueeze") else 0.0,
        th(f("cmf", 0) * 3.0),                            # CMF -1..+1 → keskinleştir
        (f("mfi", 50) - 50.0) / 30.0,                     # MFI merkezli
        th(f("adxVal", 0) / 30.0),                        # 30+ trend → ~0.76+
        1.0 if smc == "bullish" else (-1.0 if smc == "bearish" else 0.0),
        1.0 if ofi == "guclu_alis" else (0.5 if ofi == "alis" else (-1.0 if ofi == "guclu_satis" else (-0.5 if ofi == "satis" else 0.0))),
        1.0 if st == "yukselis" else (-1.0 if st == "dusus" else 0.0),
        1.0 if hull == "yukselis" else (-1.0 if hull == "dusus" else 0.0),
        1.0 if emac == "golden" else (-1.0 if emac == "death" else 0.0),
        1.0 if trix == "bullish" else (-1.0 if trix == "bearish" else 0.0),
        th(f("cmo", 0) / 40.0),                           # CMO ±100 sınırlı
        1.0 if ao == "yukselis" else (-1.0 if ao == "dusus" else 0.0),
        1.0 if kel == "ust_bant" else (-1.0 if kel == "alt_bant" else 0.0),
        (f("ultimateOsc", 50) - 50.0) / 25.0,             # UO merkezli
        th(f("cci", 0) / 120.0),                          # ±200 sınırını yumuşat
        1.0 if vwap == "ust2" else (0.5 if vwap == "ust1" else (-1.0 if vwap == "alt2" else (-0.5 if vwap == "alt1" else 0.0))),
        th(f("aroonOsc", 0) / 60.0),                      # ±100 → smooth
        (f("williamsR", -50) + 50.0) / 30.0,              # -100..0 → merkezli
        1.0 if mode == "bull" else (-1.0 if mode == "ayi" else 0.0),
    ]


def _to_np(weights: dict) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Hem yeni Python şeması (W:[...], b:[...]) hem de PHP şeması (w1,b1,w2,b2,...) destekli."""
    if "W" in weights and "b" in weights:
        Ws = [np.array(W, dtype=float) for W in weights["W"]]
        bs = [np.array(b, dtype=float) for b in weights["b"]]
        return Ws, bs
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
    # Şekli kontrol et: ilk katmanın input boyutu features() çıktısıyla aynı olmalı (26).
    if Ws[0].shape[0] != 26 and Ws[0].shape[1] == 26:
        Ws = [W.T for W in Ws]
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
    """0..1 arası tahmin — yüksek = boğa beklentisi."""
    if not net or "weights" not in net:
        return 0.5
    x = features(snap)
    y, _ = forward(net["weights"], x)
    return y


def _adaptive_lr(net: dict, base_lr: float) -> float:
    """v37.3: Adam adım sayısına göre kademeli LR azaltma."""
    t = int((net.get("optimizer") or {}).get("t", 0))
    decays = t // LR_DECAY_EVERY
    lr = base_lr * (LR_DECAY_GAMMA ** decays)
    return max(LR_MIN, lr)


def _clip_grad(g, max_norm: float = GRAD_CLIP):
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
    net["avg_loss"] = round(0.95 * float(net.get("avg_loss", 1.0)) + 0.05 * loss, 6)
    net["last_trained"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return float(loss)


def train_on_outcome(net: dict, snap: dict, ret: float) -> float:
    """Sonuç getirisinden hedef üret ve eğit.

    v37.2: tanh tabanlı risk-ayarlı hedef. ret/15 üzerinden satüre olur.
    v37.3 iyileştirmeleri:
      • Sınıf dengesi: kazanan/kaybeden oranına göre sample_weight (azınlığı yukseltir)
      • Zor örnek bonus: tahmin yanlışsa weight 1.5x (focal-benzeri)
      • Yüksek mutlak getiri (|ret|>10) güçlü sinyal → +25% weight
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

    return train_step(net, snap, target, sample_weight=sample_w)


def neural_get_stats(net: dict | None) -> dict:
    if not net:
        return {"ready": False, "trained": 0}
    trained = int(net.get("trained_samples", 0))
    wins = int(net.get("wins", 0))
    losses = int(net.get("losses", 0))
    return {
        "ready": trained >= 5,
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
