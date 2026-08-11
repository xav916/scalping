"""Refuser les heures ou le spread coute anormalement cher, par instrument.

Mesure du 2026-08-11 sur **15 150 bougies M1 / 14 jours**, or :

```
06h-19h  x1,00   plateau, le moins cher
02h-05h  x1,14-1,28
00h-01h  x1,53-1,63
20h, 22h x2,13   le double
23h      x1,63
```

⚠️ **Honnetement : l'effet est petit.** Rapporte a la distance au stop
reellement utilisee (0,153 %), le spread passe de 1,28 % a 2,73 % de R — soit
**~0,015 R** sur les trades concernes, deux ordres de grandeur sous les 0,329 R
recuperes en desarmant le stop suiveur. La porte est posee parce qu'elle est
gratuite et que le glissement nocturne, non mesurable ici, joue dans le meme
sens — pas parce qu'elle serait un levier majeur.

⚠️ La porte est **par instrument et pilotee par la configuration**, jamais des
heures codees en dur : le profil de spread appartient au COUPLE (courtier,
instrument) et changera.
"""
import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.services import mt5_bridge


@pytest.fixture
def fenetres(monkeypatch):
    def _poser(config):
        monkeypatch.setattr(mt5_bridge, "PAIR_TRADING_HOURS_UTC", config)
    return _poser


def _a(h):
    return datetime(2026, 8, 11, h, 30, tzinfo=timezone.utc)


# --- la fenetre simple -----------------------------------------------------

def test_dans_la_fenetre_on_laisse_passer(fenetres):
    fenetres({"XAU/USD": "06-19"})
    assert mt5_bridge._heure_defavorable("XAU/USD", _a(12)) is None


@pytest.mark.parametrize("h", [20, 22, 23, 0, 1, 5])
def test_hors_fenetre_on_refuse(fenetres, h):
    fenetres({"XAU/USD": "06-19"})
    assert mt5_bridge._heure_defavorable("XAU/USD", _a(h)) == "heure_spread_defavorable"


@pytest.mark.parametrize("h", [6, 19])
def test_les_bornes_sont_INCLUSES(fenetres, h):
    """06-19 doit couvrir toute l'heure de 19h, pas s'arreter a 19h00."""
    fenetres({"XAU/USD": "06-19"})
    assert mt5_bridge._heure_defavorable("XAU/USD", _a(h)) is None


# --- la fenetre qui enjambe minuit -----------------------------------------

def test_fenetre_a_cheval_sur_minuit(fenetres):
    """Une session asiatique s'ecrit 22-05 et ne doit pas devenir vide."""
    fenetres({"XAU/USD": "22-05"})
    for h in (22, 23, 0, 3, 5):
        assert mt5_bridge._heure_defavorable("XAU/USD", _a(h)) is None
    for h in (6, 12, 21):
        assert mt5_bridge._heure_defavorable("XAU/USD", _a(h)) == "heure_spread_defavorable"


# --- ne rien casser --------------------------------------------------------

def test_paire_non_configuree_passe_toujours(fenetres):
    """Seuls les instruments explicitement mesures sont contraints."""
    fenetres({"XAU/USD": "06-19"})
    assert mt5_bridge._heure_defavorable("EUR/USD", _a(23)) is None


def test_configuration_vide_ne_bloque_rien(fenetres):
    fenetres({})
    assert mt5_bridge._heure_defavorable("XAU/USD", _a(23)) is None


@pytest.mark.parametrize("mauvais", ["", "abc", "06", "06-", "-19", "25-30", "06-19-22", None])
def test_configuration_illisible_ne_bloque_JAMAIS(fenetres, mauvais):
    """⚠️ Une porte qui se ferme sur une config mal ecrite arreterait le
    trading sans que personne ne comprenne pourquoi. Illisible = pas de
    contrainte, comme l'ajustement a la marge et le controle du risque."""
    fenetres({"XAU/USD": mauvais})
    assert mt5_bridge._heure_defavorable("XAU/USD", _a(23)) is None


# --- la porte est-elle branchee ? ------------------------------------------

def test_la_porte_est_appelee_dans_la_chaine():
    """Verification par arbre syntaxique : un correctif non branche ne sert a
    rien, ce projet en a deja livre un."""
    src = Path(mt5_bridge.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(src)
    chaine = next(n for n in ast.walk(arbre)
                  if isinstance(n, ast.FunctionDef) and n.name == "_check_rejection")
    appels = {n.func.id for n in ast.walk(chaine)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_heure_defavorable" in appels
