"""La sonde de l'échelle : rendre VÉRIFIABLE « c'est passé au-dessus d'1 € ».

## ⛔ CE QU'ELLE EXISTE POUR EMPÊCHER

Xavier, le 2026-10-09 : « Pourquoi les SL n'ont pas évolué car les trades sont
passés au-delà d'1 € ». Je n'ai **pas pu répondre** : quand l'échelle décide de
ne rien faire, elle ne journalise **rien** — zéro ligne en 30 minutes. Sa
question restait donc un **désaccord** au lieu d'être une **mesure**.

Et la limite est réelle : l'échelle sonde toutes les **15 s**, alors que ses
paliers sont espacés d'environ 0,28 $ sur l'or. Un pic qui franchit +1 € et
redescend entre deux sondages est **invisible**.

## 🔑 POURQUOI UN TÉMOIN EXTÉRIEUR, ET NON UN JOURNAL DE L'ÉCHELLE

Une échelle qui rend compte d'elle-même ne peut pas prouver qu'elle n'a rien
raté : elle ne voit que ce qu'elle a regardé. La sonde échantillonne **plus
vite** qu'elle (5 s contre 15 s) et conserve le **maximum vu**. Si un palier a
été franchi sans que le stop bouge, c'est elle qui le dira.

⚠️ Et elle **réutilise** `echelle_stop_or` pour juger — jamais une copie de la
règle. Une doublure dériverait en silence le jour où les paliers changent,
et ce dépôt a déjà payé ce piège deux fois.

## Ce que ces tests épinglent

1. le **maximum** est conservé même quand le profit redescend — c'est tout
   l'objet ;
2. une position **à la main** est enregistrée avec le **motif** de sa
   non-prise en charge : c'est l'explication la plus probable de la question
   de Xavier, et elle doit être lisible sans relire le code ;
3. un palier franchi est enregistré **avec le stop du moment**, pour qu'on
   puisse dire si l'échelle a agi ou non ;
4. une ligne par ticket, jamais de doublon ;
5. ⛔ une position illisible est **écartée et dite**, jamais devinée.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2] / "scripts"
           / "sonde_echelle_or.py")


@pytest.fixture()
def s(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("sonde_echelle_or", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    f = tmp_path / "trades.db"
    monkeypatch.setattr(mod, "_db_path", lambda: str(f))
    return mod


def _pos(ticket, sens="buy", entree=4190.0, courant=4190.0, sl=4168.0,
         comment="scalping-radar-2026-10-09", profit=0.0):
    return {"ticket": ticket, "symbol": "XAUUSD", "type": sens,
            "price_open": entree, "price_current": courant, "sl": sl,
            "tp": 0.0, "profit": profit, "volume": 0.01, "comment": comment}


def _lignes(s) -> list[dict]:
    """⚠️ Table absente == aucune ligne. La sonde ne la cree qu'au premier
    enregistrement reussi : un test qui verifie << rien n'a ete ecrit >> doit
    accepter les deux formes de << rien >>, sinon il echoue sur le bon
    comportement."""
    with sqlite3.connect(s._db_path()) as c:
        c.row_factory = sqlite3.Row
        try:
            return [dict(x) for x in c.execute(
                "SELECT * FROM echelle_or_suivi ORDER BY ticket")]
        except sqlite3.OperationalError:
            return []


TAUX = 1.1235


# ─────────────────────────────────────────────────────────────────────────
# 1. Le MAXIMUM est conservé
# ─────────────────────────────────────────────────────────────────────────

def test_le_maximum_vu_est_CONSERVE_quand_le_profit_redescend(s):
    """🔑 Tout l'objet de la sonde. Un BUY monte a +1,34 € puis redescend a
    −0,80 € : c'est le +1,34 qui doit rester inscrit."""
    # +1,34 € => prix = entree + 1,34 x taux
    haut = _pos(1, courant=4190.0 + 1.34 * TAUX)
    bas = _pos(1, courant=4190.0 - 0.80 * TAUX)

    s.observer([haut], TAUX)
    s.observer([bas], TAUX)

    l = _lignes(s)[0]
    assert l["profit_max_eur"] == pytest.approx(1.34, abs=0.01)
    assert l["profit_dernier_eur"] == pytest.approx(-0.80, abs=0.01)


def test_un_maximum_PLUS_HAUT_remplace_l_ancien(s):
    s.observer([_pos(1, courant=4190.0 + 1.10 * TAUX)], TAUX)
    s.observer([_pos(1, courant=4190.0 + 1.90 * TAUX)], TAUX)

    assert _lignes(s)[0]["profit_max_eur"] == pytest.approx(1.90, abs=0.01)


def test_une_seule_ligne_par_ticket(s):
    for _ in range(5):
        s.observer([_pos(1, courant=4191.0)], TAUX)

    assert len(_lignes(s)) == 1
    assert _lignes(s)[0]["vu_n"] == 5


# ─────────────────────────────────────────────────────────────────────────
# 2. ⛔ Le MOTIF de non-prise en charge — la question de Xavier
# ─────────────────────────────────────────────────────────────────────────

def test_une_position_A_LA_MAIN_est_enregistree_avec_son_MOTIF(s):
    """⛔ C'est l'explication la plus probable de « pourquoi mon SL n'a pas
    bouge ». Elle doit etre lisible sans relire le code."""
    s.observer([_pos(9, comment="", courant=4190.0 + 2.0 * TAUX)], TAUX)

    l = _lignes(s)[0]
    assert l["suivie"] == 0
    assert "main" in l["motif"].lower() or "marque" in l["motif"].lower()
    # 🔑 …et son maximum est quand meme mesure : c'est ce qui permet de dire
    # << elle a atteint +2 €, et l'echelle ne la suit pas >>.
    assert l["profit_max_eur"] == pytest.approx(2.0, abs=0.01)


def test_une_position_du_RADAR_est_marquee_suivie(s):
    s.observer([_pos(1)], TAUX)

    l = _lignes(s)[0]
    assert l["suivie"] == 1
    assert l["motif"] in ("", None)


# ─────────────────────────────────────────────────────────────────────────
# 3. Le palier franchi, AVEC le stop du moment
# ─────────────────────────────────────────────────────────────────────────

def test_un_palier_franchi_est_enregistre_avec_le_stop_du_moment(s):
    """Sans le stop de l'instant, impossible de dire si l'echelle a agi."""
    s.observer([_pos(1, courant=4190.0 + 1.30 * TAUX, sl=4168.0)], TAUX)

    l = _lignes(s)[0]
    assert l["palier_max_eur"] == pytest.approx(1.00, abs=0.01)
    assert l["sl_au_max"] == pytest.approx(4168.0)


def test_le_stop_du_MAX_survit_aux_echantillons_SUIVANTS(s):
    """⛔ LACUNE DE MON PREMIER TEST, trouvee en reinjectant le defaut.

    Le test voisin n'appelle `observer` QU'UNE FOIS : il n'exerce donc que
    l'INSERTION, jamais la branche `ON CONFLICT DO UPDATE`. J'ai pu mettre
    `sl_au_max = NULL` dans la mise a jour sans qu'aucun test ne tombe.

    🔑 Or c'est exactement le cas reel : le maximum survient au 3e echantillon
    sur onze, et les suivants ne doivent PAS effacer le stop d'alors — sans
    lui, impossible de dire si l'echelle a agi apres le palier.
    """
    # 1) sous le palier, stop initial
    s.observer([_pos(1, courant=4190.0 + 0.40 * TAUX, sl=4168.0)], TAUX)
    # 2) LE MAXIMUM, avec un stop encore du cote de la perte
    s.observer([_pos(1, courant=4190.0 + 1.30 * TAUX, sl=4168.0)], TAUX)
    # 3) le prix redescend, et le stop a bouge depuis
    s.observer([_pos(1, courant=4190.0 - 0.50 * TAUX, sl=4190.9)], TAUX)

    l = _lignes(s)[0]
    assert l["profit_max_eur"] == pytest.approx(1.30, abs=0.01)
    assert l["palier_max_eur"] == pytest.approx(1.00, abs=0.01)
    # 🔑 Le stop AU MOMENT du max, pas celui de maintenant.
    assert l["sl_au_max"] == pytest.approx(4168.0)
    assert l["sl_dernier"] == pytest.approx(4190.9)


def test_sous_le_premier_palier_aucun_palier_n_est_inscrit(s):
    s.observer([_pos(1, courant=4190.0 + 0.50 * TAUX)], TAUX)

    assert _lignes(s)[0]["palier_max_eur"] is None


def test_le_PALIER_vient_de_l_echelle_et_n_est_pas_recopie(s):
    """⚠️ La sonde REUTILISE `echelle_stop_or.palier_atteint`. Une copie de la
    regle dériverait le jour ou les paliers changent."""
    import inspect
    src = inspect.getsource(s)

    assert "palier_atteint" in src
    assert "echelle_stop_or" in src or "import echelle_stop_or" in src


# ─────────────────────────────────────────────────────────────────────────
# 4. ⛔ On n'invente rien
# ─────────────────────────────────────────────────────────────────────────

def test_une_position_ILLISIBLE_est_ecartee_et_DITE(s, caplog):
    with caplog.at_level("WARNING"):
        n = s.observer([{"ticket": 7, "symbol": "XAUUSD"}], TAUX)

    assert n == 0
    assert _lignes(s) == []
    assert "7" in caplog.text


def test_une_position_illisible_ne_fait_pas_tomber_les_AUTRES(s):
    n = s.observer([{"ticket": 7, "symbol": "XAUUSD"},
                    _pos(1, courant=4191.0)], TAUX)

    assert n == 1
    assert [x["ticket"] for x in _lignes(s)] == [1]


def test_un_taux_ABSENT_n_invente_aucun_profit(s, caplog):
    """⛔ Sans le taux, les euros sont inconvertibles. On ne devine pas."""
    with caplog.at_level("WARNING"):
        n = s.observer([_pos(1, courant=4191.0)], 0)

    assert n == 0
    assert _lignes(s) == []


def test_une_paire_qui_n_est_pas_de_l_or_est_ignoree(s):
    p = _pos(1)
    p["symbol"] = "EURUSD"

    assert s.observer([p], TAUX) == 0
    assert _lignes(s) == []


# ─────────────────────────────────────────────────────────────────────────
# 5. L'HISTOIRE que lit la protection des pertes (2026-10-09)
# ─────────────────────────────────────────────────────────────────────────

def test_negatif_depuis_est_POSE_au_passage_en_negatif(s):
    """🔑 La regle de protection des pertes a besoin d'une DUREE, pas d'un
    instantane. C'est la sonde qui la tient, parce qu'elle seule echantillonne
    assez vite (5 s)."""
    s.observer([_pos(1, courant=4190.0 + 0.50 * TAUX)], TAUX)   # positif
    assert _lignes(s)[0]["negatif_depuis"] is None

    s.observer([_pos(1, courant=4190.0 - 0.50 * TAUX)], TAUX)   # negatif
    pose = _lignes(s)[0]["negatif_depuis"]
    assert pose is not None


def test_negatif_depuis_NE_BOUGE_PAS_tant_qu_on_reste_negatif(s):
    """⛔ C'est tout l'interet : si l'horodatage se remettait a jour a chaque
    passage, la duree vaudrait toujours zero et la regle ne se declencherait
    JAMAIS."""
    s.observer([_pos(1, courant=4190.0 - 0.50 * TAUX)], TAUX)
    premier = _lignes(s)[0]["negatif_depuis"]

    for _ in range(4):
        s.observer([_pos(1, courant=4190.0 - 0.80 * TAUX)], TAUX)

    assert _lignes(s)[0]["negatif_depuis"] == premier


def test_un_RETOUR_en_positif_remet_le_compteur_a_zero(s):
    """Une position qui repasse au-dessus de l'equilibre n'est plus << negative
    depuis >> : le compteur doit repartir de zero si elle replonge."""
    s.observer([_pos(1, courant=4190.0 - 0.50 * TAUX)], TAUX)
    assert _lignes(s)[0]["negatif_depuis"] is not None

    s.observer([_pos(1, courant=4190.0 + 0.30 * TAUX)], TAUX)

    assert _lignes(s)[0]["negatif_depuis"] is None


def test_l_heure_d_OUVERTURE_est_conservee(s):
    """La regle laisse le trade evoluer 5 min : il faut son age."""
    p = _pos(1, courant=4191.0)
    p["time"] = "2026-10-09T15:09:01+00:00"

    s.observer([p], TAUX)

    assert _lignes(s)[0]["ouvert_depuis"] == "2026-10-09T15:09:01+00:00"
