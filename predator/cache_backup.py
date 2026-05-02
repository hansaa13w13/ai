"""Cache yedekleme — Telegram grubu üzerinden (gizli/şifreli).

Render.com gibi efemer disklerde cache silindiğinde, en son yedek pinlenmiş
mesajdan otomatik geri yüklenir. Bot her N dakikada bir cache'i ZIP'leyip
AES (Fernet) ile şifreler ve `.bin` uzantılı, sıradan görünen bir dosya
olarak TG grubuna yükler. Önceki yedeği unpin/yenisini pin'ler ve eski
mesajları gruptan siler — kullanıcılar yedek olduğunu fark etmez.
"""
from __future__ import annotations

import base64
import hashlib
import io
import time
import zipfile
from pathlib import Path
from typing import Iterable

from cryptography.fernet import Fernet, InvalidToken

from . import config
from .http_utils import safe_request
from .observability import log_event, log_exc

BACKUP_INTERVAL_SEC = 1800  # 30 dakikada bir yedek
# Caption gizli — "yedek/cache/backup" gibi kelimeler geçmez. İnsan gözüne
# anlamsız bir log/metric kaydı gibi görünür. Kullanıcılar fark etmesin.
BACKUP_CAPTION_TAG = "#metrics"
# Ana grupta sadece son N yedek kalsın (restore için 1 yeterli; 1 = sadece sonuncu).
BACKUP_KEEP_LAST = 1
# Yüklenen yedek mesaj ID'leri burada tutulur (eskileri silmek için).
_BACKUP_TRACK_FILE = config.CACHE_DIR / "predator_backup_msgs.json"
# Birleşik pinli mesaj durumu: {chat_id: {message_id, ts, last_doc_ts, filename}}
_UNIFIED_PIN_STATE_FILE = config.CACHE_DIR / "predator_unified_pin_state.json"
# Telegram document caption üst limiti
_TG_CAPTION_MAX = 1024

# ── Şifreleme (AES-128-CBC + HMAC, Fernet) ─────────────────────────────────
# Sabit şifre koda gömülü — paylaşılan yedeklerin gizliliği için. Anahtar
# PBKDF2-HMAC-SHA256 ile türetilir. Şifre değişirse eski yedekler okunamaz.
_BACKUP_PASSWORD = b"PrEdAt0r-BIST-2026!CaChE-S3cur3-v1"
_BACKUP_SALT = b"predator-bist-cache-backup-v1"
_BACKUP_ITERS = 200_000


def _derive_key() -> bytes:
    raw = hashlib.pbkdf2_hmac(
        "sha256", _BACKUP_PASSWORD, _BACKUP_SALT, _BACKUP_ITERS, dklen=32)
    return base64.urlsafe_b64encode(raw)


_FERNET = Fernet(_derive_key())


def _encrypt_blob(data: bytes) -> bytes:
    """ZIP byte'larını şifrele. Çıktı Fernet token (urlsafe-base64 metin,
    bytes olarak)."""
    return _FERNET.encrypt(data)


def _decrypt_blob(token: bytes) -> bytes:
    """Şifreli yedeği çöz. Eski (şifresiz) ZIP yedekleri için fallback."""
    try:
        return _FERNET.decrypt(token)
    except InvalidToken:
        # Geriye uyum: eski şifresiz ZIP yedekleri olduğu gibi dönsün
        return token


# ── JPG sarmalama (steganografi-light) ─────────────────────────────────────
# Yedek artık `.jpg` uzantılı, geçerli bir resim olarak yüklenir. Resmin EOI
# (FFD9) sonrasına özel bir magic marker + şifreli yedek bayt'ları eklenir.
# JPEG decoder'lar EOI sonrasını yok sayar, dolayısıyla resim normal görünür;
# normal kullanıcılar yedek olduğunu fark etmez.
_JPG_MAGIC = b"\x00\x00\x00PRDTRBKPv1\x00\x00\x00"
_COVER_PATH = Path(__file__).parent / "assets" / "cover.jpg"


def _load_cover_bytes() -> bytes:
    """Kapak JPG'yi diskten oku (modül yükleme zamanında bir kez cache'le)."""
    try:
        return _COVER_PATH.read_bytes()
    except OSError as e:
        log_event("backup", f"cover read failed: {e}", level="warn")
        # Asgari geçerli minimal JPG (1x1 boş) — daima upload edilebilsin
        return (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01"
                b"\x00\x01\x00\x00\xff\xdb\x00C\x00" + b"\x08" * 64 +
                b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
                b"\xff\xc4\x00\x14\x00\x01" + b"\x00" * 15 + b"\x09"
                b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfa\xff\xd9")


_COVER_BYTES = _load_cover_bytes()


def _current_cover_bytes() -> bytes:
    """Açık pozisyondaki hissenin canlı grafiğini üret; başarısızsa
    statik kapak resmine geri düş. Geçerli bir JPG döner.
    """
    try:
        from .portfolio_chart import render_cover_jpg
        b = render_cover_jpg()
        if b and b[:2] == b"\xff\xd8":
            return b
    except Exception as e:
        log_event("backup", f"cover render failed: {e}", level="warn")
    return _COVER_BYTES


def _wrap_in_jpg(encrypted_payload: bytes) -> bytes:
    """Şifreli yedeği geçerli bir JPG dosyasına sarmala. Kapak resmi:
    portföydeki hissenin hedef seviyeleri ile çizilen canlı grafik
    (yoksa statik fallback)."""
    cover = _current_cover_bytes()
    return cover + _JPG_MAGIC + encrypted_payload


def _unwrap_from_jpg(blob: bytes) -> bytes | None:
    """JPG sarmalı dosyadan şifreli payload'ı çıkar.
    Magic marker bulunamazsa None döner (eski .bin yedekleri).
    """
    idx = blob.rfind(_JPG_MAGIC)
    if idx < 0:
        return None
    return blob[idx + len(_JPG_MAGIC):]

CRITICAL_FILES = (
    "predator_ai_brain.json",
    "predator_oto_portfolio.json",
    "predator_oto_log.json",
    "predator_signal_history.json",
    "predator_auto_status.json",
    "predator_auto_log.json",
    "predator_market_mode.json",
    "predator_allstocks_cache.json",
    "predator_bist_full_list.json",
    "predator_daily_summary_state.json",
    "predator_kelly_log.json",
    "predator_adaptive_vol.json",
    "predator_volatility.json",
    "predator_ai_performance.json",
    # Pinned-mesaj durum dosyaları — bunlar yedeğe dahil edilmezse Render
    # redeploy sonrası eski pinli mesajları silebilmek için referans kaybolur
    # ve grupta birden fazla "PANO" / chart_*.jpg birikir.
    "predator_unified_pin_state.json",
    "predator_backup_msgs.json",
    "predator_tg_pin_state.json",
)
EXTRA_GLOBS = ("predator_smc_*.json", "bilanco_*.json")

_LAST_BACKUP_TS = 0.0


def _load_tracked() -> list[dict]:
    """Daha önce yüklenmiş yedek mesajların listesi (en yenisi sonda)."""
    try:
        import json
        if not _BACKUP_TRACK_FILE.exists():
            return []
        data = json.loads(_BACKUP_TRACK_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and x.get("message_id")]
    except Exception:
        pass
    return []


def _save_tracked(items: list[dict]) -> None:
    try:
        import json
        _BACKUP_TRACK_FILE.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception as e:
        log_event("backup", f"track save failed: {e}", level="warn")


def _delete_tg_message(chat_id, message_id: int) -> bool:
    if not message_id:
        return False
    r = safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/deleteMessage",
        data={"chat_id": str(chat_id), "message_id": str(message_id)},
        timeout=15, retries=2, backoff=0.5, metric_kind="tg_backup",
    )
    if r is None:
        return False
    try:
        return bool(r.json().get("ok"))
    except Exception:
        return False


def _prune_old_backups(keep_last: int = BACKUP_KEEP_LAST) -> int:
    """Track'teki en yeni `keep_last` kayıt hariç tüm eski yedekleri sil.
    Telegram'a deleteMessage çağırır + track dosyasını günceller.
    Silinen mesaj sayısını döner.
    """
    items = _load_tracked()
    if len(items) <= keep_last:
        return 0
    # En yenisi sonda; silinecekler baştakiler
    to_delete = items[:-keep_last] if keep_last > 0 else items[:]
    keep = items[-keep_last:] if keep_last > 0 else []
    deleted = 0
    for it in to_delete:
        try:
            if _delete_tg_message(it.get("chat_id"), int(it.get("message_id", 0) or 0)):
                deleted += 1
        except Exception as e:
            log_event("backup", f"delete failed: {e}", level="warn",
                      message_id=it.get("message_id"))
    _save_tracked(keep)
    if deleted:
        log_event("backup", f"pruned {deleted} old backup(s) from chat",
                  level="info", deleted=deleted, kept=len(keep))
    return deleted


def _select_files() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for name in CRITICAL_FILES:
        p = config.CACHE_DIR / name
        if p.exists() and p.name not in seen:
            out.append(p)
            seen.add(p.name)
    for pattern in EXTRA_GLOBS:
        for p in config.CACHE_DIR.glob(pattern):
            if p.name not in seen:
                out.append(p)
                seen.add(p.name)
    return out


def _build_zip() -> tuple[bytes, int, int]:
    files = _select_files()
    buf = io.BytesIO()
    raw_total = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in files:
            try:
                data = p.read_bytes()
            except OSError:
                continue
            zf.writestr(p.name, data)
            raw_total += len(data)
    return buf.getvalue(), len(files), raw_total


_RESTORE_DATA_FILES = (
    "predator_ai_brain.json",
    "predator_oto_portfolio.json",
    "predator_oto_log.json",
    "predator_signal_history.json",
    "predator_allstocks_cache.json",
    "predator_bist_full_list.json",
    "predator_unified_pin_state.json",
)

# Anlamlı cache kalitesi için minimum boyut eşikleri (byte).
# Küçük/stub dosyalar "boş cache" sayılır — iyi yedeği ezip silmez.
_QUALITY_MIN_SIZES: dict[str, int] = {
    "predator_ai_brain.json":        2_000,   # eğitimli brain ≥ 2 KB
    "predator_allstocks_cache.json": 20_000,  # gerçek tarama ≥ 20 KB
}

# /tmp manifest — warm-restart (redeploy değil sıradan restart) için file_id önbelleği
_TMP_MANIFEST = Path("/tmp") / "predator_backup_manifest.json"


def cache_has_real_data() -> bool:
    """Cache'te yüklemeye değer gerçek veri var mı?

    Boyut eşiğini geçen kritik dosya varsa True döner.
    Sadece varoluşa değil, anlamlı içeriğe göre karar verir:
    - Boş/yeni başlatılmış {} dosyaları False döner → yedek KORUNUR
    - Gerçek tarama + eğitilmiş brain varsa True → yedek güncellenir
    """
    for fname, min_bytes in _QUALITY_MIN_SIZES.items():
        p = config.CACHE_DIR / fname
        try:
            if p.exists() and p.stat().st_size >= min_bytes:
                return True
        except OSError:
            pass
    return False


def cache_is_empty() -> bool:
    """Cache boş = kritik dosyalarda anlamlı veri yok.

    Sadece dosya varlığına değil, boyut kalitesine göre karar verir:
    daemon başlangıcında oluşan küçük stub dosyalar 'gerçek veri' sayılmaz.
    Böylece daemon thread'i başlamadan önce oluşan küçük dosyalar nedeniyle
    restore yanlışlıkla skip edilmez.
    """
    return not cache_has_real_data()


def _save_tmp_manifest(file_id: str, filename: str, message_id: int = 0) -> None:
    """Yedek metadata'sını /tmp'ye kaydet — warm-restart fallback için."""
    try:
        import json as _json
        _TMP_MANIFEST.write_text(_json.dumps({
            "file_id":    file_id,
            "filename":   filename,
            "message_id": int(message_id),
            "ts":         int(time.time()),
        }), encoding="utf-8")
    except Exception as e:
        log_event("backup", f"tmp manifest save failed: {e}", level="warn")


def _load_tmp_manifest() -> dict:
    """Warm-restart /tmp manifestini oku. Geçersiz/yok → boş dict."""
    try:
        import json as _json
        if _TMP_MANIFEST.exists():
            d = _json.loads(_TMP_MANIFEST.read_text(encoding="utf-8"))
            if isinstance(d, dict) and d.get("file_id"):
                return d
    except Exception:
        pass
    return {}


def _download_and_extract(file_id: str, overwrite: bool = True) -> dict:
    """Verilen file_id'yi Telegram'dan indir, şifre çöz, cache dizinine aç."""
    rf = safe_request(
        "GET",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/getFile",
        params={"file_id": file_id}, timeout=20,
        retries=3, backoff=0.5, metric_kind="tg_restore",
    )
    if rf is None:
        return {"ok": False, "error": "getFile_fail: retries exhausted"}
    try:
        j = rf.json()
    except Exception as e:
        return {"ok": False, "error": f"getFile_fail: bad json ({e})"}
    if not j.get("ok"):
        return {"ok": False, "error": f"getFile_fail: {j.get('description')}"}
    file_path = j["result"]["file_path"]
    durl = f"https://api.telegram.org/file/bot{config.TG_BOT_TOKEN}/{file_path}"
    rd = safe_request("GET", durl, timeout=120,
                      retries=3, backoff=1.0, metric_kind="tg_restore")
    if rd is None or not rd.ok:
        st = rd.status_code if rd is not None else "no_response"
        return {"ok": False, "error": f"download_fail: {st}"}
    try:
        unwrapped = _unwrap_from_jpg(rd.content)
        enc_blob  = unwrapped if unwrapped is not None else rd.content
        zip_bytes = _decrypt_blob(enc_blob)
    except Exception as e:
        return {"ok": False, "error": f"decrypt_fail: {e}"}
    restored: list[str] = []
    skipped = 0
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        for name in zf.namelist():
            target = config.CACHE_DIR / name
            if target.exists() and not overwrite:
                skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
            restored.append(name)
    except Exception as e:
        return {"ok": False, "error": f"unzip_fail: {e}"}
    return {
        "ok":           True,
        "restored":     len(restored),
        "skipped":      skipped,
        "size_kb":      len(rd.content) // 1024,
        "decrypted_kb": len(zip_bytes) // 1024,
        "encrypted":    rd.content != zip_bytes,
    }


def backup_cache_to_telegram(force: bool = False) -> dict:
    """Cache'i ZIP'le, TG grubuna document olarak yükle ve mesajı pinle."""
    global _LAST_BACKUP_TS
    now = time.time()
    if not force and (now - _LAST_BACKUP_TS) < BACKUP_INTERVAL_SEC:
        return {"ok": False, "skipped": "throttled",
                "next_in": int(BACKUP_INTERVAL_SEC - (now - _LAST_BACKUP_TS))}
    if not config.TG_BOT_TOKEN or not config.TG_CHAT_ID:
        return {"ok": False, "error": "telegram_config_missing"}

    # ── GÜVENLİK KILIFI: Boş/taze cache'i Telegram'a yükleme ───────────────
    # Render.com'da cache silindiğinde daemon yeniden başlar ama ilk tarama
    # tamamlanmadan tg_pin_loop buraya ulaşabilir. O anda cache'te anlamlı
    # veri yoksa yükleme YAPMA — mevcut iyi yedeği asla ezme.
    if not cache_has_real_data():
        return {"ok": False, "error": "cache_empty_skip",
                "info": "Cache henüz dolu değil — mevcut Telegram yedeği korundu"}

    payload, n_files, raw_size = _build_zip()
    if n_files == 0:
        return {"ok": False, "error": "no_files"}

    # ZIP'i şifrele + geçerli bir JPG'e sarmala — Telegram'da sıradan bir
    # resim gibi görünsün, kullanıcılar yedek olduğunu fark etmesin.
    enc_payload = _encrypt_blob(payload)
    jpg_payload = _wrap_in_jpg(enc_payload)

    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
    fname = f"chart_{ts}.jpg"
    caption = (f"{BACKUP_CAPTION_TAG}\n"
               f"📊 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}")

    r = safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/sendDocument",
        data={"chat_id": config.TG_CHAT_ID, "caption": caption,
              "disable_notification": "true"},
        files={"document": (fname, jpg_payload, "image/jpeg")},
        timeout=120, retries=3, backoff=1.0, metric_kind="tg_backup",
    )
    if r is None:
        return {"ok": False, "error": "upload_fail: retries exhausted"}
    try:
        j = r.json()
    except Exception as e:
        return {"ok": False, "error": f"upload_fail: bad json ({e})"}

    if not j.get("ok"):
        return {"ok": False, "error": f"tg_error: {j.get('description')}"}

    msg_id = j["result"]["message_id"]
    # Yeni yedek başarılı → file_id'yi /tmp'ye kaydet (warm-restart fallback)
    doc_result = j["result"].get("document") or {}
    saved_file_id = doc_result.get("file_id", "")
    if saved_file_id:
        _save_tmp_manifest(saved_file_id, fname, int(msg_id))

    unpin_r = safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/unpinAllChatMessages",
        data={"chat_id": config.TG_CHAT_ID},
        timeout=20, retries=2, backoff=0.5, metric_kind="tg_backup",
    )
    if unpin_r is None:
        log_event("backup", "unpinAll failed", level="warn", message_id=msg_id)
    pin_r = safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/pinChatMessage",
        data={"chat_id": config.TG_CHAT_ID, "message_id": msg_id,
              "disable_notification": "true"},
        timeout=20, retries=2, backoff=0.5, metric_kind="tg_backup",
    )
    if pin_r is None:
        log_event("backup", "pinChatMessage failed", level="warn", message_id=msg_id)

    # Pin'in oluşturduğu "X pinned a message" servis mesajını proaktif sil.
    time.sleep(1.5)
    for offset in range(1, 6):
        _delete_tg_message(config.TG_CHAT_ID, int(msg_id) + offset)

    _LAST_BACKUP_TS = now

    # Yeni yedeği takip listesine ekle ve eskileri otomatik sil (sadece son
    # BACKUP_KEEP_LAST kalsın). Pin ana grupta zaten en yenisini gösteriyor;
    # eskiler feed'i kirletmesin.
    items = _load_tracked()
    items.append({
        "chat_id":  str(config.TG_CHAT_ID),
        "message_id": int(msg_id),
        "ts":       int(now),
        "filename": fname,
        "file_id":  saved_file_id,  # restore fallback için sakla
    })
    _save_tracked(items)
    # Ayrıca yeni akıllı yöneticiye de kaydet (v37.12)
    try:
        from . import tg_cleanup
        tg_cleanup.track(config.TG_CHAT_ID, int(msg_id), kind="backup_doc")
    except Exception:
        pass
    pruned = 0
    try:
        pruned = _prune_old_backups(keep_last=BACKUP_KEEP_LAST)
    except Exception as e:
        log_exc("backup", "prune failed", e)

    return {"ok": True, "files": n_files,
            "size_kb": len(jpg_payload) // 1024,
            "enc_kb": len(enc_payload) // 1024,
            "zip_kb": len(payload) // 1024,
            "raw_kb": raw_size // 1024,
            "encrypted": True, "wrapped_in_jpg": True,
            "message_id": msg_id, "filename": fname,
            "pruned": pruned}


def restore_cache_from_telegram(overwrite: bool = True) -> dict:
    """Cache yedeğini Telegram'dan geri yükle — çok aşamalı strateji.

    Strateji sırası:
      1. getChat → pinned_message → document (birincil — her zaman denenir)
      2. /tmp manifest → kaydedilmiş file_id (warm-restart: redeploy değil
         sıradan yeniden başlatma senaryosu)
      3. _load_tracked() izleme listesi → kayıtlı file_id'ler (backup yedeği)

    Her strateji başarısız olursa bir sonraki denenir; tüm hatalar raporlanır.
    """
    if not config.TG_BOT_TOKEN or not config.TG_CHAT_ID:
        return {"ok": False, "error": "telegram_config_missing"}

    errors: list[str] = []

    # ── Strateji 1: getChat → pinned_message ─────────────────────────────
    file_id_s1: str = ""
    filename_s1: str = ""
    try:
        rg = safe_request(
            "GET",
            f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/getChat",
            params={"chat_id": config.TG_CHAT_ID},
            timeout=20, retries=3, backoff=0.5, metric_kind="tg_restore",
        )
        if rg is None:
            errors.append("S1:getChat_timeout")
        else:
            jg = rg.json()
            if not jg.get("ok"):
                errors.append(f"S1:tg_error:{jg.get('description')}")
            else:
                pinned = (jg.get("result") or {}).get("pinned_message")
                if pinned and "document" in pinned:
                    doc = pinned["document"]
                    file_id_s1 = doc.get("file_id", "")
                    filename_s1 = doc.get("file_name", "backup.jpg")
                else:
                    errors.append("S1:no_pinned_document")
    except Exception as e:
        errors.append(f"S1:exception:{e}")

    if file_id_s1:
        result = _download_and_extract(file_id_s1, overwrite=overwrite)
        if result.get("ok"):
            result.update({"strategy": "pinned_message", "filename": filename_s1})
            _save_tmp_manifest(file_id_s1, filename_s1)
            log_event("backup", "restore OK via pinned_message",
                      level="info", restored=result.get("restored"),
                      size_kb=result.get("size_kb"))
            return result
        errors.append(f"S1:download:{result.get('error')}")

    # ── Strateji 2: /tmp manifest → file_id (warm-restart) ───────────────
    manifest = _load_tmp_manifest()
    if manifest.get("file_id") and manifest["file_id"] != file_id_s1:
        age_h = (int(time.time()) - int(manifest.get("ts", 0))) // 3600
        log_event("backup", f"trying /tmp manifest (age ~{age_h}h)",
                  level="info", filename=manifest.get("filename"))
        result = _download_and_extract(manifest["file_id"], overwrite=overwrite)
        if result.get("ok"):
            result.update({"strategy": "tmp_manifest",
                           "filename": manifest.get("filename", "?")})
            log_event("backup", "restore OK via tmp_manifest",
                      level="info", restored=result.get("restored"),
                      age_h=age_h)
            return result
        errors.append(f"S2:tmp_manifest:{result.get('error')}")
    else:
        errors.append("S2:no_tmp_manifest_or_same_as_S1")

    # ── Strateji 3: _load_tracked() → kayıtlı file_id'ler ────────────────
    tracked = _load_tracked()
    if tracked:
        # En son yedek — sonda (append ile eklendi)
        for item in reversed(tracked):
            fid = item.get("file_id", "")
            if fid and fid not in (file_id_s1, manifest.get("file_id")):
                log_event("backup",
                          f"trying tracked backup file_id msg={item.get('message_id')}",
                          level="info")
                result = _download_and_extract(fid, overwrite=overwrite)
                if result.get("ok"):
                    result.update({"strategy": "tracked_list",
                                   "filename": item.get("filename", "?")})
                    log_event("backup", "restore OK via tracked_list",
                              level="info", restored=result.get("restored"))
                    return result
                errors.append(f"S3:tracked_fid:{result.get('error')}")
                break  # sadece en yeni birini dene
        else:
            errors.append("S3:tracked_items_have_no_file_id")
    else:
        errors.append("S3:no_tracked_items")

    full_err = " | ".join(errors)
    log_event("backup", f"tüm restore stratejileri başarısız: {full_err}",
              level="error")
    return {"ok": False, "error": full_err,
            "strategies_tried": 3}


# ── BİRLEŞİK PİNLİ MESAJ (PANO + ŞİFRELİ YEDEK) ────────────────────────────
def _load_unified_state() -> dict:
    try:
        import json
        if _UNIFIED_PIN_STATE_FILE.exists():
            d = json.loads(_UNIFIED_PIN_STATE_FILE.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}


def _save_unified_state(d: dict) -> None:
    try:
        import json
        _UNIFIED_PIN_STATE_FILE.write_text(
            json.dumps(d, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception as e:
        log_event("backup", f"unified state save failed: {e}", level="warn")


def _truncate_caption(text: str, limit: int = _TG_CAPTION_MAX) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _edit_caption(chat_id, message_id: int, caption: str) -> bool:
    """editMessageCaption — başarılı veya 'not modified' = True."""
    r = safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/editMessageCaption",
        data={"chat_id": str(chat_id), "message_id": str(message_id),
              "caption": caption, "parse_mode": "Markdown"},
        timeout=20, retries=2, backoff=0.5, metric_kind="tg_backup",
    )
    if r is None:
        return False
    try:
        j = r.json()
    except Exception:
        return False
    if j.get("ok"):
        return True
    desc = (j.get("description") or "").lower()
    if "not modified" in desc:
        return True
    return False


def _send_text_pinned(caption: str, prev_pin_id: int) -> dict:
    """Cache henüz boşsa: sadece text pano gönder + pinle (geçici).
    Yedek dolduğunda update_unified_panel bir sonraki çağrıda doc'a yükseltir.
    """
    r = safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/sendMessage",
        data={"chat_id": str(config.TG_CHAT_ID), "text": caption,
              "parse_mode": "Markdown",
              "disable_notification": "true",
              "disable_web_page_preview": "true"},
        timeout=20, retries=2, backoff=0.5, metric_kind="tg_backup",
    )
    if r is None:
        return {"ok": False, "error": "send_fail"}
    try:
        j = r.json()
    except Exception as e:
        return {"ok": False, "error": f"send_fail: bad json ({e})"}
    if not j.get("ok"):
        return {"ok": False, "error": f"tg_error: {j.get('description')}"}
    new_msg_id = int(j["result"]["message_id"])
    safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/unpinAllChatMessages",
        data={"chat_id": str(config.TG_CHAT_ID)},
        timeout=20, retries=2, backoff=0.5, metric_kind="tg_backup")
    safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/pinChatMessage",
        data={"chat_id": str(config.TG_CHAT_ID),
              "message_id": str(new_msg_id),
              "disable_notification": "true"},
        timeout=20, retries=2, backoff=0.5, metric_kind="tg_backup")
    # Pin'in oluşturduğu "X pinned a message" servis mesajını temizle
    time.sleep(1.5)
    for offset in range(1, 6):
        _delete_tg_message(config.TG_CHAT_ID, new_msg_id + offset)
    if prev_pin_id and prev_pin_id != new_msg_id:
        _delete_tg_message(config.TG_CHAT_ID, prev_pin_id)
        try:
            from . import tg_cleanup
            tg_cleanup.untrack(config.TG_CHAT_ID, prev_pin_id)
        except Exception:
            pass
    try:
        from . import tg_cleanup
        tg_cleanup.track(config.TG_CHAT_ID, new_msg_id, kind="panel_text")
    except Exception:
        pass
    return {"ok": True, "mode": "text_only", "message_id": new_msg_id}


# Birleşik state içinde son N pano mesaj ID'sini saklayan FIFO listesi.
# Cache/Render redeploy sonrası bile encrypted-backup içinden geri yüklenir,
# böylece eski `PREDATOR PANOSU` mesajları izlenmeye devam eder.
_PANEL_HISTORY_MAX = 50


def _push_panel_history(state: dict, chat_key: str, msg_id: int) -> None:
    """Yeni bir pano mesaj ID'sini state[chat_key]['panel_history'] listesine ekle (FIFO)."""
    try:
        if not msg_id:
            return
        entry = state.get(chat_key) or {}
        if not isinstance(entry, dict):
            entry = {}
        hist = entry.get("panel_history") or []
        if not isinstance(hist, list):
            hist = []
        # Tekilleştir + yeniyi sona ekle
        hist = [int(x) for x in hist if str(x).isdigit() and int(x) != int(msg_id)]
        hist.append(int(msg_id))
        if len(hist) > _PANEL_HISTORY_MAX:
            hist = hist[-_PANEL_HISTORY_MAX:]
        entry["panel_history"] = hist
        state[chat_key] = entry
    except Exception as e:
        log_event("backup", f"panel_history push failed: {e}", level="warn")


def get_panel_history(chat_id) -> list[int]:
    """Bilinen geçmiş pano mesaj ID'lerini döner (orphan temizliği için)."""
    try:
        st = _load_unified_state() or {}
        ent = st.get(str(chat_id)) or {}
        hist = ent.get("panel_history") or []
        return [int(x) for x in hist if str(x).isdigit()]
    except Exception:
        return []


def prune_panel_history(chat_id, keep_ids: Iterable[int]) -> None:
    """panel_history listesini sadece `keep_ids` içerenlere indirger."""
    try:
        st = _load_unified_state() or {}
        ck = str(chat_id)
        ent = st.get(ck) or {}
        if not isinstance(ent, dict):
            return
        keep_set = {int(x) for x in keep_ids if x}
        ent["panel_history"] = [int(x) for x in (ent.get("panel_history") or [])
                                if int(x) in keep_set]
        st[ck] = ent
        _save_unified_state(st)
    except Exception as e:
        log_event("backup", f"panel_history prune failed: {e}", level="warn")


def update_unified_panel(caption: str,
                         force_new_doc: bool = False,
                         extra_cleanup_ids: list[int] | None = None) -> dict:
    """Tek pinli mesajda portföy panosu (caption) + şifreli yedek (document).

    Davranış:
      - Eğer henüz pinli birleşik mesaj yoksa veya yedek aralığı (BACKUP_INTERVAL_SEC)
        dolmuşsa: yeni şifreli ZIP yükle, pinle, eski mesajı sil.
      - Aksi halde: sadece caption'ı düzenle (cheap, hızlı).

    `extra_cleanup_ids` — yeni doc başarıyla yüklendikten sonra grupta silinecek
    eski mesaj ID'leri (örn. eski text-only PANO mesajı).
    """
    global _LAST_BACKUP_TS
    if not config.TG_BOT_TOKEN or not config.TG_CHAT_ID:
        return {"ok": False, "error": "telegram_config_missing"}

    chat_key = str(config.TG_CHAT_ID)
    state = _load_unified_state()
    entry = state.get(chat_key) or {}
    if not isinstance(entry, dict):
        entry = {}
    pin_id = int(entry.get("message_id", 0) or 0)
    last_doc_ts = float(entry.get("last_doc_ts", 0) or 0)
    has_doc = bool(entry.get("filename"))
    now = time.time()
    caption = _truncate_caption(caption or "")

    # State boşsa (örn. Render redeploy sonrası yedek henüz restore edilmemiş)
    # Telegram'a sor: şu anda pinli olan mesaj kim? Eğer bizim chart_*.jpg
    # belgemizse onu "önceki pin" olarak kabul et ki yenisi yüklendiğinde
    # silinsin — böylece grupta duplicate birikmesin.
    if not pin_id:
        try:
            rg = safe_request(
                "GET",
                f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/getChat",
                params={"chat_id": str(config.TG_CHAT_ID)},
                timeout=15, retries=2, backoff=0.5, metric_kind="tg_backup",
            )
            if rg is not None:
                jg = rg.json()
                if jg.get("ok"):
                    pinned = (jg.get("result") or {}).get("pinned_message") or {}
                    pmid = int(pinned.get("message_id") or 0)
                    pdoc = pinned.get("document") or {}
                    pname = (pdoc.get("file_name") or "")
                    pcap = (pinned.get("caption") or pinned.get("text") or "")
                    looks_like_ours = (
                        pname.startswith("chart_") and pname.endswith(".jpg")
                    ) or ("PREDATOR" in pcap.upper())
                    if pmid and looks_like_ours:
                        pin_id = pmid
                        # Eğer document varsa "has_doc" davranışını da koru
                        if pdoc:
                            has_doc = True
                            last_doc_ts = float(pinned.get("date") or now)
        except Exception as e:
            log_event("backup", f"getChat fallback failed: {e}", level="warn")

    # Sadece caption düzenleme yeterli mi?
    need_new_doc = (
        force_new_doc
        or not pin_id
        or not has_doc
        or (now - last_doc_ts) >= BACKUP_INTERVAL_SEC
    )

    if not need_new_doc:
        if _edit_caption(config.TG_CHAT_ID, pin_id, caption):
            return {"ok": True, "mode": "edit_caption", "message_id": pin_id}
        # Mesaj silinmiş olabilir — yeniden gönder
        need_new_doc = True

    # ── GÜVENLİK KILIFI: Boş/taze cache'i Telegram'a ASLA yükleme ──────────
    # Render.com'da cache silinince daemon yeniden başlar; ilk tarama
    # tamamlanmadan tg_pin_loop buraya gelirse n_files > 0 olsa bile içerik
    # anlamsız olabilir. Bu noktada yeni mesaj göndermek + eski mesajı silmek
    # iyi yedeği KALICI OLARAK YOK EDER.
    #
    # Çözüm: Cache'te anlamlı veri yoksa yeni belge YÜKLEME.
    #   - Mevcut pin'i koru (silinmez)
    #   - Sadece caption'ı düzenle (pano görünür, yedek kaybolmaz)
    if not cache_has_real_data():
        log_event("backup",
                  "cache boş/küçük — yeni yedek yüklenmedi, mevcut pin korunuyor",
                  level="warn", pin_id=pin_id)
        if pin_id:
            _edit_caption(config.TG_CHAT_ID, pin_id, caption)
            return {"ok": True, "mode": "caption_preserved_empty_cache",
                    "message_id": pin_id,
                    "info": "Cache henüz dolu değil — Telegram yedeği korundu"}
        return {"ok": False, "error": "cache_empty_no_pin",
                "info": "Cache boş ve mevcut pin yok — yedek korunamadı"}

    # Yeni belge yükle
    payload, n_files, raw_size = _build_zip()
    if n_files == 0:
        # Build zip başarısız ama cache_has_real_data geçti — edge case.
        # Mevcut pin'i koru, sadece caption güncelle.
        log_event("backup", "zip empty after real_data check — preserving pin",
                  level="warn", pin_id=pin_id)
        if pin_id:
            _edit_caption(config.TG_CHAT_ID, pin_id, caption)
            return {"ok": True, "mode": "caption_preserved_empty_zip",
                    "message_id": pin_id}
        return {"ok": False, "error": "no_files"}

    enc_payload = _encrypt_blob(payload)
    jpg_payload = _wrap_in_jpg(enc_payload)
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(now))
    fname = f"chart_{ts}.jpg"

    r = safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/sendDocument",
        data={"chat_id": str(config.TG_CHAT_ID),
              "caption": caption,
              "parse_mode": "Markdown",
              "disable_notification": "true"},
        files={"document": (fname, jpg_payload, "image/jpeg")},
        timeout=120, retries=3, backoff=1.0, metric_kind="tg_backup",
    )
    if r is None:
        return {"ok": False, "error": "upload_fail: retries exhausted"}
    try:
        j = r.json()
    except Exception as e:
        return {"ok": False, "error": f"upload_fail: bad json ({e})"}
    if not j.get("ok"):
        return {"ok": False, "error": f"tg_error: {j.get('description')}"}

    new_msg_id = int(j["result"]["message_id"])

    # Pin yeni mesajı: önce unpin all, sonra pin
    safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/unpinAllChatMessages",
        data={"chat_id": str(config.TG_CHAT_ID)},
        timeout=20, retries=2, backoff=0.5, metric_kind="tg_backup")
    safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/pinChatMessage",
        data={"chat_id": str(config.TG_CHAT_ID),
              "message_id": str(new_msg_id),
              "disable_notification": "true"},
        timeout=20, retries=2, backoff=0.5, metric_kind="tg_backup")

    # PROAKTİF SERVİS-MESAJ TEMİZLİĞİ — Telegram `pinChatMessage` her seferinde
    # otomatik bir "X pinned a message" servis mesajı oluşturur (disable_notification
    # bunu engellemez, sadece bildirim sesi engeller). Bu servis mesajının ID'si
    # genellikle yeni dokümanın ID'sinden sonraki ilk 1-3 mesajdır. Listener'a
    # güvenmek yerine, anında birkaç ileri ID'yi silmeyi deneyelim. Var olmayan
    # veya başkasına ait ID'lere deleteMessage çağrıları sessizce başarısız olur
    # (zararsız). Servis mesajını hızla yakaladığımız için grupta birikmez.
    time.sleep(1.5)  # servis mesajının sunucuda oluşması için kısa bekleme
    for offset in range(1, 6):
        candidate_id = new_msg_id + offset
        # Bizim yeni doküman değilse silmeyi dene
        if candidate_id != new_msg_id:
            _delete_tg_message(config.TG_CHAT_ID, candidate_id)

    # Eski birleşik mesajı sil (varsa)
    if pin_id and pin_id != new_msg_id:
        _delete_tg_message(config.TG_CHAT_ID, pin_id)
        try:
            from . import tg_cleanup
            tg_cleanup.untrack(config.TG_CHAT_ID, pin_id)
        except Exception:
            pass

    # Bağımsız eski yedeklerin track listesini de boşalt (artık unified var).
    try:
        _prune_old_backups(keep_last=0)
    except Exception as e:
        log_exc("backup", "legacy prune failed", e)

    # tg_listener'ın bıraktığı eski text-only PANO mesajları gibi ek temizlik.
    if extra_cleanup_ids:
        for mid in extra_cleanup_ids:
            try:
                if int(mid) and int(mid) != new_msg_id:
                    _delete_tg_message(config.TG_CHAT_ID, int(mid))
            except Exception:
                pass

    # Yeni doc'u akıllı yöneticiye kaydet + opsiyonel sweep tetikle (v37.12)
    try:
        from . import tg_cleanup
        tg_cleanup.track(config.TG_CHAT_ID, new_msg_id, kind="panel_doc")
        # Yeni pin yerleşti, eski track edilen yedekleri tara
        tg_cleanup.sweep(config.TG_CHAT_ID)
    except Exception as e:
        log_event("backup", f"tg_cleanup track/sweep failed: {e}",
                  level="warn")

    _LAST_BACKUP_TS = now
    # Başarılı yedek → file_id'yi /tmp manifest'e kaydet (warm-restart fallback)
    new_doc_info = (j.get("result") or {}).get("document") or {}
    new_file_id  = new_doc_info.get("file_id", "")
    if new_file_id:
        _save_tmp_manifest(new_file_id, fname, new_msg_id)

    prev_hist = (state.get(chat_key) or {}).get("panel_history") or []
    state[chat_key] = {
        "message_id": new_msg_id,
        "ts": int(now),
        "last_doc_ts": int(now),
        "filename": fname,
        "file_id":   new_file_id,  # restore fallback
        "panel_history": prev_hist,
    }
    _push_panel_history(state, chat_key, new_msg_id)
    _save_unified_state(state)

    return {"ok": True, "mode": "new_doc", "message_id": new_msg_id,
            "files": n_files,
            "size_kb": len(jpg_payload) // 1024,
            "enc_kb": len(enc_payload) // 1024,
            "zip_kb": len(payload) // 1024, "raw_kb": raw_size // 1024,
            "encrypted": True, "wrapped_in_jpg": True, "filename": fname}
