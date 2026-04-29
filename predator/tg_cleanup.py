"""Telegram mesaj akıllı yöneticisi (v37.12).

Bot'un gönderdiği TÜM mesajları izler ve aktif pinli mesaj/panel haricinde
eski yedekleri, panoları, document'leri otomatik siler. Bu modül olmadan
önce bot mesajları grupta birikiyordu çünkü:
  • Track dosyası (`predator_backup_msgs.json`) silinince eski yedek ID'leri
    kayboluyordu.
  • Yedek aralığı dışında atılan diğer bot mesajlarının (eski PANO, eski
    chart_*.jpg) ID'leri hiç kaydedilmiyordu.
  • `pinChatMessage` servis mesajları (ilk +1..+5 ID) bazen Telegram'da
    daha geç oluşuyor, anlık silme penceresini kaçırıyordu.

Yeni davranış:
  • `track(chat_id, msg_id, kind, ttl?)` — her bot mesaj atışında çağırılır.
  • `sweep(chat_id)` — track tablosunu süpürür: TTL aşımı + aktif olmayan
    yedek/pano/chart_* mesajlarını siler. `tg_cleanup_loop` her 10dk çağırır.
  • `reconcile(chat_id)` — getChat ile şu anki pin'i öğrenip state ile
    uyumlu hale getirir, eski sahipsiz pin'leri tespit eder.
  • `nuke_range(chat_id, start_id, end_id, kinds=None)` — agresif
    temizlik: track dosyası kaybolmuş eski mesajları aralık tarayarak
    silmeye çalışır (var olmayan/sahipsiz ID'lere DELETE sessizce başarısız).

Kayıt formatı (`predator_tg_msg_track.json`):
  [
    {"chat_id": "-100...", "msg_id": 2195, "kind": "backup_doc",
     "ts": 1777458848, "ttl": 0},
    ...
  ]

`kind` sınıfları:
  • "backup_doc"  — chart_*.jpg yedek dokümanı (aktif pin = koru)
  • "panel_text"  — birleşik PANO text mesajı (aktif pin = koru)
  • "panel_doc"   — birleşik PANO doc mesajı (aktif pin = koru)
  • "report"      — kullanıcı sorgusuna analiz cevabı (TTL ile silinir)
  • "warn"        — moderasyon uyarısı (TTL ile silinir)
  • "service"     — bot tarafından gönderilen başka servis mesajı
  • "unknown"     — sınıflandırılamadı, varsayılan davranış
"""
from __future__ import annotations

import json
import threading
import time
from typing import Iterable

from . import config
from .http_utils import safe_request
from .observability import log_event

_TRACK_FILE = config.CACHE_DIR / "predator_tg_msg_track.json"
_TRACK_LOCK = threading.Lock()

# Aktif olmadığı kabul edildikten sonra silinmesi GEREKEN tipler:
_PROTECTED_KINDS = {"backup_doc", "panel_text", "panel_doc"}
# Bunlar yaş + aktif değilse silinir
_DEFAULT_TTL = {
    "report": 30 * 60,          # 30 dakika (analiz cevapları — eski hali 12h)
    "warn": 60 * 60,            # 1 saat (moderasyon uyarıları)
    "service": 5 * 60,          # 5 dakika (servis mesajları)
    "unknown": 24 * 3600,       # 1 gün
    "backup_doc": 0,            # 0 = aktif pin değilse her zaman sil
    "panel_text": 0,
    "panel_doc": 0,
    # Engine alertleri (AI AL/SAT, rotasyon, vb.) — kullanıcı görsün diye
    # 15 dk yaşa, sonra otomatik silinsin. Böylece grupta sadece pinli
    # PREDATOR PANOSU kalır.
    "bot_msg": 15 * 60,
}
# Track tablosunda en fazla saklanacak kayıt sayısı (FIFO)
_MAX_TRACK = 5000


def _load() -> list[dict]:
    try:
        if not _TRACK_FILE.exists():
            return []
        d = json.loads(_TRACK_FILE.read_text(encoding="utf-8"))
        if isinstance(d, list):
            return [x for x in d if isinstance(x, dict)
                    and x.get("msg_id") and x.get("chat_id")]
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return []


def _save(items: list[dict]) -> None:
    try:
        # FIFO trim
        if len(items) > _MAX_TRACK:
            items = items[-_MAX_TRACK:]
        tmp = _TRACK_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(_TRACK_FILE)
    except OSError as e:
        log_event("tg_cleanup", f"track save failed: {e}", level="warn")


def track(chat_id, msg_id: int, kind: str = "unknown",
          ttl_sec: int | None = None) -> None:
    """Bir bot mesaj ID'sini takip listesine ekle."""
    if not msg_id or not chat_id:
        return
    try:
        msg_id_i = int(msg_id)
    except (TypeError, ValueError):
        return
    if msg_id_i <= 0:
        return
    ttl = _DEFAULT_TTL.get(kind, _DEFAULT_TTL["unknown"]) \
        if ttl_sec is None else int(ttl_sec)
    rec = {
        "chat_id": str(chat_id),
        "msg_id": msg_id_i,
        "kind": kind,
        "ts": int(time.time()),
        "ttl": ttl,
    }
    with _TRACK_LOCK:
        items = _load()
        # Aynı msg_id varsa güncelle
        items = [x for x in items
                 if not (str(x.get("chat_id")) == rec["chat_id"]
                         and int(x.get("msg_id") or 0) == msg_id_i)]
        items.append(rec)
        _save(items)


def untrack(chat_id, msg_id: int) -> None:
    """Bir mesaj ID'sini takip listesinden çıkar."""
    try:
        msg_id_i = int(msg_id)
    except (TypeError, ValueError):
        return
    if not msg_id_i:
        return
    with _TRACK_LOCK:
        items = _load()
        n = len(items)
        items = [x for x in items
                 if not (str(x.get("chat_id")) == str(chat_id)
                         and int(x.get("msg_id") or 0) == msg_id_i)]
        if len(items) != n:
            _save(items)


def _delete_msg(chat_id, msg_id: int) -> bool:
    if not msg_id or not config.TG_BOT_TOKEN:
        return False
    r = safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/deleteMessage",
        data={"chat_id": str(chat_id), "message_id": str(msg_id)},
        timeout=15, retries=2, backoff=0.5, metric_kind="tg_cleanup",
    )
    if r is None:
        return False
    try:
        return bool(r.json().get("ok"))
    except (ValueError, AttributeError):
        return False


def _bot_owns_message(chat_id, msg_id: int) -> int:
    """`editMessageReplyMarkup` probe — bu mesaj bot tarafından mı atılmış?

    Dönüş:
      1  → mesaj bota ait ve düzenlenebilir (silinebilir).
      0  → mesaj YOK (silinmiş/erişim yok).
     -1  → mesaj başkasının VE/VEYA editlenemez yaşta.

    Probe `reply_markup` olarak boş `inline_keyboard` gönderir; mesaj bota
    aitse "not modified" döner, değilse "message can't be edited" /
    "MESSAGE_AUTHOR_REQUIRED" gibi hata döner. Probe başarılı olursa sonradan
    `_delete_msg` ile silinir. Düzenleme başarısız olsa bile mesaj silinmemiş
    olur — sadece "edited" işareti görünür ki onu zaten siliyoruz.
    """
    if not msg_id or not config.TG_BOT_TOKEN:
        return 0
    r = safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/editMessageReplyMarkup",
        data={
            "chat_id": str(chat_id),
            "message_id": str(msg_id),
            "reply_markup": '{"inline_keyboard":[]}',
        },
        timeout=10, retries=1, backoff=0.3, metric_kind="tg_cleanup",
    )
    if r is None:
        return -1
    try:
        j = r.json()
    except (ValueError, AttributeError):
        return -1
    if j.get("ok"):
        return 1
    desc = (j.get("description") or "").lower()
    if "not modified" in desc:
        return 1
    if "message to edit not found" in desc or "message_id_invalid" in desc \
            or "not found" in desc:
        return 0
    # "message can't be edited", "MESSAGE_AUTHOR_REQUIRED", "chat not found",
    # "bot was kicked", vb. → bota ait DEĞİL veya yetki yok.
    return -1


def nuke_my_messages(chat_id, scan_back: int = 500,
                     max_deletes: int = 500,
                     pause_sec: float = 0.05) -> dict:
    """Aktif pinin gerisindeki ID aralığında bota ait TÜM mesajları sil.

    Bot mesajlarının ID'sini takipte tutmaya gerek kalmaz — Telegram'a tek tek
    `editMessageReplyMarkup` probu atıp sahipliği doğrulayarak yalnızca botun
    kendi eski mesajlarını siler. Kullanıcı mesajlarına dokunmaz.

    Akış:
      1) Aktif pin = max(state_pin, telegram_pin).
      2) `start = active_pin - 1`, `end = max(1, active_pin - scan_back)`.
      3) Her ID için: probe → bota aitse → deleteMessage.
      4) Pin'in KENDİSİ daima atlanır.
      5) `max_deletes` veya aralık sonu — durdur.
    """
    if not config.TG_BOT_TOKEN or not chat_id:
        return {"ok": False, "error": "tg_config_missing"}

    active_pin = max(_active_pin_id(chat_id), _telegram_pin_id(chat_id))
    if active_pin <= 1:
        return {"ok": False, "error": "active_pin_unknown"}

    start = active_pin - 1
    end = max(1, active_pin - max(1, int(scan_back)))
    deleted = 0
    probed = 0
    not_found = 0
    not_ours = 0
    skipped_pin = 0
    err_count = 0

    for mid in range(start, end - 1, -1):
        if mid == active_pin:
            skipped_pin += 1
            continue
        if deleted >= max_deletes:
            break
        try:
            owns = _bot_owns_message(chat_id, mid)
            probed += 1
            if owns == 1:
                if _delete_msg(chat_id, mid):
                    deleted += 1
                    untrack(chat_id, mid)
                else:
                    err_count += 1
            elif owns == 0:
                not_found += 1
            else:
                not_ours += 1
        except Exception:
            err_count += 1
        if pause_sec > 0:
            time.sleep(pause_sec)

    log_event("tg_cleanup",
              f"nuke_my_messages: scanned={probed} deleted={deleted} "
              f"not_ours={not_ours} not_found={not_found}",
              level="info", deleted=deleted, scanned=probed,
              not_ours=not_ours, not_found=not_found,
              skipped_pin=skipped_pin, active_pin=active_pin)

    return {
        "ok": True,
        "active_pin": active_pin,
        "range": [end, start],
        "scanned": probed,
        "deleted": deleted,
        "not_ours": not_ours,
        "not_found": not_found,
        "skipped_pin": skipped_pin,
        "errors": err_count,
    }


def _active_pin_id(chat_id) -> int:
    """Birleşik pin state'inden aktif pinli mesaj ID'sini döner."""
    try:
        from .cache_backup import _load_unified_state
        st = _load_unified_state() or {}
        ent = st.get(str(chat_id)) or {}
        return int(ent.get("message_id") or 0)
    except Exception:
        return 0


def _telegram_pin_id(chat_id) -> int:
    """Telegram'da şu anda gerçekten pinli olan mesaj ID'sini sor."""
    if not config.TG_BOT_TOKEN:
        return 0
    r = safe_request(
        "GET",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/getChat",
        params={"chat_id": str(chat_id)},
        timeout=15, retries=2, backoff=0.5, metric_kind="tg_cleanup",
    )
    if r is None:
        return 0
    try:
        j = r.json()
        if not j.get("ok"):
            return 0
        pinned = (j.get("result") or {}).get("pinned_message") or {}
        return int(pinned.get("message_id") or 0)
    except (ValueError, AttributeError, TypeError):
        return 0


def reconcile(chat_id) -> dict:
    """getChat ile şu anki pinli mesajı öğren, state ile karşılaştır.

    Eğer Telegram'daki pin bizim state'imizden farklıysa:
      • Eski state pin'i artık geçerli değil → track'ten 'panel_*' korumasını
        kaldırmak için kayıtları normal hale getirmemiz gerekmez (sweep
        zaten yaş ve aktiflik kontrolü yapacak).
      • Bilgi log'la, sweep döngüsü uyumlu çalışsın.
    """
    state_pin = _active_pin_id(chat_id)
    tg_pin = _telegram_pin_id(chat_id)
    return {"state_pin": state_pin, "telegram_pin": tg_pin,
            "in_sync": state_pin == tg_pin and state_pin > 0}


def sweep(chat_id, dry: bool = False) -> dict:
    """Track tablosunu süpür: TTL aşımı + aktif olmayan koruma tipleri.

    Akış:
      1) Aktif pin ID'sini öğren (state + Telegram cross-check).
      2) Her track kaydı için:
         - msg_id == aktif pin → KORU.
         - kind PROTECTED ve TTL=0 → aktif değilse SİL.
         - TTL > 0 ve yaş > TTL → SİL.
         - Aksi halde tut.
      3) `panel_history` listesindeki orphan mesajları da sil (track dosyası
         kaybolmuşsa bile encrypted-backup içinden geri gelir).
      4) Silinen + tutulan kayıtları kaydet.
    """
    state_pin = _active_pin_id(chat_id)
    tg_pin = _telegram_pin_id(chat_id)
    # Aktif pin: ikisinden hangisi büyükse onu koru (Telegram pin daha güncel
    # olabilir; ya da state Render redeploy sonrası boş)
    active_pin = max(state_pin, tg_pin)

    now = time.time()
    deleted: list[dict] = []
    kept: list[dict] = []
    deleted_ids: set[int] = set()

    with _TRACK_LOCK:
        items = _load()

    for rec in items:
        try:
            cid = str(rec.get("chat_id"))
            mid = int(rec.get("msg_id") or 0)
        except (TypeError, ValueError):
            continue
        if cid != str(chat_id) or mid <= 0:
            kept.append(rec)
            continue
        kind = str(rec.get("kind") or "unknown")
        ts = float(rec.get("ts") or 0)
        ttl = int(rec.get("ttl") or 0)
        age = now - ts if ts else 0

        # Aktif pin → koru
        if mid == active_pin:
            kept.append(rec)
            continue

        # Korumalı tipler (yedek/panel) — aktif pin değilse sil
        if kind in _PROTECTED_KINDS:
            if dry:
                deleted.append({**rec, "reason": "stale_protected", "age": int(age)})
                continue
            if _delete_msg(chat_id, mid):
                deleted.append({**rec, "reason": "stale_protected", "age": int(age)})
                deleted_ids.add(mid)
            continue

        # TTL>0 mesajlar — yaş aşımı varsa sil
        if ttl > 0 and age > ttl:
            if dry:
                deleted.append({**rec, "reason": "ttl_expired", "age": int(age)})
                continue
            if _delete_msg(chat_id, mid):
                deleted.append({**rec, "reason": "ttl_expired", "age": int(age)})
                deleted_ids.add(mid)
            continue

        kept.append(rec)

    if not dry and deleted:
        with _TRACK_LOCK:
            _save(kept)

    # ── EK: panel_history orphan temizliği ──────────────────────────────────
    history_deleted = 0
    history_kept_ids: list[int] = []
    try:
        from .cache_backup import get_panel_history, prune_panel_history
        hist = get_panel_history(chat_id)
        for mid in hist:
            if not mid or mid == active_pin:
                if mid:
                    history_kept_ids.append(mid)
                continue
            if dry:
                deleted.append({"chat_id": str(chat_id), "msg_id": mid,
                                "kind": "panel_history",
                                "reason": "orphan_panel"})
                continue
            # Tekrar silmeyi denemek zararsız (Telegram NOT FOUND döner, ok=false).
            ok = (mid in deleted_ids) or _delete_msg(chat_id, mid)
            if ok:
                history_deleted += 1
                deleted.append({"chat_id": str(chat_id), "msg_id": mid,
                                "kind": "panel_history",
                                "reason": "orphan_panel"})
                deleted_ids.add(mid)
        if not dry:
            # Sadece aktif pin (varsa) listede kalsın
            keep = {active_pin} if active_pin else set()
            prune_panel_history(chat_id, keep)
    except Exception as e:
        log_event("tg_cleanup", f"panel_history sweep failed: {e}",
                  level="warn")

    if not dry and (deleted or history_deleted):
        log_event("tg_cleanup",
                  f"sweep deleted {len(deleted)} message(s) "
                  f"(history={history_deleted})",
                  level="info", deleted=len(deleted), kept=len(kept),
                  active_pin=active_pin, history_deleted=history_deleted)

    return {
        "ok": True,
        "dry": dry,
        "active_pin": active_pin,
        "state_pin": state_pin,
        "telegram_pin": tg_pin,
        "tracked": len(items),
        "deleted": len(deleted),
        "kept": len(kept),
        "history_deleted": history_deleted,
        "deleted_items": deleted[:50],   # rapor için ilk 50
    }


def nuke_range(chat_id, start_id: int, end_id: int,
               step: int = 1, max_calls: int = 500) -> dict:
    """Agresif temizlik — start..end aralığındaki ID'lere deleteMessage at.

    Telegram başkasına ait / silinmiş / yetkisiz ID'lere sessizce başarısız
    olur (zararsız). Track dosyası kaybolduğu için bilinmeyen eski bot
    mesajlarını süpürmek için kullanılır. Aktif pin atlanır.

    `max_calls` güvenlik tavanı (varsayılan 500 → ~500 deleteMessage çağrısı).
    """
    if start_id < 1 or end_id < start_id:
        return {"ok": False, "error": "invalid_range"}
    active_pin = max(_active_pin_id(chat_id), _telegram_pin_id(chat_id))
    deleted = 0
    skipped_pin = 0
    calls = 0
    for mid in range(int(start_id), int(end_id) + 1, max(1, int(step))):
        if calls >= max_calls:
            break
        if mid == active_pin:
            skipped_pin += 1
            continue
        if _delete_msg(chat_id, mid):
            deleted += 1
            untrack(chat_id, mid)
        calls += 1
    log_event("tg_cleanup", f"nuke_range {start_id}-{end_id} → del={deleted}",
              level="info", deleted=deleted, calls=calls,
              skipped_pin=skipped_pin)
    return {"ok": True, "deleted": deleted, "calls": calls,
            "skipped_pin": skipped_pin, "range": [start_id, end_id]}


def status(chat_id=None) -> dict:
    """Track durumu — UI/teşhis."""
    with _TRACK_LOCK:
        items = _load()
    by_kind: dict[str, int] = {}
    for r in items:
        k = str(r.get("kind") or "unknown")
        by_kind[k] = by_kind.get(k, 0) + 1
    out = {
        "trackedTotal": len(items),
        "byKind": by_kind,
        "trackFile": str(_TRACK_FILE),
        "fileExists": _TRACK_FILE.exists(),
    }
    if chat_id is not None:
        out["statePin"] = _active_pin_id(chat_id)
        out["telegramPin"] = _telegram_pin_id(chat_id)
    return out


def cleanup_loop(interval_sec: int = 600) -> None:
    """Daemon thread: her `interval_sec` saniyede bir sweep.

    Başlangıçta hemen bir sweep + agresif `nuke_my_messages` çalışır:
      • Sweep — track tablosu + panel_history orphan'larını siler.
      • nuke_my_messages — aktif pinin gerisindeki 500 ID aralığını probe
        ederek (editMessageReplyMarkup) bota ait TÜM eski mesajları yakalar
        ve siler. Kullanıcı mesajları dokunulmadan kalır.
    Böylece Render redeploy sonrası bile grupta sadece güncel pinli
    PREDATOR PANOSU + son şifreli yedek doc kalır.
    """
    if not config.TG_BOT_TOKEN or not config.TG_CHAT_ID:
        return
    print(f"[tg_cleanup] loop started (interval={interval_sec}s)", flush=True)

    # 1) İlk sweep — track + panel_history orphan'ları
    try:
        r0 = sweep(config.TG_CHAT_ID)
        if r0.get("deleted") or r0.get("history_deleted"):
            print(f"[tg_cleanup] startup sweep: deleted={r0.get('deleted')} "
                  f"history_deleted={r0.get('history_deleted')} "
                  f"active_pin={r0.get('active_pin')}", flush=True)
    except Exception as e:
        log_event("tg_cleanup", f"startup sweep error: {e}", level="warn")

    # 2) İlk agresif geriye-tarama — bota ait tüm eski mesajları sil
    try:
        rN = nuke_my_messages(config.TG_CHAT_ID, scan_back=500,
                              max_deletes=500, pause_sec=0.05)
        if rN.get("ok") and (rN.get("deleted") or rN.get("scanned")):
            print(f"[tg_cleanup] startup nuke: scanned={rN.get('scanned')} "
                  f"deleted={rN.get('deleted')} "
                  f"not_ours={rN.get('not_ours')} "
                  f"not_found={rN.get('not_found')} "
                  f"active_pin={rN.get('active_pin')}", flush=True)
    except Exception as e:
        log_event("tg_cleanup", f"startup nuke error: {e}", level="warn")

    while True:
        try:
            time.sleep(max(60, int(interval_sec)))
            sweep(config.TG_CHAT_ID)
            # Periyodik daha küçük tarama: aktif pinin gerisindeki 100 ID
            # aralığını her sweep'ta tara → araya sıkışmış unutulan bot
            # mesajlarını yakala (örn. tracking yapılmamış servis mesajları).
            try:
                nuke_my_messages(config.TG_CHAT_ID, scan_back=100,
                                 max_deletes=100, pause_sec=0.05)
            except Exception as e:
                log_event("tg_cleanup", f"periodic nuke err: {e}",
                          level="warn")
        except Exception as e:
            log_event("tg_cleanup", f"loop error: {e}", level="warn")
            time.sleep(max(60, int(interval_sec)))
