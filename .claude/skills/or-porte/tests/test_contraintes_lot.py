import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import porte as P  # noqa: E402

# Limites REELLES de admin_live, relevees dans son /health le 2026-10-29.
LIM_LIVE = {"max_correlated_positions": 3, "order_cooldown_sec": 0,
            "max_risque_engage_pct": 5.0, "places_par_paire": 2}

S = {"pair": "XAU/USD", "direction": "buy", "entry_price": 2412.50,
     "stop_loss": 2404.10, "confidence_score": 71, "pattern": "range_bounce",
     "horizon": "30min", "chaine": None, "shadow_system_id": None,
     "is_simulated": False, "verdict_blockers": [], "risk_pct": 0.35}


def _passer(setup, lim, cumul, classe="metal"):
    return P.contraintes_lot(setup, "admin_live", classe, lim, cumul)


def test_un_setup_seul_passe_les_quatre_contraintes():
    code, _ = _passer(S, LIM_LIVE, P.cumul_vide())
    assert code is None


def test_places_par_paire_bloque_le_troisieme_sur_la_meme_paire():
    cumul = P.cumul_vide()
    for _ in range(2):
        code, cumul = _passer(S, LIM_LIVE, cumul)
        assert code is None
    code, _ = _passer(S, LIM_LIVE, cumul)
    assert code == "lot_places_par_paire"


def test_exposition_correlee_bloque_au_dela_du_plafond_de_classe():
    cumul = P.cumul_vide()
    lim = dict(LIM_LIVE, places_par_paire=99)
    for paire in ("XAU/USD", "XAG/USD", "WTI/USD"):
        code, cumul = _passer(dict(S, pair=paire), lim, cumul)
        assert code is None
    code, _ = _passer(dict(S, pair="EUR/USD"), lim, cumul)
    assert code == "lot_exposition_correlee"


def test_risque_engage_bloque_quand_le_cumul_depasse():
    cumul = P.cumul_vide()
    lim = dict(LIM_LIVE, places_par_paire=99, max_correlated_positions=99)
    gros = dict(S, risk_pct=3.0)
    code, cumul = _passer(gros, lim, cumul)
    assert code is None
    code, _ = _passer(gros, lim, cumul)
    assert code == "lot_risque_engage"


def test_cadence_bloque_le_second_sur_la_meme_paire_quand_cooldown_positif():
    lim = dict(LIM_LIVE, order_cooldown_sec=60, places_par_paire=99)
    code, cumul = _passer(S, lim, P.cumul_vide())
    assert code is None
    code, _ = _passer(S, lim, cumul)
    assert code == "lot_cadence"


def test_une_limite_illisible_BLOQUE_au_lieu_de_passer():
    for champ in ("max_correlated_positions", "order_cooldown_sec",
                  "max_risque_engage_pct", "places_par_paire"):
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
