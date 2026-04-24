"""Merkezi HTTP istemci — verify=True (TLS doğrulama açık) + retry/backoff.

Tüm dış API çağrıları (Telegram, idealdata, burgan) bu sarıcıdan geçer.
Eski `verify=False` kullanımı güvenlik riskiydi (MITM); artık certifi CA
bundle'ı ile doğrulama yapılır. Sertifika hatası `requests.exceptions.SSLError`
fırlatır — observability'ye loglanır.

Retry stratejisi:
  • Yalnızca ağ hatası (Connection/Timeout/SSL) ve 5xx için yeniden dener.
  • 4xx istemci hatasıdır → tek atışta döner (yeniden denemenin anlamı yok).
  • Üstel geri çekilme: 0.5s, 1s, 2s, ... + ±%20 jitter.
"""
from __future__ import annotations
import random
import time
import requests
from typing import Any

from .observability import log_event, log_exc, metric_inc, metric_observe

_DEFAULT_RETRIES = 3
_DEFAULT_BACKOFF = 0.5
_DEFAULT_TIMEOUT = 12


class HttpRetryExhausted(Exception):
    """Tüm retry'lar tükendiğinde fırlar — son istisnayı `cause` ile saklar."""
    def __init__(self, msg: str, cause: BaseException | None = None):
        super().__init__(msg)
        self.cause = cause


def _is_retriable(exc: BaseException | None, status: int | None) -> bool:
    if exc is not None:
        if isinstance(exc, (requests.ConnectionError, requests.Timeout,
                            requests.exceptions.ChunkedEncodingError)):
            return True
        # SSL hatası: sertifika gerçekten geçersizse retry işe yaramaz; ama
        # bazı sağlayıcılar OCSP/zincir geçici aksatır → 1 deneme şansı verelim.
        if isinstance(exc, requests.exceptions.SSLError):
            return True
        return False
    if status is not None and 500 <= status < 600:
        return True
    return False


def safe_request(method: str, url: str, *,
                 retries: int = _DEFAULT_RETRIES,
                 backoff: float = _DEFAULT_BACKOFF,
                 timeout: float | tuple = _DEFAULT_TIMEOUT,
                 session: requests.Session | None = None,
                 raise_on_fail: bool = False,
                 metric_kind: str = "http",
                 **kwargs: Any) -> requests.Response | None:
    """Tüm dış HTTP çağrıları için tek giriş noktası.

    `verify` parametresi varsayılan True'dur — explicit override gerekirse
    kwargs'ta geçilebilir (örn. self-signed dev sunucuları için).
    """
    kwargs.setdefault("verify", True)
    sess = session or requests
    last_exc: BaseException | None = None
    last_status: int | None = None
    t0 = time.time()
    for attempt in range(1, retries + 1):
        try:
            resp = sess.request(method, url, timeout=timeout, **kwargs)
            last_status = resp.status_code
            if not _is_retriable(None, resp.status_code):
                metric_inc(f"{metric_kind}.requests_total")
                metric_inc(f"{metric_kind}.status_{(resp.status_code // 100)}xx")
                metric_observe(f"{metric_kind}.duration_sec", time.time() - t0)
                return resp
            # 5xx → log ve retry
            log_event(metric_kind, "5xx response, retrying",
                      level="warn", url=_safe_url(url), attempt=attempt,
                      status=resp.status_code)
        except requests.RequestException as e:
            last_exc = e
            if not _is_retriable(e, None):
                log_exc(metric_kind, f"non-retriable request error: {e}", e,
                        url=_safe_url(url))
                metric_inc(f"{metric_kind}.errors_total")
                if raise_on_fail:
                    raise
                return None
            log_event(metric_kind, f"retriable error: {type(e).__name__}",
                      level="warn", url=_safe_url(url), attempt=attempt,
                      err=str(e)[:120])
        if attempt >= retries:
            break
        sleep = backoff * (2 ** (attempt - 1))
        sleep *= (1.0 + random.uniform(-0.2, 0.2))
        time.sleep(max(0.05, sleep))
    metric_inc(f"{metric_kind}.exhausted_total")
    metric_observe(f"{metric_kind}.duration_sec", time.time() - t0)
    log_event(metric_kind, "retry exhausted", level="error",
              url=_safe_url(url), attempts=retries,
              last_status=last_status,
              last_exc=type(last_exc).__name__ if last_exc else None)
    if raise_on_fail:
        raise HttpRetryExhausted(f"retry exhausted after {retries}", last_exc)
    return None


def _safe_url(url: str) -> str:
    """Token gibi sırları log'a sızdırma — bot URL'sinde token kısmını maskele."""
    if "/bot" in url and ":" in url:
        try:
            head, rest = url.split("/bot", 1)
            tok, tail = rest.split("/", 1)
            tok_safe = tok[:4] + "***" + tok[-4:] if len(tok) > 8 else "***"
            return f"{head}/bot{tok_safe}/{tail}"
        except Exception:
            return url[:64] + "..."
    return url[:200]


def safe_get(url: str, **kwargs: Any) -> requests.Response | None:
    return safe_request("GET", url, **kwargs)


def safe_post(url: str, **kwargs: Any) -> requests.Response | None:
    return safe_request("POST", url, **kwargs)
