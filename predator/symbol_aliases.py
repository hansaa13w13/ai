"""Sembol takma adları (BIST kod değişikliği / yeniden adlandırma takibi).

Bazı şirketler birleşme, ters birleşme, unvan değişikliği gibi nedenlerle
yeni bir BIST koduyla işlem görmeye başlar; eski kod kayıtlı kalır ama
fiyat verisi donar (Fark=0, OncHafta=boş, Hacim≈0).

Örnek: METUR (METEMTUR) → BLUME (BLUME METAL KIMYA).

Bu modül:
  • `cache/predator_symbol_aliases.json` dosyasında {OLD: NEW} eşlemesi tutar.
  • `get_active_symbol(code)` → varsa yeni kodu döner.
  • `detect_successor(old_code)` → eski kodun stale olduğunu doğrulayıp,
    API'de aynı `Tanim`'a sahip başka bir aktif kod arar.
  • Tespit halinde cache'e yazıp Telegram'a bildirim gönderir.
"""
from __future__ import annotations
import json
import threading
import time
from typing import Any

from . import config

_FILE = config.CACHE_DIR / "predator_symbol_aliases.json"
_LOCK = threading.Lock()
_ALIASES: dict[str, dict] = {}  # OLD → {"new": NEW, "ts": unix, "reason": str}
_LOADED = False


def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        try:
            if _FILE.exists():
                raw = json.loads(_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for k, v in raw.items():
                        if isinstance(v, dict) and v.get("new"):
                            _ALIASES[str(k).upper()] = v
                        elif isinstance(v, str):
                            _ALIASES[str(k).upper()] = {"new": v.upper(),
                                                        "ts": 0,
                                                        "reason": "manual"}
        except (OSError, json.JSONDecodeError):
            pass
        _LOADED = True


def _save() -> None:
    try:
        tmp = _FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_ALIASES, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(_FILE)
    except OSError:
        pass


def get_active_symbol(code: str) -> str:
    """Eski kod için kayıtlı yeni kod varsa onu döner; yoksa orijinali."""
    if not code:
        return code
    _load()
    code = code.strip().upper()
    info = _ALIASES.get(code)
    if info and info.get("new"):
        return str(info["new"]).upper()
    return code


def all_aliases() -> dict[str, dict]:
    """Tüm kayıtlı eşlemeleri döner (UI / teşhis için)."""
    _load()
    with _LOCK:
        return {k: dict(v) for k, v in _ALIASES.items()}


def register_alias(old: str, new: str, reason: str = "auto") -> None:
    """Yeni eşleme kaydet ve diske yaz."""
    if not old or not new:
        return
    old_u, new_u = old.strip().upper(), new.strip().upper()
    if old_u == new_u:
        return
    _load()
    with _LOCK:
        _ALIASES[old_u] = {"new": new_u, "ts": int(time.time()),
                           "reason": reason}
        _save()


def remove_alias(old: str) -> bool:
    _load()
    old_u = (old or "").strip().upper()
    with _LOCK:
        if old_u in _ALIASES:
            del _ALIASES[old_u]
            _save()
            return True
    return False


# ── Tespit (heuristic) ───────────────────────────────────────────────────────
def _is_stale(detail: dict) -> bool:
    """API yanıtı 'donmuş veri' mi? (Fark=0 + OncHafta boş + Hacim çok düşük)"""
    if not isinstance(detail, dict):
        return False
    fark = str(detail.get("Fark") or "").strip().replace(",", ".")
    onc_hafta = str(detail.get("OncHafta") or "").strip()
    hacim_s = str(detail.get("Hacim") or "0").replace(",", "")
    try:
        fark_f = float(fark) if fark else 0.0
    except ValueError:
        fark_f = 0.0
    try:
        hacim_f = float(hacim_s) if hacim_s else 0.0
    except ValueError:
        hacim_f = 0.0
    # OncHafta boşsa ve Fark=0 → kuvvetli işaret
    return fark_f == 0.0 and not onc_hafta


def _is_fresh(detail: dict) -> bool:
    """API yanıtı taze veri mi?

    Hacim alanı bayat veride bile 0'dan farklı kalabildiği için (kümülatif
    geçmiş hacim donar) güvenilir değildir. Asıl taze veri sinyali:
      • OncHafta dolu (geçen hafta verisi var) VE
      • Fark!=0 (bugün hareket var) — VEYA en azından OncAy doluysa
    METUR vakasında: Hacim=304M ama Fark=0, OncHafta='', OncAy=''  → BAYAT.
    """
    if not isinstance(detail, dict):
        return False
    fark = str(detail.get("Fark") or "").strip().replace(",", ".")
    onc_hafta = str(detail.get("OncHafta") or "").strip()
    onc_ay = str(detail.get("OncAy") or "").strip()
    try:
        fark_f = float(fark) if fark else 0.0
    except ValueError:
        fark_f = 0.0
    # En kuvvetli sinyal: OncHafta dolu + (Fark!=0 veya OncAy dolu)
    if onc_hafta and (fark_f != 0.0 or onc_ay):
        return True
    # OncHafta dolu ama Fark=0 ve OncAy boş → şüpheli, bayat say
    if not onc_hafta and not onc_ay and fark_f == 0.0:
        return False
    # Geri kalan kombinasyonlarda OncHafta'yı belirleyici kabul et
    return bool(onc_hafta) or bool(onc_ay)


def _norm_tanim(s: str) -> str:
    """Tanim karşılaştırma için temizler."""
    s = (s or "").upper()
    tr = {"Ç": "C", "Ğ": "G", "İ": "I", "I": "I",
          "Ö": "O", "Ş": "S", "Ü": "U"}
    s = "".join(tr.get(c, c) for c in s)
    return "".join(c for c in s if c.isalnum())


def _candidate_codes(tanim: str) -> list[str]:
    """Tanim'dan olası BIST kodu adayları üret (ör. 'BLUME METAL KIMYA' → BLUME, BLUM, BMK)."""
    if not tanim:
        return []
    tr = {"Ç": "C", "Ğ": "G", "İ": "I", "I": "I",
          "Ö": "O", "Ş": "S", "Ü": "U"}
    ascii_up = "".join(tr.get(c, c) for c in tanim.upper())
    words = [w for w in "".join(c if c.isalnum() else " "
                                 for c in ascii_up).split()
             if len(w) >= 2]
    s = "".join(c for c in ascii_up if c.isalnum())
    cands: list[str] = []
    seen: set[str] = set()

    def _add(c: str) -> None:
        c = (c or "").upper()
        if 3 <= len(c) <= 5 and c not in seen and c.isalpha():
            seen.add(c)
            cands.append(c)

    if words:
        first = words[0]
        for L in (5, 4, 3):
            if len(first) >= L:
                _add(first[:L])
        _add(first)
        if len(words) >= 2:
            second = words[1]
            for L in (1, 2):
                if len(first) + L <= 5:
                    _add(first[: 5 - L] + second[:L])
        ini = "".join(w[0] for w in words[:5] if w)
        if 3 <= len(ini) <= 5:
            _add(ini)
    if len(s) >= 5:
        _add(s[:5])
    if len(s) >= 4:
        _add(s[:4])
    return cands


def detect_successor(old_code: str, bist_list: list[dict] | None = None
                     ) -> dict | None:
    """Eski kod stale ise, aynı Tanim'a sahip aktif yeni kodu bulmayı dene.

    Algoritma:
      1) Eski kodun API yanıtını al; Tanim ve stale olup olmadığını ölç.
      2) Stale değilse → None (başka şey değiştirme).
      3) BIST listesinde aynı Tanim'a sahip başka bir kod var mı? Varsa onu dön.
      4) Tanim'dan kod adayları üret (örn. 'BLUME...' → 'BLUME','BLUM','BLUMET').
      5) Her aday için API yanıtı al; Tanim eşleşip taze ise → yeni kod.

    Dönüş: {'old': X, 'new': Y, 'tanim': '...', 'reason': '...'} veya None.
    """
    from .api_client import fetch_sirket_detay
    if not old_code:
        return None
    old_code = old_code.strip().upper()
    # raw_code=True → alias çözümleme atlanır, gerçekten ESKİ kodu sorgular
    detail = fetch_sirket_detay(old_code, raw_code=True)
    if not isinstance(detail, dict):
        # Eski kod tamamen ölü → tipik delisting; tanım bilinmediği için
        # geri kalan adımlar tutmaz, kullanıcıya rapor edilsin.
        return {"old": old_code, "new": None, "tanim": "",
                "reason": "API yanıt vermiyor — kod silinmiş (delist) olabilir"}
    tanim = str(detail.get("Tanim") or "").strip()
    if not tanim:
        return None
    if _is_fresh(detail):
        # Veri taze, başka kod aramaya gerek yok
        return None

    target = _norm_tanim(tanim)

    # 3) BIST listesinde aynı Tanim'a sahip başka kod
    if bist_list:
        for it in bist_list:
            if not isinstance(it, dict):
                continue
            c = str(it.get("code") or "").upper()
            n = str(it.get("name") or "")
            if c and c != old_code and target and target in _norm_tanim(n):
                # Adayı doğrula
                d2 = fetch_sirket_detay(c)
                if isinstance(d2, dict) and _is_fresh(d2) \
                        and target in _norm_tanim(str(d2.get("Tanim") or "")):
                    return {"old": old_code, "new": c, "tanim": tanim,
                            "reason": f"BIST listesinde aynı şirket: {c}"}

    # 4-5) Tanim'dan aday kodlar üret ve API'de prob
    for cand in _candidate_codes(tanim):
        if cand == old_code:
            continue
        d2 = fetch_sirket_detay(cand)
        if not isinstance(d2, dict):
            continue
        t2 = str(d2.get("Tanim") or "").strip()
        if not t2:
            continue
        # Aynı Tanim ve taze veri?
        if _norm_tanim(t2) == target and _is_fresh(d2):
            return {"old": old_code, "new": cand, "tanim": tanim,
                    "reason": f"API probu: {cand} aynı şirketin aktif kodu"}

    return None
