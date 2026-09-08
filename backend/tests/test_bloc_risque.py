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
    texte = "\n".join(br.lignes(_etat_ok()))
    assert "✅" in texte and "or/argent" in texte


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


def test_le_trade_typique_reste_lie_au_seuil_de_saturation():
    """🔑 `SEUIL_PCT` est DÉRIVÉ de ce chiffre (100 × (1 − 9/plafond) ≈ 67 %).
    Les laisser diverger rendrait l'alerte tardive sans que rien ne le dise."""
    assert br.RISQUE_TRADE_TYPIQUE_EUR == 9.0
