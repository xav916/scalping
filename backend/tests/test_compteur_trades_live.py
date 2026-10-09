"""Le COMPTE des trades en live, en permanence — et l'alerte sur le RÉSULTAT.

Reproche de Xavier le 2026-10-09, et il est juste :

> « Tu dois te demander par toi-même pourquoi je n'ai plus de trades de lancés,
> il faut que tu aies constamment le nombre de trades en live »

## ⛔ MON ERREUR DE CONCEPTION

J'avais construit des sondes qui vérifient que les **mécanismes** fonctionnent,
pas que le **résultat** arrive. Ma sonde P0-3 ne se déclenchait que sur le
**silence** :

```python
if ... and ordres_recents == 0 and setups_recents > 0 and not refus_recents:
```

🔑 Ce `not refus_recents` est le défaut. **Si les portes refusent 100 % du temps
pendant deux heures, la sonde se tait** — tout « fonctionne », et rien ne sort.
Or ce qui compte pour Xavier n'est pas que les portes parlent : c'est **combien
de trades sont vivants**.

## Ce que ces tests épinglent

1. le compte est **séparé** RADAR / MAIN — un trade à la main n'est pas un
   trade du système, et les confondre cacherait l'arrêt de l'automatique
   derrière l'activité de Xavier ;
2. l'absence **PERSISTANTE** de résultat est une anomalie **même quand les
   portes refusent** ;
3. ⛔ et l'anomalie **NOMME le blocage dominant** : sans lui, « aucun trade »
   n'est pas actionnable. Le 09/10 à 18h21 la réponse était « tes deux
   positions à la main consomment la marge » ;
4. un blocage dont la cause est **chez Xavier** escalade au lieu d'être
   « réparé » : on ne ferme pas ses positions à sa place.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2] / "scripts" / "sondes_p0.py")
MARQUE = "scalping-radar-2026-10-09"


@pytest.fixture()
def s(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("sondes_p0", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_db_path", lambda: str(tmp_path / "trades.db"))
    return mod


def _pos(ticket, comment=MARQUE):
    return {"ticket": ticket, "symbol": "XAUUSD", "type": "buy",
            "price_open": 4190.0, "price_current": 4190.0, "sl": 4168.0,
            "profit": 0.0, "comment": comment}


# ─────────────────────────────────────────────────────────────────────────
# 1. Le compte, séparé RADAR / MAIN
# ─────────────────────────────────────────────────────────────────────────

def test_le_compte_SEPARE_le_radar_de_la_main(s):
    """🔑 Les confondre cacherait l'arret de l'automatique derriere l'activite
    de Xavier — exactement la situation du 09/10 a 18h21 : 2 positions live,
    ZERO du radar."""
    live = s.compter_live([_pos(1), _pos(2, comment=""), _pos(3, comment="")])

    assert live["total"] == 3
    assert live["radar"] == 1
    assert live["main"] == 2


def test_aucune_position_rend_des_zeros_et_non_une_absence(s):
    live = s.compter_live([])

    assert live == {"total": 0, "radar": 0, "main": 0}


def test_le_compte_est_INSCRIT_a_chaque_passage(s):
    """« Constamment » veut dire : une trace, pas un instantane perdu."""
    s.inscrire_live({"total": 3, "radar": 1, "main": 2}, ordres_60min=6)
    s.inscrire_live({"total": 2, "radar": 0, "main": 2}, ordres_60min=6)

    with sqlite3.connect(s._db_path()) as c:
        c.row_factory = sqlite3.Row
        lignes = [dict(x) for x in c.execute(
            "SELECT * FROM trades_live_compte ORDER BY id")]
    assert len(lignes) == 2
    assert lignes[-1]["radar"] == 0
    assert lignes[-1]["ordres_60min"] == 6


# ─────────────────────────────────────────────────────────────────────────
# 2. ⛔ L'absence PERSISTANTE de résultat, MÊME quand les portes refusent
# ─────────────────────────────────────────────────────────────────────────

def test_aucun_ordre_depuis_longtemps_est_une_anomalie_MEME_avec_des_refus(s):
    """⛔ LE DEFAUT DE MA CONCEPTION. Avant, `not refus_recents` faisait taire
    la sonde des que les portes parlaient. Deux heures de refus a 100 % ne
    disaient rien."""
    anos = s.detecter_ouverture(
        {"decision": "ALLOW", "reason_code": "ARMED"},
        refus_recents={"pattern_not_allowed": 57,
                       "bridge_marge_insuffisante": 4},
        ordres_recents=0, setups_recents=61,
        minutes_sans_ordre=95)

    a = next(x for x in anos if x["code"] == "aucun_resultat_prolonge")
    assert "95" in a["detail"]


def test_l_anomalie_NOMME_le_blocage_dominant(s):
    """⛔ Sans le blocage dominant, << aucun trade >> n'est pas actionnable.
    Le 09/10 la reponse etait : tes deux positions a la main consomment la
    marge."""
    anos = s.detecter_ouverture(
        {"decision": "ALLOW", "reason_code": "ARMED"},
        refus_recents={"bridge_marge_insuffisante": 40,
                       "pattern_not_allowed": 5},
        ordres_recents=0, setups_recents=45, minutes_sans_ordre=95)

    a = next(x for x in anos if x["code"] == "aucun_resultat_prolonge")
    assert "bridge_marge_insuffisante" in a["detail"]
    assert "40" in a["detail"]


def test_un_blocage_qui_vient_de_XAVIER_escalade_sans_rien_tenter(s):
    """⛔ On ne ferme pas ses positions a sa place. La marge saturee par ses
    propres trades n'est pas une panne a reparer : c'est un arbitrage a lui
    rendre."""
    anos = s.detecter_ouverture(
        {"decision": "ALLOW", "reason_code": "ARMED"},
        refus_recents={"bridge_marge_insuffisante": 40},
        ordres_recents=0, setups_recents=40, minutes_sans_ordre=95)

    a = next(x for x in anos if x["code"] == "aucun_resultat_prolonge")
    assert a["reparable"] is False
    # ⛔ ET LE MESSAGE DOIT LE DIRE, pas seulement le drapeau. Ma premiere
    # version du test ne verifiait que `reparable is False` — or la branche
    # << tri normal des portes >> le met AUSSI a False, donc retirer la branche
    # << cause chez Xavier >> ne faisait tomber aucun test. Le drapeau etait
    # bon par accident ; c'est le MESSAGE qui est actionnable.
    assert "TON cote" in a["detail"] or "ton arbitrage" in a["detail"], (
        "le message ne dit pas que la cause est chez Xavier : "
        f"{a['detail']}")


def test_un_SILENCE_complet_reste_reparable(s):
    """Aucun refus du tout : le chemin dort, et le reveiller est legitime."""
    anos = s.detecter_ouverture(
        {"decision": "ALLOW", "reason_code": "ARMED"},
        refus_recents={}, ordres_recents=0, setups_recents=0,
        minutes_sans_ordre=95)

    a = next(x for x in anos if x["code"] == "aucun_resultat_prolonge")
    assert a["reparable"] is True


def test_des_ordres_RECENTS_ne_declenchent_rien(s):
    """Le 09/10 a 18h21 : 6 ordres dans l'heure. Le systeme VIT, et la sonde
    doit se taire — sinon elle crie a chaque creux normal."""
    anos = s.detecter_ouverture(
        {"decision": "ALLOW", "reason_code": "ARMED"},
        refus_recents={"pattern_not_allowed": 57}, ordres_recents=6,
        setups_recents=63, minutes_sans_ordre=12)

    assert [x for x in anos if x["code"] == "aucun_resultat_prolonge"] == []


def test_sous_le_seuil_de_temps_aucune_anomalie(s):
    """⚠️ Les setups qualifies arrivent ~33/jour, soit un toutes les ~25 min :
    un creux de 40 min est NORMAL. Le seuil doit etre franchement au-dessus."""
    anos = s.detecter_ouverture(
        {"decision": "ALLOW", "reason_code": "ARMED"},
        refus_recents={"pattern_not_allowed": 20}, ordres_recents=0,
        setups_recents=20, minutes_sans_ordre=40)

    assert [x for x in anos if x["code"] == "aucun_resultat_prolonge"] == []


def test_interrupteur_DESARME_ne_double_pas_l_alerte(s):
    """⚠️ Quand l'execution est desarmee, l'absence d'ordre en DECOULE. Deux
    alertes pour une seule cause noieraient le fil."""
    anos = s.detecter_ouverture(
        {"decision": "DENY", "reason_code": "NEW_DEPLOYMENT"},
        refus_recents={}, ordres_recents=0, setups_recents=0,
        minutes_sans_ordre=95)

    codes = [x["code"] for x in anos]
    assert "execution_desarmee" in codes
    assert "aucun_resultat_prolonge" not in codes


# ─────────────────────────────────────────────────────────────────────────
# 3. Le motif « position sans stop » cesse de se cacher
# ─────────────────────────────────────────────────────────────────────────

def test_position_sans_stop_porte_son_nom():
    """⛔ Releve le 09/10 a 18h15:01, range sous `bridge_refus_indetermine` :

        "Position sans stop (tickets ['1360859402']) : risque non bornable,
         ouverture refusee"

    🔑 C'est un refus parfaitement LEGITIME — on n'ouvre pas tant qu'un risque
    n'est pas bornable — mais sous un nom qui ne dit RIEN. Troisieme fois
    aujourd'hui qu'un motif se cache dans un fourre-tout."""
    from backend.services.mt5_bridge import _categoriser_refus

    msg = ("Position sans stop (tickets ['1360859402']) : risque non bornable, "
           "ouverture refusee")
    assert _categoriser_refus(429, msg) == "bridge_position_sans_stop"


def test_il_ne_VOLE_PAS_l_etiquette_des_autres():
    from backend.services.mt5_bridge import _categoriser_refus

    cas = {
        "Marge libre apres ordre -42.02 < 130.04": "bridge_marge_insuffisante",
        "Max open positions reached": "bridge_max_positions",
        "Daily drawdown reached: loss=181": "bridge_perte_journaliere",
        "Risque engage trop eleve": "bridge_plafond_risque",
    }
    for corps, attendu in cas.items():
        assert _categoriser_refus(429, corps) == attendu, corps
