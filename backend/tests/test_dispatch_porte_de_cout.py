"""La porte de cout au dispatch (2026-08-04).

Verifie par `resolve_destinations`, jamais par les attributs de settings :
`MT5_BRIDGE_LEGACY_MIN_CONFIDENCE` passe par `os.getenv` sans `config.settings`,
et le seuil per-user vit en base. Lire les settings donnerait une reponse
fausse.
"""
from __future__ import annotations


def test_les_destinations_portent_un_modele_de_cout():
    from backend.services.bridge_destinations import BridgeConfig

    champs = BridgeConfig.__dataclass_fields__
    assert "cost_model" in champs
    assert "expected_edge_r" in champs


def test_le_defaut_est_inconnu_pas_gratuit():
    """Une destination qui ne declare rien ne doit pas passer pour gratuite."""
    from backend.services.bridge_destinations import BridgeConfig

    dest = BridgeConfig(
        destination_id="test",
        user_id=None,
        bridge_url="http://x",
        bridge_api_key="k",
        min_confidence=50.0,
        allowed_asset_classes=frozenset({"forex"}),
        auto_exec_enabled=True,
    )
    assert dest.cost_model is None
    assert dest.expected_edge_r is None


def test_kraken_est_refuse_par_ses_propres_chiffres():
    """Le refus doit tomber des valeurs declarees, sans cas particulier."""
    from backend.services.cost_model import CostModel, cost_in_r, exceeds_edge

    modele = CostModel(proportional_rate_per_leg=0.0005)
    entry = 1000.0
    cout = cost_in_r(entry=entry, stop_loss=entry * (1 - 0.00347), model=modele)

    assert exceeds_edge(cout, 0.110, auto_exec=True) is True


def test_mt5_reste_non_declare_donc_inchange():
    """La route qui trade aujourd'hui ne doit pas changer de comportement.

    Aucun taux unique ne decrit `admin_live`, qui melange forex, metaux et
    actions CFD : la distance de stop y varie d'un facteur 27 (EUR/USD
    0,073 %, DOT/USD 1,99 %, mesure le 2026-08-04 sur 1 352 trades auto).
    Declarer un taux reviendrait a inventer un chiffre.
    """
    from backend.services.bridge_destinations import _admin_live_destination

    dest = _admin_live_destination()
    if dest is None:  # destination non configuree dans cet environnement
        import pytest

        pytest.skip("admin_live non configuree ici")
    assert dest.cost_model is None
    assert dest.expected_edge_r is None
