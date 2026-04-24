"""extras paketi: ek analitik / brain / backtest fonksiyonları (v35 façade).

Bu paket eskiden tek dosyalı `predator/extras.py` modülüydü; v35.x'te alt
modüllere bölündü. Geriye uyumluluk için tüm public sembolleri burada
yeniden ihraç ediyoruz; çağrı kodları (app.py, brain.py, daemon.py vb.)
hâlâ `from predator import extras; extras.X` veya `from predator.extras import X`
biçiminde kullanabilir.

Alt modüller:
- _chart_io     : fetch_chart2_candles, _read_json_cache, _write_json_cache,
                  calculate_atr_chart, _ideal_text
- _smc          : calculate_smc, detect_harmonic_patterns
- _volume       : calculate_volume_profile, calculate_vwap_bands,
                  _calc_avwap_from, calculate_avwap_strategies,
                  detect_gap_analysis, calculate_ofi_full,
                  calculate_adaptive_volatility
- _risk         : run_monte_carlo_risk, calculate_kelly_criterion
- _mtf          : get_weekly_signal, mtf_confluence_score
- _brain_stats  : brain_get_stats, brain_find_similar_history,
                  get_backtest_stats
- _movers       : find_similar_movers, find_price_only_movers ve yardımcılar
- _news         : fetch_news, fetch_gundem, fetch_bilanco
- _smc_pack     : compute_smc_pack, warm_smc_cache (predictive warm cache)
"""
from __future__ import annotations

from ._brain_stats import (
    brain_find_similar_history,
    brain_get_stats,
    get_backtest_stats,
)
from ._chart_io import (
    _ideal_text,
    _read_json_cache,
    _write_json_cache,
    calculate_atr_chart,
    fetch_chart2_candles,
)
from ._movers import (
    _cosine_sim_pm,
    _movement_similarity,
    _price_mov_vec,
    _stock_fingerprint,
    find_price_only_movers,
    find_similar_movers,
)
from ._mtf import get_weekly_signal, mtf_confluence_score
from ._news import fetch_bilanco, fetch_gundem, fetch_news
from ._risk import calculate_kelly_criterion, run_monte_carlo_risk
from ._smc import calculate_smc, detect_harmonic_patterns
from ._smc_pack import compute_smc_pack, warm_smc_cache
from ._volume import (
    _calc_avwap_from,
    calculate_adaptive_volatility,
    calculate_avwap_strategies,
    calculate_ofi_full,
    calculate_volume_profile,
    calculate_vwap_bands,
    detect_gap_analysis,
)

__all__ = [
    "brain_find_similar_history",
    "brain_get_stats",
    "calculate_adaptive_volatility",
    "calculate_atr_chart",
    "calculate_avwap_strategies",
    "calculate_kelly_criterion",
    "calculate_ofi_full",
    "calculate_smc",
    "calculate_volume_profile",
    "calculate_vwap_bands",
    "compute_smc_pack",
    "detect_gap_analysis",
    "detect_harmonic_patterns",
    "fetch_bilanco",
    "fetch_chart2_candles",
    "fetch_gundem",
    "fetch_news",
    "find_price_only_movers",
    "find_similar_movers",
    "get_backtest_stats",
    "get_weekly_signal",
    "mtf_confluence_score",
    "run_monte_carlo_risk",
    "warm_smc_cache",
]
