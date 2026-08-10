"""Dispatch IBKR actions US — ouvert le 2026-08-10 à la demande de Xavier.

Le bridge (`ibkr-bridge/bridge.py`, port 8792) existait depuis le 2026-08-04
en lecture seule, bracket validé en réel sur AAPL, permission Actions US
approuvée. Ce module ouvre le chemin de dispatch.

⚠️ **Ce que la mesure dit, et que l'ouverture ne change pas** : sur les actions
US individuelles les patterns font **−0,182 R contre une entrée au hasard**
(p < 0,001). C'est une décision produit ; ces tests verrouillent les garde-fous
qui la bornent.

Trois différences structurelles avec les routes crypto :

1. **quantité entière** — une fraction d'action n'existe pas sur un compte
   cash. Zéro action est un **refus**, pas un ordre nul ;
2. **le marché ferme** — 13:30-20:30 UTC, contrairement au crypto ;
3. **le Gateway a son propre interrupteur** — `IBKR_ALLOW_ORDERS` côté bridge.
   Un `403` est le garde-fou qui fonctionne, pas une panne.
"""
from types import SimpleNamespace

import pytest

from backend.services import destinations_registry as registry
from backend.services.ibkr_bridge_client import actions_pour


# ─── La quantité entière ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "risque,entree,stop,attendu",
    [
        # AAPL a 306 USD, stop 0,563 % => 1,72 USD de risque par action.
        (1.15, 306.32, 304.60, 0),     # compte a 115 USD, risque 1 % : PAS une action
        (1.72, 306.32, 304.60, 1),     # tout juste une
        (5.20, 306.32, 304.60, 3),     # 3,02 -> planche a 3
        (0.0, 306.32, 304.60, 0),      # sizing refuse en amont
        (10.0, 306.32, 306.32, 0),     # stop colle a l'entree
    ],
)
def test_la_quantite_est_un_entier_planche_vers_le_bas(risque, entree, stop, attendu):
    """Arrondir au supérieur dépasserait le risque voulu — c'est exactement ce
    que le lot minimum impose déjà côté MT5, et qu'on ne reproduit pas ici."""
    assert actions_pour(risque, entree, stop) == attendu


def test_zero_action_est_le_cas_NOMINAL_a_ce_capital():
    """115 USD de compte, 1 % de risque, une action à 306 USD : rien ne passe.

    Ce n'est pas une anomalie à corriger, c'est la réponse juste — et le motif
    de rejet doit le dire (`ibkr_capital_insuffisant`), pas laisser croire à un
    stop collé à l'entrée.
    """
    assert actions_pour(1.15, 306.32, 304.60) == 0


# ─── La déclaration au registre ────────────────────────────────────────


def test_la_destination_est_declaree():
    d = registry.get("admin_ibkr_us")
    assert d is not None
    assert d.reel is True
    assert d.bridge_type == "ibkr"
    assert d.asset_classes == frozenset({"equity"})


def test_le_compte_cash_interdit_le_levier():
    """Achat d'action sur compte cash : le notionnel ne peut pas dépasser le
    capital. La vente à découvert exigerait un compte Margin qu'on n'a pas."""
    assert registry.get("admin_ibkr_us").max_notional_leverage == 1.0


def test_le_solde_est_lu_en_direct_pas_le_capital_global():
    """Le compte vaut ~115 USD ; le global vaut 3 000. Dimensionner sur le
    second reproduirait l'incident `invalidSize` de Kraken."""
    assert registry.get("admin_ibkr_us").sizing == "live_balance"
    assert "ibkr" in registry.bridge_types_with_live_balance()


def test_les_actions_ne_cotent_PAS_en_continu():
    """Marché 13:30-20:30 UTC : la grille de séance doit s'appliquer, contrairement
    au crypto. Une neutralisation ici ferait sizer un ordre marché fermé."""
    assert registry.cote_en_continu("admin_ibkr_us") is False


def test_le_risque_par_trade_reste_le_global():
    """Aucune surcharge : seule Kraken en déclare une."""
    assert registry.get("admin_ibkr_us").risk_per_trade_pct is None


# ─── Coût et edge ──────────────────────────────────────────────────────


def test_le_cout_est_declare_FIXE_et_non_proportionnel(monkeypatch):
    """0,35 USD par ordre au palier Tiered. Sans `min_per_order`, `cost_in_r`
    verrait une route gratuite — le pire des défauts pour une porte de coût."""
    from config import settings as st
    monkeypatch.setattr(st, "IBKR_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(st, "IBKR_BRIDGE_URL", "http://x:8792", raising=False)
    from backend.services.bridge_destinations import _admin_ibkr_destination

    d = _admin_ibkr_destination()
    assert d.cost_model.min_per_order == 0.35
    assert d.cost_model.proportional_rate_per_leg == 0.0
    # Compte cash : aucun portage, contrairement aux perpetuels Kraken.
    assert d.cost_model.funding_interval_hours == 0.0


def test_sans_edge_declare_la_route_reste_fermee(monkeypatch):
    """⚠️ LE garde-fou. `expected_edge_r = None` ⇒ la porte de coût refuse,
    quel que soit le capital. Ouvrir le flux demande un acte NOMMÉ."""
    from config import settings as st
    monkeypatch.setattr(st, "IBKR_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(st, "IBKR_BRIDGE_URL", "http://x:8792", raising=False)
    monkeypatch.setattr(st, "IBKR_BRIDGE_EXPECTED_EDGE_R", None, raising=False)
    from backend.services.bridge_destinations import _admin_ibkr_destination

    assert _admin_ibkr_destination().expected_edge_r is None


def test_l_edge_se_declare_par_variable_nommee(monkeypatch):
    from config import settings as st
    monkeypatch.setattr(st, "IBKR_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(st, "IBKR_BRIDGE_URL", "http://x:8792", raising=False)
    monkeypatch.setattr(st, "IBKR_BRIDGE_EXPECTED_EDGE_R", 0.05, raising=False)
    from backend.services.bridge_destinations import _admin_ibkr_destination

    assert _admin_ibkr_destination().expected_edge_r == 0.05


def test_seul_le_journalier_est_servi(monkeypatch):
    """Une action US ne donne qu'UNE bougie H4 exploitable par jour de
    cotation — le pire rapport observation/temps du système."""
    from config import settings as st
    monkeypatch.setattr(st, "IBKR_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(st, "IBKR_BRIDGE_URL", "http://x:8792", raising=False)
    from backend.services.bridge_destinations import _admin_ibkr_destination

    assert _admin_ibkr_destination().allowed_horizons == frozenset({"1d"})


# ─── Le routage ────────────────────────────────────────────────────────


def test_desactivee_par_defaut(monkeypatch):
    """Fail-closed : sans `IBKR_BRIDGE_ENABLED` ni URL, aucune destination."""
    from config import settings as st
    monkeypatch.setattr(st, "IBKR_BRIDGE_ENABLED", False, raising=False)
    from backend.services.bridge_destinations import _admin_ibkr_destination

    assert _admin_ibkr_destination() is None


@pytest.mark.parametrize("sens,attendu", [("buy", True), ("sell", False)])
def test_seuls_les_ACHATS_sont_routes(monkeypatch, sens, attendu):
    """Compte cash : la vente à découvert exige un compte Margin. Filtrer ici
    évite de router pour rien — même raisonnement que Kraken Spot."""
    from config import settings as st
    monkeypatch.setattr(st, "IBKR_BRIDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(st, "IBKR_BRIDGE_URL", "http://x:8792", raising=False)
    from backend.services import bridge_destinations as bd

    setup = SimpleNamespace(
        pair="XLK", asset_class="equity",
        direction=SimpleNamespace(value=sens),
        confidence_score=70.0, verdict_action="TAKE",
    )
    ids = [d.destination_id for d in bd.resolve_destinations(setup)]
    assert ("admin_ibkr_us" in ids) is attendu
