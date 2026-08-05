"""Porte d'horizon au dispatch (2026-08-05).

Une destination déclare les horizons qu'elle accepte. MT5 est dimensionné
pour le scalping, Kraken pour la détention. Router un setup 4h vers une
route scalping enverrait un ordre dont le sizing, les stops et les frais
ont été pensés pour une autre échelle de temps.
"""
from types import SimpleNamespace

import pytest

from backend.services.mt5_bridge import _horizon_rejection


def _setup(horizon):
    return SimpleNamespace(pair="XAU/USD", horizon=horizon, entry_price=2000.0,
                           stop_loss=1990.0, confidence_score=80.0)


def _dest(allowed):
    return SimpleNamespace(destination_id="test", allowed_horizons=allowed,
                           auto_exec_enabled=True)


def test_horizon_admis_passe():
    assert _horizon_rejection(_setup("5min"), _dest(frozenset({"5min"}))) is None


def test_horizon_non_admis_refuse():
    assert _horizon_rejection(_setup("4h"), _dest(frozenset({"5min"}))) == "horizon_not_allowed"


def test_ecriture_non_normalisee_admise_quand_meme():
    # Le setup porte "4H", la destination declare "4h" : c'est le meme
    # horizon. La normalisation evite un refus sur une difference de casse.
    assert _horizon_rejection(_setup("4H"), _dest(frozenset({"4h"}))) is None


def test_destination_sans_declaration_ne_filtre_rien():
    # allowed_horizons=None => comportement d'avant le 2026-08-05. C'est ce
    # qui garantit que les destinations user:N (Cedric) ne changent pas.
    assert _horizon_rejection(_setup("4h"), _dest(None)) is None
    assert _horizon_rejection(_setup(None), _dest(None)) is None


def test_horizon_inconnu_bloque_quand_la_porte_est_active():
    # Fail-closed, comme la whitelist de patterns : declarer allowed_horizons
    # est un opt-in explicite. Un setup sans horizon face a une porte active
    # est un setup qu'on ne sait pas router — on ne devine pas.
    assert _horizon_rejection(_setup(None), _dest(frozenset({"5min"}))) == "horizon_not_allowed"
    assert _horizon_rejection(_setup("2h"), _dest(frozenset({"5min"}))) == "horizon_not_allowed"


def test_destination_absente_ne_filtre_rien():
    assert _horizon_rejection(_setup("4h"), None) is None


def test_la_porte_est_reellement_appelee_par_check_rejection():
    # Une fonction qui existe sans etre appelee ne protege de rien. Meme
    # verification par inspection que pour la porte de cout du plan 1, mais
    # via l'AST plutot qu'une recherche de sous-chaine : un simple
    # commentaire ("# horizon_reason = _horizon_rejection(...)") laisse la
    # sous-chaine intacte dans le texte source et ne ferait donc pas
    # echouer un `in src` naif — verifie le 2026-08-05 par mutation (Step 9).
    import ast
    import inspect

    from backend.services import mt5_bridge

    src = inspect.getsource(mt5_bridge._check_rejection)
    arbre = ast.parse(src)
    appels = {
        node.func.id
        for node in ast.walk(arbre)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_horizon_rejection" in appels


def test_le_code_de_refus_est_public_et_libelle():
    # Un code prefixe `_` serait supprime silencieusement — c'est ce qui a
    # rendu AAPL invisible deux jours durant.
    from backend.services.rejection_service import REASON_LABELS_FR

    assert not "horizon_not_allowed".startswith("_")
    assert "horizon_not_allowed" in REASON_LABELS_FR


def test_les_destinations_reelles_declarent_les_horizons_de_la_spec(monkeypatch):
    # Les valeurs de la spec section 3.3 : MT5 scalping, Kraken detention.
    from backend.services import bridge_destinations as bd

    monkeypatch.setenv("MT5_BRIDGE_URL", "http://x")
    monkeypatch.setenv("MT5_BRIDGE_API_KEY", "k")
    live = bd._admin_live_destination()
    if live is not None:
        assert live.allowed_horizons == frozenset({"5min"})


def test_kraken_declare_les_horizons_longs():
    from backend.services import bridge_destinations as bd

    kraken = bd._admin_kraken_destination()
    if kraken is not None:
        assert kraken.allowed_horizons == frozenset({"4h", "1d"})


def test_les_destinations_user_ne_filtrent_pas_l_horizon():
    # Cedric doit continuer a recevoir exactement ce qu'il recoit.
    import inspect

    from backend.services import bridge_destinations as bd

    src = inspect.getsource(bd._user_destinations)
    assert "allowed_horizons" not in src, (
        "les destinations user ne doivent pas declarer d'horizon"
    )
