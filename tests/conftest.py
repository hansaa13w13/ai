"""Test ortak fixtures — cache dizini izolasyonu vb."""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Proje kökünü PYTHONPATH'e ekle
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Her test kendi tmp cache dizinine sahip olsun → diskteki gerçek
    cache/predator_*.json dosyalarına dokunulmaz."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    from predator import config as _cfg
    monkeypatch.setattr(_cfg, "CACHE_DIR", cache_dir, raising=False)
    monkeypatch.setattr(_cfg, "AI_BRAIN_FILE", cache_dir / "brain.json", raising=False)
    monkeypatch.setattr(_cfg, "OTO_PORTFOLIO_FILE", cache_dir / "oto.json", raising=False)
    monkeypatch.setattr(_cfg, "OTO_LOG_FILE", cache_dir / "oto_log.json", raising=False)
    monkeypatch.setattr(_cfg, "KELLY_LOG_FILE", cache_dir / "kelly.json", raising=False)
    monkeypatch.setattr(_cfg, "SCAN_LOCK_FILE", cache_dir / "scan.lock", raising=False)
    yield cache_dir
