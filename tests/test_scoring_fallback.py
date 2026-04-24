"""calculate_ai_score → phpmatch ana yol + fallback şeffaflığı."""
from __future__ import annotations

from predator import scoring


def _minimal_stock():
    return {
        "rsi": 55, "adxVal": 25, "adxDir": "yukseli", "cmf": 0.05,
        "mfi": 55, "volRatio": 1.2, "pos52wk": 60,
        "fiyat": 10.0, "score": 100, "aiScore": 100, "techScore": 50,
    }


class TestAIScoreNormalPath:
    def test_returns_int_and_marks_no_fallback(self):
        s = _minimal_stock()
        score = scoring.calculate_ai_score(s)
        assert isinstance(score, int)
        # phpmatch yüklendiğinde bayrak False olmalı
        assert s.get("aiScoreFallback") is False
        # alPuani UI için işaretlenmeli
        assert "alPuani" in s


class TestAIScoreFallbackPath:
    def test_fallback_marks_flag_and_returns_int(self, monkeypatch):
        """phpmatch import'u patlatılınca fallback devreye girer ve damga
        düşer — sessiz fallback yok."""
        import sys
        import predator.scoring_phpmatch as pm

        # phpmatch'in fonksiyonu patlasın
        def _boom(*a, **kw):
            raise RuntimeError("simülasyon: phpmatch indisposed")

        monkeypatch.setattr(pm, "calculate_al_puani", _boom)
        # Loglamayı yeniden tetikleyebilmek için global bayrağı sıfırla
        monkeypatch.setattr(scoring, "_AI_SCORE_FALLBACK_LOGGED", False)
        monkeypatch.setattr(scoring, "_AI_SCORE_FALLBACK_COUNT", 0)

        s = _minimal_stock()
        score = scoring.calculate_ai_score(s)

        assert isinstance(score, int)
        assert s.get("aiScoreFallback") is True
        assert scoring._AI_SCORE_FALLBACK_COUNT >= 1

    def test_fallback_score_in_reasonable_range(self, monkeypatch):
        import predator.scoring_phpmatch as pm
        monkeypatch.setattr(pm, "calculate_al_puani",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("x")))

        s = _minimal_stock()
        score = scoring.calculate_ai_score(s)
        # Fallback skor mantıklı bir aralıkta olmalı
        assert -50 <= score <= 500
