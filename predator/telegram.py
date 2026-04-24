"""Telegram istemci — dedup destekli mesaj gönderimi."""
from __future__ import annotations
import hashlib
import re
import time

from . import config
from .utils import load_json, save_json, tg_footer
from .http_utils import safe_request
from .observability import log_event

_DEDUP_TTL_DEFAULT = 3600
_DEDUP_TTL_OZET4 = 14400
_DEDUP_TTL_PREFIX = 21600


def send_tg(msg: str) -> bool:
    """PHP sendTgSimple birebir karşılığı. Aynı içeriği TTL içinde tekrar göndermez."""
    if not msg:
        return False
    msg = msg.strip()

    dedup = load_json(config.TG_DEDUP_FILE, {})
    if not isinstance(dedup, dict):
        dedup = {}

    dedup_key = None
    m = re.match(r"^(__[a-z_]+_[A-Z0-9]+__)", msg)
    if m:
        dedup_key = m.group(1)
        msg = msg[len(dedup_key):].strip()

    h = hashlib.md5((dedup_key or msg).encode("utf-8")).hexdigest()
    now = int(time.time())
    if dedup_key:
        ttl = _DEDUP_TTL_OZET4 if "_ozet4_" in dedup_key else _DEDUP_TTL_PREFIX
    else:
        ttl = _DEDUP_TTL_DEFAULT

    if h in dedup and (now - dedup[h]) < ttl:
        return False

    if not config.TG_BOT_TOKEN or not config.TG_CHAT_ID:
        log_event("tg", "send_tg skipped — TG secret missing", level="warn")
        return False

    r = safe_request(
        "POST",
        f"https://api.telegram.org/bot{config.TG_BOT_TOKEN}/sendMessage",
        data={
            "chat_id": config.TG_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown",
        },
        timeout=10, retries=3, backoff=0.5, metric_kind="tg_send",
    )
    ok = bool(r and r.ok and '"ok":true' in r.text)

    if ok:
        dedup[h] = now
        # 24 saatten eski kayıtları temizle
        cutoff = now - 86400
        dedup = {k: v for k, v in dedup.items() if v > cutoff}
        save_json(config.TG_DEDUP_FILE, dedup)
    return ok


def send_oto_tg(msg: str) -> bool:
    return send_tg(msg)
