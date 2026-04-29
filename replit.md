# BIST PREDATOR v35 — Python sürümü

15.699 satırlık monolitik PHP `index.php` dosyasının tamamı modüler bir Flask uygulamasına dönüştürüldü. Türkçe BIST hisse senedi yapay zekâ trade botu — SMC, Harmonik, Monte Carlo, Kelly, üç sinir ağı, Telegram entegrasyonu, web dashboard ve CLI daemon.

## Proje yapısı
```
app.py                 # Flask web sunucusu — tüm ?action= uç noktaları
predator/
  __init__.py
  config.py            # Sabitler, dosya yolları, .env okuyucu
  utils.py             # parse_api_num, JSON I/O, ScanLock, tarih yardımcıları
  sectors.py           # BIST hisse → sektör eşleme
  telegram.py          # Telegram istemci (dedup destekli)
  api_client.py        # idealdata + Burgan dış API'leri
  indicators.py        # 25+ teknik indikatör (numpy)
  market.py            # Piyasa modu (bull/temkinli/ayi)
  portfolio.py         # Pozisyon yükle/kaydet/aç/kapat
  neural.py            # Üçlü sinir ağı (Alpha/Beta/Gamma) numpy + Adam
  brain.py             # Snapshot, öğrenme, prediction bonus, ensemble
  formations.py        # 30+ mum/grafik formasyonu
  smc.py               # Smart Money Concepts + OFI
  montecarlo.py        # GBM tahmin + Kelly fraction
  scoring.py           # AI skor, hız skoru, sinyal kalitesi, hedefler
  scoring_extras/      # v40: paket — 13 PHP fonksiyonu 11 alt-modüle bölündü
    __init__.py        #   façade — geri uyumlu re-export (19 sembol)
    _safe.py           #   _safe_num, _safe_str
    _perf.py           #   ai_performance_stats, update_signal_outcomes, get_calibration_suggestions
    _confidence.py     #   calculate_confidence_score
    _brain_bonus.py    #   get_confluence_key, brain_get_confluence_bonus, brain_get_time_bonus
    _breadth.py        #   get_market_breadth, reset_breadth_cache
    _reasoning.py      #   get_ai_reasoning
    _consensus.py      #   calculate_consensus_score (8 sistem)
    _radar.py          #   get_radar_membership, reset_radar_caches
    _position.py       #   get_unified_position_confidence, get_brain_backtest_fusion
    _breakdown.py      #   build_ai_breakdown
    _dual.py           #   dual_brain_knowledge_transfer
  extras/              # v40: önceki extras.py (1462 satır) bölündü
    __init__.py        #   façade — 24 public sembol
    _chart_io, _smc, _volume, _risk, _mtf, _brain_stats, _movers, _news, _smc_pack
  ai_think.py          # ai_auto_think + ai_driven_* parametreler
  scan.py              # BIST tarama motoru (paralel ThreadPoolExecutor)
  engine.py            # otoEngineMulti — sprint modu pozisyon yöneticisi
  signal_history.py    # Sinyal geçmişi
  daemon.py            # CLI: python -m predator.daemon --daemon
templates/index.html   # Sade dashboard
static/app.css         # Stil
static/app.js          # API çağrıları + yenileme
cache/                 # Tüm predator_*.json dosyaları (eski PHP ile uyumlu)
```

## Önemli kararlar
- **Cache uyumluluğu**: 57+ adet `predator_*.json` dosyasının şeması korundu — eski PHP'den kalan brain, portfolio, snapshot ve sinir ağı ağırlıkları doğrudan okunuyor.
- **Sinir ağları**: PHP'deki yapı birebir korundu. Alpha 26→32→16→8→1 (λ=0.00008), Beta 26→16→8→4→1 (λ=0.0015), Gamma 26→20→10→5→1 (λ=0.0010), LeakyReLU + Adam optimizasyonu, ağırlıklar JSON-serializable list olarak saklanıyor.
- **Çerçeve**: Kullanıcı Flask seçti. Modüler dizin yapısı.
- **UI**: Kullanıcı sade UI'yi onayladı — orijinal 4000 satırlık HTML/CSS/JS yerine basit dashboard.
- **Türkçe**: Tüm UI ve loglar Türkçe.
- **Telegram**: TG_BOT_TOKEN/TG_CHAT_ID env'den okunuyor, fallback olarak hardcoded.
- **Workflow**: Replit "Start application" workflow'u `python app.py` çalıştırır (port 5000).
- **Daemon**: `python -m predator.daemon --daemon` ile sürekli oto-pilot.

## API uç noktaları (`/?action=...`)
- `ping` — sunucu durumu
- `bist_scan` (`_async=1` ile arka plan) — tüm BIST'i tara
- `bist_scan_two_phase` / `bist_scan_2p` (`_async=1` ile arka plan) — iki fazlı tarama: Faz 1 SirketDetay+SirketProfil+BilancoRasyo (tüm hisseler), Faz 1.5 SonFiyat>0 adayları, Faz 1.7 Getiri+SirketSermaye, Faz 2 CHART2 (sadece adaylar), Faz 3 analiz + sektör momentum + ortak katlama bonusu + ad-bazlı sektör fallback. PHP `runBISTScanTwoPhase` birebir Python portu. Parametreler: `parallel` (varsayılan 20), `limit` (test için).

## PHP ile birebir uyum tamamlanan ek fonksiyonlar
- `predator/api_client.py`: `fetch_bilanco_rasyo`, `fetch_getiri`, `fetch_sirket_sermaye`, `fetch_sirket_sektor_ham`, `fetch_many` (paralel batch).
- `predator/sectors.py`: `piyasa_to_grup` (Y/A/ALT/IZL/POIP), `sektor_from_ad` (şirket adından sektör fallback).
- `predator/indicators.py`: `volume_momentum` (PHP calculateVolumeMomentum), `obv_trend` (PHP calculateOBVTrend artis/dusus/notr).
- `predator/scan.py`: `_enrich_with_fundamentals` (Faz 3 finData + tüm aiScore bonusları), `_apply_sector_momentum_boost` (sektör üst %20'ye +15), `_ortak_katlama_analysis` (Kural 1+2+3 büyük ortak katlama bonusu), `run_bist_scan_two_phase` (ana orkestrator).
- `scan_progress` — tarama yüzde durumu
- `top_picks?n=25` — en iyi fırsatlar
- `oto_status`, `oto_log`, `oto_engine_run`, `oto_close?code=XYZ`
- `neural_bootstrap`, `neural_train?epochs=3`, `neural_stats`, `neural_predict?code=XYZ`
- `market_mode`, `send_tg?msg=...`, `daemon_status`, `brain_state`
- **Yeni (PHP birebir)** — `chart_data?code=XYZ`, `brain_stats`, `backtest_stats`,
  `brain_similar?code=XYZ`, `chart_compare`, `haber_firma?code=XYZ&adet=5`, `gundem`,
  `bilanco_detay?code=XYZ`, `smclevels?code=XYZ`, `multi_tf?code=XYZ`,
  `monte_carlo?entry=..&stop=..&h1=..&h2=..&vol=..`, `volume_profile?code=XYZ`,
  `kelly_size?win=..&avgwin=..&avgloss=..`
- **PHP isim alias'ları** — `oto_close_position`, `oto_close_all_manual`,
  `oto_add_manual`, `scan_status`, `auto_status`, `neural_status`
- **v37 ek action** — `cache_flush?kind=...` — geçici cache dosyalarını siler
  (oto/brain/auto/dedup dosyaları korunur).

## v37: PHP UI/Yardımcı eksiklerinin tamamlanması
- `predator/utils.py` → `quantile`, `calculate_graham`, `safe_str_decode` PHP
  birebir karşılığı eklendi.
- `predator/sectors.py` → `api_sektor_to_intern(api_sektor)` API metnini iç
  sektör sabitine çevirir (PHP apiSektorToIntern; sıra-kritik 20 kural).
- `static/app.js` → `openAiReasoning(code)` (AI Gerekçesi modalı: ai_reasoning
  + ai_breakdown + consensus_score birleşik panel), `openCompareChart`,
  `showCompareInput`, `renderCompareCanvas`, `renderNormalizedComparison`,
  `calcEMA` — PHP karşılaştırma motoru birebir taşındı.
- `static/app.css` → Cyberpunk neon tema sınıfları (.neon-cy, .neon-grn,
  .modal-overlay, .modal-card, .reason-block, .cmp-grid, .cmp-norm).
- `templates/index.html` → "İncele" sütunu (🔍 AI Gerekçesi + 🔗 Karşılaştır
  butonları), "Cache Sıfırla" butonu.

## Çalıştırma
- Web: workflow otomatik başlar (port 5000)
- Daemon: `python -m predator.daemon --daemon`
- Tek tarama: `python -m predator.daemon --scan-once`

## v37.4: Kapsamlı kod denetimi düzeltmeleri
- **Beyin yarış durumu** — `predator/brain.py`'a `brain_lock()` context manager
  eklendi (RLock tabanlı). Daemon eğitim döngüsü ve kullanıcı eğitim uç noktaları
  (`neural_train`, `neural_bootstrap`, `neural_negative_train`) artık aynı kilidi
  kullanır; eş zamanlı RMW ezilmesi engellendi.
- **TZ bug** — `count_business_days` artık TR zaman dilimini kullanıyor
  (eskiden naif `datetime.now()` ile UTC sunucularda 1 gün hatası olabiliyordu).
- **Girdi sınırları** — `neural_train` epochs 1-50, `neural_negative_train`
  epochs 1-20 olarak sınırlandı (DoS koruması).

## v37.5: Tam otomatik — manuel eğitim uç noktaları kaldırıldı
- `neural_train`, `neural_bootstrap`, `neural_negative_train` action'ları
  app.py'dan tamamen silindi. Eğitim YALNIZCA daemon `_train()` döngüsünden
  otomatik tetiklenir. Hiçbir manuel tetikleyici (UI butonu, HTTP endpoint)
  artık mevcut değil.
- Sadece okuma uç noktaları kaldı: `neural_stats`, `neural_predict`.
- `brain_lock` korundu (gelecekteki otomatik yazıcılar için savunma).

## v37.6: KAÇIN'lar "En İyi 25 Fırsat" listesinden çıkarıldı
- AI `autoThinkDecision == "KAÇIN"` olan hisseler `topPicks` cache'ine
  artık YAZILMIYOR (predator/scan.py — her iki tarama fonksiyonu).
- Sıralamada da KAÇIN'lar en alta düşüyor (savunma katmanı).
- `act_top_picks` okuma anında da süzme yapar — eski cache temizlenmeden
  düzeltme anında devreye girer.
- Cache'e `opportunities` sayacı eklendi (KAÇIN OLMAYAN aday sayısı).
- KAÇIN'lar `allStocks`'ta kalır → AI eğitimi negatif örnek olarak kullanır.

## v37.7: Fırsat listesi artık limitsiz
- "En İyi 25 Fırsat" → "Tüm Fırsatlar" (skor sırasına göre, KAÇIN'lar hariç).
- `act_top_picks` varsayılan olarak tüm picks'i döndürür (n=0 = limit yok).
- `topPicks` cache'inde [:200] kesimi kaldırıldı; tam liste saklanıyor.

## v37.8: Liste TAM evren (579 hisse) gösterir
- `act_top_picks` artık `allStocks` üzerinden döner — KAÇIN dahil taranan
  tüm hisseler skor sırasına göre listelenir.
- Sıralama anahtarı: `score → predatorScore → aiScore` fallback zinciri.
- Başlık: "🎯 Tüm Hisseler (skor sırasına göre · KAÇIN dahil)".

## v37.9: İki kritik veri kaybı yarış durumu çözüldü
**Sorun:** 2-3 tarama sonrasında Triple Brain (Alpha/Beta/Gamma), açık
pozisyon cache'i ve tarama geçmişi sıfırlanıyordu.

**Kök neden 1 — Brain RMW yarışı:**
- Daemon `_train()` brain_lock ile sarılıydı (v37.4)
- AMA scan.py'daki snapshot kayıt blokları (`brain = brain_load()` → 50 snapshot
  ekle → `brain_save(brain)`) kilit DIŞINDAYDI
- Daemon eğitirken scan tamamlanınca: scan'in elindeki bayat brain
  daemon'un yeni öğrendiklerini OVERWRITE ediyordu
- **Düzeltme:** scan.py'daki her iki snapshot bloğu da `brain_lock` içine alındı

**Kök neden 2 — Oto pozisyon RMW yarışı:**
- `oto_engine_multi` çoklu pozisyon iter'inde `oto_save(oto)` çağırıyor,
  sonra `oto_close_position(...)` (kendi içinde load/save yapan) tetikliyordu
- Engine'in elindeki bayat dict, kapatılan pozisyonu sıradaki yazışta
  diriltebiliyor veya yeni pozisyonları kaybediyor
- **Düzeltme:** `predator/portfolio.py`'a `oto_lock` (RLock) eklendi;
  `oto_engine_multi` tüm gövde tek bir `with oto_lock():` içine sarıldı

## v37.10: Bellek limiti (varsayılan 512 MB hedef)
- `predator/memlimit.py` eklendi — iki katmanlı koruma:
  - **Soft monitor** (varsayılan): arka plan thread her 30 sn RSS okur,
    %80'de `gc.collect()`, %90'da brain snapshot (90→30) ve oto log (500→200)
    kırpar.
  - **Hard cap** (opsiyonel): `PREDATOR_MEM_HARD=1` ile `RLIMIT_AS = 2×limit`
    set edilir. Numpy lazy mmap'ları yüzünden hard AS = limit dar gelir.
- Çevre değişkenleri:
  - `PREDATOR_MEM_MB` (varsayılan: 512) — hedef bellek MB
  - `PREDATOR_MEM_HARD=1` — kernel hard cap aktif
- Anlık RSS izleme şu an 128 MB / 512 MB (%25); soft limit %80'de tetiklenir.

## v38: AI zekâ + şeffaflık iyileştirmeleri (24 Nis 2026)

### Neural ağ (`predator/neural.py`)
- **Eksik özellik takibi:** `_track_missing()` her kayıp/None/parse-edilemeyen
  girdiyi sayar; `get_missing_feature_report()` en sık 5 eksik özelliği döker.
  Veri akışındaki sessiz boşluklar artık `/?action=neural_stats` ile teşhis
  edilebilir.
- **Tahmin teşhisi:** `predict()` artık NaN/Inf'e karşı korumalı; iç hatayı
  `net['last_predict_error']`'e yazar (fallback 0.5 kalır, ancak sebep görünür).
- **Sıcaklık kalibrasyonu:** yeni `predict_calibrated(net, snap) → (p, conf)`.
  Ham logit `temperature=1.5` ile yumuşatılır → aşırı güven (0.95+) törpülenir;
  güven skoru `|p-0.5|*2`.
- **ReduceLROnPlateau:** `_adaptive_lr()` artık plateau çarpanı uygular.
  `train_step()` her adımda `best_loss` izler; 30 adım iyileşme yoksa LR ×0.6
  düşer (alt sınır 0.1×). Daha kararlı eğitim.
- **Eğitim hazır eşiği:** 5 → 20 örnek (yetersiz veriyle güven yayma riskini azaltır).

### Beyin (`predator/brain.py`)
- **Kalibre topluluk:** `neural_ensemble_predict()` Alpha/Beta/Gamma'yı
  `predict_calibrated` ile çağırır; her ağın kalibre güveni topluluk ağırlığına
  ek faktör (`0.5 + 0.5*conf`) — düşük güvenli ağ daha az ses çıkarır.
  Çıktıda yeni `raw` ve `calibration_conf` alanları teşhis için.
- **Çeşitlilik cezası:** `neural_dual_bonus()` iki ağ aynı yönü çok güçlü
  birlikte söylerse (|delta|≤8) bonusu ×0.85 ile çarpar — eko-odasına karşı
  güvenlik.
- **Çok-ufuklu eğitim:** Eskiden sadece `outcome5` (7-gün) ile eğitiliyordu.
  Şimdi `outcome3` (Beta'ya 0.7×), `outcome10` (Alpha'ya 0.6×) ve `outcome21`
  (Gamma'ya 0.5×) ek sinyaller verir → her ağ kendi vade ufkunu öğrenir.

### Skor (`predator/scoring.py`)
- **Sessiz fallback bayrağı:** `calculate_ai_score()` artık `phpmatch`
  yüklenemediğinde sessizce eski hesaba düşmüyor; ilk hata stderr'e yazılır,
  her hisseye `aiScoreFallback=True/False` damgalanır → UI/log şeffaf.

### Monte Carlo (`predator/montecarlo.py`)
- **Vektörize GBM:** `np.cumprod` ile döngü kalktı (5–10× hızlı).
- **Güven alanları:** `confidence`, `low_confidence`, `n_obs`, `sigma_ann`,
  `reason` eklendi — < 30 gün geçmiş varsa "düşük güven" işaretlenir.

### Daemon (`predator/daemon.py`)
- **Bağımsız kalp atışı:** Her 60 sn `_heartbeat_loop` "💓 daemon canlı"
  yazar (faz, tarama sayısı, borsa durumu, sonraki tarama, uptime). Web UI
  trafikten bağımsız çalışır → Render/24-7 dağıtımda canlılık kanıtlanır.

## v38.1: Kod kalitesi sertleştirmesi (24 Nis 2026)

8 maddelik düzeltme (testler, app.py refactor, backtesting, PHP silme dışında).

### Yeni modüller
- **`predator/observability.py`** — `log_event/log_exc` (structured), error/event
  ring buffer'ları (200/500), counter/gauge/histogram. UI'dan
  `?action=health|metrics|errors` ile okunur.
- **`predator/http_utils.py`** — `safe_request`: `verify=True` (TLS açık),
  3 deneme + üstel geri çekilme + jitter, 4xx tek atış, 5xx retry, URL
  token'ı log'da maskelenir, `metric_kind` ile ölçü etiketlenir.

### Güvenlik
- **TLS doğrulama açık** — `api_client.py`, `telegram.py`, `cache_backup.py`,
  `tg_listener.py`, `extras.py` artık `verify=True`. `app.py`'de
  `Unverified HTTPS request` susturucusu kaldırıldı.
- **Token sabit fallback'i kaldırıldı** — `config.py`'de hardcoded
  `TG_BOT_TOKEN`/`TG_CHAT_ID` silindi. `validate_secrets()` startup'ta
  uyarı yayar; `PREDATOR_STRICT_SECRETS=1` ile sert mod.

### Triple Brain DÜELLO (aktif rekabet)
- `brain.py::brain_update_outcomes` her olgunlaşan 7-günlük snapshot için
  3 ağın tahminini eğitimden ÖNCE ölçer, `_decide_duel_loser()` ile
  kayıp ağ(lar)ı belirler (EPS=0.08), `dual_brain_knowledge_transfer`'a
  iletir.
- `scoring_extras.py::dual_brain_knowledge_transfer` yeniden yazıldı —
  artık Beta ve Gamma'ya da extra adım uyguluyor, `gamma_streak` resetleri
  doğru, "gamma" tek-kayıp davası işleniyor.
- `neural.py::train_on_outcome(lr_mult=1.0)` parametresi eklendi —
  düello cezası `LR × 2.2` ile uygulanır.

### Sayısal kararlılık
- `indicators.py::adx()` overflow'u tamamen baskılandı — `np.where`
  içindeki bölme önce `str_safe` gibi sıfır-koruyucu denominator'lara
  ayrıldı, `np.nan_to_num` üç çıktıyı temizliyor.

### Operasyonel sertlik
- `daemon.py` artık `signal.SIGTERM/SIGINT` yakalıyor, `_STOP` Event
  tüm uzun döngülerde (`run_daemon`, `_heartbeat_loop`, sleep'ler)
  yoklanıyor. Render restart'ında <3 sn temiz iniş; kilit dosyası
  bırakılıyor, status `stopped` yazılıyor.
- Kritik sessiz `except: pass` bloklar `log_exc()`'a çevrildi
  (brain.py outcome eğitim hataları, api_client worker hataları,
  cache_backup pin/unpin başarısızlıkları).
- **Cache yedek otomatik temizliği + şifreleme** (`cache_backup.py`):
  yüklenen yedek mesaj ID'leri `cache/predator_backup_msgs.json`
  dosyasında tutulur. Yeni yedek atıldıktan sonra `_prune_old_backups()`
  çağrılır ve `BACKUP_KEEP_LAST` (varsayılan 1) hariç tüm eski yedekler
  grup feed'inden `deleteMessage` ile silinir.
  Yedekler ZIP'lendikten sonra **AES-128-CBC + HMAC (Fernet)** ile
  şifrelenip **geçerli bir JPG'ye sarmalanır** ve `chart_<ts>.jpg`
  adıyla yüklenir — Telegram'da sıradan bir resim olarak görünür,
  preview thumbnail'i kapak resmidir. Format:
  `[cover.jpg bytes (FFD9 ile biter)] + [16B magic marker
  PRDTRBKPv1] + [Fernet token (encrypted ZIP)]`. JPEG decoder'lar
  EOI sonrasını yok sayar, dolayısıyla resim normal açılır.
  Kapak resmi artık dinamik: `predator/portfolio_chart.py::render_cover_jpg`
  açık pozisyondaki hissenin son ~120 günlük fiyat eğrisini ve GİRİŞ /
  H1 / H2 / H3 / STOP seviyelerini Pillow ile çizer (1280×720 JPG, %88,
  10dk in-memory cache). Pozisyon yoksa veya render hata verirse
  `predator/assets/cover.jpg` statik kapak resmine geri düşer. Şifre
  sabit ve koda gömülü (`_BACKUP_PASSWORD`); anahtar PBKDF2-HMAC-SHA256
  (200K iter) ile türetilir. `restore_cache_from_telegram` önce
  `_unwrap_from_jpg` ile magic marker'dan sonrasını alır, yoksa
  tüm dosyayı şifreli sayar; sonra `_decrypt_blob` çözer. Hem yeni
  JPG-sarmalı, hem eski `.bin` (sadece encrypted), hem de daha eski
  şifresiz ZIP yedekleri okunabilir (geriye uyum). Bağımlılık:
  `cryptography==43.0.3`, `Pillow==11.0.0` (kapak grafiği için).
- **Birleşik pinli mesaj** (`cache_backup.update_unified_panel`):
  portföy panosu (PANO) artık ayrı bir text mesaj olarak değil; şifreli
  yedek `.bin` dosyasının **caption**'ı olarak gönderilir. Tek pinli
  mesaj — caption'a `editMessageCaption` ile in-place güncellenir
  (60sn'de bir, `tg_pin_loop`). Yedek aralığı (30dk) gelince yeni `.bin`
  yüklenir, eski mesaj silinir, yenisi pinlenir. Durum:
  `cache/predator_unified_pin_state.json`. `tg_listener._ensure_pinned_board`
  ve `?action=cache_backup` artık bu fonksiyona delegasyon yapar; eski
  text-only PANO mesajları ilk yeni doc yüklemesinde otomatik temizlenir.
  `daemon._maybe_backup_to_tg` artık no-op (mükerrer mesajı önler).
  Caption Telegram limiti olan 1024 karaktere otomatik truncate edilir.

### Yeni HTTP action'lar
- `?action=health` → ok/uptime/errors_last_60s/daemon_status
- `?action=metrics` → counters + histograms (api_ideal, tg_send, ...)
- `?action=errors[&limit=N]` → son N hata kayıt
- `?action=triple_brain` (alias `duel_stats`) → `dual_brain_stats` +
  Alpha/Beta/Gamma ağ özetleri

### v37.12 — TG akıllı mesaj yöneticisi (Nis 2026)
- **Sorun**: Bot grupta birikmiş eski yedek (chart_*.jpg) ve PANO mesajlarını
  kendi başına temizleyemiyordu. `cache/predator_backup_msgs.json` dosyası
  Render redeploy'da uçunca eski yedeklerin ID'leri kayboluyor; sonraki bot
  sürümleri "yetim" mesajları silemiyordu.
- **Çözüm**: `predator/tg_cleanup.py` — kalıcı disk kaydı tutan
  `TgMessageManager`. Tüm bot mesajlarını otomatik kaydeder, periyodik
  süpürür.
  - **Track dosyası**: `cache/predator_tg_msg_track.json` (FIFO 5000 öğe).
  - **Mesaj türleri** (`kind`):
    - `panel_doc` / `panel_text` / `backup_doc` → KORUMALI; aktif pin değilse
      silinir, aktifse korunur.
    - `report` / `warn` / `service` / `unknown` → TTL bazlı (varsayılan
      report=72h, warn=4h, service=10dk).
  - **Aktif pin** = `max(state_pin, telegram_pin)`. `cache_backup` state'i
    veya canlı `getChat` cevabıyla tespit edilir; iki kaynaktan biri
    kayıpsa diğeri kullanılır.
  - **API**: `track()`, `untrack()`, `sweep(dry=)`, `reconcile()`,
    `nuke_range()`, `status()`, `cleanup_loop(interval_sec=600)`.
- **Entegrasyon**:
  - `predator/cache_backup.py` → `backup_cache_to_telegram`,
    `_send_text_pinned`, `update_unified_panel` her yeni doc/text
    mesajından sonra `track()` + eski pin için `untrack()` çağırıyor;
    update sonrası otomatik `sweep()` tetikleniyor.
  - `predator/tg_listener.py::_tg_send_raw` → tüm bot text mesajları
    otomatik track ediliyor (varsayılan `kind="report"`).
  - `predator/tg_listener.py::_process_update` → bot kendi mesajını long-poll
    ile gördüğünde: `chart_*.jpg` veya PREDATOR/PANO/YEDEK içerikli text
    aktif pin değilse anında siliniyor; diğer bot mesajları track listesine
    yazılıyor.
  - `predator/daemon.py` → `tg_cleanup_loop` thread'i (her 10dk) açıldı.
- **Yeni endpoint'ler** (`app.py`):
  - `?action=tg_cleanup_status` → track sayısı, aktif pin, kind dağılımı.
  - `?action=tg_sweep[&dry=1]` → manuel süpürme; dry mode raporlar, silmez.
  - `?action=tg_nuke_range&start=N&end=M[&step=1&max=500]` → eski yetim
    mesajlar için aralık silme (track dosyası kayıpsa kurtarma için).
  - `?action=tg_reconcile` → state ile canlı pin uyumunu yeniler.
- **Backfill**: Mevcut grupta birikmiş eski mesajlar için bir kez
  `tg_nuke_range` çağrısı yeterli; sonrası otomatik temizliğe bırakılır.

### v37.11 — Sembol yeniden adlandırma & KAP cache kalıcılığı (Nis 2026)
- **Hisse kod değişikliği takibi** (METUR → BLUME vakası): `predator/symbol_aliases.py`
  yeni modülü. Borsa kodu değişen şirketleri otomatik tespit eder ve
  `cache/predator_symbol_aliases.json` dosyasında {OLD: NEW} eşlemesi tutar.
  - `get_active_symbol(code)` → varsa yeni kodu döner; `api_client._resolve()`
    içinden `fetch_sirket_detay/profil/chart2` çağrılarında otomatik kullanılır
    (yeni `raw_code=True` flag'i ile detection sırasında bypass edilebilir).
  - `detect_successor(old)` → eski kodun stale olup olmadığını ölçer, BIST
    listesinde aynı `Tanim` arar, yoksa `Tanim`'dan kod adayları üretip API'de
    prob eder. Stale tespiti: `OncHafta` boş + `Fark=0` + `OncAy` boş (Hacim
    bayatta da dolu kalabildiği için güvenilir değil — METUR'da 304M Hacim
    olmasına rağmen veri donmuş).
- **Yeni HTTP action'lar:**
  - `?action=detect_aliases[&codes=A,B][&dry=1]` → açık pozisyonlar (veya
    listedeki kodlar) için stale durumu tara, yeni kod adayı bul, kaydet
    (dry=1 → sadece raporla).
  - `?action=migrate_position&old=X&new=Y[&confirm=1]` → portföydeki pozisyonu
    eski koddan yeni koda taşı; alias'ı kaydet; `confirm=1` yoksa dry-run
    plan döner. Pozisyon meta'sı (qty, entry) korunur — yeni kodda fiyat
    farklı olabileceği için kullanıcı manuel doğrulamalı.
  - `?action=aliases_list` → kayıtlı eski→yeni eşlemeleri.
  - `?action=stock_health` artık her sorunlu (dead/renamed/stale) pozisyon için
    `successor` alanı ekler (ya cache'den ya da `detect_successor` ile).
- **`fetch_live_price` kritik düzeltme** (`predator/api_client.py`): API
  alanı `Son`/`son`/`guncel` aranıyordu ama gerçek alan `SonFiyat`. Tüm
  hisseler 0.0 fiyat dönüyordu. Türkçe ondalık virgülü de işleniyor.
- **KAP 'Tipe Dönüşüm' cache kalıcılığı** (`predator/scoring_extras/_kap_news.py`):
  Cache restart sonrası kayboluyor → bonus sıfırdan hesaplanıyordu.
  Artık disk'e kalıcı:
  - `cache/predator_kap_news_cache.json` (per-stock bonus, 30dk TTL)
  - `cache/predator_kap_watchlist.json` (UI watchlist, 15dk TTL)
  - Modül yüklenince `_hydrate()` ile bellekleştirilir; yazımlar 3sn
    debounce'ludur (`force=True` debounce penceresini sıfırlamaz, böylece
    reset → populate sırası bozulmaz). Atomik yazım (`.tmp` → `replace`).
  - `?action=kap_news_status` → cache durum teşhisi (dosya yolları, entry
    sayısı, watchlist yaşı).
- **METUR vakası end-to-end doğrulandı:** `detect_aliases` METUR→BLUME
  eşlemesini buldu/kaydetti; `stock_health` `renamed` olarak işaretledi ve
  `successor.new=BLUME` ekledi; `migrate_position` dry-run planı doğru;
  KAP cache YIGIT örneğinden sonra disk'e yazıldı ve restart sonrası
  hidrate edildi.
