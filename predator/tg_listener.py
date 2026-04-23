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
        r = requests.get(f"{_TG_API}/getMe", timeout=10, verify=False)
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
                 reply_to: int | None = None) -> int | None:
    """Doğrudan Telegram'a gönder. Mesaj başarılıysa message_id döner, değilse None."""
    if not text:
        return None
    data = {"chat_id": str(chat_id), "text": text, "parse_mode": "Markdown",
            "disable_web_page_preview": "true"}
    if reply_to:
        data["reply_to_message_id"] = str(reply_to)
    try:
        r = requests.post(f"{_TG_API}/sendMessage", data=data, timeout=15, verify=False)
        if r.ok:
            j = r.json()
            if j.get("ok"):
                return ((j.get("result") or {}).get("message_id"))
    except requests.RequestException:
        pass
    return None


def _tg_delete(chat_id: str | int, message_id: int) -> bool:
    if not message_id:
        return False
    try:
        r = requests.post(f"{_TG_API}/deleteMessage",
                          data={"chat_id": str(chat_id), "message_id": str(message_id)},
                          timeout=10, verify=False)
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
            timeout=10, verify=False)
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
            timeout=10, verify=False)
        return r.ok and '"ok":true' in r.text
    except requests.RequestException:
        return False


def _tg_unpin(chat_id: str | int, message_id: int) -> bool:
    try:
        r = requests.post(
            f"{_TG_API}/unpinChatMessage",
            data={"chat_id": str(chat_id), "message_id": str(message_id)},
            timeout=10, verify=False)
        return r.ok
    except requests.RequestException:
        return False


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
    msg = f"📌 *PREDATOR — CANLI PORTFÖY PANOSU*\n"
    msg += f"_Güncelleme: {n.strftime('%d.%m.%Y %H:%M')}_\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    try:
        oto = oto_load()
    except Exception as e:
        return msg + f"_Pano okunamadı: {e}_"
    positions = oto.get("positions", {}) or {}
    if not positions:
        msg += "💤 *Açık pozisyon yok* — AI fırsat tarıyor.\n"
    else:
        total_pnl = 0.0
        for code, pos in positions.items():
            pnl = float(pos.get("pnl_pct", 0) or 0)
            total_pnl += pnl
            sign = "+" if pnl >= 0 else ""
            entry = float(pos.get("entry", 0) or 0)
            cur = float(pos.get("guncel", 0) or 0)
            h1 = float(pos.get("h1", 0) or 0)
            stop = float(pos.get("stop", 0) or 0)
            ai_live = pos.get("ai_decision_live", "")
            h1_hit = " ✅H1" if pos.get("h1_hit") else ""
            ai_tag = f" · AI:{ai_live}" if ai_live else ""
            msg += (f"*{code}* {sign}{pnl:.2f}%{h1_hit}\n"
                    f"  Giriş:{entry:.2f}₺ → Şu an:{cur:.2f}₺\n"
                    f"  H1:{h1:.2f}₺  Stop:{stop:.2f}₺{ai_tag}\n")
        avg = total_pnl / len(positions)
        msg += f"\n📊 Ort. K/Z: *{('+' if avg >= 0 else '')}{avg:.2f}%*\n"
    stats = oto.get("stats", {}) or {}
    t = int(stats.get("total_trades", 0) or 0)
    if t > 0:
        wr = round(stats.get("wins", 0) / t * 100, 1)
        msg += f"📈 Tarihsel: {t} işlem · %{wr} kazanma\n"
    msg += "\n💡 _Komut: `T HISSE` (örn `T ARENA`) → anlık AI raporu_"
    return msg


def _ensure_pinned_board(chat_id: str | int) -> None:
    """Sabit panonun varlığını sağla; varsa içeriği güncelle, yoksa gönder + pinle."""
    state = load_json(_PIN_STATE_FILE, {}) or {}
    chat_key = str(chat_id)
    pin_id = (state.get(chat_key) or {}).get("message_id")
    text = _build_position_board()

    if pin_id:
        if _tg_edit(chat_id, int(pin_id), text):
            return
        # Eski mesaj silinmiş olabilir — yeniden gönder
        _tg_unpin(chat_id, int(pin_id))

    new_id = _tg_send_raw(chat_id, text)
    if not new_id:
        return
    if _tg_pin(chat_id, new_id, disable_notification=True):
        state[chat_key] = {"message_id": new_id, "ts": int(time.time())}
        save_json(_PIN_STATE_FILE, state)


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
def _moderation_violation(text: str, msg: dict) -> str | None:
    """Mesaj kural ihlali içeriyorsa kısa açıklama döner, temizse None."""
    if not text:
        # Medya/sticker spam — şimdilik dokunma, kısa metin yoksa geç
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

    # Forward edilen mesaj (başka kanaldan reklam)
    if msg.get("forward_from") or msg.get("forward_from_chat") or msg.get("forward_origin"):
        return "forward"

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

    msg = f"🌅 *GÜNAYDIN — {n.strftime('%d.%m.%Y %A')}*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    # Top 5 fırsat
    msg += "🎯 *BUGÜNÜN İLK 5 FIRSATI*\n"
    if not picks:
        msg += "_Henüz tarama verisi yok._\n"
    else:
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
            msg += (f"{i}. *{code}* — Skor:{score} · RR:{rr} · AI:{ai} (%{conf})\n"
                    f"   Fiyat:{cur:.2f}₺ → H1:{h1:.2f}₺ (+%{up_pct:.1f}) · Stop:{stop:.2f}₺\n")

    # Portföy
    msg += "\n💼 *PORTFÖY DURUMU*\n"
    try:
        oto = oto_load()
        positions = oto.get("positions", {}) or {}
        if not positions:
            msg += "_Açık pozisyon yok — AI fırsat bekliyor._\n"
        else:
            total_pnl = 0.0
            for code, pos in positions.items():
                pnl = float(pos.get("pnl_pct", 0) or 0)
                total_pnl += pnl
                sign = "+" if pnl >= 0 else ""
                h1_hit = " ✅" if pos.get("h1_hit") else ""
                msg += (f"• *{code}* {sign}{pnl:.2f}%{h1_hit}  "
                        f"Giriş:{float(pos.get('entry', 0)):.2f}₺ · H1:{float(pos.get('h1', 0)):.2f}₺\n")
            avg = total_pnl / len(positions)
            msg += f"\nOrt. K/Z: *{('+' if avg >= 0 else '')}{avg:.2f}%*\n"

        stats = oto.get("stats", {}) or {}
        t = int(stats.get("total_trades", 0) or 0)
        if t > 0:
            wr = round(stats.get("wins", 0) / t * 100, 1)
            msg += f"📈 Tarihsel: {t} işlem · %{wr} kazanma\n"
    except Exception as e:
        msg += f"_Portföy okunamadı: {e}_\n"

    msg += "\n💡 _Borsa 10:00'da açılıyor — iyi şanslar!_"
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
            return (f"⚠️ *{code}* — analiz başarısız.\n"
                    f"_Hisse BIST'te kayıtlı ama veri çekilemedi (API yanıt vermedi)._"
                    + tg_footer())
        return (f"❓ *{code}* — BIST'te bulunamadı.\n"
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

        msg = f"📋 *{code}* — YÜZEYSEL TARAMA\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        if cur > 0:
            msg += f"💰 Canlı fiyat: *{cur:.2f}₺*\n"
        msg += f"📊 Tarama skoru: *{score}* / 350\n"
        if sektor and sektor != "?":
            msg += f"🏷️ Sektör: {sektor}\n"
        msg += "\n"
        msg += ("ℹ️ Bu hisse tam BIST taramasında yer aldı ancak "
                f"*top 200 fırsat listesine giremediği* için derin analiz "
                f"(AI kararı, hedef, stop, RSI, hacim, formasyon) yapılmadı.\n\n")
        if score < 60:
            msg += "🔴 *AI değerlendirmesi:* Skor eşiğinin (60) altında — şu an alım için uygun değil.\n"
        elif score < 100:
            msg += "🟡 *AI değerlendirmesi:* Sınırda skor — güçlü sinyal yok.\n"
        else:
            msg += "🟢 *AI değerlendirmesi:* Orta skor — dip toparlanma adayı olabilir.\n"
        msg += ("\n💡 _Derin analiz için bir sonraki tarama döngüsünde top picks'e "
                "girmesi gerekir._")
        msg += tg_footer()
        return msg

    icon = {"GÜÇLÜ AL": "🟢🟢", "AL": "🟢", "NÖTR": "⚪",
            "DİKKAT": "🟡", "KAÇIN": "🔴"}.get(ai, "⚪")

    up_pct = ((h1 - cur) / cur * 100) if cur > 0 else 0
    risk_pct = ((cur - stop) / cur * 100) if cur > 0 and stop > 0 else 0

    msg = f"{icon} *{code}* — AI ANALİZ\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"💰 Fiyat: *{cur:.2f}₺* · Sektör: {sektor}\n"
    msg += f"📊 Skor: *{score}* · RR: *{rr}* · Sinyal Kalite: {sq}/10\n"
    msg += f"🤖 AI: *{ai}* · Güven: *%{conf}*\n\n"

    msg += "🎯 *HEDEFLER*\n"
    msg += f"• H1: {h1:.2f}₺ (+%{up_pct:.1f})\n"
    if h2 > 0: msg += f"• H2: {h2:.2f}₺\n"
    if h3 > 0: msg += f"• H3: {h3:.2f}₺\n"
    msg += f"• Stop: {stop:.2f}₺ (−%{risk_pct:.1f})\n\n"

    msg += "📈 *TEKNİK*\n"
    msg += f"• Trend: {trend}\n"
    msg += f"• RSI: {rsi:.1f}\n"
    msg += f"• Hacim: {vol:.2f}x ortalama\n"
    msg += f"• 52H Pozisyon: %{pos52:.0f}\n"

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
                msg += "\n💡 *GEREKÇELER*\n"
                for p in parts:
                    msg += f"• {p}\n"
        cscore = cons.get("consensus") if isinstance(cons, dict) else None
        if cscore is not None:
            msg += f"\n🧠 Konsensüs Skor: *{cscore}*"
    except Exception:
        pass

    msg += tg_footer()
    return msg


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
    # Botun kendi mesajları (cevapları) — moderasyon dışı
    if sender_id and bot_id and sender_id == bot_id:
        return

    # ── 1) MODERASYON ───────────────────────────────────────────────────────
    chat_type = chat.get("type", "")
    is_group = chat_type in ("group", "supergroup", "channel")
    if is_group:
        violation = _moderation_violation(text, msg)
        if violation:
            ok = _tg_delete(chat_id, msg_id)
            uname = sender.get("username") or sender.get("first_name") or "kullanıcı"
            label_map = {
                "link": "🔗 Link/URL paylaşımı",
                "mention": "📢 Başka kanal/bot etiketi",
                "forward": "↪️ Başka kanaldan iletme",
                "reklam": "📣 Reklam içeriği",
                "küfür": "🚫 Küfür",
                "caps_spam": "🔠 CAPS spam",
            }
            warn_label = label_map.get(violation, violation)
            print(f"[PREDATOR] MOD: {violation} → {uname} (silindi={ok})", flush=True)
            if ok:
                # 10 sn kalıp silinen kısa uyarı yaz
                warn = (f"⚠️ *Moderasyon* — @{uname} kullanıcısının mesajı silindi\n"
                        f"Sebep: {warn_label}\n"
                        f"_Bu uyarı 10 sn sonra silinecek._")
                wid = _tg_send_raw(chat_id, warn)
                if wid:
                    _schedule_delete(chat_id, wid, after_sec=10)
            return  # ihlal varsa komut işleme yapılmaz

    if not text:
        return

    # ── 2) "T HISSE" KOMUTU ─────────────────────────────────────────────────
    m = re.match(r"^[/]?[Tt][\s:]+([A-Za-zÇĞİÖŞÜçğıöşü0-9]{2,8})\s*$", text)
    if not m:
        return

    code = m.group(1).upper()
    code = (code.replace("Ç", "C").replace("Ğ", "G").replace("İ", "I")
                .replace("Ö", "O").replace("Ş", "S").replace("Ü", "U"))
    if not _CODE_RE.match(code):
        return

    print(f"[PREDATOR] TG komutu: T {code} (chat={chat_id} from={sender_id})", flush=True)

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
                             timeout=40, verify=False)
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
