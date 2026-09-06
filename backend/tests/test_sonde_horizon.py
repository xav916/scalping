"""La sonde qui garde le remplissage de `horizon`.

⛔ Ce qu'elle empêche : l'essai `or-4h-2026-08-26` ne compte que les clôtures
portant `horizon = '4h'`. Si le dispatch cesse de le transmettre dans un cas non
prévu, l'essai **n'accumulera rien** — et un essai qui n'accumule rien ressemble
exactement à un marché calme. On attendrait des mois pour découvrir qu'on a
attendu pour rien.

Les tests portent sur la fonction de décision, pas sur l'envoi : c'est là que
sont les jugements, et c'est ce qui doit rester juste.
"""
from __future__ import annotations

import pytest


def _t(horizon, pair="XAU/USD"):
    return {"pair": pair, "horizon": horizon}


# ── Le régime nominal ─────────────────────────────────────────────────────

def test_aucun_trade_recent_ne_declenche_rien():
    """⚠️ Le silence n'est pas une preuve, mais il n'est pas non plus une
    panne : sans trade, il n'y a rien à juger."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[], essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=0, confirmation_deja_envoyee=False)
    assert v["action"] == "rien"


def test_le_premier_trade_rempli_declenche_la_confirmation():
    """Un détecteur ne se teste pas sur son silence : la sonde doit dire au
    moins une fois que la chaîne fonctionne."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h"), _t("4h")], essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=0, confirmation_deja_envoyee=False)
    assert v["action"] == "confirmation"
    assert v["remplis"] == 2


def test_apres_confirmation_la_sonde_se_tait_quand_tout_va_bien():
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h"), _t("1h")], essai_n_obs=3, essai_min=60,
              clotures_or_depuis_declaration=3, confirmation_deja_envoyee=True)
    assert v["action"] == "rien"


# ── La régression ─────────────────────────────────────────────────────────

def test_un_trade_sans_horizon_est_une_regression():
    """⛔ C'est le point de rupture le plus probable de toute la chaîne."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h"), _t(None), _t(None)], essai_n_obs=1, essai_min=60,
              clotures_or_depuis_declaration=1, confirmation_deja_envoyee=True)
    assert v["action"] == "alerte"
    assert v["manquants"] == 2
    assert "horizon" in v["message"].lower()


def test_la_regression_prime_sur_la_confirmation():
    """Si la toute première fenêtre contient déjà des trous, c'est l'alerte qui
    part — pas un message rassurant suivi d'un silence."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h"), _t(None)], essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=0, confirmation_deja_envoyee=False)
    assert v["action"] == "alerte"


# ── L'essai qui n'accumule pas ────────────────────────────────────────────

def test_de_l_or_qui_cloture_sans_rien_nourrir_alerte():
    """⛔ Le cas qui ressemble le plus à un marché calme : l'or trade, l'essai
    reste à zéro. Sans ce contrôle, personne ne le verrait avant des mois."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h")], essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=12, confirmation_deja_envoyee=True)
    assert v["action"] == "alerte"
    assert "n'accumule" in v["message"] or "accumule" in v["message"]


def test_peu_de_clotures_or_ne_suffit_pas_a_crier():
    """En dessous du seuil, l'absence d'accumulation peut n'être que la lenteur
    normale du 4 h. Crier là-dessus rendrait la sonde inaudible."""
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h")], essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=2, confirmation_deja_envoyee=True)
    assert v["action"] == "rien"


def test_un_essai_qui_avance_ne_declenche_rien():
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t("4h")], essai_n_obs=9, essai_min=60,
              clotures_or_depuis_declaration=12, confirmation_deja_envoyee=True)
    assert v["action"] == "rien"


# ── Le message ────────────────────────────────────────────────────────────

def test_le_message_dit_quoi_faire_pas_seulement_ce_qui_ne_va_pas():
    from scripts.notify_horizon_rempli import juger

    v = juger(recents=[_t(None)] * 4, essai_n_obs=0, essai_min=60,
              clotures_or_depuis_declaration=0, confirmation_deja_envoyee=True)
    assert v["action"] == "alerte"
    assert "mt5_pushes" in v["message"], "le message doit nommer où regarder"


# ── Le contrat d'envoi ────────────────────────────────────────────────────
#
# ⛔ Défaut trouvé le 26/08 en prouvant que l'alerte ARRIVE, et pas seulement
# qu'elle part : la sonde postait son texte sous la clé `message`, quand
# l'endpoint lit `body`. Mesuré sur la production — `{"message": ...}` rend
# `chars: 10`, soit le TITRE SEUL. L'alerte serait arrivée vide de son contenu,
# et rien ne l'aurait signalé.

def test_le_texte_part_sous_la_cle_body(monkeypatch):
    """La clé attendue par l'endpoint est `body`. `message` est silencieusement
    ignorée — le pire des deux comportements possibles."""
    import json
    from scripts import notify_horizon_rempli as sonde

    captures = {}

    class _Rep:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _faux_urlopen(rq, timeout=None):
        captures["charge"] = json.loads(rq.data.decode("utf-8"))
        return _Rep()

    monkeypatch.setattr(sonde.urllib.request, "urlopen", _faux_urlopen)
    monkeypatch.delenv("DRY_RUN", raising=False)
    sonde.envoyer("Un titre", "Un corps qui doit arriver en entier.")

    assert "body" in captures["charge"], "l'endpoint lit `body`, pas `message`"
    assert captures["charge"]["body"] == "Un corps qui doit arriver en entier."


def test_les_messages_ne_contiennent_pas_de_balises():
    """⛔ Le corps est `html.escape`é côté serveur : une balise n'y est pas
    interprétée, elle s'affiche telle quelle. Mesuré : un corps `AB<b>CD</b>`
    de 11 caractères en pèse 23 une fois échappé."""
    from scripts.notify_horizon_rempli import juger

    cas = [
        juger([{"pair": "XAU/USD", "horizon": None}], 0, 60, 0, True),
        juger([{"pair": "XAU/USD", "horizon": "4h"}], 0, 60, 12, True),
        juger([{"pair": "XAU/USD", "horizon": "4h"}], 0, 60, 0, False),
    ]
    for v in cas:
        assert "<" not in v["message"] and ">" not in v["message"], \
            f"balise dans : {v['message'][:60]}"


# ── Un essai clos ne doit plus faire crier (2026-09-06) ───────────────────
#
# ⛔ L'essai `or-4h-2026-08-26` est resté à 0/60 pendant onze jours : l'or a
# clôturé 39 fois, toutes en `5min` ou sans horizon, jamais en `4h` — parce
# que ses motifs ont été élargis à tous les horizons le 26/08, le jour même où
# l'essai a été déclaré. Les deux décisions travaillaient l'une contre l'autre.
#
# 🔑 Une fois l'essai abandonné, continuer de crier « il n'accumule rien » est
# le bruit exact qu'on cherche à supprimer — celui qui finit par faire ignorer
# les vraies alertes.

def test_un_essai_ABANDONNE_est_traite_comme_absent(monkeypatch):
    import importlib.util
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "notify_horizon_rempli.py")
    spec = importlib.util.spec_from_file_location("horizon_clos", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _RB:
        @staticmethod
        def get_trial(slug):
            return {"status": "abandoned", "selector": {}, "declared_at": "2026-08-26",
                    "min_sample": 60}

    import sys
    faux = type(sys)("backend.services.research_bench")
    faux.get_trial = _RB.get_trial
    monkeypatch.setitem(sys.modules, "backend.services.research_bench", faux)

    assert mod.etat_essai() == (0, 0, None), (
        "un essai abandonné doit être vu comme absent, sinon la sonde crie "
        "sur un essai que personne n'alimente plus")


def test_sans_essai_declare_aucune_cloture_or_n_est_comptee():
    """⛔ `clotures_or_depuis(None)` doit rendre 0 : sans déclaration, il n'y a
    pas de fenêtre à mesurer, donc pas d'alerte « n'accumule rien »."""
    import importlib.util
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "notify_horizon_rempli.py")
    spec = importlib.util.spec_from_file_location("horizon_sans", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.clotures_or_depuis(None) == 0
