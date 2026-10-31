"""Le collecteur de spreads : agrégation, idempotence, et les deux pièges.

## Pourquoi ce collecteur existe

`cout_execution` ne mesure que l'or. Partout ailleurs il rend une hypothèse
déclarée, que `exiger_mesure()` refuse pour tout niveau absolu. Et la route
`/rates` ne peut pas y suppléer : MT5 y tronque le spread à l'entier, donc
**96 % des bougies `EUR/USD` affichent zéro** — alors que la route `/ticks`
montre un spread réel de **0,8 pip**.

## Les deux pièges, mesurés le 2026-10-31

⛔ **Marché FERMÉ** : un samedi à 09h25 UTC, l'or cotait **0,40 $** d'écart
contre **0,086 $** de médiane en séance — **4,6× plus large**. Collecter sans
le noter aurait pollué le magasin dans le sens pessimiste.

⛔ **Minute EN COURS** : l'agréger donnerait une valeur partielle, que le
`INSERT OR IGNORE` des passages suivants figerait définitivement.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

import pytest

from scripts import collecter_spreads_forex as C


def _tick(t, bid, ask):
    return {"t": t, "bid": bid, "ask": ask, "ms": 0}


# --- agregation ----------------------------------------------------------

def test_les_ticks_se_groupent_par_MINUTE():
    out = C.agreger([
        _tick("2026-10-30T12:00:01+00:00", 1.1000, 1.1001),
        _tick("2026-10-30T12:00:59+00:00", 1.1002, 1.1004),
        _tick("2026-10-30T12:01:00+00:00", 1.1000, 1.1001),
    ])
    assert sorted(out) == ["2026-10-30T12:00", "2026-10-30T12:01"]
    assert out["2026-10-30T12:00"]["n"] == 2


def test_min_med_max_bornent_la_variation_intra_minute():
    """🔑 C'est tout l'intérêt de garder trois valeurs : l'or passe de 15 à
    22 points en deux minutes, et un agrégat qui n'aurait que la médiane
    masquerait cette enveloppe."""
    out = C.agreger([
        _tick("2026-10-30T12:00:01+00:00", 100.00, 100.01),   # 0,01
        _tick("2026-10-30T12:00:02+00:00", 100.00, 100.05),   # 0,05
        _tick("2026-10-30T12:00:03+00:00", 100.00, 100.03),   # 0,03
    ])["2026-10-30T12:00"]
    assert out["spread_min"] == pytest.approx(0.01)
    assert out["spread_med"] == pytest.approx(0.03)
    assert out["spread_max"] == pytest.approx(0.05)
    assert out["spread_min"] < out["spread_max"], "l'enveloppe doit rester lisible"


@pytest.mark.parametrize("bid,ask", [
    (1.1001, 1.1000),   # ask < bid : croise
    (1.1000, 1.1000),   # ask == bid : spread nul, impossible
    (0.0, 1.1000),      # bid nul
    (-1.0, 1.1),        # bid negatif
])
def test_une_cotation_IMPOSSIBLE_est_ecartee(bid, ask):
    """⛔ `ask <= bid` n'est pas un spread serré, c'est un instrument faux."""
    assert C.agreger([_tick("2026-10-30T12:00:01+00:00", bid, ask)]) == {}


@pytest.mark.parametrize("mauvais", [
    {"t": "2026-10-30T12:00:01+00:00", "bid": "x", "ask": 1.1},
    {"t": "2026-10-30T12:00:01+00:00", "ask": 1.1},
    {"t": "pas une date", "bid": 1.0, "ask": 1.1},
    {"bid": 1.0, "ask": 1.1},
])
def test_un_tick_ILLISIBLE_ne_fait_pas_tomber_la_minute(mauvais):
    """Un tick fautif est ecarte ; les voisins doivent survivre."""
    out = C.agreger([mauvais, _tick("2026-10-30T12:00:02+00:00", 1.1, 1.2)])
    assert out["2026-10-30T12:00"]["n"] == 1


def test_aucun_tick_rend_un_dict_vide():
    assert C.agreger([]) == {}


# --- magasin : idempotence et piege de la minute en cours ----------------

@pytest.fixture()
def magasin(tmp_path):
    chemin = str(tmp_path / "spreads.db")
    with sqlite3.connect(chemin) as c:
        C._schema(c)
    return chemin


def _faux_pont(monkeypatch, ticks, point=1e-05):
    class _R:
        def raise_for_status(self): pass
        def json(self): return {"ticks": ticks, "point": point}
    monkeypatch.setattr(C.httpx, "get", lambda *a, **k: _R())


def test_la_meme_minute_n_est_PAS_ecrite_deux_fois(magasin, monkeypatch):
    """Idempotence : relancer le collecteur ne duplique rien."""
    quand = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)
             ).replace(second=5, microsecond=0)
    _faux_pont(monkeypatch, [_tick(quand.isoformat(), 1.1000, 1.1001)])
    with sqlite3.connect(magasin) as c:
        C._schema(c)
        a, _ = C.collecter_paire(c, "http://x", "k", "EUR/USD", 120)
        b, _ = C.collecter_paire(c, "http://x", "k", "EUR/USD", 120)
        n = c.execute("SELECT COUNT(*) FROM spread_minute").fetchone()[0]
    assert a == 1 and b == 0, "le second passage ne doit rien reecrire"
    assert n == 1


def test_la_minute_EN_COURS_n_est_jamais_agregee(magasin, monkeypatch):
    """⛔ Elle serait partielle, et le `INSERT OR IGNORE` la figerait."""
    maintenant = dt.datetime.now(dt.timezone.utc)
    _faux_pont(monkeypatch, [_tick(maintenant.isoformat(), 1.1000, 1.1001)])
    with sqlite3.connect(magasin) as c:
        C._schema(c)
        C.collecter_paire(c, "http://x", "k", "EUR/USD", 120)
        minutes = [r[0] for r in c.execute("SELECT minute FROM spread_minute")]
    assert maintenant.isoformat()[:16] not in minutes


def test_la_reprise_part_de_la_DERNIERE_minute_connue(magasin, monkeypatch):
    """Incremental : on ne redemande pas ce qu'on a deja."""
    with sqlite3.connect(magasin) as c:
        C._schema(c)
        # colonnes NOMMEES : un INSERT positionnel casse des qu'une colonne
        # est ajoutee -- ce qui vient d'arriver avec `spread_constant`.
        c.execute("INSERT INTO spread_minute (pair, minute, n, spread_min,"
                  " spread_med, spread_max, mid_med, point, marche_ouvert)"
                  " VALUES ('EUR/USD','2026-10-30T12:00',10,0.0001,0.0001,"
                  "0.0001,1.1,1e-05,1)")
        assert C.derniere_minute(c, "EUR/USD") == "2026-10-30T12:00"
        assert C.derniere_minute(c, "GBP/USD") is None


# --- le piege du marche ferme --------------------------------------------

def test_l_etat_du_marche_est_ENREGISTRE(magasin, monkeypatch):
    """🔑 Sans ce drapeau, une mesure melangerait un samedi a 0,40 $ et une
    seance a 0,086 $ — et conclurait a un cout 4,6x trop haut."""
    quand = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)
             ).replace(second=5, microsecond=0)
    _faux_pont(monkeypatch, [_tick(quand.isoformat(), 1.1000, 1.1001)])
    monkeypatch.setattr(C, "_marche_ouvert", lambda p: 0)
    with sqlite3.connect(magasin) as c:
        C._schema(c)
        C.collecter_paire(c, "http://x", "k", "EUR/USD", 120)
        r = c.execute("SELECT marche_ouvert FROM spread_minute").fetchone()
    assert r[0] == 0, "un marche ferme doit se voir dans le magasin"


def test_un_etat_de_marche_INDETERMINABLE_vaut_NULL_et_pas_0(monkeypatch):
    """⛔ « Inconnu » n'est pas « ferme ». Le confondre ferait jeter des
    minutes valides, ou garder des minutes fermees."""
    import backend.services.market_hours as mh
    monkeypatch.setattr(mh, "is_market_open_for",
                        lambda p: (_ for _ in ()).throw(RuntimeError("x")))
    assert C._marche_ouvert("EUR/USD") is None


# --- la provenance, et ce qu'elle doit AVOUER ----------------------------

def test_la_provenance_declare_le_markup_INCONNU(magasin):
    """⛔ Les 10 points mesures le 12/10 valent pour l'or sur cette route.
    Rien ne dit qu'ils valent pour EUR/USD : la provenance doit le DIRE,
    sinon une mesure future extrapolera en silence."""
    with sqlite3.connect(magasin) as c:
        p = dict(c.execute("SELECT cle, valeur FROM provenance"))
    assert "INCONNU" in p["markup"]
    assert "A ETABLIR" in p["markup"]


def test_la_provenance_declare_la_RESOLUTION_minute(magasin):
    with sqlite3.connect(magasin) as c:
        p = dict(c.execute("SELECT cle, valeur FROM provenance"))
    assert "MINUTE" in p["resolution"]
    assert "temoin" in p and "XAU/USD" in p["temoin"]


def test_l_OR_est_dans_les_paires_par_defaut():
    """🔑 Le temoin : son cout est deja mesure, donc c'est lui qui dira si
    cet instrument-ci est juste."""
    assert "XAU/USD" in C.PAIRES_DEFAUT


def test_la_crypto_n_est_PAS_collectee_ici():
    """Elle n'est pas dans les classes autorisees d'admin_live, ni dans
    celles que le registre declare acceptees par IC Markets."""
    assert not [p for p in C.PAIRES_DEFAUT
                if p.split("/")[0] in {"BTC", "ETH", "SOL", "ADA", "XRP"}]


# ─── La COTATION GELEE : on la marque, on ne la jette pas ────────────────
#
# Mesure du 2026-10-30 : le flux de l'or s'est fige a 09h15 sur un spread de
# 0,4000 EXACTEMENT (min = max) pendant 18 minutes, puis le magasin de ticks
# s'est arrete a 11h06. Un spread de marche FLUCTUE ; un spread constant a une
# valeur ronde est une cotation qui ne se met plus a jour.
#
# Verification sur ma propre mesure : cette periode pese 0,553 % du magasin
# (66 995 ticks sur 12,1 M) et l'exclure deplace la mediane de 1 %. La mesure
# du cout de l'or tient donc -- mais il fallait le VERIFIER, pas l'esperer.

def test_un_spread_CONSTANT_sur_assez_de_ticks_est_marque():
    """Le cas reel : 0,4000 exactement, min == max, sur 100 ticks."""
    t = [_tick("2026-10-30T09:25:%02d+00:00" % (i % 60), 4000.00, 4000.40)
         for i in range(100)]
    a = C.agreger(t)["2026-10-30T09:25"]
    assert a["spread_constant"] == 1
    assert a["spread_min"] == a["spread_max"]


def test_un_spread_QUI_FLUCTUE_n_est_pas_marque():
    """Le contre-exemple : une seance normale varie."""
    t = [_tick("2026-10-30T09:00:%02d+00:00" % i, 4000.00, 4000.05 + (i % 3) * 0.01)
         for i in range(30)]
    assert C.agreger(t)["2026-10-30T09:00"]["spread_constant"] == 0


def test_une_minute_CALME_avec_peu_de_ticks_n_est_pas_accusee():
    """⛔ Sur une minute calme, min == max est LEGITIME. Le marquer serait
    jeter des minutes valides -- d'ou le seuil de 10 ticks, et le mot
    « suspicion » plutot que « gele »."""
    t = [_tick("2026-10-30T03:00:%02d+00:00" % i, 1.1000, 1.1001)
         for i in range(5)]
    assert C.agreger(t)["2026-10-30T03:00"]["spread_constant"] == 0


def test_le_drapeau_arrive_dans_le_magasin(magasin, monkeypatch):
    quand = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)
             ).replace(second=0, microsecond=0)
    t = [_tick((quand + dt.timedelta(seconds=i)).isoformat(), 4000.0, 4000.40)
         for i in range(20)]
    _faux_pont(monkeypatch, t)
    with sqlite3.connect(magasin) as c:
        C._schema(c)
        C.collecter_paire(c, "http://x", "k", "XAU/USD", 120)
        r = c.execute("SELECT spread_constant, spread_min, spread_max "
                      "FROM spread_minute").fetchone()
    assert r[0] == 1 and r[1] == r[2]


def test_la_provenance_explique_le_drapeau(magasin):
    """⛔ Un drapeau sans explication se lit comme un verdict. La provenance
    doit dire que c'est une SUSPICION, et ou filtrer."""
    with sqlite3.connect(magasin) as c:
        p = dict(c.execute("SELECT cle, valeur FROM provenance"))
    assert "SUSPICION" in p["spread_constant"]
    assert "0,4000" in p["spread_constant"], "l'incident doit etre date et chiffre"
    assert "MESURER" in p["spread_constant"]
