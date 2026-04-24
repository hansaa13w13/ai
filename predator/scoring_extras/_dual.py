"""Triple Brain DÜELLO bilgi transferi."""

from __future__ import annotations

from ..utils import now_tr


def dual_brain_knowledge_transfer(brain: dict, snap: dict, ret: float, loser: str) -> None:
    """v38.1 Triple Brain DÜELLO — kayıp ağ(lar)a cezalı eğitim + düello istatistikleri.

    PHP dualBrainKnowledgeTransfer + üçüncü ağ (Gamma) tam desteği. Python'da
    artık üç ayrı ağ (`neural_net`, `neural_net_beta`, `neural_net_gamma`)
    olduğu için her birine bağımsız extra step uygulanır.

    Loser etiketleri (brain._decide_duel_loser ile uyumlu):
      • "alpha" / "beta" / "gamma" — tek kayıp
      • "alpha_beta" — Alpha+Beta kaybı (Gamma şampiyon)
      • "alpha_gamma" — Alpha+Gamma kaybı (Beta şampiyon)
      • "beta_gamma" — Beta+Gamma kaybı (Alpha şampiyon)
      • "tie" / "all" — beraberlik, sadece sayaç
    """
    extra_steps = 3
    lr_mult = 2.2

    loser_set: set[str] = set()
    if loser == "alpha":
        loser_set = {"alpha"}
    elif loser == "beta":
        loser_set = {"beta"}
    elif loser == "gamma":
        loser_set = {"gamma"}
    elif loser == "alpha_beta":
        loser_set = {"alpha", "beta"}
    elif loser == "alpha_gamma":
        loser_set = {"alpha", "gamma"}
    elif loser == "beta_gamma":
        loser_set = {"beta", "gamma"}
    elif loser in ("all", "both"):
        loser_set = {"alpha", "beta", "gamma"}
    # tie / unknown → boş set, sadece sayaç güncellenir

    # Hangi ağ(lar) kaybetti → ek lr×2.2 adım uygula
    if loser_set:
        try:
            from ..neural import train_on_outcome
            from ..observability import log_exc
            mapping = {
                "alpha": "neural_net",
                "beta":  "neural_net_beta",
                "gamma": "neural_net_gamma",
            }
            for name in loser_set:
                net = brain.get(mapping[name])
                if not net:
                    continue
                for _ in range(extra_steps):
                    try:
                        train_on_outcome(net, snap, ret, lr_mult=lr_mult)
                    except TypeError:
                        # Eski imzayla uyumluluk: lr_mult parametresi yoksa
                        train_on_outcome(net, snap, ret)
                    except Exception as e:
                        log_exc("brain", f"duel extra-step fail ({name})", e)
                        break
        except Exception as e:
            try:
                from ..observability import log_exc as _le
                _le("brain", "duel transfer outer fail", e)
            except Exception:
                pass

    # Triple Brain rekabet istatistikleri
    if "dual_brain_stats" not in brain:
        brain["dual_brain_stats"] = {
            "alpha_wins": 0, "beta_wins": 0, "gamma_wins": 0,
            "ties": 0, "total_duels": 0,
            "alpha_streak": 0, "beta_streak": 0, "gamma_streak": 0,
            "current_champion": "tie", "last_duel": "", "duel_log": [],
        }
    ds = brain["dual_brain_stats"]
    ds["total_duels"] = int(ds.get("total_duels") or 0) + 1
    ds["last_duel"] = now_tr().strftime("%Y-%m-%d %H:%M:%S")
    # v38.1: Üç ağ için tam streak/win sayımı
    if loser in ("beta", "beta_gamma"):
        # Alpha tek (veya birlikte top) şampiyon
        ds["alpha_wins"] = int(ds.get("alpha_wins") or 0) + 1
        ds["alpha_streak"] = int(ds.get("alpha_streak") or 0) + 1
        ds["beta_streak"] = 0
        ds["gamma_streak"] = 0
        ds["current_champion"] = "alpha"
    elif loser in ("alpha", "alpha_gamma"):
        ds["beta_wins"] = int(ds.get("beta_wins") or 0) + 1
        ds["beta_streak"] = int(ds.get("beta_streak") or 0) + 1
        ds["alpha_streak"] = 0
        ds["gamma_streak"] = 0
        ds["current_champion"] = "beta"
    elif loser == "alpha_beta":
        ds["gamma_wins"] = int(ds.get("gamma_wins") or 0) + 1
        ds["gamma_streak"] = int(ds.get("gamma_streak") or 0) + 1
        ds["alpha_streak"] = 0
        ds["beta_streak"] = 0
        ds["current_champion"] = "gamma"
    elif loser == "gamma":
        # Gamma tek kaybeden → Alpha+Beta birlikte üstte → split win
        ds["alpha_wins"] = int(ds.get("alpha_wins") or 0) + 1
        ds["beta_wins"] = int(ds.get("beta_wins") or 0) + 1
        ds["gamma_streak"] = 0
        # Şampiyon mevcut akışı koru ya da Alpha/Beta'dan birini seç → Alpha
        ds["current_champion"] = "alpha"
    else:  # tie / all
        ds["ties"] = int(ds.get("ties") or 0) + 1
        ds["alpha_streak"] = 0
        ds["beta_streak"] = 0
        ds["gamma_streak"] = 0
    code = snap.get("code") or "?"
    log = ds.get("duel_log") or []
    log.insert(0, {
        "code": code, "loser": loser,
        "ret": round(ret, 2),
        "at": now_tr().strftime("%d.%m %H:%M"),
    })
    ds["duel_log"] = log[:20]
