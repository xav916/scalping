"""La question d'arbitrage doit dire quand répondre « continue » NE SUFFIRA PAS.

⛔ **Ce qui s'est passé le 2026-09-09 à 17h18 UTC.** Xavier répond `continue`.
Le plafond du RADAR se lève. Deux minutes plus tard, le courtier refuse :

```
17:20:10  XAG/USD sell -> blocked
  "Daily drawdown reached: loss=23.43 >= limit=21.47 (3.0% of 715.69)"
```

**Il y a DEUX plafonds journaliers indépendants**, tous deux à 3 % mais sur des
bases différentes :

| | base | seuil |
|---|---|---|
| radar (arbitrage) | solde réel, ou 650 € en repli | −21,08 € |
| **bridge (courtier)** | **solde réel chez le courtier** | **−21,47 €** |

Répondre `continue` ne lève que le premier. Or le message promettait :

    « continue : il retrade, pour CETTE tranche de perte seulement »

**C'était faux.** Il ne retrade pas — le courtier refuse derrière. Xavier a pris
une décision sur une promesse que le système ne pouvait pas tenir.

*Même famille que le message qui disait « sans réponse il reste bloqué » alors
que minuit le débloquait : un message qui ment sur ce qu'il fait.*

## Ce qui n'est PAS fait, et pourquoi

⛔ Le `continue` n'est **pas** câblé jusqu'au courtier. Deux plafonds
indépendants sont une protection en profondeur : le bridge tient même si le
radar est compromis, et son seuil est calculé sur le solde **réellement** chez
le courtier. On rend le message honnête, on ne desserre pas le dernier garde-fou
avant l'argent.

⚠️ J'ai aussi cru à un second défaut — « le radar utilise 650 € au lieu du solde
réel ». **Faux** : je l'avais mesuré depuis un `docker exec python`, donc un
processus NEUF au cache froid, pas l'application. L'état écrit par
l'application dit l'inverse (seuils de 713 € et 703 €). *Répliquer un pipeline
hors production, c'est fabriquer une copie qui dérive.*
"""
from datetime import datetime, timezone

import pytest

from backend.services import plafond_arbitrage as pa


DEMANDE = [{"destination_id": "admin_live", "palier": 1,
            "pnl_au_moment": -24.62, "seuil": -21.08}]
MAINTENANT = datetime(2026, 9, 9, 17, 18, tzinfo=timezone.utc)


def _question(courtier=None):
    return pa.construire_question(DEMANDE, maintenant=MAINTENANT,
                                  plafond_courtier=courtier)


def test_le_message_AVERTIT_quand_le_courtier_refusera_aussi(db=None):
    """⛔ Le cœur : sans cet avertissement, `continue` promet un déblocage
    que le système ne peut pas livrer."""
    texte = _question({"admin_live": {"seuil": -21.47, "solde": 715.69}})
    plat = " ".join(texte.split())

    assert "21.47" in plat or "21,47" in plat
    assert "courtier" in plat.lower()
    assert "refusera" in plat.lower() or "ne suffira pas" in plat.lower()


def test_PAS_d_avertissement_quand_le_courtier_laisse_passer():
    """⚠️ Un avertissement qui s'affiche toujours ne veut plus rien dire."""
    texte = _question({"admin_live": {"seuil": -80.0, "solde": 715.69}})
    assert "ne suffira pas" not in texte.lower()
    assert "refusera" not in texte.lower()


def test_un_courtier_ILLISIBLE_ne_fabrique_aucune_promesse():
    """⛔ Ne pas savoir ce que fera le courtier n'autorise pas à affirmer
    qu'il laissera passer. On se tait plutôt que de rassurer à tort."""
    for absent in (None, {}, {"admin_live": None}):
        texte = _question(absent)
        assert "refusera" not in texte.lower()
        assert "laissera passer" not in texte.lower()


def test_le_message_reste_SANS_chevrons():
    """L'endpoint échappe le HTML — une balise s'afficherait telle quelle."""
    texte = _question({"admin_live": {"seuil": -21.47, "solde": 715.69}})
    assert "<" not in texte and ">" not in texte


def test_l_echeance_de_minuit_est_TOUJOURS_la():
    """Le correctif d'aujourd'hui ne doit pas être écrasé par celui-ci."""
    texte = _question({"admin_live": {"seuil": -21.47, "solde": 715.69}})
    assert "02h00 Paris" in texte


def test_construire_question_marche_SANS_le_nouveau_parametre():
    """Rétrocompatible : les appelants existants ne le passent pas."""
    assert "PLAFOND DE PERTE FRANCHI" in pa.construire_question(DEMANDE)


# ─── La lecture du plafond courtier ──────────────────────────────────

def test_plafond_du_courtier_ne_LEVE_jamais(monkeypatch):
    """⛔ Cette lecture est sur le chemin qui PRÉVIENT Xavier. La faire
    tomber sur un bridge injoignable produirait un blocage muet — exactement
    ce que ce job existe pour empêcher."""
    def _boom(*a, **k):
        raise RuntimeError("bridge injoignable")
    monkeypatch.setattr(pa, "_lire_health", _boom, raising=False)
    assert pa.plafond_du_courtier(["admin_live"]) == {}


def test_plafond_du_courtier_calcule_le_seuil(monkeypatch):
    monkeypatch.setattr(
        pa, "_lire_health",
        lambda dest: {"garde_fous": {"max_daily_loss_pct": 3.0},
                      "balance": 715.69},
        raising=False)
    r = pa.plafond_du_courtier(["admin_live"])
    assert r["admin_live"]["seuil"] == pytest.approx(-21.47, abs=0.01)
    assert r["admin_live"]["solde"] == pytest.approx(715.69)


def test_un_health_INCOMPLET_ne_rend_rien_pour_ce_compte(monkeypatch):
    """Un solde absent ou un pourcentage nul ne permettent aucun seuil —
    et inventer un seuil serait pire que de se taire."""
    for creux in ({"garde_fous": {}, "balance": 715.69},
                  {"garde_fous": {"max_daily_loss_pct": 3.0}},
                  {"garde_fous": {"max_daily_loss_pct": 0}, "balance": 715.69}):
        monkeypatch.setattr(pa, "_lire_health", lambda d, c=creux: c,
                            raising=False)
        assert pa.plafond_du_courtier(["admin_live"]) == {}


# ─── Le test qui aurait attrapé le vrai défaut ───────────────────────

def test_lire_health_interroge_les_DEUX_endpoints(monkeypatch):
    """⛔ Le défaut réel, trouvé APRÈS déploiement : `_lire_health` ne lisait
    que `/health`, où `balance` N'EXISTE PAS. Le correctif se déployait, les
    tests passaient — et il ne lisait rien en production.

    Les tests ci-dessus remplacent `_lire_health` : ils auraient laissé passer
    cette version cassée. Celui-ci exerce la vraie fonction.

        /health   garde_fous.max_daily_loss_pct   (sans clé)
        /account  balance                         (clé X-API-Key requise)
    """
    import json
    import urllib.request

    vus: list[str] = []
    reponses = {
        "/health": {"garde_fous": {"max_daily_loss_pct": 3.0}},
        "/account": {"balance": 715.69},
    }

    class _Rep:
        def __init__(self, charge):
            self._c = json.dumps(charge).encode()

        def read(self):
            return self._c

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _faux_urlopen(req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        chemin = "/health" if url.endswith("/health") else "/account"
        vus.append(chemin)
        return _Rep(reponses[chemin])

    monkeypatch.setattr(urllib.request, "urlopen", _faux_urlopen)
    monkeypatch.setattr(json, "load", lambda f: json.loads(f.read()))
    monkeypatch.setenv("MT5_BRIDGE_LIVE_URL", "http://bridge:8788")
    monkeypatch.setenv("MT5_BRIDGE_LIVE_API_KEY", "secret")

    h = pa._lire_health("admin_live")

    assert vus == ["/health", "/account"], (
        f"les deux endpoints ne sont pas interroges : {vus}")
    assert h["balance"] == 715.69
    assert h["garde_fous"]["max_daily_loss_pct"] == 3.0
