"""Telegram entegrasyonu — günlük özet + komut dinleyici + grup yöneticisi.

Üç bağımsız thread sağlar:
  * `daily_summary_loop()`    — hafta içi 09:30 TR'de top picks + portföy özetini gönderir.
  * `tg_listener_loop()`      — getUpdates long-polling, komutlar + moderasyon.
  * `tg_pin_loop()`           — pinned pozisyon panosunu 60sn'de bir tazeler.
  * `tg_deletion_worker()`    — zamanlanmış mesaj silmeleri (bot cevapları 60sn sonra).
"""
from __future__ import annotations
import json
import re
import threading
import time
import requests
from pathlib import Path

from . import config
from .utils import load_json, save_json, now_tr, tg_footer
from .portfolio import oto_load

_TG_API = f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}"
_DAILY_STATE_FILE = Path(config.CACHE_DIR) / "predator_daily_summary_state.json"
_TG_OFFSET_FILE = Path(config.CACHE_DIR) / "predator_tg_offset.json"
_PIN_STATE_FILE = Path(config.CACHE_DIR) / "predator_tg_pin_state.json"

_DAILY_HOUR = 9
_DAILY_MIN = 30
_CODE_RE = re.compile(r"^[A-ZÇĞİÖŞÜ0-9]{2,8}$")
_AUTO_DELETE_SEC = 60          # Bot cevapları kaç sn sonra silinsin
_USER_CMD_DELETE = True        # Kullanıcının "T XXX" mesajını da sil
_PIN_REFRESH_SEC = 60          # Pano kaç sn'de bir güncellensin

# ── PROFESYONEL GRUP YÖNETİMİ AYARLARI ─────────────────────────────────────
_NEW_MEMBER_GRACE_HOURS = 24   # Yeni üye için sıkı kurallar süresi
_FLOOD_WINDOW_SEC = 10         # Flood penceresi
_FLOOD_THRESHOLD = 6           # Bu pencerede bu kadar mesaj → flood
_FLOOD_MUTE_SEC = 300          # Flood cezası 5 dk sustur
_STRIKE_TTL_HOURS = 24         # Strike sayacı 24 saatte sıfırlanır
_ADMIN_REFRESH_SEC = 600       # Admin listesi 10 dk'da bir yenilensin
_WELCOME_DELETE_SEC = 120      # Karşılama mesajı 2 dk sonra silinsin
_SERVICE_MSG_DELETE = True     # join/leave/photo değişikliği mesajları silinsin

# Strike eşikleri (24sa içindeki kümülatif strike sayısı):
#   1 → uyarı + sil (mevcut davranış)
#   2 → 1 saat sustur
#   3 → 24 saat sustur
#   4+ → at (kick) — ban değil, isterse geri katılabilir
_MUTE_1H_SEC = 3600
_MUTE_24H_SEC = 86400

# Cache dosyaları
_STRIKES_FILE = Path(config.CACHE_DIR) / "predator_tg_strikes.json"
_NEW_MEMBERS_FILE = Path(config.CACHE_DIR) / "predator_tg_new_members.json"
_MOD_STATS_FILE = Path(config.CACHE_DIR) / "predator_tg_mod_stats.json"

# In-memory: kullanıcı başına son N mesaj zamanı (flood tespiti için)
_RECENT_MSGS: dict[int, list[float]] = {}
_RECENT_MSGS_LOCK = threading.Lock()

# In-memory: T komutu rate limiting (kullanıcı başına 60sn içinde max 3 sorgu)
_T_CMD_RATE: dict[int, list[float]] = {}
_T_CMD_LOCK = threading.Lock()
_T_CMD_WINDOW = 60      # saniye
_T_CMD_MAX = 3          # pencere içinde max sorgu

# In-memory: admin önbelleği (chat_id → {ids: set, fetched_at: float})
_ADMIN_CACHE: dict = {}
_ADMIN_LOCK = threading.Lock()

# ── MODERASYON KURALLARI ────────────────────────────────────────────────────
# URL/link tespiti
_URL_RE = re.compile(
    r"(?:https?://|www\.|t\.me/|telegram\.me/|bit\.ly/|tinyurl\.com/|goo\.gl/|"
    r"\b\w+\.(?:com|net|org|io|co|tv|me|ru|info|biz|xyz|club|site|online|shop|app)\b)",
    re.IGNORECASE)
# @kullanıcı_adı (başka kanalları/botları tag'leme)
_MENTION_BOT_RE = re.compile(r"@\w{4,}", re.IGNORECASE)
# Yaygın spam/reklam, bahis, kripto ve dolandırıcılık ipuçları
_AD_KEYWORDS = [
    # Senin listen
    "kazanç garantili", "garantili kazanç", "vip kanal", "vip grup", "premium grup",
    "ücretsiz sinyal", "ücretsiz kanal", "kazandırıyoruz", "promosyon kodu",
    "iletişim için dm", "dm at", "özel mesaj at", "whatsapp grub",
    "casino", "bahis", "deneme bonusu", "1xbet", "betturkey", "mostbet",
    "binance ref", "kripto sinyal", "coin sinyal", "telegram premium",
    "follow back", "takip iade", "referans kodu",
    
    # Kripto / Finans Spamleri
    "pump", "dump", "airdrop", "pancakeswap", "metamask", "trust wallet",
    "ön satış", "presale", "100x", "uçacak", "fırsatı kaçırma", "kaldıraçlı işlem",
    "forex", "yatırım tavsiyesi", "para kazanma", "kripto para", "altcoin",
    
    # Bahis / Kumar / İllegal Platform Spamleri
    "slot", "rulet", "iddaa", "şikeli maç", "banko maç", "şike", "fix maç",
    "kupon", "çevrimsiz bonus", "hoşgeldin bonusu", "bedava dönüş", "freespin", 
    "kaçak bahis", "illegal bahis", "sweet bonanza", "gates of olympus", "aviator",
    "casibom", "matbet", "grandpashabet", "holiganbet", "meritroyal", "iddaa tahmin",
    
    # Sosyal Medya / Etkileşim Kasmaya Çalışan Spamler
    "karşılıklı takip", "gt", "takibe takip", "profilime bak", "link bio", 
    "linkte", "abone ol", "beğeni hilesi", "takipçi hilesi", "ucuz takipçi", 
    "smm panel", "izlenme hilesi", "şifresiz beğeni", "profilime tıkla", "rt yap",
    
    # Dolandırıcılık / Sahte Kampanya Spamleri
    "evde ek iş", "paketleme işi", "kolay para", "linke tıkla", "şifresiz", 
    "hediye", "çekiliş", "kazandınız", "iphone kazan", "ücretsiz para", 
    "sadece bugün", "sınırlı kontenjan", "hemen katıl", "detaylar profilde",
    "kredi kartsız", "burs veriyoruz", "yardım başvurusu", "e-devlet onaylı"
]

# Küfür listesi (Genişletilmiş Regex varyasyonları ile)
_PROFANITY = [
    # --- Temel ve En Yaygın Kısaltmalar ---
    r"\ba[mqk]+\b",                           # amk, aq, amq
    r"\bm[qk]+\b",                            # mk, mq
    r"\bo[çc]\b",                             # oç, oc
    r"\bo[rş]osp[uü]\s?[çc]o[cç]u[gğ]u?\b",   # orospu çocuğu
    
    # --- Ana Küfür Kökleri ve Çekimleri ---
    r"\bama?[ck][ıi]?[kğ]?\b",                # am, amcık, amcığı
    r"\bam[ıi]na\s?k[oy]y?a?y?[ıi]m\b",       # amına koyayım, amına koyim
    r"\bam[ıi]na\s?s[oö]kay[ıi]m\b",          # amına sokayım
    r"\bs[iı]k[iı]?m?\b",                     # sik, sikim
    r"\bs[iı]k[iı][şs]\b",                    # sikiş
    r"\bs[iı]k[iı][kğ]\b",                    # sikik
    r"\bs[iı]kmek\b",                         # sikmek
    r"\bs[iı]k[e]r[iı]m\b",                   # sikerim
    r"\bs[iı]kt?[iı]r\b",                     # siktir
    r"\bs[iı]ken\b",                          # siken
    r"\bya[r]+a[gğk]\b",                      # yarrak, yarak
    r"\bdalya[r]+a[kğ]\b",                    # dalyarak
    r"\bg[oö]t[üu]n?\b",                      # götü, götün
    r"\bg[oö]t\s?veren\b",                    # göt veren
    r"\bs[ıi]ç(?:ay[ıi]m|t[ıi]m|s[ıi]n)\b",   # sıçayım, sıçtım, sıçsın
    
    # --- Hakaret ve Aşağılayıcı Kelimeler ---
    r"\bo[rş]p[uü]\b",                        # orpu
    r"\bo[rş]osp[uü]\b",                      # orospu
    r"\bp[iı][çc]\b",                         # piç, pic
    r"\bi[b|p]ne\b",                          # ibne, ipne
    r"\bkahpe\b",                             # kahpe
    r"\bf[aâ]hi[şs]e\b",                      # fahişe
    r"\byav[şs]a[kğ]\b",                      # yavşak, yavsak
    r"\bpu[şs]t\b",                           # puşt, pust
    r"\bpezeven[kğ]\b",                       # pezevenk
    r"\bpzvn[kğ]\b",                          # pzvnk
    r"\bgodo[şs]\b",                          # godoş
    r"\bkalta[kğ]\b",                         # kaltak
    r"\bs[üu]rt[üu][kğ]\b",                   # sürtük
    r"\bd[üu]mb[üu]k\b",                      # dümbük
    
    # --- Ailevi ve Yöresel Kalıplar ---
    r"\bmal\s?s[ıi]kt[ıi]r\b",                # mal siktir
    r"\bbinmek\b.*\banan?[ıi]\b",             # binmek ... ananı
    r"\banan[ıi]?n\s?a[mvğk]\b",              # ananın amı, ananın amk
    r"\bana[s]?[ıi]n[ıi]\b.*\bs[iı]k\b",      # anasını ... sik
    r"\bavradın[ıi]\b",                       # avradını
    r"\bbac[ıi]n[ıi]\b",                      # bacını
    r"\bs[üu]lalen[iı]\b"                     # sülaleni
]
_PROFANITY_RE = re.compile("|".join(_PROFANITY), re.IGNORECASE)


# ── BOT KİMLİĞİ (kendi mesajlarını / komutlarını ayırmak için) ──────────────
_BOT_INFO_CACHE: dict = {"id": None, "username": None, "fetched_at": 0}


def _get_bot_info() -> dict:
    if _BOT_INFO_CACHE["id"] and (time.time() - _BOT_INFO_CACHE["fetched_at"] < 3600):
        return _BOT_INFO_CACHE
    try:
        r = requests.get(f"{_TG_API}/getMe", timeout=10, verify=True)
        if r.ok:
            d = r.json().get("result") or {}
            _BOT_INFO_CACHE["id"] = d.get("id")
            _BOT_INFO_CACHE["username"] = d.get("username")
            _BOT_INFO_CACHE["fetched_at"] = time.time()
    except Exception:
        pass
    return _BOT_INFO_CACHE


# ── Düşük seviyeli gönderme/silme/pinleme ──────────────────────────────────
def _tg_send_raw(chat_id: str | int, text: str,
                 reply_to: int | None = None,
                 kind: str = "report") -> int | None:
    """Doğrudan Telegram'a gönder. Mesaj başarılıysa message_id döner, değilse None.

    `kind` — yeni akıllı yöneticiye verilen tip ("report", "warn", "service").
    Tüm bot mesajları otomatik olarak track edilir, böylece TTL veya pin
    geçişinde sweep loop'u eski mesajları temizleyebilir.
    """
    if not text:
        return None
    data = {"chat_id": str(chat_id), "text": text, "parse_mode": "Markdown",
            "disable_web_page_preview": "true"}
    if reply_to:
        data["reply_to_message_id"] = str(reply_to)
    try:
        r = requests.post(f"{_TG_API}/sendMessage", data=data, timeout=15, verify=True)
        if r.ok:
            j = r.json()
            if j.get("ok"):
                mid = (j.get("result") or {}).get("message_id")
                if mid:
                    try:
                        from . import tg_cleanup
                        tg_cleanup.track(chat_id, int(mid), kind=kind)
                    except Exception:
                        pass
                return mid
    except requests.RequestException:
        pass
    return None


def _tg_delete(chat_id: str | int, message_id: int) -> bool:
    if not message_id:
        return False
    try:
        r = requests.post(f"{_TG_API}/deleteMessage",
                          data={"chat_id": str(chat_id), "message_id": str(message_id)},
                          timeout=10, verify=True)
        return r.ok and '"ok":true' in r.text
    except requests.RequestException:
        return False


def _tg_edit(chat_id: str | int, message_id: int, text: str) -> bool:
    try:
        r = requests.post(
            f"{_TG_API}/editMessageText",
            data={"chat_id": str(chat_id), "message_id": str(message_id),
                  "text": text, "parse_mode": "Markdown",
                  "disable_web_page_preview": "true"},
            timeout=10, verify=True)
        return r.ok and '"ok":true' in r.text
    except requests.RequestException:
        return False


def _tg_pin(chat_id: str | int, message_id: int,
            disable_notification: bool = True) -> bool:
    try:
        r = requests.post(
            f"{_TG_API}/pinChatMessage",
            data={"chat_id": str(chat_id), "message_id": str(message_id),
                  "disable_notification": "true" if disable_notification else "false"},
            timeout=10, verify=True)
        return r.ok and '"ok":true' in r.text
    except requests.RequestException:
        return False


def _tg_unpin(chat_id: str | int, message_id: int) -> bool:
    try:
        r = requests.post(
            f"{_TG_API}/unpinChatMessage",
            data={"chat_id": str(chat_id), "message_id": str(message_id)},
            timeout=10, verify=True)
        return r.ok
    except requests.RequestException:
        return False


def _tg_restrict(chat_id: str | int, user_id: int, mute_seconds: int) -> bool:
    """Kullanıcıyı belirtilen süre kadar sustur (yazma izni kapat)."""
    if not user_id or mute_seconds <= 0:
        return False
    until = int(time.time()) + int(mute_seconds)
    perms = json.dumps({
        "can_send_messages": False,
        "can_send_audios": False,
        "can_send_documents": False,
        "can_send_photos": False,
        "can_send_videos": False,
        "can_send_video_notes": False,
        "can_send_voice_notes": False,
        "can_send_polls": False,
        "can_send_other_messages": False,
        "can_add_web_page_previews": False,
    })
    try:
        r = requests.post(
            f"{_TG_API}/restrictChatMember",
            data={"chat_id": str(chat_id), "user_id": str(user_id),
                  "permissions": perms, "until_date": str(until)},
            timeout=10, verify=True)
        return r.ok and '"ok":true' in r.text
    except requests.RequestException:
        return False


def _tg_unrestrict(chat_id: str | int, user_id: int) -> bool:
    """Kullanıcıya tüm yazma izinlerini geri ver."""
    perms = json.dumps({
        "can_send_messages": True,
        "can_send_audios": True,
        "can_send_documents": True,
        "can_send_photos": True,
        "can_send_videos": True,
        "can_send_video_notes": True,
        "can_send_voice_notes": True,
        "can_send_polls": True,
        "can_send_other_messages": True,
        "can_add_web_page_previews": True,
    })
    try:
        r = requests.post(
            f"{_TG_API}/restrictChatMember",
            data={"chat_id": str(chat_id), "user_id": str(user_id),
                  "permissions": perms},
            timeout=10, verify=True)
        return r.ok
    except requests.RequestException:
        return False


def _tg_kick(chat_id: str | int, user_id: int) -> bool:
    """Kullanıcıyı at (ban + hemen unban → tekrar katılabilir)."""
    if not user_id:
        return False
    try:
        r = requests.post(
            f"{_TG_API}/banChatMember",
            data={"chat_id": str(chat_id), "user_id": str(user_id),
                  "revoke_messages": "true"},
            timeout=10, verify=True)
        ok = r.ok and '"ok":true' in r.text
        # Kalıcı ban değil — hemen kaldır ki tekrar katılabilsin
        time.sleep(0.5)
        try:
            requests.post(
                f"{_TG_API}/unbanChatMember",
                data={"chat_id": str(chat_id), "user_id": str(user_id),
                      "only_if_banned": "true"},
                timeout=10, verify=True)
        except requests.RequestException:
            pass
        return ok
    except requests.RequestException:
        return False


# ── ADMIN ÖNBELLEĞİ ──────────────────────────────────────────────────────────
def _get_chat_admins(chat_id: str | int) -> set[int]:
    """Chat'in admin user_id setini döndür (10 dk önbellekli)."""
    key = str(chat_id)
    now = time.time()
    with _ADMIN_LOCK:
        cached = _ADMIN_CACHE.get(key)
        if cached and (now - cached.get("fetched_at", 0)) < _ADMIN_REFRESH_SEC:
            return cached.get("ids") or set()
    ids: set[int] = set()
    try:
        r = requests.get(f"{_TG_API}/getChatAdministrators",
                         params={"chat_id": str(chat_id)},
                         timeout=10, verify=True)
        if r.ok:
            res = r.json().get("result") or []
            for adm in res:
                u = (adm.get("user") or {}).get("id")
                if u:
                    ids.add(int(u))
    except requests.RequestException:
        pass
    with _ADMIN_LOCK:
        _ADMIN_CACHE[key] = {"ids": ids, "fetched_at": now}
    return ids


def _is_admin(chat_id: str | int, user_id: int) -> bool:
    if not user_id:
        return False
    return int(user_id) in _get_chat_admins(chat_id)


# ── STRIKE / CEZA YÖNETİMİ ───────────────────────────────────────────────────
def _strikes_load() -> dict:
    d = load_json(_STRIKES_FILE, {}) or {}
    return d if isinstance(d, dict) else {}


def _strikes_save(d: dict) -> None:
    save_json(_STRIKES_FILE, d)


def _strikes_for(user_id: int) -> int:
    """Son 24sa içindeki aktif strike sayısı."""
    if not user_id:
        return 0
    d = _strikes_load()
    rec = d.get(str(user_id)) or {}
    cutoff = time.time() - _STRIKE_TTL_HOURS * 3600
    history = [t for t in (rec.get("history") or []) if t > cutoff]
    return len(history)


def _add_strike(user_id: int, reason: str) -> int:
    """Strike ekle ve toplam aktif strike sayısını döndür."""
    if not user_id:
        return 0
    d = _strikes_load()
    key = str(user_id)
    rec = d.get(key) or {"history": [], "reasons": []}
    cutoff = time.time() - _STRIKE_TTL_HOURS * 3600
    history = [t for t in (rec.get("history") or []) if t > cutoff]
    history.append(time.time())
    reasons = (rec.get("reasons") or [])[-9:]
    reasons.append({"ts": int(time.time()), "reason": reason})
    rec["history"] = history
    rec["reasons"] = reasons
    d[key] = rec
    # Eski (24sa+) kullanıcı kayıtlarını temizle
    d = {k: v for k, v in d.items()
         if any(t > cutoff for t in (v.get("history") or []))}
    _strikes_save(d)
    return len(history)


# ── MODERASYON İSTATİSTİKLERİ ────────────────────────────────────────────────
def _stats_bump(action: str) -> None:
    """Günlük moderasyon sayacı (delete, mute, kick, flood, welcome)."""
    today = now_tr().strftime("%Y-%m-%d")
    s = load_json(_MOD_STATS_FILE, {}) or {}
    if not isinstance(s, dict):
        s = {}
    day = s.get(today) or {}
    day[action] = int(day.get(action, 0) or 0) + 1
    s[today] = day
    # 30 günden eski kayıtları temizle
    keep_days = 30
    keys = sorted(s.keys())
    if len(keys) > keep_days:
        for k in keys[:-keep_days]:
            s.pop(k, None)
    save_json(_MOD_STATS_FILE, s)


def _stats_today() -> dict:
    today = now_tr().strftime("%Y-%m-%d")
    s = load_json(_MOD_STATS_FILE, {}) or {}
    return (s.get(today) or {}) if isinstance(s, dict) else {}


# ── YENİ ÜYE TAKİBİ ──────────────────────────────────────────────────────────
def _new_member_record(user_id: int) -> None:
    if not user_id:
        return
    d = load_json(_NEW_MEMBERS_FILE, {}) or {}
    if not isinstance(d, dict):
        d = {}
    d[str(user_id)] = int(time.time())
    # 7 günden eski kayıtları temizle
    cutoff = time.time() - 7 * 86400
    d = {k: v for k, v in d.items() if v > cutoff}
    save_json(_NEW_MEMBERS_FILE, d)


def _is_new_member(user_id: int) -> bool:
    """Üye son _NEW_MEMBER_GRACE_HOURS saatte mi katıldı?"""
    if not user_id:
        return False
    d = load_json(_NEW_MEMBERS_FILE, {}) or {}
    ts = (d or {}).get(str(user_id))
    if not ts:
        return False
    return (time.time() - int(ts)) < _NEW_MEMBER_GRACE_HOURS * 3600


# ── ANTİ-FLOOD ───────────────────────────────────────────────────────────────
def _flood_check(user_id: int) -> bool:
    """True dönerse kullanıcı flood ediyor demek."""
    if not user_id:
        return False
    now = time.time()
    cutoff = now - _FLOOD_WINDOW_SEC
    with _RECENT_MSGS_LOCK:
        lst = _RECENT_MSGS.get(user_id, [])
        lst = [t for t in lst if t > cutoff]
        lst.append(now)
        _RECENT_MSGS[user_id] = lst
        # Bellek temizliği — çok eski kullanıcı girdilerini sil
        if len(_RECENT_MSGS) > 500:
            for uid in list(_RECENT_MSGS.keys()):
                if not _RECENT_MSGS[uid] or max(_RECENT_MSGS[uid]) < cutoff:
                    _RECENT_MSGS.pop(uid, None)
        return len(lst) >= _FLOOD_THRESHOLD


# ── GÖRSEL YARDIMCILAR (renkli rozetler, progress bar, ayraçlar) ────────────
_SEP_DOUBLE  = "═══════════════════════════"   # ana ayraç
_SEP_THIN    = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"     # alt başlık ayracı
_SEP_DOTTED  = "▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰▰"     # vurgu ayracı


def _progress_bar(value: float, vmax: float = 350.0, width: int = 10) -> str:
    """Skor için görsel ilerleme çubuğu: ▰▰▰▰▰▰▱▱▱▱"""
    if vmax <= 0:
        return ""
    pct = max(0.0, min(1.0, float(value) / float(vmax)))
    filled = int(round(pct * width))
    return "▰" * filled + "▱" * (width - filled)


def _score_badge(score: float) -> str:
    """Skor seviyesine göre rozet: 💎/🏆/🥇/🥈/🥉/⭐/⚪"""
    s = float(score or 0)
    if s >= 200: return "💎"   # elmas — efsane
    if s >= 150: return "🏆"   # şampiyon
    if s >= 110: return "🥇"   # altın
    if s >= 80:  return "🥈"   # gümüş
    if s >= 60:  return "🥉"   # bronz
    if s >= 40:  return "⭐"   # ortalama
    return "⚫"                # zayıf


def _pnl_pill(pnl: float) -> str:
    """K/Z için renkli baloncuk: 🟢+5.20% / 🔴−2.15% / ⚪0.00%"""
    p = float(pnl or 0)
    if p > 0.05:
        return f"🟢 +{p:.2f}%"
    if p < -0.05:
        return f"🔴 {p:.2f}%"
    return f"⚪ {p:.2f}%"


def _decision_chip(decision: str) -> str:
    """AI Karar için renkli rozet."""
    d = (decision or "").upper().strip()
    return {
        "GÜÇLÜ AL": "🟢🟢 GÜÇLÜ AL",
        "AL":        "🟢 AL",
        "NÖTR":      "⚪ NÖTR",
        "DİKKAT":    "🟡 DİKKAT",
        "KAÇIN":     "🔴 KAÇIN",
    }.get(d, f"⚪ {d or '—'}")


def _confidence_bar(conf: float, width: int = 10) -> str:
    """Güven yüzdesi için yatay bar: ▰▰▰▰▰▰▰▱▱▱  %72"""
    c = max(0.0, min(100.0, float(conf or 0)))
    filled = int(round(c / 100 * width))
    return "▰" * filled + "▱" * (width - filled) + f"  %{int(c)}"


def _trend_arrow(trend: str) -> str:
    """Trend metnine renkli ok ekle."""
    t = (trend or "").lower()
    if "yükseliş" in t or "yukari" in t or "up" in t or "yukarı" in t:
        return f"🔺 {trend}"
    if "düşüş" in t or "dusus" in t or "down" in t:
        return f"🔻 {trend}"
    if "yatay" in t or "side" in t:
        return f"▶ {trend}"
    return f"• {trend}" if trend else "—"


# ── KARŞILAMA ────────────────────────────────────────────────────────────────
def _send_welcome(chat_id: str | int, user: dict) -> None:
    name = user.get("first_name") or user.get("username") or "Hoş geldin"
    uname = user.get("username")
    mention = f"@{uname}" if uname else name
    msg = (f"╔══════════════════════╗\n"
           f"   🎉 *HOŞ GELDİN* 🎉\n"
           f"╚══════════════════════╝\n"
           f"👋 Selam {mention}!\n"
           f"{_SEP_DOTTED}\n"
           f"🤖 Burada *PREDATOR AI* canlı BIST sinyalleri yayımlıyor.\n\n"
           f"💎 *Neler yapabilirsin?*\n"
           f"  🔍 `T HISSE` → anlık AI analizi (örn `T ARENA`)\n"
           f"  💼 `/portfoy` → açık pozisyonları gör\n"
           f"  📋 `/komutlar` → tüm komut listesi\n"
           f"  📜 `/kurallar` → grup kuralları\n\n"
           f"⚠️ *Hızlı kurallar:*\n"
           f"  🔗 Link / reklam / başka kanal etiketi → 🚫\n"
           f"  🤬 Küfür / hakaret → 🚫\n"
           f"  🌊 Spam / flood → 🚫\n\n"
           f"_⏳ Bu mesaj 2 dk sonra otomatik silinecek._")
    mid = _tg_send_raw(chat_id, msg)
    if mid:
        _schedule_delete(chat_id, mid, after_sec=_WELCOME_DELETE_SEC)
    _stats_bump("welcome")


# ── Zamanlanmış mesaj silme kuyruğu ─────────────────────────────────────────
_PENDING_DELETIONS: list[tuple[float, str | int, int]] = []
_PENDING_LOCK = threading.Lock()


def _schedule_delete(chat_id: str | int, message_id: int,
                     after_sec: int = _AUTO_DELETE_SEC) -> None:
    if not message_id:
        return
    when = time.time() + max(1, after_sec)
    with _PENDING_LOCK:
        _PENDING_DELETIONS.append((when, chat_id, message_id))


def tg_deletion_worker() -> None:
    """Kuyruktaki süresi gelen mesajları sil."""
    print("[PREDATOR] TG silme işçisi başlatıldı.", flush=True)
    while True:
        try:
            now = time.time()
            with _PENDING_LOCK:
                due = [x for x in _PENDING_DELETIONS if x[0] <= now]
                _PENDING_DELETIONS[:] = [x for x in _PENDING_DELETIONS if x[0] > now]
            for _, ch, mid in due:
                _tg_delete(ch, mid)
            time.sleep(3)
        except Exception as e:
            print(f"[PREDATOR] silme işçisi hatası: {e}", flush=True)
            time.sleep(5)


# ── PINNED POZİSYON PANOSU ──────────────────────────────────────────────────
def _build_position_board() -> str:
    """Üstte sabitlenecek canlı pozisyon panosu metni."""
    n = now_tr()
    msg = f"╔══════════════════════╗\n"
    msg += f"  📌 *PREDATOR PANOSU* 📌\n"
    msg += f"╚══════════════════════╝\n"
    msg += f"🕐 _Güncelleme: {n.strftime('%d.%m.%Y · %H:%M')}_\n"
    msg += f"{_SEP_DOTTED}\n"
    try:
        oto = oto_load()
    except Exception as e:
        return msg + f"⚠️ _Pano okunamadı: {e}_"
    positions = oto.get("positions", {}) or {}
    if not positions:
        msg += "💤 *Açık pozisyon yok*\n"
        msg += "   _🔍 AI fırsat tarıyor..._\n"
    else:
        msg += f"💼 *AÇIK POZİSYONLAR* ({len(positions)})\n"
        msg += f"{_SEP_THIN}\n"
        total_pnl = 0.0
        for code, pos in positions.items():
            pnl = float(pos.get("pnl_pct", 0) or 0)
            total_pnl += pnl
            entry = float(pos.get("entry", 0) or 0)
            cur = float(pos.get("guncel", 0) or 0)
            h1 = float(pos.get("h1", 0) or 0)
            stop = float(pos.get("stop", 0) or 0)
            ai_live = pos.get("ai_decision_live", "")
            h1_hit_badge = " 🎯" if pos.get("h1_hit") else ""
            ai_tag = f" · 🤖 {_decision_chip(ai_live)}" if ai_live else ""
            arrow = "🔺" if pnl >= 0 else "🔻"
            rb_prob = float(pos.get("rb_prob", -1) or -1)
            rb_tag = ""
            if rb_prob >= 0:
                rb_pct = int(rb_prob * 100)
                if rb_prob >= 0.65:   rb_tag = f" · 🧠 *%{rb_pct}*🟢"
                elif rb_prob >= 0.50: rb_tag = f" · 🧠 %{rb_pct}🔵"
                elif rb_prob >= 0.35: rb_tag = f" · 🧠 %{rb_pct}🟡"
                else:                 rb_tag = f" · 🧠 %{rb_pct}🔴"
            msg += (f"{arrow} *{code}* — {_pnl_pill(pnl)}{h1_hit_badge}\n"
                    f"   💵 Giriş `{entry:.2f}₺` → Şu an `{cur:.2f}₺`\n"
                    f"   🎯 H1 `{h1:.2f}₺` · 🛡️ Stop `{stop:.2f}₺`{ai_tag}{rb_tag}\n")
        avg = total_pnl / len(positions)
        msg += f"{_SEP_THIN}\n"
        msg += f"📊 *Ort. K/Z:* {_pnl_pill(avg)}\n"
    # Geçmiş işlemler: son N kapanan pozisyon (al → sat fiyatları)
    history = oto.get("history", []) or []
    closed = [h for h in history if h.get("exit") is not None][:3]
    if closed:
        msg += f"\n📜 *SON İŞLEMLER*\n"
        msg += f"{_SEP_THIN}\n"
        for h in closed:
            code = h.get("code", "?")
            entry = float(h.get("entry", 0) or 0)
            exit_price = float(h.get("exit", 0) or 0)
            pnl = float(h.get("pnl_pct", 0) or 0)
            badge = "🏆" if pnl > 0 else "💥"
            msg += (f"  {badge} *{code}* `{entry:.2f}₺` → `{exit_price:.2f}₺` "
                    f"· {_pnl_pill(pnl)}\n")

    stats = oto.get("stats", {}) or {}
    t = int(stats.get("total_trades", 0) or 0)
    if t > 0:
        total_pnl_amt = float(stats.get("total_pnl", 0) or 0)
        # Toplam K/Z %: kapanan tüm işlemlerin pnl_pct toplamı
        total_pnl_pct = sum(float(h.get("pnl_pct", 0) or 0)
                            for h in history if h.get("exit") is not None)
        wins = int(stats.get("wins", 0) or 0)
        wr = round((wins / t) * 100, 1) if t > 0 else 0
        sign_amt = "+" if total_pnl_amt >= 0 else ""
        msg += f"\n{_SEP_DOTTED}\n"
        msg += f"📈 *TOPLAM PERFORMANS*\n"
        msg += f"{_SEP_THIN}\n"
        msg += f"💰 K/Z Toplam: {_pnl_pill(total_pnl_pct)} · `{sign_amt}{total_pnl_amt:.2f}₺`\n"
        msg += f"🎯 İşlem: *{t}* · Kazanma: *%{wr}*\n"
    return msg


def _ensure_pinned_board(chat_id: str | int) -> None:
    """Sabit panonun varlığını sağla — birleşik mesaj olarak (portföy + yedek).

    Delegasyon: tüm pin/edit/upload mantığı `cache_backup.update_unified_panel`
    içinde. Bu fonksiyon sadece güncel pano metnini üretip iletir ve eski
    text-only PANO mesajları varsa onları temizleme listesine ekler.
    """
    from .cache_backup import update_unified_panel  # geç içe-aktarma
    text = _build_position_board()
    chat_key = str(chat_id)

    # Eski text-only pano (önceki sürümden) varsa, yeni doc yüklendiğinde silinsin
    legacy_state = load_json(_PIN_STATE_FILE, {}) or {}
    legacy_entry = legacy_state.get(chat_key) or {}
    legacy_id = int(legacy_entry.get("message_id", 0) or 0)
    extra = [legacy_id] if legacy_id else None

    try:
        r = update_unified_panel(text, extra_cleanup_ids=extra)
    except Exception as e:
        print(f"[PREDATOR] Pano güncelleme hatası: {e}", flush=True)
        return

    if not r.get("ok"):
        return

    # Geriye uyum için kendi state dosyamızı da güncelle (legacy referansı temizle)
    if r.get("mode") == "new_doc" and legacy_id:
        legacy_state.pop(chat_key, None)
        save_json(_PIN_STATE_FILE, legacy_state)
    else:
        legacy_state[chat_key] = {"message_id": int(r.get("message_id") or 0),
                                  "ts": int(time.time())}
        save_json(_PIN_STATE_FILE, legacy_state)


def tg_pin_loop() -> None:
    """Pinned pozisyon panosunu periyodik olarak günceller."""
    print("[PREDATOR] Pinned pano güncelleyici başlatıldı.", flush=True)
    # İlk çağrıdan önce kısa bekle ki diğer thread'ler ayağa kalksın
    time.sleep(20)
    while True:
        try:
            _ensure_pinned_board(config.TG_CHAT_ID)
        except Exception as e:
            print(f"[PREDATOR] Pin loop hatası: {e}", flush=True)
        time.sleep(_PIN_REFRESH_SEC)


# ── MODERASYON ──────────────────────────────────────────────────────────────
def _moderation_violation(text: str, msg: dict, is_new_member: bool = False) -> str | None:
    """Mesaj kural ihlali içeriyorsa kısa açıklama döner, temizse None.

    is_new_member=True ise daha sıkı kurallar uygulanır (forward'lar yasak,
    media-only mesajlarda da forward kontrolü yapılır).
    """
    # Forward edilen mesaj — yeni üye için sıkı: text olmasa da bloklanır
    is_forward = bool(msg.get("forward_from") or msg.get("forward_from_chat")
                      or msg.get("forward_origin"))
    if is_forward and (is_new_member or text):
        return "forward"

    if not text:
        # Medya/sticker spam — yeni üye değilse şimdilik dokunma
        return None

    low = text.lower()

    # Link / URL
    if _URL_RE.search(text):
        return "link"

    # Telegram mention/forward (botun kendisi hariç)
    bot_user = (_get_bot_info().get("username") or "").lower()
    for m in _MENTION_BOT_RE.findall(text):
        u = m.lstrip("@").lower()
        if u and u != bot_user and len(u) >= 4:
            return "mention"

    # Reklam anahtar kelimeleri
    for kw in _AD_KEYWORDS:
        if kw in low:
            return "reklam"

    # Küfür
    if _PROFANITY_RE.search(low):
        return "küfür"

    # Aşırı CAPS spam (10+ karakter ve %80'den fazlası büyük harf)
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 15 and sum(1 for c in letters if c.isupper()) / len(letters) > 0.85:
        return "caps_spam"

    return None


# ── GÜNLÜK ÖZET ──────────────────────────────────────────────────────────────
def _build_daily_summary() -> str:
    cache = load_json(config.ALLSTOCKS_CACHE, {}) or {}
    picks = cache.get("topPicks", []) or []
    n = now_tr()

    gun_emoji = ["🌟", "💎", "🚀", "⚡", "🎯", "🔥", "🌈"][n.weekday() % 7]
    msg  = f"╔══════════════════════╗\n"
    msg += f"  🌅 *GÜNAYDIN!* {gun_emoji}\n"
    msg += f"╚══════════════════════╝\n"
    msg += f"📆 _{n.strftime('%d.%m.%Y · %A')}_\n"
    msg += f"{_SEP_DOTTED}\n\n"

    # Top 5 fırsat
    msg += f"🎯 *BUGÜNÜN İLK 5 FIRSATI*\n"
    msg += f"{_SEP_THIN}\n"
    if not picks:
        msg += "💤 _Henüz tarama verisi yok..._\n"
    else:
        rank_emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, p in enumerate(picks[:5], 1):
            code = p.get("code", "?")
            score = int(float(p.get("score", 0) or 0))
            cur = float(p.get("guncel", 0) or 0)
            h1 = float(p.get("h1", 0) or 0)
            stop = float(p.get("stop", 0) or 0)
            rr = p.get("rr", 0)
            ai = p.get("autoThinkDecision", "NÖTR")
            conf = int(p.get("autoThinkConf", 50) or 50)
            up_pct = ((h1 - cur) / cur * 100) if cur > 0 else 0
            risk_pct = ((cur - stop) / cur * 100) if cur > 0 and stop > 0 else 0
            r = rank_emoji[i-1] if i <= len(rank_emoji) else f"{i}."
            rb_prob = float(p.get("rb_prob", -1) or -1)
            rb_tag = ""
            if rb_prob >= 0:
                rb_pct = int(rb_prob * 100)
                rb_tag = (f" 🟢" if rb_prob >= 0.65 else
                          f" 🔵" if rb_prob >= 0.50 else
                          f" 🟡" if rb_prob >= 0.35 else " 🔴")
                rb_tag = f" · 🧠%{rb_pct}{rb_tag}"
            msg += (f"{r} *{code}* {_score_badge(score)} `{score}`\n"
                    f"   {_decision_chip(ai)} · _güven %{conf}_ · 🎲 RR:`{rr}`{rb_tag}\n"
                    f"   💵 `{cur:.2f}₺` → 🎯 `{h1:.2f}₺` (🟢 +%{up_pct:.1f})\n"
                    f"   🛡️ Stop `{stop:.2f}₺` (🔴 −%{risk_pct:.1f})\n")

    # Portföy
    msg += f"\n💼 *PORTFÖY DURUMU*\n"
    msg += f"{_SEP_THIN}\n"
    try:
        oto = oto_load()
        positions = oto.get("positions", {}) or {}
        if not positions:
            msg += "💤 _Açık pozisyon yok — AI fırsat bekliyor..._\n"
        else:
            total_pnl = 0.0
            for code, pos in positions.items():
                pnl = float(pos.get("pnl_pct", 0) or 0)
                total_pnl += pnl
                arrow = "🔺" if pnl >= 0 else "🔻"
                h1_hit = " 🎯" if pos.get("h1_hit") else ""
                msg += (f"{arrow} *{code}* {_pnl_pill(pnl)}{h1_hit}\n"
                        f"   💵 Giriş `{float(pos.get('entry', 0)):.2f}₺` · "
                        f"🎯 `{float(pos.get('h1', 0)):.2f}₺`\n")
            avg = total_pnl / len(positions)
            msg += f"\n📊 *Ort. K/Z:* {_pnl_pill(avg)}\n"

        stats = oto.get("stats", {}) or {}
        t = int(stats.get("total_trades", 0) or 0)
        if t > 0:
            wr = round(stats.get("wins", 0) / t * 100, 1)
            wr_badge = "🏆" if wr >= 70 else ("🥇" if wr >= 55 else ("⭐" if wr >= 40 else "💪"))
            msg += f"📈 Tarihsel: *{t}* işlem · {wr_badge} kazanma *%{wr}*\n"
    except Exception as e:
        msg += f"⚠️ _Portföy okunamadı: {e}_\n"

    msg += f"\n{_SEP_DOTTED}\n"
    msg += "🔔 _Borsa **10:00**'da açılıyor — iyi şanslar!_ 🚀"
    msg += tg_footer()
    return msg


def send_daily_summary(force: bool = False) -> bool:
    """Günlük özeti gönder. force=False ise gün başına tek sefer kuralı uygulanır."""
    n = now_tr()
    today = n.strftime("%Y-%m-%d")
    state = load_json(_DAILY_STATE_FILE, {}) or {}
    if not force and state.get("last_sent_date") == today:
        return False
    msg = _build_daily_summary()
    ok = _tg_send_raw(config.TG_CHAT_ID, msg)
    if ok:
        state["last_sent_date"] = today
        state["last_sent_ts"] = int(time.time())
        save_json(_DAILY_STATE_FILE, state)
    return ok


_CLOSING_STATE_FILE = Path(config.CACHE_DIR) / "predator_closing_summary_state.json"
_CLOSING_HOUR = 16
_CLOSING_MIN  = 35


def _build_closing_summary() -> str:
    """Borsa kapanışı sonrası (16:35) gönderilecek günlük sonuç özeti."""
    n = now_tr()
    try:
        oto = oto_load()
    except Exception:
        oto = {}
    positions = oto.get("positions", {}) or {}
    history   = oto.get("history",   []) or []
    stats     = oto.get("stats",     {}) or {}

    msg  = f"╔══════════════════════╗\n"
    msg += f"  🔔 *GÜNLÜK KAPANIŞ* 🔔\n"
    msg += f"╚══════════════════════╝\n"
    msg += f"📆 _{n.strftime('%d.%m.%Y · %A')}_\n"
    msg += f"🕐 _{n.strftime('%H:%M')} TR_\n"
    msg += f"{_SEP_DOTTED}\n\n"

    # Açık pozisyonlar
    if positions:
        msg += f"💼 *AÇIK POZİSYONLAR*\n"
        msg += f"{_SEP_THIN}\n"
        total_pnl = 0.0
        for code, pos in positions.items():
            pnl = float(pos.get("pnl_pct", 0) or 0)
            total_pnl += pnl
            arrow = "🔺" if pnl >= 0 else "🔻"
            entry = float(pos.get("entry", 0) or 0)
            stop  = float(pos.get("stop", 0) or 0)
            h1    = float(pos.get("h1", 0) or 0)
            h1_hit = " 🎯" if pos.get("h1_hit") else ""
            rb_prob = float(pos.get("rb_prob", -1) or -1)
            rb_tag = ""
            if rb_prob >= 0:
                rb_pct = int(rb_prob * 100)
                rb_tag = (f" 🟢" if rb_prob >= 0.65 else
                          f" 🔵" if rb_prob >= 0.50 else
                          f" 🟡" if rb_prob >= 0.35 else " 🔴")
                rb_tag = f" · 🧠%{rb_pct}{rb_tag}"
            msg += (f"{arrow} *{code}* {_pnl_pill(pnl)}{h1_hit}\n"
                    f"   Giriş `{entry:.2f}₺` · H1 `{h1:.2f}₺` · Stop `{stop:.2f}₺`{rb_tag}\n")
        avg = total_pnl / len(positions)
        msg += f"{_SEP_THIN}\n"
        msg += f"📊 Ort. K/Z: {_pnl_pill(avg)}\n"
    else:
        msg += "💤 *Açık pozisyon yok*\n"

    # Bugün kapatılan işlemler
    today_str = n.strftime("%Y-%m-%d")
    closed_today = [h for h in history
                    if (h.get("exit") is not None) and
                       (h.get("exit_date") or h.get("date") or "")[:10] == today_str]
    if closed_today:
        msg += f"\n✅ *BUGÜN KAPANAN İŞLEMLER*\n"
        msg += f"{_SEP_THIN}\n"
        for h in closed_today:
            code     = h.get("code", "?")
            entry    = float(h.get("entry", 0) or 0)
            exit_p   = float(h.get("exit",  0) or 0)
            pnl      = float(h.get("pnl_pct", 0) or 0)
            badge    = "🏆" if pnl > 0 else "💥"
            msg += (f"  {badge} *{code}* `{entry:.2f}₺` → `{exit_p:.2f}₺` "
                    f"· {_pnl_pill(pnl)}\n")

    # Genel performans
    t = int(stats.get("total_trades", 0) or 0)
    if t > 0:
        wins = int(stats.get("wins", 0) or 0)
        wr   = round(wins / t * 100, 1)
        total_pnl_amt = float(stats.get("total_pnl", 0) or 0)
        total_pnl_pct = sum(float(h.get("pnl_pct", 0) or 0)
                            for h in history if h.get("exit") is not None)
        wr_badge = "🏆" if wr >= 65 else ("🥇" if wr >= 55 else ("⭐" if wr >= 40 else "💪"))
        sign_amt = "+" if total_pnl_amt >= 0 else ""
        msg += f"\n{_SEP_DOTTED}\n"
        msg += f"📈 *TOPLAM PERFORMANS*\n"
        msg += f"{_SEP_THIN}\n"
        msg += f"💰 K/Z: {_pnl_pill(total_pnl_pct)} · `{sign_amt}{total_pnl_amt:.2f}₺`\n"
        msg += f"🎯 İşlem: *{t}* · {wr_badge} Kazanma: *%{wr}*\n"

    msg += f"\n{_SEP_DOTTED}\n"
    msg += f"_🌙 Yarın görüşmek üzere — iyi geceler!_"
    msg += tg_footer()
    return msg


def send_closing_summary(force: bool = False) -> bool:
    """Kapanış özetini gönder. force=False ise gün başına tek sefer kuralı uygulanır."""
    n = now_tr()
    today = n.strftime("%Y-%m-%d")
    state = load_json(_CLOSING_STATE_FILE, {}) or {}
    if not force and state.get("last_sent_date") == today:
        return False
    msg = _build_closing_summary()
    ok = _tg_send_raw(config.TG_CHAT_ID, msg)
    if ok:
        state["last_sent_date"] = today
        state["last_sent_ts"] = int(time.time())
        save_json(_CLOSING_STATE_FILE, state)
    return ok


def closing_summary_loop() -> None:
    """Hafta içi 16:35 TR'de bir kez kapanış özeti gönder."""
    print("[PREDATOR] Kapanış özeti zamanlayıcısı başlatıldı.", flush=True)
    while True:
        try:
            n = now_tr()
            if 1 <= n.isoweekday() <= 5:
                if (n.hour > _CLOSING_HOUR or
                        (n.hour == _CLOSING_HOUR and n.minute >= _CLOSING_MIN)):
                    if n.hour < 20:
                        send_closing_summary(force=False)
            time.sleep(60)
        except Exception as e:
            print(f"[PREDATOR] Kapanış özeti hatası: {e}", flush=True)
            time.sleep(120)


def daily_summary_loop() -> None:
    """Hafta içi 09:30 TR'de bir kez günlük özet gönder."""
    print("[PREDATOR] Günlük özet zamanlayıcısı başlatıldı.", flush=True)
    while True:
        try:
            n = now_tr()
            if 1 <= n.isoweekday() <= 5:
                # Hedef saat geçtiyse ve bugün gönderilmediyse gönder
                if (n.hour > _DAILY_HOUR or
                        (n.hour == _DAILY_HOUR and n.minute >= _DAILY_MIN)):
                    if n.hour < 16:  # 16:00'dan sonra geç kalmış sayılır, yarın yine dener
                        send_daily_summary(force=False)
            time.sleep(60)
        except Exception as e:
            print(f"[PREDATOR] Günlük özet hatası: {e}", flush=True)
            time.sleep(120)


# ── TELEGRAM KOMUT DİNLEYİCİ ─────────────────────────────────────────────────
def _build_stock_report(code: str) -> str:
    """T komutuyla istenen hisse için kısa AI raporu üret."""
    code = code.upper().strip()
    cache = load_json(config.ALLSTOCKS_CACHE, {}) or {}

    s = None
    found_in_universe = False
    # Önce topPicks (derin veri: fiyat/hedef/AI), bulunamazsa allStocks (sadece skor)
    for key in ("topPicks", "stocks", "allStocks"):
        for x in (cache.get(key) or []):
            if (x.get("code") or "").upper() == code:
                s = x; found_in_universe = True; break
        if s is not None:
            break

    # Derin veri yok mu? → analiz fonksiyonunu anlık olarak çalıştır
    needs_deep = (s is None or not (
        float(s.get("guncel", 0) or 0) > 0 and
        float(s.get("h1", 0) or 0) > 0 and
        float(s.get("stop", 0) or 0) > 0
    ))
    if needs_deep:
        try:
            from .scan import analyze_stock
            from .market import get_market_mode
            mode = get_market_mode() or "bull"
            fresh = analyze_stock(code, mode=mode)
            if fresh:
                # Mevcut yüzeysel veriyle birleştir (sektör vs. korunsun)
                if s:
                    base = dict(s); base.update(fresh); s = base
                else:
                    s = fresh
                found_in_universe = True
        except Exception as e:
            print(f"[PREDATOR] On-demand analiz hatası ({code}): {e}", flush=True)

    if s is None or not s.get("code"):
        if found_in_universe:
            return (f"╔══════════════════════╗\n"
                    f"  ⚠️ *ANALİZ BAŞARISIZ*\n"
                    f"╚══════════════════════╝\n"
                    f"🔎 *{code}*\n"
                    f"{_SEP_THIN}\n"
                    f"_Hisse BIST'te kayıtlı ama veri çekilemedi._\n"
                    f"_API geçici olarak yanıt vermiyor olabilir._"
                    + tg_footer())
        return (f"╔══════════════════════╗\n"
                f"  ❓ *BULUNAMADI*\n"
                f"╚══════════════════════╝\n"
                f"🔎 *{code}*\n"
                f"{_SEP_THIN}\n"
                f"_Kod doğru mu? Bu sembol şu an aktif olmayabilir._" + tg_footer())

    score = int(float(s.get("score", 0) or 0))
    cur = float(s.get("guncel", 0) or 0)
    h1 = float(s.get("h1", 0) or 0)
    h2 = float(s.get("h2", 0) or 0)
    h3 = float(s.get("h3", 0) or 0)
    stop = float(s.get("stop", 0) or 0)
    rr = s.get("rr", 0)
    sq = int(float(s.get("signalQuality", 0) or 0))
    ai = s.get("autoThinkDecision", "NÖTR")
    conf = int(float(s.get("autoThinkConf", 50) or 50))
    rsi = float(s.get("rsi", 0) or 0)
    vol = float(s.get("volRatio", 0) or 0)
    trend = s.get("trend", "?")
    pos52 = float(s.get("pos52wk", 0) or 0)
    sektor = s.get("sektor", "?")

    # Faz-1 (yüzeysel) tarama: sadece skor var, fiyat/hedef/AI yok.
    deep_scanned = (cur > 0 and h1 > 0 and stop > 0)
    if not deep_scanned:
        # Canlı fiyatı anlık çekmeyi dene
        try:
            from .portfolio import oto_fetch_live_price
            live = oto_fetch_live_price(code)
            if live and live > 0:
                cur = live
        except Exception:
            pass

        msg  = f"╔══════════════════════╗\n"
        msg += f"  📋 *YÜZEYSEL TARAMA*\n"
        msg += f"╚══════════════════════╝\n"
        msg += f"🔎 *{code}* {_score_badge(score)}\n"
        msg += f"{_SEP_DOTTED}\n"
        if cur > 0:
            msg += f"💵 Canlı fiyat: *{cur:.2f}₺*\n"
        msg += f"📊 Tarama skoru: *{score}* / 350\n"
        msg += f"   {_progress_bar(score, 350)}\n"
        if sektor and sektor != "?":
            msg += f"🏷️ Sektör: _{sektor}_\n"
        msg += f"\n{_SEP_THIN}\n"
        msg += ("ℹ️ Bu hisse tam BIST taramasında yer aldı ama "
                f"*top 200 fırsat listesine giremediği* için derin analiz "
                f"(AI kararı, hedef, stop, RSI, hacim, formasyon) yapılmadı.\n\n")
        if score < 60:
            msg += "🔴 *AI değerlendirmesi:* Skor eşiğinin (60) altında — alım için uygun değil.\n"
        elif score < 100:
            msg += "🟡 *AI değerlendirmesi:* Sınırda skor — güçlü sinyal yok.\n"
        else:
            msg += "🟢 *AI değerlendirmesi:* Orta skor — dip toparlanma adayı olabilir.\n"
        msg += ("\n💡 _Derin analiz için bir sonraki tarama döngüsünde "
                "top picks'e girmesi gerekir._")
        msg += tg_footer()
        return msg

    up_pct = ((h1 - cur) / cur * 100) if cur > 0 else 0
    risk_pct = ((cur - stop) / cur * 100) if cur > 0 and stop > 0 else 0

    msg  = f"╔══════════════════════╗\n"
    msg += f"  🤖 *AI ANALİZ RAPORU*\n"
    msg += f"╚══════════════════════╝\n"
    msg += f"🔎 *{code}* {_score_badge(score)}  ·  💵 `{cur:.2f}₺`\n"
    msg += f"🏷️ _{sektor}_\n"
    msg += f"{_SEP_DOTTED}\n\n"

    msg += f"🤖 *AI KARAR*\n"
    msg += f"{_SEP_THIN}\n"
    msg += f"   {_decision_chip(ai)}\n"
    msg += f"   🎲 Güven: {_confidence_bar(conf)}\n\n"

    msg += f"📊 *SKORLAR & RİSK*\n"
    msg += f"{_SEP_THIN}\n"
    msg += f"   📈 Skor: *{score}* / 350\n"
    msg += f"      {_progress_bar(score, 350)}\n"
    msg += f"   🎲 RR Oranı: *{rr}*\n"
    msg += f"   ⚡ Sinyal Kalite: *{sq}* / 10\n\n"

    msg += f"🎯 *HEDEFLER*\n"
    msg += f"{_SEP_THIN}\n"
    msg += f"   🥇 H1: `{h1:.2f}₺`  🟢 +%{up_pct:.1f}\n"
    if h2 > 0:
        h2_pct = ((h2 - cur) / cur * 100) if cur > 0 else 0
        msg += f"   🥈 H2: `{h2:.2f}₺`  🟢 +%{h2_pct:.1f}\n"
    if h3 > 0:
        h3_pct = ((h3 - cur) / cur * 100) if cur > 0 else 0
        msg += f"   🥉 H3: `{h3:.2f}₺`  🟢 +%{h3_pct:.1f}\n"
    msg += f"   🛡️ Stop: `{stop:.2f}₺`  🔴 −%{risk_pct:.1f}\n\n"

    msg += f"📈 *TEKNİK*\n"
    msg += f"{_SEP_THIN}\n"
    msg += f"   {_trend_arrow(trend)}\n"
    rsi_emoji = "🔥" if rsi >= 70 else ("🧊" if rsi <= 30 else "⚖️")
    msg += f"   {rsi_emoji} RSI: *{rsi:.1f}*\n"
    vol_emoji = "🚀" if vol >= 2 else ("📊" if vol >= 1 else "💤")
    msg += f"   {vol_emoji} Hacim: *{vol:.2f}x* ortalama\n"
    msg += f"   📍 Tüm Zaman Pos: *%{pos52:.0f}*\n"
    msg += f"      {_progress_bar(pos52, 100)}\n"

    # Real Brain (RF+GBM) tahmini
    rb_prob = float(s.get("rb_prob", -1) or -1)
    rb_conf = float(s.get("rb_conf", -1) or -1)
    if rb_prob >= 0:
        rb_pct = int(rb_prob * 100)
        rb_conf_pct = int(rb_conf * 100) if rb_conf >= 0 else 0
        if rb_prob >= 0.65:
            rb_verdict = "🟢 Güçlü yükseliş beklentisi"
        elif rb_prob >= 0.50:
            rb_verdict = "🔵 Yükseliş eğilimi"
        elif rb_prob >= 0.35:
            rb_verdict = "🟡 Kararsız / bekleme"
        else:
            rb_verdict = "🔴 Düşüş baskısı"
        rb_bar = _progress_bar(rb_pct, 100, width=8)
        msg += f"\n🧠 *GERÇEK BEYİN (RF+GBM)*\n"
        msg += f"{_SEP_THIN}\n"
        msg += f"   📊 Yükseliş olasılığı: *%{rb_pct}*\n"
        msg += f"      {rb_bar}\n"
        msg += f"   {rb_verdict}\n"
        if rb_conf_pct > 0:
            msg += f"   🎯 Model güveni: *%{rb_conf_pct}*\n"

    # AI gerekçesi
    try:
        from . import scoring_extras as sx
        cons = sx.calculate_consensus_score(s, {
            "FK": s.get("fk"), "PiyDegDefterDeg": s.get("pddd"), "ROE": s.get("roe"),
        })
        reasoning = sx.get_ai_reasoning(s, cons) or ""
        if reasoning:
            # En güçlü 4 gerekçe
            parts = [p.strip() for p in reasoning.split("·") if p.strip()][:4]
            if parts:
                msg += f"\n💡 *NEDEN BU KARAR?*\n"
                msg += f"{_SEP_THIN}\n"
                for p in parts:
                    msg += f"   ✦ {p}\n"
        cscore = cons.get("consensus") if isinstance(cons, dict) else None
        if cscore is not None:
            msg += f"\n🧠 *Konsensüs Skor:* *{cscore}*"
    except Exception:
        pass

    msg += tg_footer()
    return msg


# ── GENEL KOMUTLAR (/yardim, /kurallar, /komutlar, /portfoy, /stats) ────────
def _cmd_yardim() -> str:
    return ("╔══════════════════════╗\n"
            "  📋 *KOMUT REHBERİ*\n"
            "╚══════════════════════╝\n"
            f"{_SEP_DOTTED}\n"
            "🔍 *ANALİZ*\n"
            "  ✦ `T HISSE` — anlık AI+Gerçek Beyin analizi (örn `T ARENA`)\n\n"
            "💼 *PORTFÖY & İSTATİSTİK*\n"
            "  ✦ `/portfoy` — açık pozisyonlar\n"
            "  ✦ `/performans` — AI sinyal performansı\n"
            "  ✦ `/beyin` — Gerçek Beyin (RF+GBM) durumu\n"
            "  ✦ `/stats` — bugünkü moderasyon raporu\n\n"
            "📜 *YARDIM*\n"
            "  ✦ `/kurallar` — grup kuralları\n"
            "  ✦ `/komutlar` — bu liste\n"
            f"{_SEP_THIN}\n"
            "🔒 *Sadece admin:* `/ozet` · `/kapanis`\n"
            f"{_SEP_THIN}\n"
            "_⏳ Bot cevapları 60 sn sonra otomatik silinir._")


def _cmd_kurallar() -> str:
    return ("╔══════════════════════╗\n"
            "  📜 *GRUP KURALLARI*\n"
            "╚══════════════════════╝\n"
            f"{_SEP_DOTTED}\n"
            "🚫 *YASAKLAR*\n"
            "  1️⃣ Reklam, link, başka kanal etiketi\n"
            "  2️⃣ Küfür / hakaret\n"
            "  3️⃣ Spam / flood (10sn'de 6+ mesaj)\n"
            "  4️⃣ İlk 24 saatte forward gönderme\n"
            "  5️⃣ Konu dışı sohbet (sadece BIST & TA)\n\n"
            "⚖️ *KADEMELİ CEZA*\n"
            f"{_SEP_THIN}\n"
            "  ⚠️ 1. ihlal → uyarı + mesaj silme\n"
            "  🔇 2. ihlal → 1 saat susturma\n"
            "  🔕 3. ihlal → 24 saat susturma\n"
            "  👢 4. ihlal → gruptan atma (geri katılabilir)\n\n"
            "_🔄 Strike sayacı 24 saatte sıfırlanır._")


def _cmd_portfoy() -> str:
    return _build_position_board()


def _cmd_stats() -> str:
    s = _stats_today()
    if not s:
        return "📊 *Bugün* — moderasyon eylemi yok. Grup temiz! ✨"
    msg = "📊 *BUGÜNKÜ MODERASYON RAPORU*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    label = {
        "delete": "🗑️ Silinen mesaj",
        "mute_1h": "🔇 1sa susturma",
        "mute_24h": "🔇 24sa susturma",
        "kick": "👢 Atılan üye",
        "flood": "🌊 Flood vakası",
        "welcome": "👋 Karşılanan üye",
        "service_clean": "🧹 Servis mesajı temizliği",
    }
    for k in ["welcome", "delete", "flood", "mute_1h", "mute_24h", "kick", "service_clean"]:
        v = int(s.get(k, 0) or 0)
        if v:
            msg += f"• {label.get(k, k)}: *{v}*\n"
    return msg


def _cmd_performans() -> str:
    """AI sinyal performans özeti."""
    try:
        from .scoring_extras._perf import ai_performance_stats
        st = ai_performance_stats()
    except Exception as e:
        return f"⚠️ Performans verisi alınamadı: {e}"
    if not st or not st.get("degerlendirilmis"):
        return ("╔══════════════════════╗\n"
                "  📈 *PERFORMANS*\n"
                "╚══════════════════════╝\n"
                "_Henüz değerlendirilebilir sinyal yok._\n"
                "_5 günlük sonuçlar birikim gösterdikçe burada görünecek._")
    toplam   = int(st.get("toplam_sinyal", 0) or 0)
    degerlend = int(st.get("degerlendirilmis", 0) or 0)
    wr       = float(st.get("kazanma_orani", 0) or 0)
    ort      = float(st.get("ort_getiri", 0) or 0)
    wr_badge = "🏆" if wr >= 65 else ("🥇" if wr >= 55 else ("⭐" if wr >= 45 else "💪"))
    sign_ort = "+" if ort >= 0 else ""
    msg  = "╔══════════════════════╗\n"
    msg += "  📈 *AI PERFORMANS*\n"
    msg += "╚══════════════════════╝\n"
    msg += f"{_SEP_DOTTED}\n"
    msg += f"📊 *Genel*\n"
    msg += f"{_SEP_THIN}\n"
    msg += f"   📋 Toplam sinyal: *{toplam}*\n"
    msg += f"   🔬 Değerlendirilen: *{degerlend}*\n"
    msg += f"   {wr_badge} Kazanma oranı: *%{wr}*\n"
    msg += f"   💰 Ort. 5G getiri: *{sign_ort}{ort:.2f}%*\n"
    # AI Karar bazlı
    dec_list = st.get("by_decision") or []
    if dec_list:
        msg += f"\n🤖 *KARAR BAZLI BAŞARI*\n"
        msg += f"{_SEP_THIN}\n"
        for d in dec_list[:5]:
            karar = d.get("karar", "?")
            basari = float(d.get("basari", 0) or 0)
            getiri = float(d.get("ort_getiri", 0) or 0)
            t2 = int(d.get("toplam", 0) or 0)
            sign = "+" if getiri >= 0 else ""
            badge2 = "🟢" if basari >= 60 else ("🟡" if basari >= 45 else "🔴")
            msg += f"   {badge2} *{karar}* — %{basari} · {sign}{getiri:.1f}% `({t2})`\n"
    # Real Brain olasılık bazlı
    rb_list = st.get("by_rb_prob") or []
    if rb_list:
        msg += f"\n🧠 *GERÇEK BEYİN × BAŞARI*\n"
        msg += f"{_SEP_THIN}\n"
        for d in rb_list:
            aralik = d.get("aralik", "?")
            basari = float(d.get("basari", 0) or 0)
            getiri = float(d.get("ort_getiri", 0) or 0)
            t2 = int(d.get("toplam", 0) or 0)
            sign = "+" if getiri >= 0 else ""
            badge2 = "🟢" if basari >= 60 else ("🟡" if basari >= 45 else "🔴")
            msg += f"   {badge2} *{aralik}* — %{basari} · {sign}{getiri:.1f}% `({t2})`\n"
    # En başarılı formasyonlar
    form_list = st.get("by_formation") or []
    if form_list:
        msg += f"\n📐 *EN BAŞARILI FORMASYONLAR*\n"
        msg += f"{_SEP_THIN}\n"
        for f2 in form_list[:3]:
            msg += (f"   ✦ {f2.get('ad','?')} — "
                    f"*%{f2.get('basari',0)}* `({f2.get('toplam',0)})`\n")
    return msg


def _cmd_beyin() -> str:
    """Real Brain (RF+GBM) model durumu."""
    try:
        from .brain import brain_load
        from .real_brain import rb_get_status
        brain = brain_load()
        st = rb_get_status(brain)
    except Exception as e:
        return f"⚠️ Gerçek Beyin durumu alınamadı: {e}"
    n       = int(st.get("n", 0) or 0)
    min_n   = int(st.get("min_n", 30) or 30)
    acc     = st.get("accuracy")
    wr      = float(st.get("win_rate", 0) or 0)
    ready   = bool(st.get("ready"))
    feats   = st.get("top_features") or []
    msg  = "╔══════════════════════╗\n"
    msg += "  🧠 *GERÇEK BEYİN*\n"
    msg += "╚══════════════════════╝\n"
    msg += f"{_SEP_DOTTED}\n"
    if ready:
        msg += "✅ *Model aktif ve tahmin üretiyor*\n\n"
    else:
        msg += f"⏳ *Eğitim için veri biriktiriliyor*\n"
        msg += f"   {n}/{min_n} örnek hazır\n\n"
    msg += f"📊 *İSTATİSTİKLER*\n"
    msg += f"{_SEP_THIN}\n"
    msg += f"   📋 Toplam örnek: *{n}*\n"
    msg += f"   🎯 Eğitim eşiği: *{min_n}*\n"
    if acc is not None:
        acc_badge = "🏆" if acc >= 70 else ("🥇" if acc >= 60 else ("⭐" if acc >= 55 else "💪"))
        msg += f"   {acc_badge} CV doğruluğu: *%{acc:.1f}*\n"
    msg += f"   📈 Gerçek kazanma oranı: *%{wr:.1f}*\n"
    if feats:
        msg += f"\n🔬 *EN ETKİLİ İNDİKATÖRLER*\n"
        msg += f"{_SEP_THIN}\n"
        for i, f2 in enumerate(feats[:5], 1):
            fname = f2.get("feature", "?") if isinstance(f2, dict) else str(f2)
            fimp  = f2.get("importance", 0) if isinstance(f2, dict) else 0
            msg += f"   {i}. `{fname}` — *%{fimp:.1f}*\n"
    msg += f"\n_GBM %60 + RF %40 ağırlıklı ensemble_"
    return msg


def _cmd_ozet_admin() -> str:
    """Admin: günlük özeti zorla gönder."""
    ok = send_daily_summary(force=True)
    if ok:
        return "✅ Günlük özet zorla gönderildi."
    return "⚠️ Özet gönderilemedi (TG token/chat eksik olabilir)."


def _cmd_kapanis_admin() -> str:
    """Admin: kapanış özetini zorla gönder."""
    msg = _build_closing_summary()
    ok = _tg_send_raw(config.TG_CHAT_ID, msg)
    return "✅ Kapanış özeti gönderildi." if ok else "⚠️ Kapanış özeti gönderilemedi."


def _try_handle_command(text: str, sender_id: int = 0,
                        chat_id=None, is_admin: bool = False) -> str | None:
    """Genel komutları işle. Eşleşmezse None döner."""
    if not text:
        return None
    # /komut@botname formatını destekle
    t = text.strip().lower().split("@")[0].split()[0] if text.strip() else ""
    if t in ("/yardim", "/help", "/komutlar", "/start"):
        return _cmd_yardim()
    if t in ("/kurallar", "/rules"):
        return _cmd_kurallar()
    if t in ("/portfoy", "/portföy", "/portfolio"):
        return _cmd_portfoy()
    if t in ("/stats", "/istatistik"):
        return _cmd_stats()
    if t in ("/performans", "/performance"):
        return _cmd_performans()
    if t in ("/beyin", "/brain", "/realbeyin"):
        return _cmd_beyin()
    # Admin komutları
    if t in ("/ozet", "/summary") and is_admin:
        return _cmd_ozet_admin()
    if t in ("/kapanis", "/kapanış", "/closing") and is_admin:
        return _cmd_kapanis_admin()
    return None


# ── ANA UPDATE İŞLEYİCİ ──────────────────────────────────────────────────────
def _handle_service_message(chat_id, msg_id, msg, chat_type) -> bool:
    """Servis mesajını ele al (yeni üye, ayrılan üye, başlık değişikliği vb.)
    True dönerse mesaj işlendi, ana akışta devam edilmemeli."""
    is_group = chat_type in ("group", "supergroup")
    if not is_group:
        return False

    # Yeni üyeler
    new_members = msg.get("new_chat_members") or []
    if new_members:
        for u in new_members:
            uid = u.get("id")
            if not uid:
                continue
            # Botun kendisi gruba eklendi → karşılama yok
            bot_id = _get_bot_info().get("id")
            if bot_id and uid == bot_id:
                continue
            # Bot/spam hesabı (is_bot True) → karşılama yok ve at
            if u.get("is_bot"):
                _tg_kick(chat_id, uid)
                _stats_bump("kick")
                continue
            _new_member_record(uid)
            _send_welcome(chat_id, u)
        if _SERVICE_MSG_DELETE:
            _tg_delete(chat_id, msg_id)
            _stats_bump("service_clean")
        return True

    # Ayrılan üye / başlık / fotoğraf vs. servis mesajları
    service_keys = ("left_chat_member", "new_chat_title", "new_chat_photo",
                    "delete_chat_photo", "group_chat_created",
                    "supergroup_chat_created", "channel_chat_created",
                    "migrate_to_chat_id", "migrate_from_chat_id",
                    "pinned_message", "message_auto_delete_timer_changed")
    for k in service_keys:
        if msg.get(k) is not None:
            if _SERVICE_MSG_DELETE:
                _tg_delete(chat_id, msg_id)
                _stats_bump("service_clean")
            return True
    return False


def _apply_strike_action(chat_id, sender_id, sender, violation: str) -> str:
    """Strike ekle ve uygun cezayı uygula. Kullanıcı uyarı metni döner."""
    strikes = _add_strike(sender_id, violation) if sender_id else 1
    uname = sender.get("username") or sender.get("first_name") or "kullanıcı"
    mention = f"@{uname}" if sender.get("username") else uname

    label_map = {
        "link": "🔗 Link/URL paylaşımı",
        "mention": "📢 Başka kanal/bot etiketi",
        "forward": "↪️ Başka kanaldan iletme",
        "reklam": "📣 Reklam içeriği",
        "küfür": "🚫 Küfür/hakaret",
        "caps_spam": "🔠 CAPS spam",
        "flood": "🌊 Flood (hızlı mesaj)",
    }
    reason = label_map.get(violation, violation)

    if strikes >= 4 and sender_id:
        _tg_kick(chat_id, sender_id)
        _stats_bump("kick")
        return (f"👢 *Atıldı* — {mention}\n"
                f"Sebep: {reason} (4. ihlal)\n"
                f"_Geri katılabilir ama tekrarda kalıcı yasak._")
    if strikes == 3 and sender_id:
        _tg_restrict(chat_id, sender_id, _MUTE_24H_SEC)
        _stats_bump("mute_24h")
        return (f"🔇 *24 saat susturuldu* — {mention}\n"
                f"Sebep: {reason} (3. ihlal)")
    if strikes == 2 and sender_id:
        _tg_restrict(chat_id, sender_id, _MUTE_1H_SEC)
        _stats_bump("mute_1h")
        return (f"🔇 *1 saat susturuldu* — {mention}\n"
                f"Sebep: {reason} (2. ihlal)")
    # Tier 1 — sadece uyarı
    return (f"⚠️ *Uyarı* — {mention} mesajı silindi\n"
            f"Sebep: {reason}\n"
            f"_Tekrarında 1 saat susturma._")


def _process_update(upd: dict) -> None:
    msg = upd.get("message") or upd.get("channel_post") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or msg.get("caption") or "").strip()
    msg_id = msg.get("message_id")
    sender = msg.get("from") or {}
    sender_id = sender.get("id")
    bot_id = _get_bot_info().get("id")
    if not chat_id or not msg_id:
        return

    chat_type = chat.get("type", "")
    is_group = chat_type in ("group", "supergroup", "channel")

    # ── 0) SERVİS MESAJLARI (yeni üye, ayrılan, "X pinned a message", vb.)
    # ÖNEMLİ: Bot-self kontrolünden ÖNCE çalışmalı. Çünkü "Toji pinned a
    # message" servis mesajının `from` alanı = bot'un kendisi. Eğer
    # bot-self filtresini önce uygularsak, bu servis mesajları temizlenmez
    # ve grupta birikir.
    if _handle_service_message(chat_id, msg_id, msg, chat_type):
        return

    # ── 0b) BOT'UN KENDİ MESAJLARINI YAKALA — AKILLI TEMİZLİK (v37.12) ─────
    # Bot kendi mesajlarını long-poll ile geri görür (kendi sendMessage/Document
    # çağrılarımız Update olarak da gelir). Bu noktada:
    #   • chart_*.jpg yedek doc → aktif pin değilse SİL
    #   • PREDATOR/PANO/yedek text → aktif pin değilse SİL
    #   • Diğer bot mesajları → akıllı yöneticiye track et (geç gelen
    #     servis mesajları dahil). Sweep loop'u yaş + aktiflik kontrolü
    #     ile sonradan temizler.
    if sender_id and bot_id and sender_id == bot_id and is_group:
        try:
            from .cache_backup import _load_unified_state
            st = _load_unified_state() or {}
            cur_pin = int((st.get(str(chat_id)) or {}).get("message_id") or 0)
        except Exception:
            cur_pin = 0

        doc = msg.get("document") or {}
        fname = (doc.get("file_name") or "")
        is_backup_doc = fname.startswith("chart_") and fname.endswith(".jpg")
        text_upper = (text or "").upper()
        is_panel_text = any(s in text_upper for s in
                            ("PREDATOR", "PANO", "YEDEK", "📊"))

        if is_backup_doc:
            # Aktif pin değilse anında sil; aktifse track'e ekle (zaten ekli olabilir)
            if cur_pin and msg_id == cur_pin:
                try:
                    from . import tg_cleanup
                    tg_cleanup.track(chat_id, msg_id, kind="panel_doc")
                except Exception:
                    pass
            else:
                _tg_delete(chat_id, msg_id)
                _stats_bump("ghost_chart_clean")
                try:
                    from . import tg_cleanup
                    tg_cleanup.untrack(chat_id, msg_id)
                except Exception:
                    pass
            return

        if is_panel_text:
            if cur_pin and msg_id == cur_pin:
                try:
                    from . import tg_cleanup
                    tg_cleanup.track(chat_id, msg_id, kind="panel_text")
                except Exception:
                    pass
            else:
                _tg_delete(chat_id, msg_id)
                _stats_bump("ghost_panel_clean")
                try:
                    from . import tg_cleanup
                    tg_cleanup.untrack(chat_id, msg_id)
                except Exception:
                    pass
            return

        # Diğer bot mesajları (analiz cevapları vb.) — track et, sweep
        # zamanı geldiğinde TTL aşımına göre silinsin.
        try:
            from . import tg_cleanup
            tg_cleanup.track(chat_id, msg_id, kind="report")
        except Exception:
            pass
        return

    # Botun kendi diğer mesajları (cevapları) — moderasyon dışı
    if sender_id and bot_id and sender_id == bot_id:
        return

    # ── 1) ADMİN BAĞIŞIKLIĞI ────────────────────────────────────────────────
    is_admin = is_group and sender_id and _is_admin(chat_id, sender_id)

    # ── 2) ANTİ-FLOOD ───────────────────────────────────────────────────────
    if is_group and not is_admin and sender_id:
        if _flood_check(sender_id):
            _tg_delete(chat_id, msg_id)
            _stats_bump("delete")
            _stats_bump("flood")
            warn = _apply_strike_action(chat_id, sender_id, sender, "flood")
            wid = _tg_send_raw(chat_id, warn)
            if wid:
                _schedule_delete(chat_id, wid, after_sec=15)
            return

    # ── 3) MODERASYON ───────────────────────────────────────────────────────
    if is_group and not is_admin:
        is_new = bool(sender_id and _is_new_member(sender_id))
        violation = _moderation_violation(text, msg, is_new_member=is_new)
        if violation:
            ok = _tg_delete(chat_id, msg_id)
            if ok:
                _stats_bump("delete")
                warn = _apply_strike_action(chat_id, sender_id, sender, violation)
                uname = sender.get("username") or sender.get("first_name") or "kullanıcı"
                print(f"[PREDATOR] MOD: {violation} → {uname} "
                      f"(strike toplam={_strikes_for(sender_id)})", flush=True)
                wid = _tg_send_raw(chat_id, warn)
                if wid:
                    _schedule_delete(chat_id, wid, after_sec=15)
            return  # ihlal varsa komut işleme yapılmaz

    if not text:
        return

    # ── 4) GENEL KOMUTLAR (/yardim, /kurallar, vb.) ─────────────────────────
    cmd_response = _try_handle_command(text, sender_id=sender_id or 0,
                                       chat_id=chat_id, is_admin=is_admin)
    if cmd_response:
        # Kullanıcının komut mesajını sil (grup kalabalığı olmasın)
        if is_group and _USER_CMD_DELETE:
            _tg_delete(chat_id, msg_id)
            reply_target = None
        else:
            reply_target = msg_id
        bot_msg_id = _tg_send_raw(chat_id, cmd_response, reply_to=reply_target)
        if is_group and bot_msg_id:
            _schedule_delete(chat_id, bot_msg_id, after_sec=_AUTO_DELETE_SEC)
        return

    # ── 5) "T HISSE" KOMUTU ─────────────────────────────────────────────────
    m = re.match(r"^[/]?[Tt][\s:]+([A-Za-zÇĞİÖŞÜçğıöşü0-9]{2,8})\s*$", text)
    if not m:
        return

    code = m.group(1).upper()
    code = (code.replace("Ç", "C").replace("Ğ", "G").replace("İ", "I")
                .replace("Ö", "O").replace("Ş", "S").replace("Ü", "U"))
    if not _CODE_RE.match(code):
        return

    print(f"[PREDATOR] TG komutu: T {code} (chat={chat_id} from={sender_id})", flush=True)

    # ── Rate limiting: gruplarda admin dışı kullanıcıya 60sn içinde max 3 sorgu
    if is_group and not is_admin and sender_id:
        now_t = time.time()
        with _T_CMD_LOCK:
            lst = _T_CMD_RATE.get(sender_id, [])
            lst = [t for t in lst if now_t - t < _T_CMD_WINDOW]
            if len(lst) >= _T_CMD_MAX:
                # Limit aşıldı — sessizce yut (ya da kısa uyarı gönder)
                if is_group and _USER_CMD_DELETE:
                    _tg_delete(chat_id, msg_id)
                wait_sec = int(_T_CMD_WINDOW - (now_t - lst[0])) + 1
                warn_id = _tg_send_raw(
                    chat_id,
                    f"⏳ Çok hızlı! `T` komutunu {_T_CMD_WINDOW}sn içinde "
                    f"en fazla {_T_CMD_MAX} kez kullanabilirsin. "
                    f"~{wait_sec}sn bekle.",
                )
                if warn_id:
                    _schedule_delete(chat_id, warn_id, after_sec=10)
                return
            lst.append(now_t)
            _T_CMD_RATE[sender_id] = lst
            # Bellek temizliği
            if len(_T_CMD_RATE) > 200:
                cutoff = now_t - _T_CMD_WINDOW
                for uid in [k for k, v in _T_CMD_RATE.items()
                            if not v or max(v) < cutoff]:
                    _T_CMD_RATE.pop(uid, None)

    # Kullanıcının "T XXX" mesajını grupta tutmamak için sil
    if is_group and _USER_CMD_DELETE:
        _tg_delete(chat_id, msg_id)
        reply_target = None
    else:
        reply_target = msg_id

    try:
        report = _build_stock_report(code)
        bot_msg_id = _tg_send_raw(chat_id, report, reply_to=reply_target)
    except Exception as e:
        bot_msg_id = _tg_send_raw(chat_id, f"⚠️ *{code}* analiz hatası: {e}",
                                  reply_to=reply_target)

    # Bot cevabını _AUTO_DELETE_SEC sonra sil (grup kalabalığı olmasın)
    if is_group and bot_msg_id:
        _schedule_delete(chat_id, bot_msg_id, after_sec=_AUTO_DELETE_SEC)


def tg_listener_loop() -> None:
    """getUpdates long-polling. Komut formatı: 'T XXX' (örn 'T YIGIT')."""
    print("[PREDATOR] Telegram komut dinleyici başlatıldı.", flush=True)
    state = load_json(_TG_OFFSET_FILE, {}) or {}
    offset = int(state.get("offset", 0) or 0)

    while True:
        try:
            params = {"timeout": 30, "allowed_updates": json.dumps(
                ["message", "channel_post"])}
            if offset:
                params["offset"] = offset
            r = requests.get(f"{_TG_API}/getUpdates", params=params,
                             timeout=40, verify=True)
            if not r.ok:
                time.sleep(5); continue
            data = r.json()
            if not data.get("ok"):
                time.sleep(5); continue
            for upd in data.get("result", []) or []:
                uid = int(upd.get("update_id", 0) or 0)
                if uid >= offset:
                    offset = uid + 1
                try:
                    _process_update(upd)
                except Exception as e:
                    print(f"[PREDATOR] update işleme hatası: {e}", flush=True)
            save_json(_TG_OFFSET_FILE, {"offset": offset})
        except requests.RequestException:
            time.sleep(5)
        except Exception as e:
            print(f"[PREDATOR] TG listener hatası: {e}", flush=True)
            time.sleep(10)
