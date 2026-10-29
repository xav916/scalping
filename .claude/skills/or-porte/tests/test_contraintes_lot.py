import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import porte as P  # noqa: E402

# Limites REELLES de admin_live, relevees dans son /health le 2026-10-29.
# ⛔ `max_correlated_positions` RETIRE le 2026-10-29 (R17) : la production
# n'a pas de plafond par classe d'actif, son garde-fou de correlation est
# par couple (destination, paire) et fonde sur des coefficients.
# ⚠️ Important 1 (2026-10-29) : `max_open_positions` est le plafond GLOBAL
# du pont (`bridge.py:1089`), jamais un cap par paire.
# ⚠️ Important 2 (2026-10-29) : DEUX poches de risque engage, comme
# `mt5_bridge.bridge` -- la commune et celle de l'or/argent, active
# seulement si > 0.
LIM_LIVE = {"order_cooldown_sec": 0,
            "max_risque_engage_pct": 5.0,
            "max_risque_engage_or_argent_pct": 15.0,
            "max_open_positions": 2}

S = {"pair": "XAU/USD", "direction": "buy", "entry_price": 2412.50,
     "stop_loss": 2404.10, "confidence_score": 71, "pattern": "range_bounce",
     "horizon": "30min", "chaine": None, "shadow_system_id": None,
     "is_simulated": False, "verdict_blockers": [], "risk_pct": 0.35}

FOREX = dict(S, pair="EUR/USD")


def _passer(setup, lim, cumul, classe="metal"):
    return P.contraintes_lot(setup, "admin_live", classe, lim, cumul)


def test_un_setup_seul_passe_les_trois_contraintes():
    code, _ = _passer(S, LIM_LIVE, P.cumul_vide())
    assert code is None


def test_places_destination_bloque_le_troisieme_MEME_sur_une_AUTRE_paire():
    """Important 1 : le plafond est GLOBAL par destination (`bridge.py:1089`
    `len(positions) >= MAX_OPEN_POSITIONS`), jamais un cap par paire -- le
    cap par paire reel (`mt5_bridge._max_positions_for_pair`) est deja
    applique DANS `_check_rejection`, en amont. Le troisieme setup doit
    heurter le plafond meme s'il vise une TROISIEME paire differente :
    un cap garde par paire laisserait passer a tort un lot que le pont
    refuserait en 429 `bridge_max_positions`."""
    cumul = P.cumul_vide()
    xag = dict(S, pair="XAG/USD")
    eur = dict(S, pair="EUR/USD")
    code, cumul = _passer(S, LIM_LIVE, cumul)
    assert code is None
    code, cumul = _passer(xag, LIM_LIVE, cumul)
    assert code is None
    code, _ = _passer(eur, LIM_LIVE, cumul)
    assert code == "lot_places_destination"


def test_risque_engage_bloque_quand_le_cumul_depasse():
    cumul = P.cumul_vide()
    lim = dict(LIM_LIVE, max_open_positions=99)
    gros = dict(FOREX, risk_pct=3.0)
    code, cumul = _passer(gros, lim, cumul, classe="forex")
    assert code is None
    code, _ = _passer(gros, lim, cumul, classe="forex")
    assert code == "lot_risque_engage"


def test_risque_engage_or_argent_est_une_poche_separee_de_la_commune():
    """Important 2 : l'or/argent et le reste ne se pretent RIEN
    (`bridge.py:1100-1102`). Un gros setup or ne doit pas consommer le
    budget forex, et reciproquement -- sinon une skill or jugerait l'or
    contre le plafond de l'autre poche (5 % au lieu de 15-20 %)."""
    cumul = P.cumul_vide()
    lim = dict(LIM_LIVE, max_open_positions=99)
    gros_or = dict(S, risk_pct=10.0)         # <= 15.0 (poche or/argent)
    gros_forex = dict(FOREX, risk_pct=4.0)   # <= 5.0 (poche commune)
    code, cumul = _passer(gros_or, lim, cumul, classe="metal")
    assert code is None
    code, cumul = _passer(gros_forex, lim, cumul, classe="forex")
    assert code is None, "le budget or ne doit pas avoir mange celui du forex"


def test_risque_engage_or_retombe_dans_la_poche_commune_si_poches_fusionnees():
    """Quand `max_risque_engage_or_argent_pct` vaut 0 (`poches_separees =
    MAX_RISQUE_ENGAGE_OR_ARGENT_PCT > 0` est FAUX en production,
    `bridge.py:1103`), l'or retombe dans la poche commune -- exactement
    comme `mt5_bridge.bridge`, jamais dans une poche or qui n'existe plus."""
    cumul = P.cumul_vide()
    lim = dict(LIM_LIVE, max_open_positions=99,
              max_risque_engage_or_argent_pct=0.0)
    gros_or = dict(S, risk_pct=4.0)
    code, cumul = _passer(gros_or, lim, cumul, classe="metal")
    assert code is None
    # Le budget COMMUN porte deja 4.0 (consomme par l'or) : un setup forex
    # de 1.5 doit desormais heurter le plafond commun (4.0+1.5 > 5.0),
    # preuve que l'or a bien verse dans la poche commune.
    code, _ = _passer(dict(FOREX, risk_pct=1.5), lim, cumul, classe="forex")
    assert code == "lot_risque_engage"


def test_cadence_bloque_le_second_sur_la_meme_paire_quand_cooldown_positif():
    lim = dict(LIM_LIVE, order_cooldown_sec=60, max_open_positions=99)
    code, cumul = _passer(S, lim, P.cumul_vide())
    assert code is None
    code, _ = _passer(S, lim, cumul)
    assert code == "lot_cadence"


def test_une_limite_illisible_BLOQUE_au_lieu_de_passer():
    for champ in ("order_cooldown_sec", "max_risque_engage_pct",
                  "max_risque_engage_or_argent_pct", "max_open_positions"):
        lim = dict(LIM_LIVE)
        lim[champ] = None
        code, _ = _passer(S, lim, P.cumul_vide())
        assert code == "limite_illisible", champ


def test_les_cumuls_sont_separes_par_destination():
    cumul = P.cumul_vide()
    for _ in range(2):
        _, cumul = P.contraintes_lot(S, "admin_live", "metal", LIM_LIVE, cumul)
    code, _ = P.contraintes_lot(S, "admin_kraken", "metal", LIM_LIVE, cumul)
    assert code is None, "le cumul d'une destination ne doit pas en bloquer une autre"
