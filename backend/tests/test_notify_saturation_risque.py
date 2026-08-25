"""Le plafond de risque est-il sur le point de fermer l'admission ? (2026-08-23)

Mesuré ce jour-là : le démo était à **89,3 %** du plafond des 6 % et le réel à
**85,7 %**, avec 3,37 € et 4,79 € de marge restante — pour des trades qui en
risquent 7 à 9. **Le prochain signal était refusé des deux côtés**, et ce
chiffre n'était lisible nulle part : ni dans `/health`, ni par Telegram. Il
fallait le calculer à la main pour savoir que l'admission était fermée.

Ce que ces tests verrouillent, ce sont les façons dont cette sonde pourrait
mentir :

1. ⛔ **un bridge muet ne vaut PAS « 0 % de saturation »** — ce serait
   rassurant et faux, le sort exact du moniteur muet pendant trois mois.
   `None` et un pourcentage sont deux verdicts distincts ;
2. ⛔ **une position dont on ne sait pas dériver le risque ne compte pas pour
   zéro** — elle rabaisserait le total et cacherait la saturation ;
3. ⛔ **une position SANS STOP rend le total indécidable** : son risque n'est
   pas borné, donc aucune somme n'a de sens. Annoncer « 85 % » à côté d'une
   position nue serait une mesure inventée ;
4. la **transition** doit être détectée dans les deux sens, sinon on alerte
   en boucle ou on ne dit jamais que c'est rentré dans l'ordre.

⚠️ Le risque en devise se **dérive du profit rapporté** (`profit = (courant −
entrée) × k`), sans dépendre du tick value : vérifié au centime près contre
les positions réelles du 23/08.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "notify_saturation_risque.py")


@pytest.fixture()
def s():
    spec = importlib.util.spec_from_file_location("saturation", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pos(symbol="GBPUSD", type_="buy", price_open=1.36012, price_current=1.36418,
         sl=1.35117, profit=3.48, ticket=1, volume=0.01):
    return {"ticket": ticket, "symbol": symbol, "type": type_, "volume": volume,
            "price_open": price_open, "price_current": price_current,
            "sl": sl, "tp": 0.0, "profit": profit}


# --------------------------------------------------------------------------
# Dériver le risque sans tick value
# --------------------------------------------------------------------------

def test_le_cas_REEL_du_23_08(s):
    """GBPUSD ticket 1355154354 : profit 3,48 € pour 0,00406 de mouvement.
    Distance au stop 0,00895 ⇒ risque 7,67 €. Mesuré en production."""
    m = s.mesurer_position(_pos())
    assert m["risque"] == pytest.approx(7.67, abs=0.01)
    assert m["marge_r"] == pytest.approx(0.45, abs=0.01)
    assert m["nue"] is False


def test_une_VENTE_est_mesuree_dans_le_bon_sens(s):
    """Vente gagnante : le prix a BAISSE, le profit est positif."""
    v = _pos(type_="sell", price_open=1.10000, price_current=1.09500,
             sl=1.10500, profit=5.0)
    m = s.mesurer_position(v)
    assert m["risque"] == pytest.approx(5.0, abs=0.01)
    assert m["marge_r"] == pytest.approx(1.0, abs=0.01)


def test_une_position_EN_PERTE_a_une_marge_negative(s):
    p = _pos(price_current=1.35800, profit=-1.82)
    assert s.mesurer_position(p)["marge_r"] < 0


# --------------------------------------------------------------------------
# ⛔ Les zéros qui mentiraient
# --------------------------------------------------------------------------

def test_position_SANS_STOP_nue_jamais_risque_zero(s):
    """Une position nue est un risque INFINI, pas nul."""
    m = s.mesurer_position(_pos(sl=0.0))
    assert m["nue"] is True
    assert m["risque"] is None


def test_position_pile_a_son_prix_d_entree_est_NON_MESURABLE(s):
    """Le facteur se dérive du profit : à mouvement nul il est indéfini.
    ⛔ Rendre 0.0 rabaisserait le total et cacherait la saturation."""
    m = s.mesurer_position(_pos(price_current=1.36012, profit=0.0))
    assert m["nue"] is False
    assert m["risque"] is None


def test_un_champ_illisible_ne_vaut_pas_zero(s):
    assert s.mesurer_position(_pos(profit="x"))["risque"] is None
    assert s.mesurer_position(_pos(price_open=None))["risque"] is None


# --------------------------------------------------------------------------
# L'agrégat
# --------------------------------------------------------------------------

def test_la_saturation_des_deux_comptes_le_23_08(s):
    """Le réel : 4 positions, 28,75 € engagés sur 33,54 € de plafond."""
    positions = [
        _pos(ticket=1, profit=3.48),
        _pos(ticket=2, price_open=1.36073, sl=1.35183, profit=2.96),
        _pos(ticket=3, symbol="EURGBP", price_open=0.85845, price_current=0.85563,
             sl=0.85464, profit=-3.30),
        _pos(ticket=4, symbol="GBPJPY", price_open=216.999, price_current=216.870,
             sl=215.344, profit=-0.70),
    ]
    e = s.evaluer(positions, equity=558.94, plafond_pct=6.0, marge_min_r=1.0)
    assert e["lisible"] is True
    assert e["plafond"] == pytest.approx(33.54, abs=0.01)
    assert e["risque_total"] == pytest.approx(28.75, abs=0.15)
    assert 84 < e["pct"] < 88
    assert e["candidats"] == 0, "aucune position n'atteignait 1 R"
    assert e["liberable"] == pytest.approx(0.0)


# --------------------------------------------------------------------------
# ⛔ La sonde doit appliquer LA MEME regle que le bridge (2026-08-24)
#
# Elle annoncait 2 candidats sur le demo et 1 sur le reel en n'appliquant que
# le seuil en R. Le bridge, lui, applique AUSSI la porte de bruit en σ depuis
# le 24/08 — et sous cette porte, AUCUN des trois ne passait :
#
#     DEMO USDJPY 85119920    acquis 0,766     1 σ = 1,178   NON
#     DEMO USDJPY 85480095    acquis 0,358     1 σ = 1,178   NON
#     REEL GBPUSD 1355176392  acquis 0,00221   1 σ = 0,00447 NON
#
# > **Une sonde qui n'applique pas la regle qu'elle decrit annonce du budget
# > liberable qui n'existe pas.** C'est pire qu'une sonde muette : elle
# > pousserait a compter sur une soupape qui ne se declenchera pas.
#
# ⚠️ La formule de σ est DUPLIQUEE entre le bridge et la sonde — ils tournent
# sur des machines differentes et ne peuvent pas partager de code a
# l'execution. Les tests ci-dessous epinglent la formule des DEUX cotes sur
# les memes entrees ; toute derive les fait tomber.
# --------------------------------------------------------------------------

def test_un_flux_QUASI_GELE_rend_None_pas_un_sigma_minuscule(s):
    """⛔ Le trou que ce test a trouve.

    Une serie a croissance parfaitement reguliere (rendement log constant) a
    une variance nulle en theorie, et ~1e-16 en flottant. Le sigma sort donc
    minuscule mais POSITIF — et `acquis >= 1,0 × sigma` devient trivialement
    vrai : **toute position deviendrait eligible**. Fail-OPEN, exactement
    l'inverse du but de cette porte.

    Un flux gele ou casse doit rendre `None`, comme une volatilite inconnue.
    """
    clotures = [100.0 * (1.001 ** i) for i in range(200)]
    assert s.sigma_journalier(clotures) is None


def test_sigma_sur_une_serie_a_volatilite_connue(s):
    """Alternance +1 %/−1 % : l'ecart-type des rendements log vaut ln(1,01)."""
    import math
    clotures = [100.0]
    for i in range(200):
        clotures.append(clotures[-1] * (1.01 if i % 2 == 0 else 1 / 1.01))
    attendu = math.log(1.01) * math.sqrt(24.0) * clotures[-1]
    assert s.sigma_journalier(clotures) == pytest.approx(attendu, rel=0.02)


def test_trop_peu_de_bougies_rend_None(s):
    """⛔ Jamais une valeur calculee sur un echantillon trop mince : elle
    servirait a decider quand meme."""
    assert s.sigma_journalier([100.0 + i for i in range(50)]) is None
    assert s.sigma_journalier([]) is None
    assert s.sigma_journalier(None) is None


def test_le_cas_REEL_du_24_08_aucun_candidat_sous_la_porte_sigma(s):
    """Les trois positions que la sonde annoncait candidates a tort."""
    p = _pos(price_open=158.459, price_current=159.225, sl=157.859,
             profit=4.12, symbol="USDJPY")
    e = s.evaluer([p], equity=524.05, plafond_pct=6.0, marge_min_r=0.40,
                  sigmas=lambda _: 1.178, marge_min_sigma=1.0)
    assert e["candidats"] == 0, "0,766 acquis < 1,178 de bruit"


def test_sans_porte_sigma_le_comportement_est_INCHANGE(s):
    """`marge_min_sigma=0` doit rendre exactement l'ancien resultat."""
    p = _pos(price_open=1.10000, price_current=1.10500, sl=1.09500, profit=5.0)
    assert s.evaluer([p], 1000.0, 6.0, 1.0)["candidats"] == 1
    assert s.evaluer([p], 1000.0, 6.0, 1.0,
                     sigmas=lambda _: None, marge_min_sigma=0.0)["candidats"] == 1


def test_volatilite_inconnue_ECARTE_le_candidat(s):
    """⛔ Meme choix fail-closed que le bridge : ne pas annoncer liberable ce
    qu'on ne sait pas juger."""
    p = _pos(price_open=1.10000, price_current=1.10500, sl=1.09500, profit=5.0)
    e = s.evaluer([p], 1000.0, 6.0, 1.0,
                  sigmas=lambda _: None, marge_min_sigma=1.0)
    assert e["candidats"] == 0 and e["liberable"] == pytest.approx(0.0)


def test_une_position_a_1R_est_candidate_seuil_INCLUSIF(s):
    p = _pos(price_open=1.10000, price_current=1.10500, sl=1.09500, profit=5.0)
    e = s.evaluer([p], equity=1000.0, plafond_pct=6.0, marge_min_r=1.0)
    assert e["candidats"] == 1
    assert e["liberable"] == pytest.approx(5.0, abs=0.01)


def test_une_position_a_099R_n_est_PAS_candidate(s):
    p = _pos(price_open=1.10000, price_current=1.10495, sl=1.09500, profit=4.95)
    assert s.evaluer([p], 1000.0, 6.0, 1.0)["candidats"] == 0


def test_une_position_NUE_rend_le_total_INDECIDABLE(s):
    """⛔ Annoncer un pourcentage a cote d'un risque non borne serait une
    mesure inventee. Et l'admission est fermee de toute facon."""
    e = s.evaluer([_pos(), _pos(ticket=2, sl=0.0)], 558.94, 6.0, 1.0)
    assert e["nues"] == 1
    assert e["pct"] is None
    assert e["indecidable"] is True


def test_une_position_non_mesurable_est_COMPTEE_a_part(s):
    e = s.evaluer([_pos(), _pos(ticket=2, price_current=1.36012, profit=0.0)],
                  558.94, 6.0, 1.0)
    assert e["non_mesurables"] == 1
    assert e["indecidable"] is True, "on ne conclut pas sur un total amoindri"


def test_aucune_position_est_lisible_et_a_zero(s):
    """Zero position est une vraie mesure, pas un trou."""
    e = s.evaluer([], 558.94, 6.0, 1.0)
    assert e["lisible"] is True and e["pct"] == pytest.approx(0.0)
    assert e["indecidable"] is False


def test_equity_nulle_ne_divise_pas_par_zero(s):
    e = s.evaluer([_pos()], 0.0, 6.0, 1.0)
    assert e["indecidable"] is True and e["pct"] is None


# --------------------------------------------------------------------------
# ⛔ Muet n'est pas sain
# --------------------------------------------------------------------------

def test_lecture_ratee_n_est_PAS_une_saturation_de_zero(s):
    """Le sort du moniteur muet : une absence lue comme un « tout va bien »."""
    e = s.evaluation_illisible()
    assert e["lisible"] is False
    assert e["pct"] is None
    assert s.verdict(e, seuil_pct=85.0) == "illisible"


def test_verdict_sature_au_dessus_du_seuil(s):
    assert s.verdict({"lisible": True, "indecidable": False, "pct": 89.3},
                     seuil_pct=85.0) == "sature"


def test_le_seuil_est_inclusif(s):
    assert s.verdict({"lisible": True, "indecidable": False, "pct": 85.0},
                     seuil_pct=85.0) == "sature"


def test_verdict_ok_sous_le_seuil(s):
    assert s.verdict({"lisible": True, "indecidable": False, "pct": 40.0},
                     seuil_pct=85.0) == "ok"


def test_verdict_indecidable_prime_sur_le_pourcentage(s):
    assert s.verdict({"lisible": True, "indecidable": True, "pct": None},
                     seuil_pct=85.0) == "indecidable"


# --------------------------------------------------------------------------
# La transition — ni boucle, ni silence
# --------------------------------------------------------------------------

def test_franchir_le_seuil_DECLENCHE(s):
    assert s.doit_parler("ok", "sature") is True


def test_rester_sature_ne_re_declenche_pas_le_cooldown_s_en_charge(s):
    """Le cooldown cote serveur borne la repetition ; ici on note juste que
    ce n'est plus une TRANSITION."""
    assert s.doit_parler("sature", "sature") is True


def test_revenir_sous_le_seuil_est_ANNONCE(s):
    """Sinon on ne sait jamais que c'est rentre dans l'ordre."""
    assert s.doit_parler("sature", "ok") is True


def test_rester_sain_reste_SILENCIEUX(s):
    assert s.doit_parler("ok", "ok") is False


def test_premier_passage_sain_est_silencieux(s):
    assert s.doit_parler(None, "ok") is False


def test_premier_passage_sature_PARLE(s):
    assert s.doit_parler(None, "sature") is True


# --------------------------------------------------------------------------
# ⛔ Le seuil a DEUX sources — elles doivent rester d'accord
# --------------------------------------------------------------------------

_ENVELOPPE = (pathlib.Path(__file__).resolve().parents[2]
              / "scripts" / "notify-saturation-risque.sh")


def _defaut_python(monkeypatch) -> float:
    """Le seuil que prend le module quand rien n'est imposé par l'env."""
    monkeypatch.delenv("SEUIL_SATURATION_PCT", raising=False)
    spec = importlib.util.spec_from_file_location("saturation_defaut", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SEUIL_PCT


def _defaut_enveloppe() -> float:
    m = re.search(r"SEUIL_SATURATION_PCT=\$\{SEUIL_SATURATION_PCT:-([0-9.]+)\}",
                  _ENVELOPPE.read_text(encoding="utf-8"))
    assert m, "l'enveloppe cron ne fixe plus de seuil par défaut"
    return float(m.group(1))


def test_le_cron_et_la_commande_a_la_demande_partagent_LE_MEME_seuil(monkeypatch):
    """⛔ Deux sources, deux vérités — le piège qu'on referme ici.

    L'enveloppe cron passe `docker exec -e SEUIL_SATURATION_PCT=…`, ce qui
    **écrase** l'environnement du conteneur. La commande `risque` à la
    demande, elle, lit le défaut du module. Régler l'un sans l'autre ferait
    alerter le cron à un seuil pendant que l'emoji de la réponse
    instantanée bascule à un autre — deux chiffres qui se contredisent sans
    que rien ne le dise.
    """
    assert _defaut_python(monkeypatch) == _defaut_enveloppe()
