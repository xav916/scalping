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


def test_les_fabriques_kraken_declarent_reellement_leurs_valeurs():
    """Verifie le cablage, pas seulement le modele.

    Les autres tests instancient leur propre `CostModel` et ne liraient
    pas un oubli de branchement sur les fabriques. On inspecte donc la
    source : les fabriques renvoient `None` quand la destination n'est
    pas configuree dans l'environnement, ce qui rendrait un test par
    appel muet en local — or c'est precisement le cablage qu'on veut
    verrouiller, independamment de la configuration.

    Seul `_admin_kraken_destination` (les perpétuels) a un `expected_edge_r`
    mesuré : 876 trades réels. Les deux autres fabriques empruntaient un
    edge mesuré sur une autre route (perpétuels pour le spot, MT5 range_bounce
    pour xStocks) — corrigé le 2026-08-05 : elles déclarent `None`, ce qui
    fait bloquer la porte inconditionnellement en exécution réelle plutôt
    que d'ouvrir une fenêtre sur un chiffre emprunté.
    """
    import inspect

    from backend.services import bridge_destinations as bd

    for nom, edge in (
        ("_admin_kraken_destination", "0.110"),
        ("_admin_kraken_spot_destination", "None"),
        ("_admin_kraken_stocks_destination", "None"),
    ):
        src = inspect.getsource(getattr(bd, nom))
        assert "cost_model=CostModel(proportional_rate_per_leg=0.0005)" in src, nom
        assert f"expected_edge_r={edge}" in src, nom


def test_mt5_et_binance_ne_declarent_rien():
    """Le pendant du test precedent : l'absence doit etre verrouillee aussi.

    Sans ca, un ajout ulterieur de `cost_model` sur `admin_live` passerait
    inapercu et changerait le comportement de la seule route qui trade.
    """
    import inspect

    from backend.services import bridge_destinations as bd

    for nom in (
        "_admin_live_destination",
        "_admin_legacy_destination",
        "_admin_binance_destination",
    ):
        src = inspect.getsource(getattr(bd, nom))
        assert "cost_model=" not in src, nom
        assert "expected_edge_r=" not in src, nom


# ─── Task 5 : la porte au dispatch ──────────────────────────────────────
import inspect
from types import SimpleNamespace


def _setup_factice(entry: float = 1000.0, ecart_pct: float = 0.00347):
    return SimpleNamespace(
        pair="ETH/USD",
        direction=SimpleNamespace(value="sell"),
        entry_price=entry,
        stop_loss=entry * (1 - ecart_pct),
        take_profit_1=entry * (1 + ecart_pct),
        confidence_score=90.0,
        signal_pattern="range_bounce_down",
    )


def _dest_factice(dest_id, cost_model=None, edge=None, auto_exec=True):
    from backend.services.bridge_destinations import BridgeConfig

    return BridgeConfig(
        destination_id=dest_id,
        user_id=None,
        # bridge_url vide : evite que la validation de tick pre-push tente
        # un appel HTTP pendant les tests.
        bridge_url="",
        bridge_api_key="k",
        min_confidence=50.0,
        allowed_asset_classes=frozenset({"crypto"}),
        auto_exec_enabled=auto_exec,
        allowed_patterns=frozenset(),
        cost_model=cost_model,
        expected_edge_r=edge,
    )


def test_la_porte_refuse_un_signal_trop_cher():
    from backend.services.cost_model import CostModel
    from backend.services.mt5_bridge import _cost_rejection

    dest = _dest_factice("admin_kraken",
                         CostModel(proportional_rate_per_leg=0.0005), 0.110)

    assert _cost_rejection(_setup_factice(), dest) == "fees_exceed_edge"


def test_le_code_de_refus_n_est_pas_prive():
    """Un code commencant par `_` serait supprime silencieusement."""
    from backend.services.cost_model import CostModel
    from backend.services.mt5_bridge import _cost_rejection

    dest = _dest_factice("admin_kraken",
                         CostModel(proportional_rate_per_leg=0.0005), 0.110)

    code = _cost_rejection(_setup_factice(), dest)
    assert code is not None and not code.startswith("_")


def test_une_route_bon_marche_passe_la_porte():
    """Ecart de stop elargi (1 %) : le brief reutilisait le defaut crypto
    (0,347 %) de `_setup_factice`, ce qui donne un cout de 6,34 % de l'entree
    — soit 49 % de l'edge, au-dessus du seuil de 30 %. Avec un ecart de stop
    plus large (realiste hors crypto), le cout tombe a 17 % de l'edge, ce qui
    correspond exactement au chiffre documente dans cost_model.py
    ("MT5 passe a 17 %"). C'est la seule valeur ajustee vs le brief verbatim ;
    consigne dans le rapport de tache.

    Le taux de 0,00011 utilisé ici est fictif : il ne correspond à aucune
    route réelle. `admin_live` a été délibérément laissée non déclarée
    (voir `test_mt5_reste_non_declare_donc_inchange`), donc la destination
    est renommée pour ne pas laisser croire que MT5 déclare ce chiffre.
    """
    from backend.services.cost_model import CostModel
    from backend.services.mt5_bridge import _cost_rejection

    dest = _dest_factice("route_bon_marche_fictive",
                         CostModel(proportional_rate_per_leg=0.00011), 0.129)

    assert _cost_rejection(_setup_factice(ecart_pct=0.01), dest) is None


def test_une_destination_sans_modele_declare_ne_change_pas_de_comportement():
    """Retro-compatibilite : les destinations non renseignees passent comme avant."""
    from backend.services.mt5_bridge import _cost_rejection

    assert _cost_rejection(_setup_factice(), _dest_factice("user:2")) is None


def test_edge_zero_bloque_meme_sans_cost_model():
    """`exceeds_edge` garantit qu'un edge mesuré à zéro ou négatif bloque
    TOUJOURS, cost_model ou pas. Une destination qui déclare
    `expected_edge_r=0.0` sans `cost_model` ne doit donc pas s'échapper de
    la porte via le premier `return None` de `_cost_rejection` — c'est
    exactement le cas que cette route existe pour attraper.
    """
    from backend.services.mt5_bridge import _cost_rejection

    dest = _dest_factice("admin_kraken", cost_model=None, edge=0.0, auto_exec=True)

    assert _cost_rejection(_setup_factice(), dest) == "fees_exceed_edge"


def test_l_observation_n_est_pas_bloquee_faute_d_edge_connu():
    from backend.services.cost_model import CostModel
    from backend.services.mt5_bridge import _cost_rejection

    dest = _dest_factice("admin_kraken_stocks",
                         CostModel(proportional_rate_per_leg=0.0005),
                         edge=None, auto_exec=False)

    assert _cost_rejection(_setup_factice(), dest) is None


def test_la_porte_est_reellement_appelee_par_le_dispatch():
    """Une fonction qui existe sans etre appelee ne protege de rien.

    C'est la lecon des douze patches poses sur un import mort le 2026-08-04 :
    onze tests passaient par hasard, et le garde n'etait plus teste du tout.
    """
    from backend.services import mt5_bridge

    src = inspect.getsource(mt5_bridge._check_rejection)
    assert "_cost_rejection(" in src


def test_la_porte_n_est_pas_rendue_inatteignable():
    """La porte est en dernier : aucun `return None` ne doit la preceder.

    Mode de defaillance vise : on ajoute le bloc a la fin sans supprimer le
    `return None` qui s'y trouvait deja. Le code compile, les tests unitaires
    de `_cost_rejection` passent, et la porte ne s'execute jamais.
    """
    from backend.services import mt5_bridge

    src = inspect.getsource(mt5_bridge._check_rejection)
    avant_porte = src.split("_cost_rejection(")[0]
    assert "return None" not in avant_porte


# ─── Task 6 : Telegram n'annonce pas ce que la porte refuse ────────────


def test_destination_refusee_par_la_porte_absente_de_executing_destinations(
    monkeypatch,
):
    """`_executing_destinations` réimplémentait les filtres du dispatch sans
    la porte de coût : un signal crypto trop cher aurait donc été annoncé
    « Auto-exécuté → Kraken » alors que `_check_rejection` le refuse.
    """
    from backend.services import bridge_destinations, telegram_service
    from backend.services.cost_model import CostModel

    dest = _dest_factice(
        "admin_kraken", CostModel(proportional_rate_per_leg=0.0005), 0.110
    )
    setup = _setup_factice()

    monkeypatch.setattr(
        bridge_destinations, "resolve_destinations", lambda s: [dest]
    )

    assert telegram_service._executing_destinations(setup) == []
