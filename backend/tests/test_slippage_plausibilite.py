"""La sonde doit juger le SENS des valeurs, pas seulement leur présence.

⛔ LE MODE DE PANNE QUI A SURVÉCU ONZE SEMAINES (trouvé le 2026-10-28) :
`slippage_instrumentation_check` rendait **`OK, alerte: false`** sur un
glissement moyen de **−19 082,80 pips**, avec 91,7 % de couverture. Elle avait
été écrite pour attraper « la colonne reste vide » — et elle le faisait. Elle
était **aveugle** à « la colonne est pleine de non-sens ».

La cause réelle : `_pip_size` n'a aucun cas crypto ni énergie et retombe sur le
facteur forex `0.0001`, donc `BTC/USD` sortait à **1 113 350 pips**.

⚠️ La plausibilité se juge sur `slippage_pct`, le glissement en pourcentage du
prix, **jamais sur les pips** : les pips n'ont pas d'échelle universelle, donc
une valeur en pips ne peut pas être jugée. Références mesurées en production :
`BTC/USD` 0,1298 %, `XAU/USD` 0,0251 %, forex 0,006 à 0,016 %.
"""
import sqlite3

import pytest

from backend.services import slippage_instrumentation_check as chk

APRES = "2026-08-06T12:00:00+00:00"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Table AVEC `slippage_pct` — l'état après le passage de `mt5_sync`."""
    f = tmp_path / "trades.db"
    conn = sqlite3.connect(f)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY, created_at TEXT, is_auto INTEGER,
            fill_price REAL, slippage_pips REAL, slippage_pct REAL
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(chk, "_db_path", lambda: str(f))
    for v in ("SLIPPAGE_CHECK_SINCE", "SLIPPAGE_CHECK_MIN_SAMPLE",
              "SLIPPAGE_CHECK_MIN_COVERAGE", "SLIPPAGE_CHECK_MAX_PCT",
              "SLIPPAGE_CHECK_MIN_PCT_SAMPLE"):
        monkeypatch.delenv(v, raising=False)
    return str(f)


@pytest.fixture
def db_sans_pct(tmp_path, monkeypatch):
    """Table SANS `slippage_pct` — une base où `mt5_sync` n'a pas tourné."""
    f = tmp_path / "vieux.db"
    conn = sqlite3.connect(f)
    conn.execute("""
        CREATE TABLE personal_trades (
            id INTEGER PRIMARY KEY, created_at TEXT, is_auto INTEGER,
            fill_price REAL, slippage_pips REAL
        )
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(chk, "_db_path", lambda: str(f))
    for v in ("SLIPPAGE_CHECK_SINCE", "SLIPPAGE_CHECK_MIN_SAMPLE",
              "SLIPPAGE_CHECK_MIN_COVERAGE", "SLIPPAGE_CHECK_MAX_PCT",
              "SLIPPAGE_CHECK_MIN_PCT_SAMPLE"):
        monkeypatch.delenv(v, raising=False)
    return str(f)


def _seed(db_path, n, fill=1.1, slip=2.0, pct=None, avec_pct=True):
    with sqlite3.connect(db_path) as c:
        for _ in range(n):
            if avec_pct:
                c.execute(
                    "INSERT INTO personal_trades (created_at, is_auto,"
                    " fill_price, slippage_pips, slippage_pct)"
                    " VALUES (?, 1, ?, ?, ?)", (APRES, fill, slip, pct))
            else:
                c.execute(
                    "INSERT INTO personal_trades (created_at, is_auto,"
                    " fill_price, slippage_pips) VALUES (?, 1, ?, ?)",
                    (APRES, fill, slip))


# ─── 🔑 LE TEST QUI REPRODUIT L'ANGLE MORT ──────────────────────────────────


def test_une_COUVERTURE_PARFAITE_avec_des_valeurs_ABSURDES_ALERTE(db):
    """🔑 C'est exactement le cas qui rendait `OK` pendant onze semaines :
    `fill_price` partout, et un glissement de 1,3 % du prix."""
    _seed(db, 30, pct=1.3)

    r = chk.run()

    assert r["couverture_fill"] == 1.0          # la couverture est PARFAITE
    assert r["plausibilite"] == "INVRAISEMBLABLE"
    assert r["verdict"] == "ECHELLE_FAUSSE"
    assert r["alerte"] is True
    assert "echelle" in r["message"].lower()
    assert "_pip_size" in r["message"]          # elle dit OU chercher


def test_des_valeurs_SENSEES_restent_OK(db):
    """Les ordres de grandeur mesurés en production ne doivent PAS alerter."""
    _seed(db, 30, pct=0.1298)                   # BTC/USD reel

    r = chk.run()

    assert r["plausibilite"] == "PLAUSIBLE"
    assert r["verdict"] == "OK"
    assert r["alerte"] is False


@pytest.mark.parametrize("pct", [0.0069, 0.0251, 0.0599, 0.1298, 0.2322])
def test_AUCUNE_valeur_mesuree_en_production_n_alerte(db, pct):
    """⛔ CONTROLE NEGATIF sur les cinq medianes reellement observees
    (forex, XAU, XAG, BTC, WTI). Une sonde qui hurle sur la realite serait
    pire qu'absente."""
    _seed(db, 30, pct=pct)

    r = chk.run()

    assert r["alerte"] is False, (pct, r["message"])
    assert r["plausibilite"] == "PLAUSIBLE"


def test_le_SIGNE_ne_change_rien_au_jugement(db):
    """Un glissement defavorable est negatif : c'est sa TAILLE qui compte."""
    _seed(db, 30, pct=-1.3)

    r = chk.run()

    assert r["plausibilite"] == "INVRAISEMBLABLE"
    assert r["alerte"] is True


# ─── ne pas hurler quand il n'y a rien à juger ──────────────────────────────


def test_TROP_PEU_de_pourcentages_ne_declenche_RIEN(db):
    """⚠️ Sinon la sonde hurlerait a chaque deploiement, le temps que la
    colonne se remplisse."""
    _seed(db, 25, pct=None)                     # 25 trades, 0 pct
    _seed(db, 5, pct=9.9)                       # 5 pct, tous absurdes

    r = chk.run()

    assert r["avec_slippage_pct"] == 5
    assert r["plausibilite"] == "INSUFFISANTE"
    assert r["verdict"] == "OK"
    assert r["alerte"] is False


def test_une_base_SANS_la_colonne_ne_PLANTE_PAS(db_sans_pct):
    """⛔ Un controle qui plante est un controle MUET — le mode de
    defaillance meme qu'il surveille. Il ne doit rien exiger du schema."""
    _seed(db_sans_pct, 30, avec_pct=False)

    r = chk.run()

    assert r["verdict"] != "ERREUR"
    assert r["plausibilite"] == "NON_JUGEE"
    assert r["avec_slippage_pct"] == 0
    assert r["alerte"] is False


def test_la_couverture_du_pourcentage_est_PUBLIEE(db):
    _seed(db, 20, pct=0.02)
    _seed(db, 20, pct=None)

    r = chk.run()

    assert r["avec_slippage_pct"] == 20
    assert r["couverture_slippage_pct"] == pytest.approx(0.5)


# ─── et le seuil se règle ───────────────────────────────────────────────────


def test_le_seuil_de_plausibilite_est_REGLABLE(db, monkeypatch):
    _seed(db, 30, pct=0.1298)                   # plausible par defaut

    monkeypatch.setenv("SLIPPAGE_CHECK_MAX_PCT", "0.05")
    r = chk.run()

    assert r["plausibilite"] == "INVRAISEMBLABLE"
    assert r["alerte"] is True


def test_un_seuil_ILLISIBLE_retombe_sur_le_defaut(db, monkeypatch):
    """⛔ Un reglage casse ne doit pas desarmer la sonde."""
    _seed(db, 30, pct=1.3)

    monkeypatch.setenv("SLIPPAGE_CHECK_MAX_PCT", "beaucoup")
    r = chk.run()

    assert r["plausibilite"] == "INVRAISEMBLABLE"
    assert r["alerte"] is True


def test_l_echantillon_minimal_du_pourcentage_est_REGLABLE(db, monkeypatch):
    _seed(db, 25, pct=None)
    _seed(db, 5, pct=9.9)

    monkeypatch.setenv("SLIPPAGE_CHECK_MIN_PCT_SAMPLE", "3")
    r = chk.run()

    assert r["plausibilite"] == "INVRAISEMBLABLE"
    assert r["alerte"] is True


# ─── l'absence de mesure reste PRIORITAIRE sur l'invraisemblance ────────────


def test_une_mesure_MORTE_garde_son_verdict(db):
    """⛔ `MORTE` dit « la mesure ne marche pas du tout » : c'est plus grave
    qu'une echelle fausse, et ca ne doit pas etre masque."""
    _seed(db, 30, fill=None, slip=None, pct=None)

    r = chk.run()

    assert r["verdict"] == "MORTE"
    assert r["alerte"] is True
