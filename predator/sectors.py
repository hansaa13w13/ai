"""BIST hisse → sektör haritalama. PHP getSectorGroup fonksiyonunun karşılığı."""
from __future__ import annotations
from . import config

# Anahtar kelime → sektör eşlemesi (PHP'de manuel kuralları taklit eder)
_SECTOR_RULES: list[tuple[tuple[str, ...], str]] = [
    (("BANK", "FINBN", "ALBRK", "AKBNK", "GARAN", "ISCTR", "YKBNK", "HALKB", "VAKBN", "SKBNK", "ICBCT", "QNBFB", "TSKB"), config.SEKTOR_BANKA),
    (("TEKN", "INNVA", "LOGO", "INDES", "DESPC", "ARENA", "KAREL", "NETAS", "ASELS", "ARMDA", "DGATE", "PAPIL", "FONET", "PLTUR"), config.SEKTOR_TEKNOLOJI),
    (("ENERJ", "AKENR", "AKSEN", "AYDEM", "AYEN", "BIOEN", "ENJSA", "GWIND", "IZENR", "MAGEN", "NATEN", "ZOREN", "PETKM", "TUPRS", "TRKSN", "ESEN", "ODAS", "PAMEL"), config.SEKTOR_ENERJI),
    (("BIMAS", "MGROS", "SOKM", "MAVI", "PASEU", "BIZIM", "TKNSA", "VAKKO", "DERIM"), config.SEKTOR_PERAKENDE),
    (("ENKAI", "TURGG", "OYAKC", "AKSGY", "GUBRF", "EDIP", "ANELE", "BORLS", "GENIL", "INTEM", "KUYAS", "TURGG", "ULAS"), config.SEKTOR_INSAAT),
    (("GYO", "EKGYO", "ISGYO", "AKMGY", "ALGYO", "ATAGY", "AVGYO", "DZGYO", "HLGYO", "IDGYO", "KLGYO", "KZGYO", "MRGYO", "NUGYO", "OZGYO", "OZKGY", "PAGYO", "PEGYO", "REIDM", "RYGYO", "SNGYO", "SRVGY", "TRGYO", "VKGYO", "YGYO", "YKGYO"), config.SEKTOR_GAYRIMENKUL),
    (("HOL", "AVHOL", "DOHOL", "ECILC", "GLYHO", "GSDHO", "ISYAT", "KCHOL", "KOZAA", "NTHOL", "SAHOL", "TRHOL", "VERUS"), config.SEKTOR_HOLDING),
    (("SIG", "AKGRT", "ANSGR", "GUSGR", "RAYSG", "TURSG", "AGESA", "ANHYT"), config.SEKTOR_SIGORTA),
    (("TEKS", "ARSAN", "ATEKS", "BLCYT", "BOSSA", "BRKSN", "DAGI", "DERIM", "DESA", "DESYT", "DIRIT", "ENSRI", "HATEK", "ISKPL", "KORDS", "KRTEK", "LUKSK", "MEMSA", "MENBA", "RODRG", "SKTAS", "SNKRN", "VAKKO", "YATAS", "YUNSA"), config.SEKTOR_TEKSTIL),
    (("KIM", "ACSEL", "AKSA", "ALKIM", "ATAGY", "BAGFS", "DEVA", "DYOBY", "EGGUB", "GUBRF", "HEKTS", "MRSHL", "PETKM", "POLHO", "POLTK", "SODA", "TRCAS", "TUPRS"), config.SEKTOR_KIMYA),
    (("GIDA", "AEFES", "ALYAG", "BANVT", "CCOLA", "ERSU", "FRIGO", "GOZDE", "KENT", "KERVT", "KNFRT", "KRSTL", "MERKO", "OYLUM", "PENGD", "PETUN", "PINSU", "PNSUT", "TATGD", "TBORG", "TUKAS", "TUPRS", "ULKER"), config.SEKTOR_GIDA),
    (("MTL", "ASUZU", "BRSAN", "BURCE", "BURVA", "CELHA", "CEMTS", "CUSAN", "DEMKA", "DMSAS", "DOGUB", "ERBOS", "EREGL", "IZMDC", "KRDMA", "KRDMB", "KRDMD", "MEGAP", "OZRDN", "SARKY"), config.SEKTOR_METAL),
    (("ULAS", "BEYAZ", "CLEBI", "DOCO", "PGSUS", "RYSAS", "TLMAN", "THYAO", "TUREX"), config.SEKTOR_ULASIM),
    (("ILTS", "TCELL", "TTKOM", "TTRAK", "TURCA"), config.SEKTOR_ILETISIM),
    (("TURIZM", "AVTUR", "MAALT", "MARTI", "MERIT", "TEKTU", "ULAS", "AYCES", "ETILR", "AYDEM"), config.SEKTOR_TURIZM),
    (("KAGIT", "ALKA", "BAKAB", "DGNMO", "KARTN", "OLMIP", "TIRE", "VKGYO"), config.SEKTOR_KAGIT),
    (("MOB", "GENTS", "INTEM", "YATAS", "MRGYO"), config.SEKTOR_MOBILYA),
    (("SAGLI", "DEVA", "ECZYT", "LKMNH", "MPARK", "POLHO", "SELEC"), config.SEKTOR_SAGLIK),
    (("SPOR", "BJKAS", "FENER", "GSRAY", "TSPOR"), config.SEKTOR_SPOR),
]

_CACHE: dict[str, str] = {}


# ── PHP apiSektorToIntern birebir karşılığı ────────────────────────────────
# API'nin döndürdüğü serbest metinli "Sektor" alanını iç sabite (SEKTOR_*) çevirir.
# Türkçe karakterler ASCII'ye normalize edilir ve **sıra kritiktir**: spesifik
# kontroller (örn. "ELEKTRIKLI CIHAZ") önce gelir, çakışan "ELEKTR" gibi
# kısa eşleşmeler sonradan değerlendirilir.
_TR_FROM = "İĞÜŞÖÇığüşöçâîû"
_TR_TO   = "IGUSOCIGUSOCAIU"
_TR_TABLE = str.maketrans(_TR_FROM, _TR_TO)


def api_sektor_to_intern(api_sektor: str) -> str:
    """API'den gelen sektör metnini iç sabit sektöre dönüştürür."""
    if not api_sektor:
        return config.SEKTOR_GENEL
    s = (api_sektor or "").upper().translate(_TR_TABLE)

    has = lambda k: k in s

    # 1. Sigorta
    if has("SIGORTA"): return config.SEKTOR_SIGORTA
    # 2. Iletisim / Telekom / Medya — BILGI'den ÖNCE
    if has("ILETIS") or has("TELEKOM") or has("MEDYA") or has("YAYIN"):
        return config.SEKTOR_ILETISIM
    # 3. Kimya / Ilac / Plastik — PETRO/ELEKTR'dan ÖNCE
    if (has("KIMYA") or has("ILAC") or has("ECZA") or has("PLASTIK")
            or has("BOYA") or has("LASTIK") or has("KAUUK") or has("KAUCUK")):
        return config.SEKTOR_KIMYA
    # 4. Metal imalat / Makine / Elektrikli Cihazlar — ENERJI'den ÖNCE
    if (has("ANA METAL") or has("METAL ESYA") or has("METAL EYA")
            or has("ELEKTRIKLI CIHAZ")):
        return config.SEKTOR_METAL
    # 5. Enerji
    if (has("ENERJI") or has("PETRO") or has("DOGALGAZ")
            or has("ELEKTRIK GAZ") or has("ELEKTRIK , GAZ")):
        return config.SEKTOR_ENERJI
    if has("ELEKTR") and not has("ELEKTRONIK"):
        return config.SEKTOR_ENERJI
    # 6. Banka / Finansal
    if (has("BANKA") or has("FINANS") or has("ARACILIK") or has("ARACI KURUMLAR")
            or has("ARAC KURUMLAR") or has("MENKUL KIYMET")
            or has("VARLIK YONETIM") or has("FINANSMAN")):
        return config.SEKTOR_BANKA
    # 7. Gayrimenkul — GIRISIM SERMAYESI hariç
    if not has("GIRISIM"):
        if (has("GAYRIMEN") or has("GAYR MENKUL") or has("REAL ESTATE")
                or has("YATIRIM ORTAKL")):
            return config.SEKTOR_GAYRIMENKUL
    # 8. Holding (Girişim Sermayesi dahil)
    if (has("HOLDING") or has("KONGLOMERA") or has("GIRISIM SERMAY")
            or has("YATRM")):
        return config.SEKTOR_HOLDING
    # 9. Perakende
    if (has("PERAKENDE") or has("TOPTAN") or has("TICARET") or has("MARKET")):
        return config.SEKTOR_PERAKENDE
    # 10. Tekstil
    if (has("TEKST") or has("GIYIM") or has("KONFEKSIYON") or has("DERI")
            or has("DOKUMA")):
        return config.SEKTOR_TEKSTIL
    # 11. Gıda / İçecek / Tarım
    if (has("GIDA") or has("GDA") or has("ICECEK") or has("TARIM")
            or has("HAYVANC") or has("BALIKC") or has("SU URUNLERI")):
        return config.SEKTOR_GIDA
    # 12. İnşaat / Çimento / Seramik / Cam
    if (has("INSAAT") or has("CIMENTO") or has("SERAMIK")
            or has("TAS VE TOPRA") or has("TA VE TOPRAA")):
        return config.SEKTOR_INSAAT
    # 13. Ulaşım / Lojistik / Havacılık
    if (has("ULASIM") or has("ULASTIR") or has("ULATRMA") or has("LOJIST")
            or has("HAVACILIK") or has("DENIZCILIK") or has("TASIMAC")):
        return config.SEKTOR_ULASIM
    # 14. Metal / Demir-Çelik / Madencilik (geniş)
    if (has("METAL") or has("CELIK") or has("DEMIR") or has("ALUMIN")
            or has("MADEN")):
        return config.SEKTOR_METAL
    # 15. Teknoloji / Yazılım / Bilişim / Savunma
    if (has("TEKNO") or has("YAZIL") or has("BILGI") or has("BILIS")
            or has("ELEKTRONIK") or has("SAVUNMA")):
        return config.SEKTOR_TEKNOLOJI
    # 16. Turizm / Otel
    if (has("OTEL") or has("KONAKLAMA") or has("TURIZM") or has("TURISTIK")
            or has("SEYAHAT") or has("ACE")):
        return config.SEKTOR_TURIZM
    # 17. Kâğıt / Ambalaj / Basım
    if (has("KAGIT") or has("AMBALAJ") or has("KARTON") or has("BASIM")
            or has("MUKAVVA") or has("KIRTASIYE") or has("MATBAACIL")):
        return config.SEKTOR_KAGIT
    # 18. Mobilya / Orman
    if has("MOBILYA") or has("ORMAN URUNL") or has("TAHTA"):
        return config.SEKTOR_MOBILYA
    # 19. Sağlık
    if (has("SAGLIK") or has("INSAN SAGL") or has("HASTANE") or has("HEKIM")
            or has("SOSYAL HIZ")):
        return config.SEKTOR_SAGLIK
    # 20. Spor / Eğlence
    if (has("SPOR FAALIY") or has("FUTBOL") or has("SPORTIF")
            or has("EGLENCE VE OYUN")):
        return config.SEKTOR_SPOR

    return config.SEKTOR_GENEL


def piyasa_to_grup(piyasa: str) -> str:
    """SirketProfil.Piyasa → grup kodu (Y/A/ALT/IZL/POIP/DIGER). PHP piyasaToGrup birebir."""
    if not piyasa:
        return "DIGER"
    parts = str(piyasa).upper().split("/")
    for p in parts:
        p = p.strip()
        if "YILDIZ"  in p: return "Y"
        if "ANA PAZAR" in p: return "A"
        if "ALT PAZAR" in p: return "ALT"
        if "ZLEME" in p or "IZLEME" in p: return "IZL"
        if "NCES" in p or "GIRISIM" in p or "GIP" in p: return "POIP"
    return "DIGER"


def get_sector_group(code: str) -> str:
    """Hisse koduna göre sektör grubu döndürür."""
    if not code:
        return config.SEKTOR_GENEL
    code = code.upper().strip()
    if code in _CACHE:
        return _CACHE[code]
    for keys, sektor in _SECTOR_RULES:
        for key in keys:
            if key in code:
                _CACHE[code] = sektor
                return sektor
    _CACHE[code] = config.SEKTOR_GENEL
    return config.SEKTOR_GENEL


# ── PHP sektorFromAd birebir karşılığı ─────────────────────────────────────
# sektorHam boş olduğunda şirket adından (Türkçe karakterli) sektör tahmini.
def sektor_from_ad(ad: str) -> str:
    """PHP sektorFromAd — Türkçe şirket adından sektör tespiti (fallback)."""
    if not ad: return config.SEKTOR_GENEL
    s = ad.upper()
    h = lambda *kw: any(k in s for k in kw)
    # 1. Sigorta
    if h("SİGORTA", "EMEKLİLİK"): return config.SEKTOR_SIGORTA
    # 2. Banka / finans
    if h("BANKA", "FAKTORİNG", "FİNANSBANK", "FİNANSAL KİRALAMA",
         "VARLIK KİRALAMA", "FİNANSMAN ŞİRKETİ", "VARLIK YÖNETİM",
         "YATIRIM MENKUL", "MENKUL DEĞERLER", "MENKUL KIYMETLERİ"):
        return config.SEKTOR_BANKA
    # 3. İletişim / medya
    if h("GAZETECİLİK", "DERGİ YAYIN", "MATBAACILIK", "RADYO",
         "TELEVİZYON", "HABER AJANSI"): return config.SEKTOR_ILETISIM
    # 4. Kimya / ilaç / plastik / petro
    if h("KİMYA", "KİMYEVİ", "İLAÇ", "PLASTİK", "POLİMER", "POLİKARB",
         "BOYA", "VERNİK", "LASTİK", "KAUÇUK", "GÜBRE", "SELÜLOZ",
         "PETRO", "AKRİLİK"): return config.SEKTOR_KIMYA
    # 5. Gayrimenkul (holding öncesi)
    if h("GAYRİMENKUL"): return config.SEKTOR_GAYRIMENKUL
    # 6. Holding / girişim sermayesi
    if h("HOLDİNG", "GİRİŞİM SERMAYESİ", "YATIRIM ORTAKLIĞI"):
        return config.SEKTOR_HOLDING
    # 7. Enerji
    if h("ENERJİ", "YENİLENEBİLİR", "SOLAR", "GÜNEŞ ENERJİ", "RÜZGAR",
         "DOĞALGAZ", "ELEKTRİK ÜRETİM"): return config.SEKTOR_ENERJI
    # 8. Gıda
    if h("GIDA", "BİRACILIK", "ŞEKER", "UN SANAYİ", "MEŞRUBAT",
         "TARIM", "BALIKÇILIK", "SÜT SANAYİ"): return config.SEKTOR_GIDA
    # 9. Tekstil / konfeksiyon
    if h("TEKSTİL", "MENSUCAT", "İPLİK", "GİYİM", "DOKUMA", "DERİ SANAYİ"):
        return config.SEKTOR_TEKSTIL
    # 10. Metal / makine / maden / otomotiv
    if h("MADENCİLİK", "DEMİR ÇELİK", "ÇELİK BORU", "METAL SANAYİ",
         "METALURJİ", "DÖKÜM SANAYİ", "OTOMOTİV", "TRAKTÖR",
         "KABLO SANAYİ", "MAKİNA SANAYİ", "ALTIN İŞLETMELERİ"):
        return config.SEKTOR_METAL
    # 11. İnşaat / çimento / seramik
    if h("ÇİMENTO", "SERAMİK", "BETON SANAYİ", "İNŞAAT VE"):
        return config.SEKTOR_INSAAT
    # 12. Ulaşım / lojistik
    if h("TAŞIMACILIK", "LOJİSTİK", "HAVALİMANI", "GEMİCİLİK",
         "HAVA YOLLARI", "NAKLİYAT"): return config.SEKTOR_ULASIM
    # 13. Perakende
    if h("MAĞAZACILIK", "MARKET"): return config.SEKTOR_PERAKENDE
    # 14. Turizm / Otel
    if h("TURİZM", "TURİSTİK", "OTEL ", "KONAKLAMA", "SEYAHAT", "RESORT"):
        return config.SEKTOR_TURIZM
    # 15. Kağıt / Ambalaj
    if h("KAĞIT", "AMBALAJ", "KARTON", "MATBAACILIK", "BASIM",
         "MUKAVVA", "KIRTASİYE"): return config.SEKTOR_KAGIT
    # 16. Mobilya / Orman
    if h("MOBİLYA", "ORMAN", "TAHTA", "DEKORATİF YÜZEY"):
        return config.SEKTOR_MOBILYA
    # 17. Sağlık
    if h("SAĞLIK", "HEKİM", "KLİNİK", "OKSİJEN", "HASTANE"):
        return config.SEKTOR_SAGLIK
    # 18. Spor / Futbol
    if h("FUTBOL", "SPORTİF", "SPOR FAALİ"): return config.SEKTOR_SPOR
    return config.SEKTOR_GENEL
