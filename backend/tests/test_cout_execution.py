"""Le cout d'execution doit dire D'OU il vient, toujours (2026-10-30).

Ces tests ne touchent PAS au vrai magasin de ticks : ils batissent un magasin
jouet. Un test qui depend de `/app/data/ticks_courtier.db` passerait en
production et echouerait en local, donc ne prouverait rien de portable.

La propriete centrale : **aucun cout ne sort sans source**. Les faux-surs du
28/10 et du 30/10 venaient tous les deux d'une absence traitee comme une
valeur ; ici c'est la chose meme qu'on teste.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import cout_execution as C


@pytest.fixture()
def magasin(tmp_path):
    """Un magasin jouet : spread de 0,0859 $ sur un or a 4 129 $.

    Ce sont les valeurs MESUREES le 30/10 sur 11 987 039 ticks, pour que le
    test serve aussi de temoin : si la cascade applique bien le markup, le
    relatif rendu doit valoir ~0,0000450.
    """
    chemin = tmp_path / "ticks.db"
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE ticks (pair TEXT, ts_utc TEXT, ms INT, "
              "bid REAL, ask REAL)")
    mid, sp = 4129.01, 0.0859
    c.executemany(
        "INSERT INTO ticks VALUES (?,?,?,?,?)",
        [("XAU/USD", "2026-10-15T12:00:%02d" % s, 0,
          mid - sp / 2, mid + sp / 2) for s in range(60)])
    c.commit()
    c.close()
    return str(chemin)


# --- etage 1 : le tick de l'instant ---------------------------------------

def test_le_tick_de_l_instant_est_une_MESURE(magasin):
    co = C.cout_spread_relatif("XAU/USD", "2026-10-15T12:00:30",
                               magasin=magasin)
    assert co.source == "tick_instant"
    assert co.est_mesure is True


def test_le_markup_est_AJOUTE_et_reproduit_la_mesure_du_30_10(magasin):
    """Temoin : 0,0859 $ de magasin + 10 points (0,10 $) sur 4 129 $
    doit rendre 0,0000450 -- le chiffre publie le 30/10."""
    co = C.cout_spread_relatif("XAU/USD", "2026-10-15T12:00:30",
                               magasin=magasin)
    assert co.relatif == pytest.approx(0.0000450, rel=0.01), (
        "attendu ~0,0000450 (magasin + markup), obtenu %.8f" % co.relatif)


def test_sans_le_markup_on_tomberait_a_cote():
    """Garde-fou de sens : si quelqu'un retire le markup, le test ci-dessus
    doit casser. On le verifie en calculant la valeur SANS markup."""
    sans = 0.0859 / 4129.01
    assert sans == pytest.approx(0.0000208, rel=0.02)
    assert abs(sans - 0.0000450) > 0.00002, (
        "le markup doit changer le resultat de facon visible")


def test_un_instant_HORS_tolerance_retombe_sur_la_moyenne(magasin):
    """Hors fenetre, on ne rend pas le tick d'a cote en pretendant qu'il est
    celui de l'instant : on descend d'un etage, et on le dit."""
    co = C.cout_spread_relatif("XAU/USD", "2026-10-15T18:00:00",
                               magasin=magasin)
    assert co.source == "tick_moyen"
    assert co.est_mesure is True


# --- etage 3 : l'hypothese, et le silence interdit -------------------------

def test_un_magasin_ABSENT_rend_une_HYPOTHESE_marquee(tmp_path):
    """LE test qui compte. Un magasin absent ne doit pas produire un nombre
    qui ressemble a une mesure -- c'est la faute du 30/10 sur le filtre
    Kraken, annonce conforme alors qu'il n'etait pas deploye."""
    co = C.cout_spread_relatif("XAU/USD", "2026-10-15T12:00:30",
                               magasin=str(tmp_path / "jamais.db"))
    assert co.source == "hypothese_classe"
    assert co.est_mesure is False
    assert "HYPOTHESE" in co.details


def test_une_paire_sans_point_connu_rend_une_HYPOTHESE(magasin):
    """BTC/USD n'a pas de taille de point declaree : on ne devine pas."""
    co = C.cout_spread_relatif("BTC/USD", "2026-10-15T12:00:30",
                               magasin=magasin)
    assert co.source == "hypothese_classe"
    assert "crypto" in co.details


def test_une_paire_absente_du_magasin_rend_une_HYPOTHESE(magasin, monkeypatch):
    """Point connu, magasin present, mais aucun tick pour cette paire."""
    monkeypatch.setitem(C.TAILLE_POINT, "XAG/USD", 0.001)
    co = C.cout_spread_relatif("XAG/USD", magasin=magasin)
    assert co.source == "hypothese_classe"
    assert "aucun tick" in co.details


def test_aucun_cout_ne_sort_sans_source(magasin, tmp_path):
    """La propriete generale, sur tous les chemins."""
    cas = [("XAU/USD", "2026-10-15T12:00:30", magasin),
           ("XAU/USD", None, magasin),
           ("XAU/USD", "2026-10-15T12:00:30", str(tmp_path / "absent.db")),
           ("BTC/USD", None, magasin),
           ("EUR/USD", None, magasin)]
    for pair, ts, mag in cas:
        co = C.cout_spread_relatif(pair, ts, magasin=mag)
        assert co.source in ("tick_instant", "tick_moyen", "hypothese_classe")
        assert co.details, "un cout sans explication est un cout sans source"
        assert co.relatif > 0


# --- exiger_mesure : la porte pour les niveaux absolus ---------------------

def test_exiger_mesure_ACCEPTE_une_mesure(magasin):
    co = C.cout_spread_relatif("XAU/USD", "2026-10-15T12:00:30",
                               magasin=magasin)
    assert C.exiger_mesure(co) is co


def test_exiger_mesure_REFUSE_une_hypothese(magasin):
    co = C.cout_spread_relatif("BTC/USD", magasin=magasin)
    with pytest.raises(ValueError, match="NON MESURE"):
        C.exiger_mesure(co)


def test_le_refus_propose_la_sortie_APPARIEE(magasin):
    """Le message doit rappeler qu'une comparaison appariee reste valide :
    c'est la seule chose qui sauve les verdicts d'horizon."""
    co = C.cout_spread_relatif("ETH/USD", magasin=magasin)
    with pytest.raises(ValueError, match="APPARIEE"):
        C.exiger_mesure(co)


# --- classification -------------------------------------------------------

@pytest.mark.parametrize("pair,attendu", [
    ("XAU/USD", "metal"), ("XAG/USD", "metal"),
    ("WTI/USD", "energy"),
    ("BTC/USD", "crypto"), ("PAXG/USD", "crypto"), ("DOGE/USD", "crypto"),
    ("USD/JPY", "forex_jpy"), ("EUR/JPY", "forex_jpy"),
    ("EUR/USD", "forex_major"), ("AUD/USD", "forex_major"),
    ("SPX", "equity_index"), ("NDX", "equity_index"),
])
def test_classe_de(pair, attendu):
    assert C.classe_de(pair) == attendu


def test_chaque_classe_a_une_hypothese():
    """Garde de derive : une classe sans hypothese ferait lever un KeyError
    au pire moment, c'est-a-dire quand la donnee manque."""
    for pair in ("XAU/USD", "WTI/USD", "BTC/USD", "USD/JPY", "EUR/USD",
                 "SPX", "", "n'importe quoi"):
        assert C.classe_de(pair) in C.HYPOTHESE_CLASSE


def test_le_markup_est_celui_de_la_provenance():
    """Il est mesure, pas choisi. S'il change ici sans remesure, c'est une
    regression -- la table `provenance` du magasin dit 10."""
    assert C.MARKUP_POINTS == 10.0
    assert C.MARKUP_MESURE_LE == "2026-10-12"
