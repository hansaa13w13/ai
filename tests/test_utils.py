"""predator.utils — sayı parse, JSON I/O, kilit, Graham, quantile."""
from __future__ import annotations
import math
import threading
import time
from pathlib import Path

import pytest

from predator import utils


class TestParseApiNum:
    def test_int_and_float(self):
        assert utils.parse_api_num(5) == 5.0
        assert utils.parse_api_num(3.14) == pytest.approx(3.14)

    def test_none_empty_false(self):
        assert utils.parse_api_num(None) == 0.0
        assert utils.parse_api_num("") == 0.0
        assert utils.parse_api_num(False) == 0.0

    def test_string_with_commas_and_spaces(self):
        # PHP-uyumlu: "1,234.56" → 1234.56, NBSP ve normal boşluklar atılır.
        assert utils.parse_api_num("1,234.56") == pytest.approx(1234.56)
        assert utils.parse_api_num("1\xa0234,5") == pytest.approx(12345.0)

    def test_garbage_returns_zero(self):
        assert utils.parse_api_num("abc") == 0.0
        assert utils.parse_api_num([]) == 0.0

    def test_nan_inf_neutralized(self):
        assert utils.parse_api_num(float("nan")) == 0.0
        assert utils.parse_api_num(float("inf")) == 0.0


class TestSafeFloatInt:
    def test_safe_float_default_on_bad(self):
        assert utils.safe_float("x", 1.5) == 1.5
        assert utils.safe_float(float("nan"), 9.0) == 9.0

    def test_safe_int_truncates_float_string(self):
        assert utils.safe_int("3.9") == 3
        assert utils.safe_int("oops", -1) == -1


class TestJsonIO:
    def test_save_and_load_roundtrip(self, tmp_path):
        p = tmp_path / "data.json"
        payload = {"a": 1, "b": [1, 2, 3], "c": "ç"}
        assert utils.save_json(p, payload) is True
        assert utils.load_json(p) == payload

    def test_load_missing_returns_default(self, tmp_path):
        p = tmp_path / "missing.json"
        assert utils.load_json(p, default=[]) == []
        assert utils.load_json(p) == {}

    def test_corrupt_json_returns_default(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json")
        assert utils.load_json(p, default={"safe": True}) == {"safe": True}

    def test_save_handles_numpy(self, tmp_path):
        np = pytest.importorskip("numpy")
        p = tmp_path / "np.json"
        data = {"arr": np.array([1, 2, 3]), "f": np.float64(1.5),
                "i": np.int32(7), "b": np.bool_(True)}
        assert utils.save_json(p, data) is True
        loaded = utils.load_json(p)
        assert loaded == {"arr": [1, 2, 3], "f": 1.5, "i": 7, "b": True}


class TestQuantile:
    def test_empty(self):
        assert utils.quantile([], 0.5) == 0.0

    def test_median_odd(self):
        assert utils.quantile([1, 2, 3, 4, 5], 0.5) == 3.0

    def test_quartiles_even(self):
        # PHP linear interpolation: q*(n-1)
        assert utils.quantile([1, 2, 3, 4], 0.0) == 1.0
        assert utils.quantile([1, 2, 3, 4], 1.0) == 4.0
        assert utils.quantile([1, 2, 3, 4], 0.5) == pytest.approx(2.5)


class TestGraham:
    def test_zero_equity_returns_zero(self):
        assert utils.calculate_graham(100, 0, 1000) == 0.0
        assert utils.calculate_graham(100, 1000, 0) == 0.0

    def test_negative_profit_uses_book_floor(self):
        # net_kar<=0 → BVPS * 0.4 döner.
        out = utils.calculate_graham(-50, 1000, 100)  # bvps=10 → 4.0
        assert out == pytest.approx(4.0)

    def test_positive_growth_returns_finite(self):
        out = utils.calculate_graham(100, 1000, 100, roe=20.0, fiyat=20.0)
        # Üst sınır fiyat*3 = 60; alt sınır bvps*0.4 = 4
        assert 4.0 <= out <= 60.0

    def test_positive_growth_caps_kick_in(self):
        # Yüksek kâr + düşük fiyat → fiyat*3 cap aktif olsun (bvps*0.4 küçük)
        out = utils.calculate_graham(net_kar=10, oz_sermaye=10, sermaye=1,
                                     roe=20.0, fiyat=2.0)
        assert out <= 6.0  # fiyat*3


class TestSafeStrDecode:
    def test_passthrough_str(self):
        assert utils.safe_str_decode("merhaba") == "merhaba"

    def test_none_to_empty(self):
        assert utils.safe_str_decode(None) == ""

    def test_bytes_utf8(self):
        assert utils.safe_str_decode("şehir".encode("utf-8")) == "şehir"

    def test_bytes_iso8859_9(self):
        # Türkçe karakter ISO-8859-9 ile encode → decode başarısız olunca
        # alternatif encoding'ler denenir.
        raw = "şehir".encode("iso-8859-9")
        out = utils.safe_str_decode(raw)
        assert "ehir" in out or "şehir" in out  # fallback bir şey döner


class TestScanLock:
    def test_acquire_release(self, tmp_path):
        lock = utils.ScanLock(path=tmp_path / "lock", ttl=60)
        assert lock.acquire() is True
        assert (tmp_path / "lock").exists()
        lock.release()
        assert not (tmp_path / "lock").exists()

    def test_busy_lock_rejected(self, tmp_path):
        path = tmp_path / "lock2"
        a = utils.ScanLock(path=path, ttl=60)
        b = utils.ScanLock(path=path, ttl=60)
        assert a.acquire() is True
        assert b.acquire() is False
        a.release()
        assert b.acquire() is True

    def test_stale_lock_takeover(self, tmp_path):
        path = tmp_path / "lock3"
        # Çok eski bir kilit yaz (ttl=1, mtime 5 sn geride)
        path.write_text("123")
        old = time.time() - 60
        import os
        os.utime(path, (old, old))
        lock = utils.ScanLock(path=path, ttl=1)
        assert lock.acquire() is True

    def test_context_manager(self, tmp_path):
        path = tmp_path / "lock4"
        with utils.ScanLock(path=path, ttl=60):
            assert path.exists()
        assert not path.exists()


class TestBusinessDays:
    def test_invalid_date_returns_zero(self):
        assert utils.count_business_days("not-a-date") == 0
        assert utils.count_business_days("") == 0

    def test_future_date_returns_zero(self):
        # Gelecek tarih → cur >= end → 0
        future = (utils.now_tr().date().isoformat())
        assert utils.count_business_days(future) == 0
