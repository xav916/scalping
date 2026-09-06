"""L'univers surveillé se scope PAR PLATEFORME (2026-09-06).

Jusqu'ici `WATCHED_PAIRS` était global : pour trader une paire sur Kraken, il
fallait l'ajouter à l'univers de TOUT LE MONDE, puis compter sur les filtres de
chaque destination pour l'en exclure. C'est un « refus par soustraction » à
maintenir N fois — et la destination qui n'a pas le bon filtre hérite de la
paire **en silence**.

Mesuré le 06/09 : le radar surveille 29 paires, Kraken en cote 276. Élargir
pour Kraken revenait à élargir pour MT5, donc pour l'argent réel.

🔑 **Deux portées, à ne jamais confondre** — c'est le piège du 04/09, « portée à
l'écriture ≠ portée à la lecture » :

  - l'**analyse** porte sur l'UNION de toutes les portées. Il faut bien
    analyser une paire pour produire son signal ;
  - le **routage** porte sur la portée de CHAQUE plateforme. Une paire déclarée
    pour Kraken n'atteint que Kraken.

⛔ Le filtre vit dans ``resolve_destinations``, **jamais chez l'appelant** :
c'est déjà là que vit le verrou « un signal externe n'atteint pas l'argent
réel ». Un appelant peut oublier, un résolveur non.

⚠️ **Une portée ABSENTE hérite du global.** C'est délibéré, et c'est ce qui rend
la migration strictement neutre : sans ce défaut, déployer ce changement
couperait toutes les destinations d'un coup. Une plateforme devient stricte le
jour où on lui déclare une portée, jamais avant.
"""
from __future__ import annotations

import pytest

from backend.services import bridge_destinations as bd


class _Setup:
    def __init__(self, pair, direction="buy"):
        self.pair = pair
        self.direction = type("D", (), {"value": direction})()
        self.asset_class = "crypto"


def _dest(destination_id, portee=frozenset()):
    return bd.BridgeConfig(
        destination_id=destination_id,
        bridge_url="http://x",
        bridge_api_key="k",
        min_confidence=0.0,
        allowed_asset_classes=frozenset({"crypto", "forex", "metal"}),
        auto_exec_enabled=True,
        user_id=None,
        watched_pairs=portee,
    )


# ── La portée elle-même ──────────────────────────────────────────────

def test_une_portee_ABSENTE_laisse_passer_LE_GLOBAL(monkeypatch):
    """⚠️ Le défaut qui rend la migration neutre : sans portée déclarée, la
    plateforme reçoit exactement l'univers commun — ni plus, ni moins.

    ⛔ « Ni plus » est le correctif du 06/09 : c'était « aucun filtre », donc
    une paire ouverte pour une seule plateforme atteignait toutes les autres."""
    from config import settings
    monkeypatch.setattr(settings, "WATCHED_PAIRS", ["EUR/USD", "BTC/USD"])
    monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION",
                        {"admin_kraken": frozenset({"SUI/USD"})})
    d = _dest("admin_live")
    assert bd.paire_dans_la_portee(d, "EUR/USD") is True
    assert bd.paire_dans_la_portee(d, "BTC/USD") is True
    assert bd.paire_dans_la_portee(d, "SUI/USD") is False


def test_une_portee_DECLAREE_est_stricte():
    d = _dest("admin_kraken", frozenset({"SUI/USD", "AVAX/USD"}))
    assert bd.paire_dans_la_portee(d, "SUI/USD") is True
    assert bd.paire_dans_la_portee(d, "EUR/USD") is False, (
        "une plateforme scopee ne recoit QUE sa portee")


def test_la_portee_ignore_la_casse_et_les_espaces():
    d = _dest("admin_kraken", frozenset({"SUI/USD"}))
    assert bd.paire_dans_la_portee(d, " sui/usd ") is True


def test_une_paire_vide_ne_passe_aucune_portee_declaree():
    d = _dest("admin_kraken", frozenset({"SUI/USD"}))
    assert bd.paire_dans_la_portee(d, "") is False
    assert bd.paire_dans_la_portee(d, None) is False


# ── ⛔ Le filtre vit dans le résolveur ────────────────────────────────

def test_une_paire_scopee_kraken_n_atteint_QUE_kraken(monkeypatch):
    """Le point du chantier : élargir pour Kraken ne doit pas élargir pour
    l'argent réel MT5."""
    kraken = _dest("admin_kraken", frozenset({"SUI/USD"}))
    live = _dest("admin_live", frozenset({"EUR/USD"}))
    legacy = _dest("admin_legacy")          # pas de portée : hérite du global

    monkeypatch.setattr(bd, "_admin_kraken_destination", lambda: kraken)
    monkeypatch.setattr(bd, "_admin_live_destination", lambda: live)
    monkeypatch.setattr(bd, "_admin_legacy_destination", lambda: legacy)
    for nom in ("_admin_binance_destination", "_admin_kraken_spot_destination",
                "_admin_kraken_stocks_destination", "_admin_ibkr_destination"):
        monkeypatch.setattr(bd, nom, lambda: None)
    monkeypatch.setattr(bd, "_user_destinations", lambda s: [])

    from config import settings
    monkeypatch.setattr(settings, "WATCHED_PAIRS", ["EUR/USD"])
    monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION",
                        {"admin_kraken": frozenset({"SUI/USD"})})

    ids = [d.destination_id for d in bd.resolve_destinations(_Setup("SUI/USD"))]
    assert ids == ["admin_kraken"], (
        "⛔ SUI n'existe que par la portee Kraken : ni le reel ni la demo "
        f"ne doivent l'attraper — vu {ids}")

    ids = [d.destination_id for d in bd.resolve_destinations(_Setup("EUR/USD"))]
    assert "admin_legacy" in ids, "le global va toujours aux destinations libres"
    assert "admin_kraken" not in ids, "Kraken est scope : il ne recoit que sa portee"


def test_une_paire_du_global_atteint_toujours_les_destinations_NON_scopees(monkeypatch):
    kraken = _dest("admin_kraken", frozenset({"SUI/USD"}))
    legacy = _dest("admin_legacy")

    monkeypatch.setattr(bd, "_admin_kraken_destination", lambda: kraken)
    monkeypatch.setattr(bd, "_admin_legacy_destination", lambda: legacy)
    monkeypatch.setattr(bd, "_admin_live_destination", lambda: None)
    for nom in ("_admin_binance_destination", "_admin_kraken_spot_destination",
                "_admin_kraken_stocks_destination", "_admin_ibkr_destination"):
        monkeypatch.setattr(bd, nom, lambda: None)
    monkeypatch.setattr(bd, "_user_destinations", lambda s: [])

    ids = [d.destination_id for d in bd.resolve_destinations(_Setup("EUR/USD"))]
    assert ids == ["admin_legacy"], (
        "EUR/USD hors portee Kraken, mais toujours servi a la destination libre")


def test_le_filtre_s_applique_AUSSI_aux_destinations_utilisateurs(monkeypatch):
    """⛔ Une porte posée d'un seul côté n'est pas une porte."""
    user = _dest("user_42", frozenset({"BTC/USD"}))
    monkeypatch.setattr(bd, "_admin_legacy_destination", lambda: None)
    monkeypatch.setattr(bd, "_admin_live_destination", lambda: None)
    for nom in ("_admin_binance_destination", "_admin_kraken_destination",
                "_admin_kraken_spot_destination", "_admin_kraken_stocks_destination",
                "_admin_ibkr_destination"):
        monkeypatch.setattr(bd, nom, lambda: None)
    monkeypatch.setattr(bd, "_user_destinations", lambda s: [user])

    assert bd.resolve_destinations(_Setup("SUI/USD")) == []
    assert [d.destination_id for d in bd.resolve_destinations(_Setup("BTC/USD"))] == ["user_42"]


# ── L'univers d'ANALYSE est l'union ──────────────────────────────────

def test_l_univers_d_analyse_est_l_UNION_des_portees(monkeypatch):
    """🔑 Il faut analyser une paire pour produire son signal. L'analyse porte
    donc sur l'union — c'est le ROUTAGE qui est scopé, pas la lecture."""
    from config import settings

    monkeypatch.setattr(settings, "WATCHED_PAIRS", ["EUR/USD", "BTC/USD"])
    monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION",
                        {"admin_kraken": frozenset({"SUI/USD", "BTC/USD"})})

    univers = settings.univers_a_analyser()
    assert set(univers) == {"EUR/USD", "BTC/USD", "SUI/USD"}
    assert len(univers) == len(set(univers)), "aucun doublon"


def test_sans_aucune_portee_l_univers_reste_le_global(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "WATCHED_PAIRS", ["EUR/USD", "BTC/USD"])
    monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION", {})
    assert settings.univers_a_analyser() == ["EUR/USD", "BTC/USD"]


def test_l_univers_est_ORDONNE_de_facon_stable(monkeypatch):
    """Un univers dont l'ordre bouge d'un cycle a l'autre rend les journaux
    incomparables, et le budget d'API impredictible."""
    from config import settings

    monkeypatch.setattr(settings, "WATCHED_PAIRS", ["EUR/USD", "BTC/USD"])
    monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION",
                        {"a": frozenset({"ZZZ/USD"}), "b": frozenset({"AAA/USD"})})
    assert settings.univers_a_analyser() == settings.univers_a_analyser()
    assert settings.univers_a_analyser()[:2] == ["EUR/USD", "BTC/USD"], (
        "le global garde sa place en tete, l'ajout vient apres")


# ── La lecture des réglages ──────────────────────────────────────────

def test_la_portee_se_lit_par_destination_dans_l_env(monkeypatch):
    from config import settings

    monkeypatch.setenv("WATCHED_PAIRS_ADMIN_KRAKEN", "SUI/USD, AVAX/USD")
    lu = settings.lire_portees_par_destination(["admin_kraken", "admin_live"])
    assert lu["admin_kraken"] == frozenset({"SUI/USD", "AVAX/USD"})
    assert "admin_live" not in lu, "une destination sans reglage n'est PAS scopee"


def test_les_guillemets_du_env_file_sont_retires(monkeypatch):
    """⚠️ `docker run --env-file` ne retire pas les guillemets : sans nettoyage,
    la premiere et la derniere paire de la liste sont abimees en silence."""
    from config import settings

    monkeypatch.setenv("WATCHED_PAIRS_ADMIN_KRAKEN", '"SUI/USD,AVAX/USD"')
    lu = settings.lire_portees_par_destination(["admin_kraken"])
    assert lu["admin_kraken"] == frozenset({"SUI/USD", "AVAX/USD"})


def test_un_reglage_VIDE_ne_scope_pas(monkeypatch):
    """⚠️ `WATCHED_PAIRS_X=` doit se lire « pas de portee », pas « portee vide » :
    une portee vide couperait la plateforme, un reglage vide est une absence."""
    from config import settings

    monkeypatch.setenv("WATCHED_PAIRS_ADMIN_KRAKEN", "  ")
    assert settings.lire_portees_par_destination(["admin_kraken"]) == {}


def test_la_portee_se_replie_sur_les_REGLAGES_par_identifiant(monkeypatch):
    """⛔ Une seule source de vérité : un constructeur de destination qui
    oublierait de porter sa portée ne doit pas créer une plateforme
    silencieusement non scopée."""
    from config import settings

    monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION",
                        {"admin_kraken": frozenset({"SUI/USD"})})
    d = _dest("admin_kraken")          # champ VIDE, portée déclarée en réglage
    assert bd.paire_dans_la_portee(d, "SUI/USD") is True
    assert bd.paire_dans_la_portee(d, "EUR/USD") is False


def test_un_reglage_de_PORTEE_illisible_retombe_sur_le_global(monkeypatch):
    """Un réglage de portée cassé ne coupe pas le routage : on retombe sur
    l'univers commun, c'est-à-dire exactement l'état d'avant ce mécanisme.

    ⚠️ Ce n'est pas un garde-fou — ici on aiguille, on ne protège pas. Le défaut
    sûr est donc « comme avant », pas « rien ne passe »."""
    import config.settings as reglages
    monkeypatch.setattr(reglages, "WATCHED_PAIRS", ["EUR/USD"])
    monkeypatch.delattr(reglages, "WATCHED_PAIRS_PAR_DESTINATION", raising=False)
    d = _dest("admin_kraken")
    assert bd.paire_dans_la_portee(d, "EUR/USD") is True
    assert bd.paire_dans_la_portee(d, "N_IMPORTE/QUOI") is True


# ── ⛔ La fuite trouvée le 06/09, avant d'ouvrir AVAX et SUI ──────────
#
# « Portée absente ⇒ hérite du global » était implémenté comme « aucun filtre ».
# Tant qu'aucune portée n'existait, les deux se confondaient. Dès qu'UNE portée
# fait entrer une paire dans l'univers, la différence devient le bug exact que
# ce chantier existe pour empêcher : la paire ouverte pour Kraken atteindrait
# l'argent réel MT5.
#
# 🔑 La règle juste : une paire du GLOBAL va aux destinations non scopées ; une
# paire qui n'existe QUE par une portée ne va qu'aux destinations qui la
# déclarent.

def test_une_paire_hors_global_n_atteint_PAS_une_destination_non_scopee(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "WATCHED_PAIRS", ["EUR/USD", "BTC/USD"])
    monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION",
                        {"admin_kraken": frozenset({"AVAX/USD"})})
    libre = _dest("admin_live")          # aucune portée déclarée

    assert bd.paire_dans_la_portee(libre, "EUR/USD") is True, "le global passe"
    assert bd.paire_dans_la_portee(libre, "AVAX/USD") is False, (
        "⛔ une paire ouverte pour Kraken ne doit PAS atteindre l'argent reel")


def test_la_paire_hors_global_atteint_bien_la_destination_qui_la_declare(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "WATCHED_PAIRS", ["EUR/USD"])
    monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION",
                        {"admin_kraken": frozenset({"AVAX/USD"})})
    kraken = _dest("admin_kraken", frozenset({"AVAX/USD"}))
    assert bd.paire_dans_la_portee(kraken, "AVAX/USD") is True


def test_sans_AUCUNE_portee_declaree_rien_ne_change(monkeypatch):
    """La migration reste neutre : sans portée déclarée, l'univers analysé EST
    le global, donc filtrer sur le global ne retire rien à personne.

    🔑 C'est ce qui rend le correctif du 06/09 sans effet de bord : il ne mord
    que sur les paires qui n'existent QUE par une portée."""
    from config import settings

    monkeypatch.setattr(settings, "WATCHED_PAIRS", ["EUR/USD", "BTC/USD"])
    monkeypatch.setattr(settings, "WATCHED_PAIRS_PAR_DESTINATION", {})
    libre = _dest("admin_live")
    for p in settings.univers_a_analyser():
        assert bd.paire_dans_la_portee(libre, p) is True, (
            f"{p} est analysee et doit atteindre une destination libre")
