"""Le contexte de marche ne doit jamais pouvoir suggerer une position (2026-09-04).

La consigne envoyee au modele lui interdit direction, score et niveau d'entree.
Une consigne n'est pas une garantie : un modele qui deraille, une version qui
change, et la sortie se met a porter un sens. Elle redeviendrait alors un
facteur de decision — donc une chose a valider sur ~700 clotures.

`_valider()` est le point ou cela se joue, et ces tests le verrouillent.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from backend.services import contexte_marche as cm


ATTENDUS = ["EUR/USD", "XAU/USD", "BTC/USD"]


# ─── Le filet anti-decision ──────────────────────────────────────────────

def test_les_clefs_de_decision_sont_retirees():
    """Le modele renvoie une direction et un score : ils ne doivent pas passer."""
    charge = {"instruments": [{
        "pair": "EUR/USD",
        "resume": "Emploi US a 162k contre 56k attendus.",
        "echeances": ["2026-09-10 — BCE"],
        "direction": "buy",
        "score": 87,
        "stop_loss": 1.1550,
    }]}

    v = cm._valider(charge, ATTENDUS)
    instrument = v["instruments"][0]
    assert set(instrument) == {"pair", "resume", "echeances"}
    assert "direction" not in instrument and "score" not in instrument


def test_toutes_les_clefs_interdites_sont_couvertes():
    """Chaque clef de la liste doit effectivement etre filtree — sinon la liste
    donne une fausse assurance."""
    for clef in cm.CLEFS_INTERDITES:
        charge = {"instruments": [
            {"pair": "EUR/USD", "resume": "x", "echeances": [], clef: "peu importe"}
        ]}
        assert clef not in cm._valider(charge, ATTENDUS)["instruments"][0]


# ─── Lacunes ─────────────────────────────────────────────────────────────

def test_instrument_absent_devient_une_lacune_pas_une_invention():
    charge = {"instruments": [{"pair": "EUR/USD", "resume": "x", "echeances": []}]}

    v = cm._valider(charge, ATTENDUS)
    assert [i["pair"] for i in v["instruments"]] == ["EUR/USD"]
    assert v["donnees_manquantes"] == ["XAU/USD", "BTC/USD"]


def test_resume_vide_compte_comme_lacune():
    """Une ligne sans contenu est pire qu'une ligne absente : elle a l'air d'une
    reponse."""
    charge = {"instruments": [{"pair": "XAU/USD", "resume": "   ", "echeances": []}]}

    v = cm._valider(charge, ATTENDUS)
    assert v["instruments"] == []
    assert "XAU/USD" in v["donnees_manquantes"]


def test_instrument_hors_perimetre_est_ignore():
    """Le modele invente une paire non suivie : elle ne rentre pas."""
    charge = {"instruments": [
        {"pair": "USD/TRY", "resume": "hors univers", "echeances": []},
        {"pair": "EUR/USD", "resume": "ok", "echeances": []},
    ]}

    assert [i["pair"] for i in cm._valider(charge, ATTENDUS)["instruments"]] == ["EUR/USD"]


def test_reponse_illisible_rend_tout_en_lacune():
    for charge in (None, [], "texte", {"instruments": "pas une liste"}):
        v = cm._valider(charge, ATTENDUS)
        assert v["instruments"] == []
        assert v["donnees_manquantes"] == ATTENDUS


# ─── Extraction JSON ─────────────────────────────────────────────────────

def test_json_extrait_meme_entoure_de_prose_et_de_balises():
    attendu = {"instruments": [{"pair": "EUR/USD", "resume": "x", "echeances": []}]}
    for texte in (
        json.dumps(attendu),
        f"Voici le resultat :\n```json\n{json.dumps(attendu)}\n```\nVoila.",
        f"```\n{json.dumps(attendu)}\n```",
        f"Bla bla {json.dumps(attendu)} bla",
    ):
        assert cm._extraire_json(texte) == attendu


def test_json_absent_rend_none():
    assert cm._extraire_json("aucun objet ici") is None
    assert cm._extraire_json("") is None


# ─── Interrupteurs ───────────────────────────────────────────────────────

def test_desactive_ne_tente_aucun_appel(monkeypatch):
    monkeypatch.setattr(cm, "CONTEXTE_MARCHE_ENABLED", False, raising=False)
    assert asyncio.run(cm.contexte(ATTENDUS)) is None


def test_actif_sans_cle_ne_tente_aucun_appel(monkeypatch):
    monkeypatch.setattr(cm, "CONTEXTE_MARCHE_ENABLED", True, raising=False)
    monkeypatch.setattr(cm, "CONTEXTE_MARCHE_API_KEY", "", raising=False)
    assert asyncio.run(cm.contexte(ATTENDUS)) is None


def test_sans_instrument_aucun_appel(monkeypatch):
    monkeypatch.setattr(cm, "CONTEXTE_MARCHE_ENABLED", True, raising=False)
    monkeypatch.setattr(cm, "CONTEXTE_MARCHE_API_KEY", "cle-factice", raising=False)
    assert asyncio.run(cm.contexte([])) is None
