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


# --------------------------------------------------------------------------
# Deux poches : 6 % hors or, 14 % pour l'or seul (2026-08-28)
# --------------------------------------------------------------------------
#
# ⛔ Le piège que ces tests ferment : avec un plafond unique de 20 %, une poche
# d'or PLEINE se lirait « 35 % du plafond » et la sonde se tairait. Ce serait
# le refus silencieux qu'elle existe pour rendre visible — sous une mesure qui
# a l'air d'une mesure.


def _or(**kw):
    """Position or, calibrée pour 20 € de risque : profit 4 € pour 4 points de
    mouvement (k = 1), stop à 20 points de l'entrée."""
    base = dict(symbol="XAUUSD", price_open=4450.0, price_current=4454.0,
                sl=4430.0, profit=4.0, ticket=90)
    base.update(kw)
    return _pos(**base)


def test_la_poche_de_l_or_SATUREE_ne_se_dilue_pas_dans_le_forex(s):
    """3 ors à 20 € = 60 € sur 14 % de 552 € (77,28 €) ⇒ 78 %, saturé.

    Le total (60 €) rapporté aux 20 % (110,40 €) donnerait 54 % : silencieux.
    """
    positions = [_or(ticket=t) for t in (91, 92, 93)]
    e = s.evaluer(positions, equity=552.0, plafond_pct=6.0, marge_min_r=1.0,
                  plafond_metaux_pct=14.0)
    assert e["poche"] == "or_argent"
    assert e["pct"] == pytest.approx(77.6, abs=0.5)
    assert s.verdict(e, 72.0) == "sature"


def test_le_forex_VIDE_ne_sauve_pas_une_poche_or_pleine(s):
    """Non-fongibilité, vue depuis la sonde : la poche vide est rapportée à
    part, jamais fondue dans le pourcentage annoncé."""
    e = s.evaluer([_or(ticket=t) for t in (91, 92, 93)], 552.0, 6.0, 1.0,
                  plafond_metaux_pct=14.0)
    assert e["detail_poches"]["autres"]["risque"] == 0.0
    assert e["detail_poches"]["or_argent"]["risque"] == pytest.approx(60.0, abs=0.5)


def test_c_est_la_poche_la_PLUS_saturee_qui_est_annoncee(s):
    """Un forex à 88 % et un or à 26 % : c'est le forex qui refusera."""
    positions = [_pos(ticket=1), _pos(ticket=2), _pos(ticket=3),
                 _pos(ticket=4), _or(ticket=91)]
    e = s.evaluer(positions, equity=552.0, plafond_pct=6.0, marge_min_r=1.0,
                  plafond_metaux_pct=14.0)
    assert e["poche"] == "autres"
    assert e["pct"] > e["detail_poches"]["or_argent"]["pct"]


def test_l_ARGENT_compte_dans_la_poche_des_14_pct(s):
    """Renverse le 28/08 sur mesure : 11,80 EUR de risque pour un 0,01 lot
    d'argent, soit le tiers de la poche des 6 % a lui seul."""
    e = s.evaluer([_or(symbol="XAGUSD", ticket=95)], 552.0, 6.0, 1.0,
                  plafond_metaux_pct=14.0)
    assert e["detail_poches"]["autres"]["risque"] == 0.0
    assert e["detail_poches"]["or_argent"]["risque"] == pytest.approx(20.0,
                                                                      abs=0.5)


def test_le_PLATINE_reste_dans_la_poche_des_6_pct(s):
    """⛔ Nommes un par un : filtrer sur « metal » embarquerait XPT et XPD."""
    e = s.evaluer([_or(symbol="XPTUSD", ticket=96)], 552.0, 6.0, 1.0,
                  plafond_metaux_pct=14.0)
    assert e["detail_poches"]["or_argent"]["risque"] == 0.0
    assert e["detail_poches"]["autres"]["risque"] == pytest.approx(20.0,
                                                                   abs=0.5)


def test_l_ANCIEN_nom_de_champ_est_encore_lu(s):
    """⛔ Entre le deploiement de l'EC2 et celui du VPS, le bridge publie
    encore `max_risque_engage_or_pct`. Ne lire que le nouveau nom ferait
    retomber la sonde a UNE poche EN SILENCE — un pourcentage rassurant et
    faux, exactement ce qu'elle existe pour empecher."""
    import inspect
    source = inspect.getsource(s._lire_destination)
    assert "max_risque_engage_or_argent_pct" in source
    assert "max_risque_engage_or_pct" in source


def test_sans_poche_or_le_comportement_est_INCHANGE(s):
    """`plafond_metaux_pct=0` (ou un vieux bridge qui ne publie rien) doit rendre
    l'état d'avant : une seule poche, tout dedans."""
    positions = [_pos(ticket=1), _or(ticket=91)]
    avant = s.evaluer(positions, 552.0, 6.0, 1.0)
    assert avant["multi_poches"] is False
    assert avant["poche"] == "autres"
    assert avant["risque_total"] == pytest.approx(7.67 + 20.0, abs=0.5)


def test_une_position_NUE_rend_les_DEUX_poches_indecidables(s):
    """Son risque n'est borné dans aucun budget : elle bloque tout, et la
    sonde ne doit surtout pas publier un pourcentage sur l'autre poche."""
    e = s.evaluer([_or(ticket=91), _pos(ticket=2, sl=0.0)], 552.0, 6.0, 1.0,
                  plafond_metaux_pct=14.0)
    assert e["indecidable"] is True
    assert e["pct"] is None
    assert s.verdict(e, 72.0) == "indecidable"


def test_le_message_NOMME_la_poche_saturee(s):
    """« 88 % du plafond » sur un compte à deux poches ne dit pas ce qui est
    fermé — et l'or bouché n'appelle pas la même décision que le forex."""
    e = s.evaluer([_or(ticket=t) for t in (91, 92, 93)], 552.0, 6.0, 1.0,
                  plafond_metaux_pct=14.0)
    e["login"] = 13137475
    e["marge_min_r"] = 1.0
    titre, corps = s._message("admin_live", e, "sature")
    assert "[or_argent]" in titre
    assert "poche <b>or_argent</b>" in corps
    assert "Autre poche <b>autres</b>" in corps


def test_la_regle_des_poches_est_LA_MEME_que_celle_du_bridge(s):
    """⚠️ Règle dupliquée entre deux machines : elle doit être épinglée des
    deux côtés sur les mêmes entrées, comme `sigma_journalier`."""
    import types

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "mt5-bridge" / "bridge.py").read_text(encoding="utf-8")
    # On part des CONSTANTES, pas de la fonction seule : les injecter ici
    # laisserait un renommage cote bridge passer inapercu, alors que c'est
    # precisement ce que ce test doit attraper.
    debut = src.index('_POCHE_OR_ARGENT = ')
    fin = src.index("# MT5 : POSITION_TYPE_BUY")
    mod = types.ModuleType("bridge_poche")
    exec(compile(src[debut:fin], "bridge.py", "exec"), mod.__dict__)

    for symbole in ("XAUUSD", "XAUEUR", "GOLD", "XAGUSD", "SILVER",
                    "XPTUSD", "GBPUSD", "BTCUSD", "", None):
        assert mod._poche_du_symbole(symbole) == s.poche_du_symbole(symbole)
