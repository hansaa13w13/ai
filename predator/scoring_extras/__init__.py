"""scoring_extras façade — geriye uyumlu re-export.

Eskiden tek dosya (`scoring_extras.py`, 1203 satır) olan modül artık
sub-modüllere bölündü. Tüm dış kullanım (``from .scoring_extras import X``)
bu façade üzerinden çalışır.

PHP eşleşmeleri:
- getAIPerformanceStats          → ai_performance_stats
- updateSignalOutcomes           → update_signal_outcomes
- calculateConfidenceScore       → calculate_confidence_score
- getCalibrationSuggestions      → get_calibration_suggestions
- brainGetConfluenceBonus        → brain_get_confluence_bonus
- brainGetTimeBonus              → brain_get_time_bonus
- getConfluenceKey               → get_confluence_key
- getMarketBreadth               → get_market_breadth
- getAIReasoning                 → get_ai_reasoning
- calculateConsensusScore        → calculate_consensus_score
- getRadarMembership             → get_radar_membership
- getUnifiedPositionConfidence   → get_unified_position_confidence
- getBrainBacktestFusion         → get_brain_backtest_fusion
- buildAIBreakdown               → build_ai_breakdown
- dualBrainKnowledgeTransfer     → dual_brain_knowledge_transfer
"""

from __future__ import annotations

from ._safe import _safe_num, _safe_str
from ._perf import (
    ai_performance_stats,
    update_signal_outcomes,
    get_calibration_suggestions,
)
from ._confidence import calculate_confidence_score
from ._brain_bonus import (
    get_confluence_key,
    brain_get_confluence_bonus,
    brain_get_time_bonus,
)
from ._breadth import get_market_breadth, reset_breadth_cache
from ._reasoning import get_ai_reasoning
from ._consensus import calculate_consensus_score
from ._radar import get_radar_membership, reset_radar_caches
from ._position import (
    get_unified_position_confidence,
    get_brain_backtest_fusion,
)
from ._breakdown import build_ai_breakdown
from ._dual import dual_brain_knowledge_transfer
from ._sleeper import sleeper_breakdown
from ._sector_rotation import (
    get_sector_metrics,
    early_catch_bonus,
    reset_sector_cache,
)
from ._sleeper_stats import sleeper_performance_stats

__all__ = [
    # Performans / kalibrasyon
    "ai_performance_stats",
    "update_signal_outcomes",
    "get_calibration_suggestions",
    # Güven
    "calculate_confidence_score",
    # Beyin bonusları
    "get_confluence_key",
    "brain_get_confluence_bonus",
    "brain_get_time_bonus",
    # Genişlik
    "get_market_breadth",
    "reset_breadth_cache",
    # Sebep
    "get_ai_reasoning",
    # Konsensüs
    "calculate_consensus_score",
    # Radar
    "get_radar_membership",
    "reset_radar_caches",
    # Pozisyon
    "get_unified_position_confidence",
    "get_brain_backtest_fusion",
    # Breakdown
    "build_ai_breakdown",
    # Dual brain
    "dual_brain_knowledge_transfer",
    # Uyuyan Mücevher
    "sleeper_breakdown",
    # Sektör rotasyon — Erken yakalama
    "get_sector_metrics",
    "early_catch_bonus",
    "reset_sector_cache",
    # Uyuyan Mücevher gerçek-getiri istatistikleri
    "sleeper_performance_stats",
    # Yardımcılar (private ama bazı modüller import ediyor olabilir)
    "_safe_num",
    "_safe_str",
]
