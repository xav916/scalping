"""Un tiers du chemin vers l'objectif, sur l'or et l'argent du compte réel.

Demandé le 2026-08-28. Deux restrictions, et elles portent l'essentiel du
sens : **compte réel seul** (le démo porte six positions en permanence) et
**or/argent seuls** (les deux instruments de la poche des 14 %).

## Ce que ces tests verrouillent

1. ⛔ **La décision se prend sur les PRIX, pas sur les euros.** `profit` peut
   manquer ; `price_open`, `price_current` et `tp` sont toujours publiés. Comme
   `profit = acquis × k` et `gain_visé = distance × k` avec `k > 0`, les deux
   formulations sont exactement équivalentes — mais une seule survit à une
   donnée absente.
2. ⛔ **Une position sans objectif ne déclenche JAMAIS**, et ce silence est
   compté puis dit dans le message. Un non-événement invisible est la forme de
   silence que ce dépôt paie depuis des mois.
3. ⛔ **Le ticket n'est retenu que sur un envoi confirmé** : une annonce ratée
   se rejoue, elle ne se perd pas.
4. Le forex ne déclenche rien, même à 90 % de son objectif.
5. La liste des métaux est **la même** que celle de la sonde du premier ordre
   métal — elle est importée, pas recopiée.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "notify_tiers_objectif.py")


@pytest.fixture()
def s():
    spec = importlib.util.spec_from_file_location("tiers_objectif", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pos(ticket=1, symbol="XAUUSD", type_="buy", entree=4598.0,
         courant=4616.0, sl=4580.0, tp=4650.0, profit=18.0):
    return {"ticket": ticket, "symbol": symbol, "type": type_,
            "volume": 0.01, "price_open": entree, "price_current": courant,
            "sl": sl, "tp": tp, "profit": profit}


TIERS = 0.3333333


# ── La mesure ──────────────────────────────────────────────────────────────

def test_un_achat_a_un_tiers_du_chemin(s):
    """4598 → 4650 = 52 points ; +18 points = 34,6 % du chemin."""
    m = s.mesurer(_pos())
    assert m["mesurable"] is True
    assert m["part"] == pytest.approx(18.0 / 52.0, abs=0.001)
    assert s.franchit(m, TIERS) is True


def test_juste_SOUS_le_tiers_ne_franchit_pas(s):
    m = s.mesurer(_pos(courant=4598.0 + 52.0 / 3 - 0.01))
    assert s.franchit(m, TIERS) is False


def test_pile_AU_tiers_franchit_seuil_inclusif(s):
    """⛔ Le seuil est inclusif, et il doit le rester A LA LIMITE EXACTE.
    `4598 + 52 x 1/3` puis la soustraction rendent 0,33333315 au lieu de
    0,3333333 : l'erreur de representation a une magnitude de 4 598 suffit a
    faire rater le franchissement. D'ou l'epsilon dans `franchit`."""
    m = s.mesurer(_pos(courant=4598.0 + 52.0 * TIERS))
    assert m["part"] < TIERS, "sans epsilon, le flottant passe SOUS le seuil"
    assert s.franchit(m, TIERS) is True


def test_une_VENTE_est_mesuree_dans_le_bon_sens(s):
    """Objectif SOUS l'entrée : le chemin se fait en descendant."""
    m = s.mesurer(_pos(type_="sell", entree=4598.0, courant=4580.0,
                       tp=4546.0, sl=4620.0, profit=18.0))
    assert m["part"] == pytest.approx(18.0 / 52.0, abs=0.001)
    assert s.franchit(m, TIERS) is True


def test_une_position_EN_PERTE_ne_franchit_rien(s):
    m = s.mesurer(_pos(courant=4580.0, profit=-18.0))
    assert m["part"] < 0
    assert s.franchit(m, TIERS) is False


# ── ⛔ La décision ne dépend PAS des euros ─────────────────────────────────

def test_un_profit_ABSENT_n_empeche_pas_la_decision(s):
    """⛔ Le cœur du choix de conception : `profit` sert au message, jamais à
    la décision. Le courtier publie toujours les prix, pas toujours le reste."""
    m = s.mesurer(_pos(profit=None))
    assert m["mesurable"] is True
    assert s.franchit(m, TIERS) is True
    assert m["gain_vise"] is None, "on n'invente pas un montant"


def test_un_profit_ILLISIBLE_ne_fait_pas_lever(s):
    m = s.mesurer(_pos(profit="beaucoup"))
    assert m["mesurable"] is True and m["profit"] is None


def test_le_gain_vise_est_derive_du_profit_reel(s):
    """+18 € pour 18 points ⇒ 1 €/point ⇒ 52 points visés = 52 €."""
    m = s.mesurer(_pos())
    assert m["gain_vise"] == pytest.approx(52.0, abs=0.01)


# ── ⛔ Ce qui n'est pas mesurable, et qui doit se VOIR ─────────────────────

def test_sans_objectif_la_position_est_NON_MESURABLE_avec_son_motif(s):
    m = s.mesurer(_pos(tp=0.0))
    assert m["mesurable"] is False
    assert "objectif" in m["motif"]
    assert s.franchit(m, TIERS) is False


def test_un_objectif_du_MAUVAIS_COTE_est_dit_autrement(s):
    """14 % des TP stockés étaient du mauvais côté de l'entrée réelle. Ici
    c'est le TP VIVANT du courtier : c'est donc un vrai défaut, pas un
    artefact de stockage, et il ne doit pas se confondre avec « pas de TP »."""
    m = s.mesurer(_pos(tp=4500.0))          # achat, objectif SOUS l'entrée
    assert m["mesurable"] is False
    assert "mauvais" in m["motif"]


def test_des_prix_illisibles_ont_leur_propre_motif(s):
    assert "prix" in s.mesurer(_pos(courant="?"))["motif"]
    assert "prix" in s.mesurer(_pos(entree=0.0))["motif"]


def test_les_non_mesurables_sont_rendues_A_PART(s):
    a_dire, muettes = s.a_annoncer(
        [_pos(ticket=1), _pos(ticket=2, tp=0.0)], set(), TIERS)
    assert [p["ticket"] for p, _ in a_dire] == [1]
    assert [p["ticket"] for p, _ in muettes] == [2]


# ── Or et argent SEULEMENT ────────────────────────────────────────────────

def test_le_forex_ne_declenche_RIEN_meme_a_90_pct(s):
    a_dire, muettes = s.a_annoncer(
        [_pos(ticket=9, symbol="EURUSD", entree=1.10, courant=1.109,
              tp=1.11, sl=1.09, profit=9.0)], set(), TIERS)
    assert a_dire == [] and muettes == []


def test_l_or_ET_l_argent_declenchent(s):
    for sym in ("XAUUSD", "XAGUSD", "GOLD", "SILVER"):
        a_dire, _ = s.a_annoncer([_pos(symbol=sym)], set(), TIERS)
        assert len(a_dire) == 1, sym


def test_un_forex_sans_objectif_n_est_PAS_compte_comme_muet(s):
    """⛔ Annoncer « 4 positions non mesurables » en comptant du forex qu'on
    ne surveille pas serait une inquiétude fabriquée."""
    _, muettes = s.a_annoncer(
        [_pos(ticket=9, symbol="USDCHF", tp=0.0)], set(), TIERS)
    assert muettes == []


def test_la_liste_des_metaux_est_CELLE_de_la_sonde_metal(s):
    """Importée, pas recopiée : une quatrième copie serait une divergence en
    attente."""
    from scripts.notify_premier_metal import est_metal
    assert s.est_metal is est_metal


# ── Une seule fois par ticket ──────────────────────────────────────────────

def test_un_ticket_deja_annonce_se_tait(s):
    a_dire, _ = s.a_annoncer([_pos(ticket=42)], {"42"}, TIERS)
    assert a_dire == []


# ── Branchement : l'état ne bouge que sur un envoi confirmé ───────────────

def _armer(s, monkeypatch, positions, etat=None, envoi=True):
    ecrits = {}
    monkeypatch.setattr(s, "_positions", lambda dest: positions)
    monkeypatch.setattr(s, "_charger_etat", lambda: dict(etat or {}))
    monkeypatch.setattr(s, "_ecrire_etat", lambda e: ecrits.update(e))
    monkeypatch.setattr(s, "_notifier", lambda t, c, dedup: envoi)
    return ecrits


def test_envoi_confirme_le_ticket_est_retenu(s, monkeypatch):
    ecrits = _armer(s, monkeypatch, [_pos(ticket=7)])
    assert s.main() == 0
    assert ecrits["annonces"] == ["7"]


def test_envoi_RATE_le_ticket_n_est_PAS_retenu(s, monkeypatch):
    """⛔ Une annonce ratée doit être rejouée au passage suivant, pas perdue."""
    ecrits = _armer(s, monkeypatch, [_pos(ticket=7)], envoi=False)
    assert s.main() == 0
    assert ecrits["annonces"] == []


def test_DRY_RUN_n_ecrit_RIEN(s, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "1")
    ecrits = _armer(s, monkeypatch, [_pos(ticket=7)])
    assert s.main() == 0
    assert ecrits == {}


def test_un_bridge_MUET_laisse_l_etat_INTACT(s, monkeypatch):
    """⛔ Illisible ne vaut pas « aucune position au tiers » : le
    franchissement sera vu au passage suivant."""
    ecrits = _armer(s, monkeypatch, None, etat={"annonces": ["7"]})
    assert s.main() == 0
    assert ecrits == {}


def test_un_ticket_FERME_sort_de_la_memoire(s, monkeypatch):
    """Sinon le fichier grossit sans fin et devient illisible."""
    ecrits = _armer(s, monkeypatch, [_pos(ticket=7)],
                    etat={"annonces": ["7", "999_ferme"]})
    assert s.main() == 0
    assert ecrits["annonces"] == ["7"]


# ── Le message ─────────────────────────────────────────────────────────────

def test_le_message_porte_les_montants_ET_le_ticket(s):
    _, corps = s.message(_pos(ticket=4242), s.mesurer(_pos()), 0)
    assert "4242" in corps and "18,00 €" in corps and "52,00 €" in corps


def test_un_montant_non_derivable_est_DIT_pas_invente(s):
    _, corps = s.message(_pos(profit=None), s.mesurer(_pos(profit=None)), 0)
    assert "non dérivable" in corps


def test_les_positions_muettes_sont_dites_dans_le_message(s):
    _, corps = s.message(_pos(), s.mesurer(_pos()), 2)
    assert "2 autre(s) position(s) metal sans objectif" in corps


def test_le_corps_ne_porte_AUCUNE_balise(s):
    """L'endpoint passe le body dans `html.escape` : une balise s'y
    afficherait telle quelle."""
    for muettes in (0, 3):
        _, corps = s.message(_pos(), s.mesurer(_pos()), muettes)
        assert "<" not in corps and ">" not in corps
