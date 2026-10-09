"""Fenêtre hebdomadaire de trading : lundi 00h05 → vendredi 22h40, HEURE DE PARIS.

Demande de Xavier le 2026-10-09 : « je veux des horaires hebdomadaires, de
00h05 lundi à 22h40 vendredi ».

## 🔑 POURQUOI PARIS, ET PAS UTC

Les séances du courtier sont modélisées en **UTC** dans `market_hours` : les
métaux ouvrent **dimanche 22:00 UTC** et ferment **vendredi 21:00 UTC**.

Ses horaires s'y superposent exactement s'ils sont lus en **heure de Paris** :

```
lundi   00h05 Paris = dimanche 22h05 UTC  ->   5 min APRÈS l'ouverture
vendredi 22h40 Paris = vendredi 20h40 UTC  ->  20 min AVANT la clôture
```

⇒ Sa fenêtre est un **sous-ensemble strict** de la séance, avec une marge de
chaque côté. Lue en UTC, elle n'aurait eu aucun sens : elle aurait commencé
2 h après l'ouverture et fini 20 min... après la clôture.

## ⛔ ET PARIS N'EST PAS UN DÉCALAGE FIXE

UTC+2 en été, UTC+1 en hiver. Mesuré dans le conteneur : décalage de 2 h le
24 octobre 2026, de 1 h le 26. Coder « UTC+2 » ferait donc glisser la fenêtre
d'une heure fin octobre, **en silence**.

⇒ On utilise `zoneinfo.ZoneInfo("Europe/Paris")`, vérifié disponible dans
l'image.

## Les bornes, et leur sens

- **début INCLUSIF** : à 00h05:00 pile, on trade ;
- **fin EXCLUSIVE** : à 22h40:00 pile, on ne trade plus. « De 00h05 à 22h40 »
  décrit une fenêtre qui *se termine* à 22h40.
"""
from __future__ import annotations

import importlib
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture()
def F(monkeypatch):
    for k in ("FENETRE_HEBDO_DEBUT", "FENETRE_HEBDO_FIN", "FENETRE_HEBDO_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    from backend.services import fenetre_hebdo as mod
    importlib.reload(mod)
    return mod


def _paris(annee, mois, jour, h, m):
    return datetime(annee, mois, jour, h, m, tzinfo=PARIS)


# ─────────────────────────────────────────────────────────────────────────
# 1. Les bornes de sa fenêtre
# ─────────────────────────────────────────────────────────────────────────

def test_la_fenetre_par_defaut_est_celle_de_Xavier(F):
    assert F.fenetre() == ((0, 0, 5), (4, 22, 40))


def test_lundi_00h04_est_FERME(F):
    """⛔ Une minute avant : on ne trade pas."""
    # 2026-10-12 est un lundi.
    assert F.ouverte(_paris(2026, 10, 12, 0, 4)) is False


def test_lundi_00h05_PILE_est_ouvert(F):
    """Borne de debut INCLUSIVE."""
    assert F.ouverte(_paris(2026, 10, 12, 0, 5)) is True


def test_le_milieu_de_semaine_est_ouvert(F):
    for jour in (12, 13, 14, 15, 16):      # lundi -> vendredi
        assert F.ouverte(_paris(2026, 10, jour, 14, 0)) is True, jour


def test_vendredi_22h39_est_encore_ouvert(F):
    assert F.ouverte(_paris(2026, 10, 16, 22, 39)) is True


def test_vendredi_22h40_PILE_est_FERME(F):
    """⛔ Borne de fin EXCLUSIVE : << de 00h05 a 22h40 >> decrit une fenetre qui
    SE TERMINE a 22h40."""
    assert F.ouverte(_paris(2026, 10, 16, 22, 40)) is False


def test_vendredi_apres_22h40_est_FERME(F):
    assert F.ouverte(_paris(2026, 10, 16, 23, 30)) is False


def test_le_WEEK_END_est_ferme(F):
    assert F.ouverte(_paris(2026, 10, 17, 12, 0)) is False   # samedi
    assert F.ouverte(_paris(2026, 10, 18, 12, 0)) is False   # dimanche
    # ⛔ Y COMPRIS dimanche soir, quand le marche de l'or REOUVRE (22h UTC) :
    # sa fenetre ne commence qu'a lundi 00h05.
    assert F.ouverte(_paris(2026, 10, 18, 23, 59)) is False


# ─────────────────────────────────────────────────────────────────────────
# 2. ⛔ PARIS, et le changement d'heure
# ─────────────────────────────────────────────────────────────────────────

def test_la_fenetre_suit_le_CHANGEMENT_D_HEURE(F):
    """⛔ Paris est UTC+2 en ete et UTC+1 en hiver. Coder un decalage FIXE
    ferait glisser la fenetre d'une heure fin octobre, EN SILENCE.

    Le test porte sur l'HEURE MURALE : vendredi 22h39 doit etre ouvert et
    22h40 ferme, en ete comme en hiver.
    """
    # Vendredi 16 octobre 2026 : heure d'ETE (UTC+2).
    assert F.ouverte(_paris(2026, 10, 16, 22, 39)) is True
    assert F.ouverte(_paris(2026, 10, 16, 22, 40)) is False
    # Vendredi 30 octobre 2026 : heure d'HIVER (UTC+1).
    assert F.ouverte(_paris(2026, 10, 30, 22, 39)) is True
    assert F.ouverte(_paris(2026, 10, 30, 22, 40)) is False


def test_un_instant_en_UTC_est_CONVERTI_et_non_lu_tel_quel(F):
    """🔑 Le cœur du piege. Vendredi 21h00 UTC vaut 23h00 a Paris : la fenetre
    est FERMEE. Lu tel quel en UTC, 21h00 serait tombe en plein dedans."""
    from datetime import timezone
    assert F.ouverte(datetime(2026, 10, 16, 21, 0, tzinfo=timezone.utc)) is False
    # …et 20h30 UTC vaut 22h30 Paris : encore ouvert.
    assert F.ouverte(datetime(2026, 10, 16, 20, 30, tzinfo=timezone.utc)) is True


def test_un_instant_SANS_fuseau_est_lu_comme_UTC(F):
    """⚠️ Le radar manipule des `datetime` naifs par endroits. Les lire comme
    de l'heure LOCALE de la machine ferait dependre la decision du poste --
    c'est le defaut du filtre << du jour >> du 07/10."""
    assert F.ouverte(datetime(2026, 10, 16, 21, 0)) is False


# ─────────────────────────────────────────────────────────────────────────
# 3. Le réglage, et ses replis
# ─────────────────────────────────────────────────────────────────────────

def test_les_bornes_sont_reglables(monkeypatch):
    monkeypatch.setenv("FENETRE_HEBDO_DEBUT", "mar 08:30")
    monkeypatch.setenv("FENETRE_HEBDO_FIN", "jeu 18:00")
    from backend.services import fenetre_hebdo as mod
    importlib.reload(mod)

    assert mod.fenetre() == ((1, 8, 30), (3, 18, 0))
    assert mod.ouverte(_paris(2026, 10, 13, 8, 30)) is True    # mardi 8h30
    assert mod.ouverte(_paris(2026, 10, 13, 8, 29)) is False
    assert mod.ouverte(_paris(2026, 10, 16, 12, 0)) is False    # vendredi


@pytest.mark.parametrize("mauvais", ["n importe quoi", "lun", "lun 25:00",
                                     "xxx 00:05", "", "lun 00:05 extra"])
def test_un_reglage_ILLISIBLE_retombe_sur_la_fenetre_DECLAREE(monkeypatch, mauvais):
    """⛔ Ni fenetre vide (qui bloquerait TOUT en silence), ni fenetre totale
    (qui ouvrirait le week-end). On retombe sur celle que Xavier a dictee --
    meme choix que `ECHELLE_STOP_OR_PALIERS`."""
    monkeypatch.setenv("FENETRE_HEBDO_DEBUT", mauvais)
    monkeypatch.delenv("FENETRE_HEBDO_FIN", raising=False)
    from backend.services import fenetre_hebdo as mod
    importlib.reload(mod)

    assert mod.fenetre() == ((0, 0, 5), (4, 22, 40))


def test_la_porte_est_DESARMABLE(monkeypatch):
    """⚠️ Un interrupteur, pour revenir en arriere sans deploiement."""
    monkeypatch.setenv("FENETRE_HEBDO_ENABLED", "false")
    from backend.services import fenetre_hebdo as mod
    importlib.reload(mod)

    assert mod.ouverte(_paris(2026, 10, 17, 12, 0)) is True    # samedi, et ouvert


# ─────────────────────────────────────────────────────────────────────────
# 4. Le motif de refus porte un nom
# ─────────────────────────────────────────────────────────────────────────

def test_le_motif_de_refus_est_NOMME(F):
    assert F.MOTIF == "hors_fenetre_hebdo"


def test_le_motif_a_un_LIBELLE_francais():
    """⚠️ Un code sans libelle s'affiche en brut dans les recapitulatifs --
    troisieme fois aujourd'hui que je le verifie."""
    from backend.services.rejection_service import REASON_LABELS_FR as L

    assert "hors_fenetre_hebdo" in L
    assert "hebdo" in L["hors_fenetre_hebdo"].lower() or \
           "semaine" in L["hors_fenetre_hebdo"].lower()


def test_le_detail_DIT_la_fenetre_et_l_heure_de_Paris(F):
    """🔑 Un refus qui ne dit pas POURQUOI oblige a relire le code. Celui-la
    doit porter la fenetre ET l'heure de Paris du moment."""
    d = F.detail(_paris(2026, 10, 17, 12, 0))

    assert "00:05" in d and "22:40" in d
    assert "Paris" in d
    assert "samedi" in d.lower() or "12:00" in d


# ─────────────────────────────────────────────────────────────────────────
# 5. ⛔ LA PORTE EST BRANCHÉE — sinon elle calcule juste et ne refuse rien
# ─────────────────────────────────────────────────────────────────────────

def test_la_porte_est_BRANCHEE_dans_la_chaine_d_admission():
    """⛔ LE DÉFAUT DE CE MATIN, EN PIRE. L'échelle de gains calculait le bon
    prix et n'appliquait rien pendant des heures. Une fenêtre horaire qui
    calcule juste et ne refuse pas serait du même ordre : parfaitement testée,
    parfaitement inerte.
    """
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "services"
           / "mt5_bridge.py").read_text(encoding="utf-8")

    assert "fenetre_hebdo" in src, (
        "la fenêtre hebdomadaire n'est pas branchée dans mt5_bridge")
    assert "hors_fenetre_hebdo" in src or "fenetre_hebdo.MOTIF" in src


def test_la_porte_est_posee_PRES_de_celle_des_horaires_de_marche():
    """🔑 Les deux portes répondent à la même question — « a-t-on le droit de
    trader MAINTENANT ? ». Les séparer dans le fichier ferait qu'une relecture
    n'en verrait qu'une."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "services"
           / "mt5_bridge.py").read_text(encoding="utf-8")

    i_marche = src.index("is_market_open_for_destination(setup.pair")
    i_hebdo = src.index("fenetre_hebdo.ouverte(")
    assert abs(i_hebdo - i_marche) < 1500, (
        "les deux portes horaires sont trop éloignées dans le fichier")
