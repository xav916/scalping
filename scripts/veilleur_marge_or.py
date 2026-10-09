#!/usr/bin/env python3
"""Pourquoi l'or automatique dort-il ? DIRE la mesure, ne pas desserrer.

    python scripts/veilleur_marge_or.py
    python scripts/veilleur_marge_or.py --essai    # n'envoie rien
    python scripts/veilleur_marge_or.py --bilan    # dit l'etat quoi qu il arrive

## ⛔ POURQUOI IL EXISTE

Le 2026-10-09, Xavier a demande pourquoi aucun ordre d'or automatique ne
partait, puis : « tu dois faire avec les 2 trades en cours ». Rien n'etait
casse. L'interrupteur etait arme, les signaux sortaient, les portes faisaient
leur tri. Le compte ne pouvait simplement pas porter une position de plus.

🔑 ET CE N'EST PAS LE COURTIER QUI REFUSAIT. Sa propre simulation
(`/order_check`) rendait `retcode 0`, commentaire « Done » : il acceptait
l'ordre. C'est NOTRE plancher `MARGE_LIBRE_MIN_PCT = 30` qui le refusait, pour
garder de la distance avec la liquidation — le niveau de marge serait tombe a
140 %.

⇒ Un refus parfaitement justifie, parfaitement invisible. Il fallait une
MESURE a lire, pas une porte a desserrer.

## L'arithmetique

Une position d'or a 0,01 lot coute ~186,75 EUR de marge (mesure : 373,49 pour
deux). Le plancher exige `marge libre apres ordre >= pct x equite`, donc :

    equite - N x marge_par_position >= pct x equite
       <=>  equite >= N x marge_par_position / (1 - pct)

    N=1 ->  266,78 EUR      N=2 ->  533,56 EUR      N=3 ->  800,34 EUR

🔑 Le lot est DEJA au minimum (`volume_min` et `volume_step` tous deux a 0,01).
La seule variable qui ne touche aucune porte est l'EQUITE.

## Mode EVENEMENT

Muet quand l'or peut passer. La cle de dedup porte l'IDENTITE du blocage : il
parle quand le blocage CHANGE, pas a chaque passage — les positions de Xavier
tournent toutes les quelques minutes, et une alerte repetee n'est plus lue
(lecon des 8 doublons du 07/10).

⛔ Un compte ILLISIBLE n'est PAS un compte qui passe : on alerte aussi.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/app")

# Assez long pour ne pas harceler, assez court pour qu'un blocage ne dure pas
# une seance entiere sans etre dit.
COOLDOWN_SEC = int(os.environ.get("MARGE_OR_COOLDOWN_SEC", "1800"))

# ⛔ VALEUR MESUREE, PAS SUPPOSEE : 373,49 EUR de marge pour deux positions
# d'or a 0,01 lot sur le compte reel IC Markets le 2026-10-09 (levier metaux
# 20:1, or a ~4185). Elle ne sert QUE de repli quand aucune position n'est
# ouverte — `margin / 0` n'existe pas — et le veilleur dit alors qu'il s'agit
# d'un repli.
MARGE_PAR_POSITION_MESUREE = 186.745

_ETIQUETTES = {
    "marge": "plancher de marge libre",
    "plafond_journalier": "plafond de perte journaliere",
    "mesure_absente": "mesure absente",
}


# ─── La mesure ───────────────────────────────────────────────────────────

def marge_par_position_et_origine(compte: dict) -> tuple[float, bool]:
    """``(marge_unitaire, mesuree_maintenant)``.

    ⛔ On DIVISE ce que le courtier declare plutot que de coder une constante :
    la marge d'une once d'or bouge avec le prix. Le repli est etiquete pour
    qu'une valeur d'hier ne passe jamais pour une mesure du moment.
    """
    try:
        n = int(compte.get("positions_count") or 0)
        marge = float(compte.get("margin") or 0.0)
    except (TypeError, ValueError):
        return (MARGE_PAR_POSITION_MESUREE, False)
    if n >= 1 and marge > 0:
        return (marge / n, True)
    return (MARGE_PAR_POSITION_MESUREE, False)


def marge_par_position(compte: dict) -> float:
    return marge_par_position_et_origine(compte)[0]


def equite_requise(n: int, marge_unitaire: float, plancher_pct: float) -> float:
    """Equite minimale pour porter `n` positions sous ce plancher."""
    reste = 1.0 - plancher_pct / 100.0
    if reste <= 0:
        return float("inf")
    return n * marge_unitaire / reste


def diagnostic(compte: dict | None, gardes: dict) -> dict:
    """Un ordre d'or a 0,01 lot passerait-il MAINTENANT ? Et sinon, pourquoi.

    ⚠️ Ne juge que ce qu'il peut MESURER : le plancher de marge et le plafond
    journalier, tous deux publies par le pont. Les portes du radar (motif,
    horizon, chaine) ne sont pas ici — elles refusent un signal donne, pas la
    capacite du compte.
    """
    if not compte:
        return {
            "verdict": "ILLISIBLE",
            "blocage": "mesure_absente",
            "detail": "le /account du pont n'a pas repondu",
            "positions_ouvertes": None,
            "equite": None,
            "equite_requise": None,
            "manque_euros": None,
        }

    equite = float(compte.get("equity") or 0.0)
    libre = float(compte.get("margin_free") or 0.0)
    n_ouvertes = int(compte.get("positions_count") or 0)
    unitaire, mesuree = marge_par_position_et_origine(compte)
    plancher_pct = float(gardes.get("marge_libre_min_pct") or 0.0)

    base = {
        "positions_ouvertes": n_ouvertes,
        "equite": round(equite, 2),
        "marge_par_position": round(unitaire, 2),
        "marge_mesuree": mesuree,
        "marge_libre": round(libre, 2),
        "plancher_pct": plancher_pct,
        "equite_requise": None,
        "manque_euros": None,
        "detail": "",
    }

    # ─── Porte 1 : le plancher de marge libre ────────────────────────────
    # `plancher_pct <= 0` desarme la porte cote pont (cf. `bridge.py`) : on lit
    # le MEME reglage, sinon on annoncerait un blocage qui n'existe pas.
    if plancher_pct > 0:
        requise = equite_requise(n_ouvertes + 1, unitaire, plancher_pct)
        base["equite_requise"] = round(requise, 2)
        plancher = equite * plancher_pct / 100.0
        restant = libre - unitaire
        if restant < plancher:
            base["manque_euros"] = round(max(requise - equite, 0.0), 2)
            base["detail"] = (
                f"marge libre apres ordre {restant:.2f} < plancher "
                f"{plancher:.2f} ({plancher_pct:.0f} % de {equite:.2f})")
            return {**base, "verdict": "BLOQUE", "blocage": "marge"}

    # ─── Porte 2 : le plafond journalier du courtier ─────────────────────
    # ⚠️ Annoncer « ca passe » alors que celle-ci refuse serait une fausse
    # bonne nouvelle. On nomme le blocage SUIVANT.
    perte = gardes.get("daily_loss")
    limite = gardes.get("daily_loss_limit")
    if perte is not None and limite is not None and float(perte) >= float(limite):
        base["detail"] = (f"perte du jour {float(perte):.2f} >= plafond "
                          f"{float(limite):.2f}")
        return {**base, "verdict": "BLOQUE", "blocage": "plafond_journalier"}

    return {**base, "verdict": "PASSE", "blocage": None}


# ─── Le message ──────────────────────────────────────────────────────────

def cle_dedup(d: dict) -> str:
    """🔑 Porte l'IDENTITE du blocage, pas l'instant.

    C'est ce qui rend le veilleur discret : le MEME blocage rend la MEME cle,
    donc le cooldown mord ; un blocage DIFFERENT rend une cle differente, donc
    le changement se dit tout de suite. Les positions de Xavier tournent toutes
    les quelques minutes — une cle qui bougerait avec elles produirait le
    harcelement qu'on veut eviter.
    """
    return f"marge_or:{d.get('blocage') or 'passe'}:{d.get('positions_ouvertes')}"


def corps(d: dict) -> str:
    if d["verdict"] == "ILLISIBLE":
        return ("⛔ Impossible de LIRE le compte réel (le `/account` du pont "
                "n'a pas répondu).\n\n"
                "Ce n'est pas « tout va bien » : c'est une absence de mesure. "
                "Aucune garantie qu'un ordre puisse partir.")

    lignes = [
        f"• Positions ouvertes : **{d['positions_ouvertes']}**",
        f"• Équité : **{d['equite']:.2f} €**",
        f"• Marge par position d'or (0,01 lot) : {d['marge_par_position']:.2f} €"
        + ("" if d["marge_mesuree"] else " _(repli mesuré, aucune position ouverte)_"),
    ]

    if d["blocage"] == "marge":
        lignes += [
            "",
            f"🛑 **Bloqué par le plancher de marge** ({d['plancher_pct']:.0f} %).",
            f"• {d['detail']}",
            f"• Il faudrait **{d['equite_requise']:.2f} €** d'équité pour "
            f"{d['positions_ouvertes'] + 1} positions — il manque "
            f"**{d['manque_euros']:.2f} €**.",
            "",
            "🔑 **Le courtier, lui, accepte l'ordre** (`/order_check` → "
            "`retcode 0`, « Done »). C'est **notre** plancher de 30 % qui "
            "refuse, pour garder de la distance avec la liquidation.",
            "",
            "Le lot est déjà au minimum (0,01, et le pas vaut 0,01) : rien "
            "n'existe en dessous. La seule variable qui ne touche aucune "
            "porte est l'**équité** — soit en fermant une position, soit en "
            "la faisant monter.",
        ]
    elif d["blocage"] == "plafond_journalier":
        lignes += [
            "",
            "🛑 **La marge passe, mais le plafond journalier refuse.**",
            f"• {d['detail']}",
            "",
            "Réponds `CONTINUER` à l'arbitrage pour lever la porte — à "
            "condition qu'un créneau d'or soit libre.",
        ]
    elif d["blocage"] == "mesure_absente":
        lignes += ["", "🛑 Mesure absente."]
    else:
        lignes += [
            "",
            "✅ **Un ordre d'or automatique peut partir** : plancher de marge "
            "et plafond journalier passent tous les deux.",
            "",
            "_Les portes du radar (motif, horizon, chaîne) restent "
            "souveraines sur chaque signal — ceci dit seulement que le COMPTE "
            "en a la capacité._",
        ]
    return "\n".join(lignes)


def titre(d: dict) -> str:
    return {
        "marge": "🛑 Or automatique bloqué — plancher de marge",
        "plafond_journalier": "🛑 Or automatique bloqué — plafond journalier",
        "mesure_absente": "⛔ Compte réel ILLISIBLE",
    }.get(d.get("blocage"), "✅ Or automatique : le compte a la capacité")


# ─── La lecture et l'envoi ───────────────────────────────────────────────

def _lire() -> tuple[dict | None, dict]:
    """``(compte, garde_fous)`` lus CHEZ LE PONT. Jamais devines."""
    import httpx
    base = (os.getenv("MT5_BRIDGE_LIVE_URL", "") or "").rstrip("/")
    cle = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "") or ""
    if not base:
        return (None, {})
    compte = None
    gardes: dict = {}
    try:
        r = httpx.get(base + "/account", headers={"X-API-Key": cle}, timeout=10)
        if r.status_code == 200:
            compte = r.json()
    except Exception as e:  # noqa: BLE001
        print(f"   /account illisible ({type(e).__name__}: {e})")
    try:
        r = httpx.get(base + "/health", timeout=10)
        if r.status_code == 200:
            gardes = r.json().get("garde_fous", {}) or {}
    except Exception as e:  # noqa: BLE001
        print(f"   /health illisible ({type(e).__name__}: {e})")
    return (compte, gardes)


def _prevenir(d: dict) -> bool:
    from backend.services.canaux_telegram import canal_pour, notifier
    # `canal_pour(None)` -> le fil infra : la capacite du compte est un fait
    # d'infrastructure, pas une position.
    return notifier(canal_pour(None), titre(d), corps(d), timeout=15,
                    dedup_key=cle_dedup(d), cooldown_seconds=COOLDOWN_SEC)


def main() -> int:
    essai = "--essai" in sys.argv
    bilan = "--bilan" in sys.argv

    compte, gardes = _lire()
    d = diagnostic(compte, gardes)

    print(f"marge or : {d['verdict']}"
          + (f" ({_ETIQUETTES.get(d['blocage'], d['blocage'])})"
             if d["blocage"] else ""))
    if d["verdict"] != "ILLISIBLE":
        print(f"   {d['positions_ouvertes']} position(s), equite "
              f"{d['equite']:.2f}, marge libre {d['marge_libre']:.2f}")
        if d.get("equite_requise"):
            print(f"   equite requise {d['equite_requise']:.2f}"
                  + (f", il manque {d['manque_euros']:.2f}"
                     if d.get("manque_euros") else ""))
        if d["detail"]:
            print(f"   {d['detail']}")

    if bilan:
        ok = _prevenir({**d, "_bilan": True}) if not essai else True
        print(f"   bilan {'envoye' if ok else 'ECHEC'}")
        return 0 if ok else 1

    if d["verdict"] == "PASSE":
        print("   rien a dire")
        return 0

    if essai:
        print("   (--essai : rien envoye)")
        return 0

    ok = _prevenir(d)
    # ⚠️ FORMULATION VOLONTAIREMENT PRUDENTE. `notifier` ne rend qu'un booleen :
    # il dit si l'APPEL au relais a abouti, pas si un message est parti. Le
    # cooldown est applique PAR LE RELAIS, qui rend alors
    # `{"sent": false, "skipped": "cooldown"}` — avec un HTTP 200, donc `True`
    # ici. Ecrire << alerte OK >> sur ce booleen laisserait croire qu'un
    # message est parti a chaque passage.
    #
    # Mesure du 2026-10-09 : deux passages consecutifs, le second a bien rendu
    # `skipped: cooldown, remaining 1733s`. Un seul message est parti.
    print(f"   {'transmis au relais (c est LUI qui applique le cooldown)' if ok else 'ECHEC de transmission'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
