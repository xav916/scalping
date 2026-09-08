"""Le risque du COMPTE dans chaque message de trade (2026-09-08).

Demandé par Xavier : voir, sur chaque courtier, la part du trade dans le risque
engagé, l'engagé global en pourcentage, la marge libre, et si un trade or peut
encore passer.

⛔ Le défaut réparé au passage était VIVANT : la sonde de saturation surveille
`admin_kraken` depuis le 06/09, Kraken rend `risque_ouvert_usd` / `plafond_usd`,
et le formateur écrivait « € ». Des dollars s'affichaient en euros sur le seul
compte dont le plafond est à 50 %.
"""
from __future__ import annotations

import inspect

import pytest

from backend.services import bloc_risque as br


def _code_seul(obj) -> str:
    """La source SANS les lignes de commentaire.

    ⛔ Une recherche naïve trouve mes propres commentaires d'explication — qui
    citent forcément le défaut réparé — et le test crie sur du code juste.
    Leçon d'août, reprise telle quelle.
    """
    lignes = [l for l in inspect.getsource(obj).splitlines()
              if not l.lstrip().startswith("#")]
    return "\n".join(lignes)


def _eval_mt5(**extra) -> dict:
    base = {
        "lisible": True, "indecidable": False, "devise": "EUR",
        "poche": "autres", "multi_poches": True,
        "detail_poches": {
            "autres": {"risque": 20.0, "plafond": 27.0, "pct": 74.1,
                       "candidats": 0, "liberable": 0.0},
            "or_argent": {"risque": 60.0, "plafond": 81.0, "pct": 74.1,
                          "candidats": 0, "liberable": 0.0},
        },
        "risque_total": 20.0, "plafond": 27.0, "pct": 74.1, "restant": 7.0,
        "nues": [], "non_mesurables": [], "positions": 4,
        "candidats": 0, "liberable": 0.0,
    }
    base.update(extra)
    return base


# ── La conversion, au POINT UNIQUE ───────────────────────────────────

def test_les_euros_ne_sont_pas_touches():
    e = br.normaliser_en_eur(_eval_mt5())
    assert e["risque_total"] == 20.0
    assert e["converti"] is False


def test_les_dollars_de_KRAKEN_sont_convertis(monkeypatch):
    """⛔ Le défaut vivant : 100 $ s'affichaient « 100 € »."""
    monkeypatch.setattr(br, "_taux_eur_usd", lambda: (1.25, True))
    e = br.normaliser_en_eur({
        "lisible": True, "devise": "USD", "risque_total": 100.0,
        "plafond": 200.0, "restant": 100.0, "detail_poches": {},
    })
    assert e["risque_total"] == 80.0        # 100 $ / 1,25
    assert e["plafond"] == 160.0
    assert e["devise"] == "EUR"
    assert e["converti"] is True


def test_les_poches_sont_converties_AUSSI():
    """⚠️ Convertir les totaux et oublier le détail donnerait un total juste
    et des poches fausses — la pire des deux, car elle se contredit."""
    e = br.normaliser_en_eur({
        "lisible": True, "devise": "USD", "risque_total": 10.0,
        "detail_poches": {"or_argent": {"risque": 50.0, "plafond": 100.0}},
    })
    q = e["detail_poches"]["or_argent"]
    assert q["risque"] < 50.0 and q["plafond"] < 100.0


def test_sans_taux_on_RETIRE_le_montant_au_lieu_d_en_inventer(monkeypatch):
    """⛔ Un montant faux serait lu comme vrai. `None` ne se lit pas."""
    monkeypatch.setattr(br, "_taux_eur_usd", lambda: (0.0, False))
    e = br.normaliser_en_eur({"lisible": True, "devise": "USD",
                              "risque_total": 100.0, "plafond": 200.0})
    assert e["risque_total"] is None and e["plafond"] is None


def test_un_taux_de_REPLI_se_signale(monkeypatch):
    monkeypatch.setattr(br, "_taux_eur_usd", lambda: (1.155, False))
    e = br.normaliser_en_eur({"lisible": True, "devise": "USD",
                              "risque_total": 10.0})
    assert e["taux_vivant"] is False
    texte = "\n".join(br.lignes({"lisible": True, "engage_eur": 8.7,
                                 "pct": 10.0, "restant_eur": 50.0,
                                 "converti": True, "taux_vivant": False}))
    assert "repli" in texte


# ── Les quatre questions de Xavier ───────────────────────────────────

def _etat_ok(**extra) -> dict:
    base = {"lisible": True, "desarme": False, "indecidable": False,
            "engage_eur": 80.0, "plafond_eur": 27.0, "restant_eur": 7.0,
            "pct": 74.1, "poche": "autres", "positions": 4,
            "metaux": {"libre_eur": 21.0, "pct": 74.1, "plafond_eur": 81.0},
            "converti": False, "taux_vivant": True}
    base.update(extra)
    return base


def test_1_la_part_du_trade_dans_l_engage():
    texte = "\n".join(br.lignes(_etat_ok(), risque_trade_eur=20.0))
    assert "25 %" in texte          # 20 sur 80


def test_2_l_engage_global_en_pourcentage():
    texte = "\n".join(br.lignes(_etat_ok()))
    assert "74 %" in texte


def test_3_la_marge_libre_chez_le_courtier():
    texte = "\n".join(br.lignes(_etat_ok()))
    assert "7,00" in texte


def test_4_un_trade_or_tient_encore():
    """⚠️ Le libellé de la poche se DÉRIVE de l'état (`metaux["nom"]`) depuis
    le 08/09 : elle s'appelle « or » et non plus « or_argent », l'argent en
    étant sorti. Épingler la chaîne referait mentir ce test au prochain
    changement de portée."""
    texte = "\n".join(br.lignes(_etat_ok()))
    assert "✅" in texte
    assert "🥇 Or" in texte and "poche" in texte


def test_4bis_un_trade_or_serait_refuse():
    texte = "\n".join(br.lignes(_etat_ok(metaux={"libre_eur": 2.0,
                                                 "pct": 98.0,
                                                 "plafond_eur": 81.0})))
    assert "REFUSÉ" in texte


def test_l_engage_somme_TOUTES_les_poches_pas_la_plus_tendue():
    """⛔ `risque_total` ne décrit que la poche qui mord. Le prendre pour un
    total rendrait un engagé crédible et amputé — 20 € au lieu de 80 €."""
    e = br.etat.__wrapped__ if hasattr(br.etat, "__wrapped__") else None
    assert e is None                       # pas de décorateur qui masquerait
    ev = br.normaliser_en_eur(_eval_mt5())
    total = sum(d["risque"] for d in ev["detail_poches"].values())
    assert total == 80.0 and ev["risque_total"] == 20.0


# ── Ce qu'on refuse de dire ──────────────────────────────────────────

def test_un_bridge_MUET_ne_rend_pas_zero_pour_cent():
    """⛔ « 0 % » sur un compte injoignable se lit « il reste de la place »."""
    texte = "\n".join(br.lignes({"lisible": False, "motif": "bridge muet"}))
    assert "Illisible" in texte and "on ne sait pas" in texte
    assert "0 %" not in texte


def test_une_position_SANS_STOP_ferme_le_bloc():
    texte = "\n".join(br.lignes(_etat_ok(indecidable=True, nues=2)))
    assert "SANS STOP" in texte
    assert "Marge libre" not in texte      # aucun total rassurant


def test_le_plafond_DESARME_n_est_pas_une_marge_infinie():
    texte = "\n".join(br.lignes(_etat_ok(desarme=True)))
    assert "désarmé" in texte and "Marge libre" not in texte


def test_on_ne_promet_JAMAIS_que_l_or_passera():
    """⛔ La porte de risque est UNE porte. Le 26/08 l'or était bloqué par la
    CORRÉLATION avec une seule position à 0,01 lot : marge large, rien ne
    passait. Dire « l'or passe » serait faux dans ce cas précis."""
    texte = "\n".join(br.lignes(_etat_ok()))
    assert "côté risque" in texte


def test_un_etat_absent_ne_produit_AUCUNE_ligne():
    """⚠️ Le message du trade doit partir même sans état de risque."""
    assert br.lignes(None) == []


# ── Le câblage ───────────────────────────────────────────────────────

def test_les_deux_messages_de_trade_acceptent_l_etat():
    from backend.services import telegram_service as ts
    for f in (ts._format_trade_opened, ts._format_close):
        assert "etat_risque" in inspect.signature(f).parameters, f.__name__


def test_les_envoyeurs_lisent_le_risque_HORS_boucle():
    """⛔ `etat()` fait du réseau bloquant. L'appeler dans le formateur
    figerait l'API à l'instant où un ordre vient de partir."""
    from backend.services import telegram_service as ts
    src = _code_seul(ts._etat_risque_hors_boucle)
    assert "to_thread" in src and "wait_for" in src
    for f in (ts.send_trade_opened, ts.send_close):
        assert "_etat_risque_hors_boucle" in _code_seul(f), f.__name__


def test_les_consommateurs_convertissent_AVANT_d_ecrire_des_euros():
    """⛔ Le test qui compte : sans cet appel, des dollars s'affichent en
    euros. C'était le cas en production jusqu'au 08/09."""
    import backend.app as app
    src_app = _code_seul(app._mesurer_risque_destinations)
    assert "normaliser_en_eur" in src_app

    import io
    sonde = io.open("scripts/notify_saturation_risque.py",
                    encoding="utf-8").read()
    code = "\n".join(l for l in sonde.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "normaliser_en_eur(_lire_destination(dest))" in code


def test_la_commande_risque_couvre_TOUS_les_comptes_de_trading():
    """⛔ Kraken engage de l'argent réel avec le plafond le plus large (50 %)
    et n'était pas dans le champ de `/risque`."""
    import backend.app as app
    assert "admin_kraken" in app._RISQUE_DESTINATIONS
    assert "admin_live" in app._RISQUE_DESTINATIONS


def test_une_part_SUPERIEURE_a_100_pct_est_nommee_pas_corrigee():
    """⛔ Vue en production le 08/09. Le message part dès le fill, et
    `/positions` peut ne pas encore lister la position : l'état lu est alors
    ANTÉRIEUR au trade. « 118 % » est absurde ; ramener à 100 % en silence
    serait pire — cela ferait croire que le total inclut le trade."""
    etat = _etat_ok(engage_eur=6.12, metaux=None)
    texte = "\n".join(br.lignes(etat, risque_trade_eur=7.20))
    assert "pas encore compté" in texte
    assert "118 %" not in texte and "100 %" not in texte


def test_KRAKEN_expose_une_marge_libre():
    """⛔ `_lire_kraken` ne posait jamais `restant` : le bloc n'affichait ni
    marge libre ni verdict sur l'or, précisément sur le compte dont le plafond
    est le plus large (50 %). Une clé absente ne lève pas — elle se lit comme
    « non mesurable »."""
    import inspect

    from scripts import notify_saturation_risque as ns
    src = _code_seul(ns._lire_kraken)
    assert '"restant"' in src, "Kraken ne rend toujours pas de marge libre"
    assert "plafond_usd" in inspect.getsource(ns._lire_kraken)


def test_la_batterie_importe_le_risque_partout_ou_elle_l_emploie():
    """⛔ Défaut que j'ai introduit le 08/09 : `_etat_risque` n'était importé
    que dans `_ouverture`, alors que `_cloture` s'en sert. La batterie mourait
    sur la première clôture — APRÈS avoir affiché « aucune anomalie ».

    🔑 Un `NameError` dans un script qui annonce son propre succès juste avant
    est invisible : c'est le COMPTE des cas rendus (1 au lieu de 6) qui l'a
    dit, jamais le message final.
    """
    import ast
    import io

    src = io.open("scripts/essai_ouverture_bout_en_bout.py",
                  encoding="utf-8").read()
    arbre = ast.parse(src)
    NOM = "_etat_risque"

    importe_au_module = any(
        isinstance(n, ast.ImportFrom)
        and any(a.asname == NOM or a.name == NOM for a in n.names)
        for n in arbre.body)

    for fn in ast.walk(arbre):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        emploie = any(isinstance(n, ast.Name) and n.id == NOM
                      and isinstance(n.ctx, ast.Load)
                      for n in ast.walk(fn))
        if not emploie:
            continue
        importe_ici = any(
            isinstance(n, ast.ImportFrom)
            and any(a.asname == NOM or a.name == NOM for a in n.names)
            for n in ast.walk(fn))
        assert importe_ici or importe_au_module, (
            f"{fn.name}() emploie {NOM} sans l'importer — NameError garanti")


def test_le_trade_typique_reste_lie_au_seuil_de_saturation():
    """🔑 `SEUIL_PCT` est DÉRIVÉ de ce chiffre (100 × (1 − 9/plafond) ≈ 67 %).
    Les laisser diverger rendrait l'alerte tardive sans que rien ne le dise."""
    assert br.RISQUE_TRADE_TYPIQUE_EUR == 9.0


# ── Éteint ≠ muet (2026-09-08) ────────────────────────────────────────

def test_un_compte_ETEINT_ne_casse_PAS_le_total():
    """⛔ Régression introduite le 07/09 en élargissant `/risque` à IBKR :
    le bridge étant débranché, chaque appel rendait « Total impossible ».

    🔑 « On ne sait pas » est la bonne réponse pour un bridge qui DEVRAIT
    répondre. C'est du bruit pour un compte qu'on a choisi d'éteindre — il
    n'engage rien, et zéro est alors la vérité."""
    import backend.app as app

    mesures = [
        {"id": "admin_live", "badge": "💰 Live", "actif": True,
         "evaluation": {"lisible": True, "indecidable": False, "pct": 10.0,
                        "risque_total": 12.0, "plafond": 120.0,
                        "restant": 108.0, "positions": 2,
                        "detail_poches": {}, "candidats": 0, "liberable": 0.0},
         "verdict": "ok"},
        {"id": "admin_ibkr_us", "badge": "💼 IBKR", "actif": False,
         "evaluation": None, "verdict": "eteint"},
    ]
    texte = app._formater_risque(mesures)
    assert "Éteint" in texte
    assert "Total tous comptes" in texte and "impossible" not in texte


def test_un_bridge_MUET_casse_toujours_le_total():
    """⚠️ Le contre-test : sans lui, la correction ci-dessus pourrait avoir
    rendu le total complaisant pour TOUS les cas, y compris celui qu'il doit
    refuser."""
    import backend.app as app

    mesures = [
        {"id": "admin_live", "badge": "💰 Live", "actif": True,
         "evaluation": {"lisible": True, "indecidable": False, "pct": 10.0,
                        "risque_total": 12.0, "plafond": 120.0,
                        "restant": 108.0, "positions": 2,
                        "detail_poches": {}, "candidats": 0, "liberable": 0.0},
         "verdict": "ok"},
        {"id": "admin_kraken", "badge": "🐙 Kraken", "actif": True,
         "evaluation": {"lisible": False}, "verdict": "illisible"},
    ]
    texte = app._formater_risque(mesures)
    assert "impossible" in texte, "un compte muet doit encore refuser le total"


def test_l_activite_se_DEDUIT_jamais_ne_se_declare():
    """🔑 La liste des comptes actifs vient de `admin_destinations()`, qui ne
    construit que ce qui est réellement armé. Un drapeau recopié ici serait à
    repenser — donc à oublier — le jour du rallumage."""
    import backend.app as app
    src = _code_seul(app._mesurer_risque_destinations)
    assert "admin_destinations()" in src
