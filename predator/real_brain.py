"""Gerçek Beyin (Real Brain) — scikit-learn RF + GBM Ensemble.

Mevcut 4 numpy sinir ağına EK olarak çalışır.
Tabular finansal veri için sinir ağlarını geçen kanıtlanmış ML modeli.

Tasarım:
  • JSON-safe: Model pickle'lanmaz; eğitim verisi brain.json'da saklanır.
    Uygulama her başladığında in-memory model <0.5sn'de sıfırdan eğitilir.
  • Module-level cache: Aynı veri için tekrar eğitim engellenir.
  • Ensemble: GBM %60 + RF %40 (BIST tabular verisi için optimal oran).
  • Min 30 örnek olmadan tahmin üretilmez (0.5 nötr döner).
  • Feature importance: Hangi indikatörler gerçekten işe yarıyor?

Dışarıya açık API:
  rb_add_sample(brain, snap, ret) → brain dict güncellenir
  rb_predict(brain, snap)         → (prob: float, conf: float)
  rb_get_status(brain)            → dict (eğitim sayısı, doğruluk, top features)
  rb_top_features(brain, n=5)     → list[dict]
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any

import numpy as np

# ── Feature isimler (neural.py ile eşleşiyor, 45 özellik)
FEATURE_NAMES: list[str] = [
    "RSI", "52hf_poz", "HacimOrani", "MACD_Kesisim", "SAR_Yon", "Ichimoku",
    "RSI_Diverjans", "BB_Sikisma", "CMF", "MFI", "ADX", "SMC_Bias",
    "OFI_Sinyal", "Supertrend", "Hull_MA", "EMA_Kesisim", "TRIX",
    "CMO", "AwesomeOsc", "Keltner_Pos", "UltOsc", "CCI",
    "VWAP_Pos", "Aroon_Osc", "WilliamsR", "Piyasa_Modu",
    "StochK", "StochD", "Elder_Ray",
    "SMC_OB_Yon", "SMC_FVG_Yon", "Lik_Supurme",
    "BB_Yuzde", "ROC5", "ROC20", "Vol_Rejim",
    "Piy_Genisligi", "Graham_Pot",
    "OBV_Trend", "SMA200_Pos", "Trend_Gucu",
    "Form_Gucu", "Donchian", "ROC60", "SMA20v50",
]

_MAX_SAMPLES   = 500      # ring buffer max
_MIN_TRAIN     = 30       # minimum tahmin için
_RETRAIN_EVERY = 5        # her N yeni örnekte yeniden eğit

# ── In-memory model cache (thread-safe)
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {
    "n_samples": -1,        # son eğitimdeki örnek sayısı
    "model_gbm": None,      # GradientBoostingClassifier
    "model_rf":  None,      # RandomForestClassifier
    "importances": None,    # np.ndarray(45)
    "accuracy": 0.0,        # cross-val tahmin doğruluğu
}


# ──────────────────────────────────────────────────────────────────────────────
def rb_add_sample(brain: dict, snap: dict, ret: float) -> None:
    """Outcome geldikçe yeni örnek ekle; gerekirse modeli yeniden eğit.

    brain["rb_samples"] → list[{"x": list[float], "y": int, "ret": float, "date": str}]
    """
    from .neural import features as _features

    try:
        x = _features(snap)
    except Exception:
        return

    y = 1 if ret >= 0.5 else 0

    samples: list[dict] = brain.setdefault("rb_samples", [])
    samples.append({
        "x":    x,
        "y":    y,
        "ret":  round(float(ret), 2),
        "date": snap.get("date", ""),
        "code": snap.get("code", ""),
    })
    # Ring buffer
    if len(samples) > _MAX_SAMPLES:
        brain["rb_samples"] = samples[-_MAX_SAMPLES:]
        samples = brain["rb_samples"]

    n = len(samples)
    if n >= _MIN_TRAIN and n % _RETRAIN_EVERY == 0:
        _retrain(samples)


def rb_predict(brain: dict, snap: dict) -> tuple[float, float]:
    """Gerçek Beyin tahmini: (prob, confidence).

    prob       : 0..1 arası, >0.5 boğa beklentisi
    confidence : 0..1 arası, modelin ne kadar emin olduğu

    Minimum 30 örnek yoksa (0.5, 0.0) döner.
    """
    samples: list[dict] = brain.get("rb_samples") or []
    n = len(samples)

    if n < _MIN_TRAIN:
        return (0.5, 0.0)

    # Cache güncelleme (sample sayısı değiştiyse veya model yoksa)
    with _cache_lock:
        if _cache["n_samples"] != n or _cache["model_gbm"] is None:
            _retrain(samples)

        gbm = _cache["model_gbm"]
        rf  = _cache["model_rf"]
        if gbm is None:
            return (0.5, 0.0)
        acc = float(_cache["accuracy"])

    # Feature vektörü
    from .neural import features as _features
    try:
        x = np.array(_features(snap), dtype=float).reshape(1, -1)
    except Exception:
        return (0.5, 0.0)

    try:
        p_gbm = float(gbm.predict_proba(x)[0][1])
        p_rf  = float(rf.predict_proba(x)[0][1])
    except Exception:
        return (0.5, 0.0)

    prob = p_gbm * 0.60 + p_rf * 0.40

    # Confidence: accuracy × data_size_factor × polarisation
    data_f = min(1.0, (n - _MIN_TRAIN) / 120.0)      # 0 → 1 with 150 samples
    polar  = abs(prob - 0.5) * 2.0                    # 0 (belirsiz) → 1 (kesin)
    acc_f  = max(0.0, (acc - 0.50) / 0.40)            # 50% acc → 0, 90% → 1
    conf   = round(0.40 * data_f + 0.35 * acc_f + 0.25 * polar, 3)
    conf   = max(0.0, min(1.0, conf))

    return (round(prob, 4), conf)


def rb_get_status(brain: dict) -> dict:
    """Panel / log için real brain durumu."""
    samples = brain.get("rb_samples") or []
    n = len(samples)
    with _cache_lock:
        acc  = float(_cache.get("accuracy", 0.0))
        cn   = int(_cache.get("n_samples", 0))
        imps = _cache.get("importances")

    wins  = sum(1 for s in samples if int(s.get("y", 0)) == 1)
    wr    = round(wins / n * 100, 1) if n > 0 else 0.0
    ready = n >= _MIN_TRAIN and cn == n

    top5  = _top_features_from_importances(imps, 5) if imps is not None else []

    return {
        "ready":    ready,
        "n":        n,
        "min_n":    _MIN_TRAIN,
        "accuracy": round(acc * 100, 1) if acc > 0 else None,
        "win_rate": wr,
        "top_features": top5,
    }


def rb_top_features(brain: dict, n: int = 5) -> list[dict]:
    """En etkili n indikatörü döndür."""
    with _cache_lock:
        imps = _cache.get("importances")
    return _top_features_from_importances(imps, n)


# ──────────────────────────────────────────────────────────────────────────────
def _retrain(samples: list[dict]) -> None:
    """GBM + RF eğitimi — cache günceller. Kilidi içeride alır."""
    try:
        from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
        from sklearn.model_selection import cross_val_score
    except ImportError:
        return

    X = np.array([s["x"] for s in samples], dtype=float)
    y = np.array([s["y"] for s in samples], dtype=int)

    # Dengesizlik kontrolü: tamamen tek sınıf varsa eğitme
    if len(np.unique(y)) < 2:
        return

    # Sample weight: yakın tarihli örneklere daha fazla ağırlık
    sw = _sample_weights(samples)

    gbm = GradientBoostingClassifier(
        n_estimators=120,
        max_depth=3,
        learning_rate=0.08,
        subsample=0.85,
        min_samples_leaf=3,
        random_state=42,
    )
    rf = RandomForestClassifier(
        n_estimators=150,
        max_depth=5,
        min_samples_leaf=3,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )

    gbm.fit(X, y, sample_weight=sw)
    rf.fit(X, y, sample_weight=sw)

    # Cross-val accuracy (küçük veri setinde 3-fold yeterli)
    cv_folds = 3 if len(y) < 100 else 5
    try:
        scores = cross_val_score(gbm, X, y, cv=cv_folds, scoring="accuracy")
        acc = float(np.mean(scores))
    except Exception:
        acc = 0.0

    # Feature importance: GBM %60 + RF %40
    imps = gbm.feature_importances_ * 0.60 + rf.feature_importances_ * 0.40

    with _cache_lock:
        _cache["model_gbm"]   = gbm
        _cache["model_rf"]    = rf
        _cache["importances"] = imps
        _cache["accuracy"]    = acc
        _cache["n_samples"]   = len(samples)


def _sample_weights(samples: list[dict]) -> np.ndarray:
    """Yakın tarihli örneklere daha fazla ağırlık (üstel azalma)."""
    n = len(samples)
    # samples listesi en yeni sona append edilmiş: son eleman en yeni
    ws = np.array([
        math.exp(-0.004 * (n - 1 - i)) for i in range(n)
    ], dtype=float)
    ws /= ws.mean()   # normalize so mean=1
    return ws


def rb_bootstrap_from_snapshots(brain: dict) -> int:
    """Mevcut outcome-etiketli snapshot'lardan rb_samples'ı önyükle.

    Neural ağların eğitim havuzu (`brain["snapshots"]`) içinde
    `outcome_ret` dolu kayıtları tarayıp Real Brain'e ekler.
    Halihazırda rb_samples içinde olan (code+date çifti) kayıtlar atlanır.

    Döner: eklenen yeni örnek sayısı
    """
    from .neural import features as _features

    existing_keys: set[str] = set()
    for s in brain.get("rb_samples") or []:
        key = f"{s.get('code','')}|{s.get('date','')}"
        existing_keys.add(key)

    added = 0
    for code, snaps in (brain.get("snapshots") or {}).items():
        for snap in snaps:
            ret = snap.get("outcome_ret")
            if ret is None:
                continue
            date_key = snap.get("date", "")
            key = f"{code}|{date_key}"
            if key in existing_keys:
                continue
            try:
                x = _features(snap)
            except Exception:
                continue
            y = 1 if float(ret) >= 0.5 else 0
            entry = {
                "x":    x,
                "y":    y,
                "ret":  round(float(ret), 2),
                "date": date_key,
                "code": code,
            }
            samples: list[dict] = brain.setdefault("rb_samples", [])
            samples.append(entry)
            existing_keys.add(key)
            added += 1

    if added > 0:
        samples = brain.get("rb_samples") or []
        if len(samples) > _MAX_SAMPLES:
            brain["rb_samples"] = samples[-_MAX_SAMPLES:]
        n = len(brain.get("rb_samples") or [])
        if n >= _MIN_TRAIN:
            _retrain(brain["rb_samples"])

    return added


def _top_features_from_importances(
    imps: "np.ndarray | None", n: int
) -> list[dict]:
    if imps is None or len(imps) == 0:
        return []
    total = float(np.sum(imps))
    if total <= 0:
        return []
    idxs = np.argsort(imps)[::-1][:n]
    out = []
    for i in idxs:
        name = FEATURE_NAMES[i] if i < len(FEATURE_NAMES) else f"feat_{i}"
        out.append({
            "name":       name,
            "importance": round(float(imps[i]) / total * 100, 1),
            "idx":        int(i),
        })
    return out
