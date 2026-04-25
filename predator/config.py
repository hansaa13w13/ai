"""Tüm sabitler ve yapılandırma. PHP `define(...)` çağrılarının birebir karşılığı."""
from __future__ import annotations
import os
from pathlib import Path

# ── Dizinler ───────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
# DATA_DIR env var → Docker/Render.com kalıcı disk desteği
CACHE_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "cache")))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── .env dosyası okuma (PHP dosyasının başındaki blokla aynı) ──────────────
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        _k = _k.strip()
        _v = _v.strip().strip('"').strip("'")
        if _k and _k not in os.environ:
            os.environ[_k] = _v

# ── Telegram ───────────────────────────────────────────────────────────────
# Render.com / GitHub deploy'unu kolaylaştırmak için TG_BOT_TOKEN ve TG_CHAT_ID
# burada gömülü. Env var verilirse o öncelikli (override), verilmezse aşağıdaki
# sabit değerler kullanılır. Bot'u/grubu değiştirmek istersen ya bu satırları
# güncelle ya da deploy ortamında TG_BOT_TOKEN / TG_CHAT_ID env var'larını set et.
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "8685592596:AAFlccSlDtVkWupFYgHjx7Wys0SS7QkqPfA").strip() or None
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "-1003862928146").strip() or None


def validate_secrets(strict: bool = False) -> dict:
    """Startup secret denetimi.

    strict=True ise eksik kritik secret bulunursa SystemExit fırlatır
    (örn. PREDATOR_STRICT_SECRETS=1 ortam değişkeni ile).
    Aksi halde uyarı loglar; çağıran tarafta TG çağrıları zaten None token'la
    no-op'a düşer.
    """
    missing: list[str] = []
    if not TG_BOT_TOKEN:
        missing.append("TG_BOT_TOKEN")
    if not TG_CHAT_ID:
        missing.append("TG_CHAT_ID")
    if missing:
        msg = ("KRITIK: Telegram secret eksik: " + ", ".join(missing) +
               " — TG yedekleme/bildirim devre dışı.")
        if strict or os.getenv("PREDATOR_STRICT_SECRETS") == "1":
            raise SystemExit(msg)
        try:
            from .observability import log_event
            log_event("config", msg, level="critical", missing=missing)
        except Exception:
            print(f"[config] {msg}", flush=True)
    return {"ok": not missing, "missing": missing}

# ── API uç noktaları ───────────────────────────────────────────────────────
API_BASE_URL = "https://apiyi.idealdata.com.tr"
API_REFERER = "https://burganyi.idealdata.com.tr/"
BURGAN_API_URL = "https://api-public.burganyatirim.com.tr/web/arastirma/sirket-karti"

# ── Cache dosya yolları ────────────────────────────────────────────────────
ALLSTOCKS_CACHE   = CACHE_DIR / "predator_allstocks_cache.json"
TG_DEDUP_FILE     = CACHE_DIR / "predator_tg_dedup.json"
OTO_FILE          = CACHE_DIR / "predator_oto_portfolio.json"
OTO_LOG_FILE      = CACHE_DIR / "predator_oto_log.json"
SIGNAL_HISTORY_FILE = CACHE_DIR / "predator_signal_history.json"
MARKET_MODE_FILE  = CACHE_DIR / "predator_market_mode.json"
AI_PERF_FILE      = CACHE_DIR / "predator_ai_performance.json"
VOLATILITY_FILE   = CACHE_DIR / "predator_volatility.json"
AI_BRAIN_FILE     = CACHE_DIR / "predator_ai_brain.json"
SMC_CACHE_FILE    = CACHE_DIR / "predator_smc_cache.json"
MTF_CACHE_FILE    = CACHE_DIR / "predator_mtf_cache.json"
VOLPROFILE_CACHE  = CACHE_DIR / "predator_volprofile_cache.json"
MONTE_CARLO_CACHE = CACHE_DIR / "predator_montecarlo_cache.json"
KELLY_LOG_FILE    = CACHE_DIR / "predator_kelly_log.json"
SCAN_LOCK_FILE    = CACHE_DIR / "predator_scan.lock"
SCAN_LOCK_TTL     = 480
ADAPTIVE_VOL_FILE = CACHE_DIR / "predator_adaptive_vol.json"
OFI_CACHE_FILE    = CACHE_DIR / "predator_ofi_cache.json"
SERVER_PORT_FILE  = CACHE_DIR / "predator_server_port.txt"
AUTO_STATUS_FILE  = CACHE_DIR / "predator_auto_status.json"
AUTO_LOG_FILE     = CACHE_DIR / "predator_auto_log.json"
SCAN_PROGRESS_FILE = Path("/tmp") / "predator_scan_progress.json"

# ── Sprint Modu / Oto-trade sabitleri ──────────────────────────────────────
OTO_MAX_POSITIONS  = 1
OTO_MIN_SCORE      = 60
OTO_MIN_RR         = 1.5
OTO_ROTATION_SCORE = 25
OTO_ROTATION_PNL   = 3.0
OTO_SPRINT_MODE    = True
OTO_MAX_HOLD_DAYS  = 4
OTO_H1_AUTO_SELL   = True
OTO_PORTFOLIO_VALUE = 100_000.0
OTO_MAX_RISK_PCT   = 0.02

# ── Skor ağırlıkları ───────────────────────────────────────────────────────
W_TEKNIK    = 0.35
W_TEMEL     = 0.25
W_MOMENTUM  = 0.20
W_FORMASYON = 0.10
W_HACIM     = 0.10

# ── Sektör kategorileri ────────────────────────────────────────────────────
SEKTOR_BANKA       = "banka"
SEKTOR_TEKNOLOJI   = "teknoloji"
SEKTOR_ENERJI      = "enerji"
SEKTOR_PERAKENDE   = "perakende"
SEKTOR_INSAAT      = "insaat"
SEKTOR_GAYRIMENKUL = "gayrimenkul"
SEKTOR_HOLDING     = "holding"
SEKTOR_SIGORTA     = "sigorta"
SEKTOR_TEKSTIL     = "tekstil"
SEKTOR_KIMYA       = "kimya"
SEKTOR_GIDA        = "gida"
SEKTOR_METAL       = "metal"
SEKTOR_ULASIM      = "ulasim"
SEKTOR_ILETISIM    = "iletisim"
SEKTOR_TURIZM      = "turizm"
SEKTOR_KAGIT       = "kagit"
SEKTOR_MOBILYA     = "mobilya"
SEKTOR_SAGLIK      = "saglik"
SEKTOR_SPOR        = "spor"
SEKTOR_GENEL       = "genel"

# ── Daemon ayarları ────────────────────────────────────────────────────────
DAEMON_MARKET_FROM = 600   # 10:00
DAEMON_MARKET_TO   = 1115  # 18:35
DAEMON_INT_MARKET  = 300
DAEMON_INT_CLOSED  = 300
DAEMON_TRAIN_INT   = 3600
DAEMON_MAX_WAIT    = 540

TIMEZONE = "Europe/Istanbul"
