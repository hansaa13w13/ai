"""predator.sectors — kod→sektör, API metni→sektör, piyasa grup eşleme."""
from __future__ import annotations

from predator import config, sectors


class TestGetSectorGroup:
    def test_bank_codes(self):
        assert sectors.get_sector_group("AKBNK") == config.SEKTOR_BANKA
        assert sectors.get_sector_group("GARAN") == config.SEKTOR_BANKA

    def test_tech_codes(self):
        assert sectors.get_sector_group("ASELS") == config.SEKTOR_TEKNOLOJI

    def test_unknown_falls_to_genel(self):
        assert sectors.get_sector_group("XYZWQ") == config.SEKTOR_GENEL

    def test_empty_returns_genel(self):
        assert sectors.get_sector_group("") == config.SEKTOR_GENEL


class TestApiSektorToIntern:
    def test_sigorta(self):
        assert sectors.api_sektor_to_intern("Sigorta Faaliyetleri") == config.SEKTOR_SIGORTA

    def test_iletisim_before_bilgi(self):
        # Sıralama kritik — "Telekomünikasyon" iletişimdir, teknoloji değil.
        assert sectors.api_sektor_to_intern("Telekomünikasyon") == config.SEKTOR_ILETISIM

    def test_kimya_includes_ilac(self):
        assert sectors.api_sektor_to_intern("İlaç") == config.SEKTOR_KIMYA
        assert sectors.api_sektor_to_intern("Plastik Ürünler") == config.SEKTOR_KIMYA

    def test_enerji_petrokimya(self):
        assert sectors.api_sektor_to_intern("Petrol Ürünleri") == config.SEKTOR_ENERJI

    def test_elektronik_is_teknoloji_not_enerji(self):
        # "ELEKTR" yakalama "ELEKTRONIK" hariç olmalı.
        assert sectors.api_sektor_to_intern("Elektronik Cihazlar") == config.SEKTOR_TEKNOLOJI

    def test_empty_default(self):
        assert sectors.api_sektor_to_intern("") == config.SEKTOR_GENEL
        assert sectors.api_sektor_to_intern(None) == config.SEKTOR_GENEL  # type: ignore[arg-type]


class TestPiyasaToGrup:
    def test_yildiz(self):
        assert sectors.piyasa_to_grup("Yıldız Pazar") == "Y"

    def test_ana(self):
        assert sectors.piyasa_to_grup("Ana Pazar") == "A"

    def test_alt(self):
        assert sectors.piyasa_to_grup("Alt Pazar") == "ALT"

    def test_empty(self):
        assert sectors.piyasa_to_grup("") == "DIGER"


class TestSektorFromAd:
    def test_banka(self):
        # "BANKASI" → "BANKA" alt-dizesini içerir
        assert sectors.sektor_from_ad("İş Bankası A.Ş.") == config.SEKTOR_BANKA

    def test_sigorta(self):
        # str.upper() Python'da "i"→"I" yapar, "İ" üretmez; bu yüzden test
        # zaten BÜYÜK Türkçe harflerle başlatılmış metin verir.
        assert sectors.sektor_from_ad("Anadolu SİGORTA") == config.SEKTOR_SIGORTA

    def test_unknown(self):
        assert sectors.sektor_from_ad("Bilinmeyen Şirket") == config.SEKTOR_GENEL
