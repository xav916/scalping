"""Registre des destinations — garde-fou anti-dérive (2026-08-04).

Brancher une plateforme exigeait de modifier au moins cinq endroits
indépendants. À l'ajout de Kraken, quatre ont été oubliés :

- `VALID_DESTINATIONS` : une admission scopée sur Kraken devenait GLOBALE
- `DESTINATION_LABELS` : un trade Kraken s'affichait « Démo » sur du réel
- sondes de santé : les deux bridges Kraken n'étaient surveillés par rien
- sizing : `TRADING_CAPITAL` global sur un compte de 103 USD → ordres 20×
  trop gros, rejetés en `invalidSize`

Aucun n'a produit d'erreur : ils ont produit du silence, ou une
affirmation fausse. Ces tests rendent la dérive impossible sans qu'un test
l'annonce — c'est le point du registre, pas un détail de style.
"""
from __future__ import annotations

import pytest

from backend.services import destinations_registry as reg


# --- LE test : rien ne doit exister hors du registre -----------------------

def test_toute_destination_construite_est_declaree():
    """Un constructeur dans `bridge_destinations` sans entrée ici = dérive.

    C'est ce test qui aurait sonné le 2026-08-02 à l'ajout de Kraken.
    """
    import inspect
    from backend.services import bridge_destinations as bd

    src = inspect.getsource(bd)
    construites = set()
    for ligne in src.split("\n"):
        if "destination_id=" in ligne and '"' in ligne:
            valeur = ligne.split('destination_id=')[1].strip().strip(",")
            if valeur.startswith('"') and valeur.endswith('"'):
                construites.add(valeur.strip('"'))
    construites = {d for d in construites if not d.startswith("user")}

    manquantes = sorted(construites - reg.ids())
    assert manquantes == [], (
        f"destinations construites mais non declarees : {manquantes}. "
        "Ajouter une entree dans destinations_registry."
    )


def test_les_consommateurs_derivent_bien_du_registre():
    """Les trois listes historiques ne doivent plus vivre leur vie."""
    from backend.services import pair_admission_controller as pac
    from backend.services import sizing, telegram_service as ts

    assert pac.VALID_DESTINATIONS == reg.ids()
    assert set(ts.DESTINATION_LABELS) == reg.ids()
    assert sizing.LIVE_BALANCE_BRIDGE_TYPES == reg.bridge_types_with_live_balance()


# --- cohérence interne de chaque déclaration ------------------------------

@pytest.mark.parametrize("dest_id", sorted(reg.ids()))
def test_chaque_destination_est_complete(dest_id):
    d = reg.DESTINATIONS[dest_id]
    assert d.badge.strip() and d.mode.strip()
    assert d.bridge_type
    assert d.sizing in ("global", "live_balance")
    assert d.asset_classes, "au moins une classe d'actif"


@pytest.mark.parametrize("dest_id", sorted(reg.ids()))
def test_le_libelle_dit_la_verite_sur_l_argent(dest_id):
    """Un message ne doit jamais laisser croire à du démo sur du réel."""
    d = reg.DESTINATIONS[dest_id]
    assert ("réel" in d.mode.lower()) is d.reel, dest_id


@pytest.mark.parametrize("dest_id", sorted(reg.ids()))
def test_une_destination_sondable_declare_ses_variables(dest_id):
    """Sans url_env/key_env, la sonde de santé ne peut pas l'atteindre."""
    d = reg.DESTINATIONS[dest_id]
    assert d.url_env and d.key_env, f"{dest_id} n'est pas sondable"
    assert d.key_header in ("X-API-Key", "X-Bridge-Key")


def test_les_bridges_qui_envoient_la_quantite_lisent_leur_solde():
    """Kraken et Binance envoient la qty telle quelle : sizing sur le solde.

    C'est l'incident `invalidSize` : `TRADING_CAPITAL` global (3 000 €)
    appliqué à un compte de 103 USD produisait ~10 175 USD de notionnel.
    """
    for dest_id in ("admin_kraken", "admin_kraken_spot", "admin_kraken_stocks"):
        assert reg.DESTINATIONS[dest_id].sizing == "live_balance", dest_id


def test_les_bridges_mt5_gardent_le_sizing_global():
    """Ils reclampent au minimum du broker : ne pas y toucher."""
    for dest_id in ("admin_live", "admin_legacy"):
        assert reg.DESTINATIONS[dest_id].sizing == "global", dest_id


# --- la résolution ---------------------------------------------------------

def test_resolution_par_identifiant():
    assert reg.get("admin_kraken").bridge_type == "kraken"
    assert reg.get("user:42") is reg.USER_DESTINATION
    assert reg.get("user:7").reel is False


def test_destination_inconnue_renvoie_none():
    """Pas d'objet par défaut : l'appelant doit décider, et le défaut sûr
    est de se taire."""
    assert reg.get("admin_truc") is None
    assert reg.get("") is None
    assert reg.get(None) is None
    assert reg.is_real_money("admin_truc") is False


@pytest.mark.parametrize("brut", ["user:", "user:abc", "userX:2", "USER:2"])
def test_les_faux_user_ne_passent_pas(brut):
    assert reg.get(brut) is None or brut == "USER:2"


# --- le dump pour les scripts shell ---------------------------------------

def test_le_dump_json_est_exploitable():
    """Les scripts shell doivent lire le registre, pas recopier ses tables.

    C'est ainsi que `notify-new-*-pushes.sh` s'était dupliqué en quatre
    fichiers, chacun avec sa propre copie des libellés.
    """
    import json
    d = json.loads(reg.as_json())
    assert set(d) == reg.ids()
    for dest_id, meta in d.items():
        assert {"badge", "mode", "reel", "bridge_type", "plateforme"} <= set(meta)
