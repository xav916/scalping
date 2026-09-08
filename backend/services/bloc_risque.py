"""Le risque du COMPTE, dit dans le message du trade lui-même.

Demandé par Xavier le 2026-09-08 : « dans chaque message concernant les trades,
sur chaque courtier, avoir de la visibilité sur le risque engagé par le trade
sur le risque global, le risque global à l'instant t en pourcentage, la marge
de risque libre chez le courtier, et si un trade or peut encore passer ».

Quatre questions, quatre lignes. Elles existaient toutes — mais seulement dans
la commande `/risque`, qu'il faut penser à taper. Un montant de risque isolé
(« Risque −7,20 € ») ne dit pas s'il reste de la place pour le suivant.

## Trois refus assumés

⛔ **On ne recalcule rien.** L'état vient de `_lire_destination`, qui lit la
porte du bridge — celle qui refuse vraiment. Un calcul parallèle serait une
énième copie, et une copie dérive : c'est l'histoire des quatre tables de
canaux et des deux bridges Kraken.

⛔ **Un bridge muet ne rend pas « 0 % ».** Il rend « on ne sait pas ». Un zéro
rassurant sur un compte injoignable est précisément le défaut que la commande
`/risque` refuse déjà en quatre endroits.

⛔ **On ne dit pas « l'or passera ».** La porte de risque est UNE porte parmi
plusieurs : la corrélation a interdit tout achat d'or le 26/08 avec une seule
position à 0,01 lot, et le plafond journalier, la whitelist et le coût mordent
aussi. On dit donc « côté risque », jamais « ça passe ».

## ⚠️ La devise n'est pas la même partout

MT5 rend des euros (l'equity du compte est libellée en EUR), Kraken rend des
**dollars** (`risque_ouvert_usd`, `plafond_usd`). Le formateur historique
écrivait `€` sur les deux. Ici tout est ramené en euros, et une conversion
faite sur un taux de repli se **signale** au lieu de passer pour un taux vivant.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 🔑 Le trade typique risque jusqu'à 9 €. Ce n'est pas un chiffre choisi : c'est
# celui dont `SEUIL_PCT` est DÉRIVÉ dans `notify_saturation_risque`
# (100 × (1 − 9/plafond) ≈ 67 %). Le poser ailleurs en dur les ferait diverger
# en silence — le défaut apparié du seuil de saturation, déjà vu.
RISQUE_TRADE_TYPIQUE_EUR = 9.0

POCHE_METAUX = "or_argent"


def _taux_eur_usd() -> tuple[float, bool]:
    """Rend (taux, vivant).

    ⚠️ `taux_eur_usd()` replie en silence sur une constante : on veut savoir,
    pour ne pas afficher un montant converti comme s'il était mesuré.
    """
    from backend.services.risk_eur import _close_macro, taux_eur_usd
    v = _close_macro("eurusd")
    if v is not None and 0.5 < v < 2.0:
        return v, True
    return taux_eur_usd(), False


_CHAMPS_MONNAIE = ("risque_total", "plafond", "restant", "liberable")


def normaliser_en_eur(evaluation: dict) -> dict:
    """Ramène une évaluation en EUROS, quel que soit le courtier.

    ⛔ **Point de conversion UNIQUE.** MT5 rend des euros, Kraken des dollars
    (`risque_ouvert_usd`, `plafond_usd`) — et les formateurs écrivaient `€` sur
    les deux. Convertir dans chaque formateur en ferait autant de copies, donc
    autant de divergences : c'est exactement ainsi que le risque en euros avait
    fini faux d'un facteur 156.

    Rend une COPIE. `devise` passe à `"EUR"`, et deux drapeaux disent d'où
    vient le chiffre : `converti` et `taux_vivant`.
    """
    e = dict(evaluation or {})
    if e.get("devise") != "USD":
        e.setdefault("converti", False)
        e.setdefault("taux_vivant", True)
        return e

    taux, vivant = _taux_eur_usd()
    if not taux:
        # ⛔ Sans taux, on ne fabrique pas un montant : on le retire. Un
        # montant faux serait lu comme vrai.
        for c in _CHAMPS_MONNAIE:
            e[c] = None
        e.update({"converti": True, "taux_vivant": False})
        return e

    for c in _CHAMPS_MONNAIE:
        if e.get(c) is not None:
            e[c] = float(e[c]) / taux
    detail = {}
    for q, d in (e.get("detail_poches") or {}).items():
        d = dict(d)
        for c in ("risque", "plafond"):
            if d.get(c) is not None:
                d[c] = float(d[c]) / taux
        detail[q] = d
    e["detail_poches"] = detail
    e.update({"devise": "EUR", "converti": True, "taux_vivant": vivant})
    return e


def _compter(valeur) -> int:
    """⚠️ `nues` est une LISTE côté MT5 et un ENTIER ailleurs."""
    if isinstance(valeur, (list, tuple, set)):
        return len(valeur)
    try:
        return int(valeur or 0)
    except (TypeError, ValueError):
        return 0


def etat(destination_id: str | None) -> dict:
    """Lit la porte du courtier. **Bloquant** (urllib) : à sortir de la boucle
    d'événements par l'appelant, comme `_mesurer_risque_destinations`.

    Tout montant rendu est en EUROS.
    """
    if not destination_id:
        return {"lisible": False, "motif": "destination inconnue"}
    try:
        from backend.services.destinations_registry import DESTINATIONS
        from scripts.notify_saturation_risque import _lire_destination
    except Exception as e:  # noqa: BLE001
        logger.debug(f"bloc_risque: import impossible ({e})")
        return {"lisible": False, "motif": "module de risque indisponible"}

    dest = DESTINATIONS.get(str(destination_id).strip())
    if dest is None:
        return {"lisible": False, "motif": "destination inconnue"}
    try:
        e = _lire_destination(dest)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"bloc_risque: lecture {destination_id} : {exc}")
        return {"lisible": False, "motif": "bridge injoignable"}

    if not e.get("lisible"):
        return {"lisible": False, "motif": "bridge muet"}

    e = normaliser_en_eur(e)          # tout est en euros à partir d'ici

    detail = e.get("detail_poches") or {}
    # ⛔ `risque_total` ne décrit QUE la poche la plus tendue depuis le 28/08.
    # L'employer comme total rendrait un engagé crédible et AMPUTÉ.
    engage = (sum(d["risque"] for d in detail.values() if d.get("risque"))
              if detail else e.get("risque_total"))

    metaux = None
    if detail.get(POCHE_METAUX):
        d = detail[POCHE_METAUX]
        plafond_m = d.get("plafond")
        libre = (None if plafond_m is None
                 else plafond_m - (d.get("risque") or 0.0))
        metaux = {"libre_eur": libre, "pct": d.get("pct"),
                  "plafond_eur": plafond_m}

    return {
        "lisible": True,
        "desarme": bool(e.get("desarme")),
        "indecidable": bool(e.get("indecidable")),
        "nues": _compter(e.get("nues")),
        "non_mesurables": _compter(e.get("non_mesurables")),
        "engage_eur": engage,
        "plafond_eur": e.get("plafond"),
        "restant_eur": e.get("restant"),
        "pct": e.get("pct"),
        "poche": e.get("poche"),
        "positions": int(e.get("positions") or 0),
        "metaux": metaux,
        "converti": bool(e.get("converti")),
        "taux_vivant": bool(e.get("taux_vivant")),
    }


def _fr(x: float) -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")


def lignes(etat_risque: dict | None, risque_trade_eur: float | None = None,
           apres_cloture: bool = False) -> list[str]:
    """Rend le bloc en **Markdown** (le format des messages de trade).

    Fonction PURE : aucun réseau. L'état lui est donné.
    """
    if not etat_risque:
        return []
    titre = "🎛 *Risque du compte*"

    if not etat_risque.get("lisible"):
        # ⚠️ Le message du trade part quand même : ne pas savoir le risque ne
        # doit pas empêcher d'annoncer la position. Mais on le NOMME.
        return [titre,
                f"❓ Illisible — {etat_risque.get('motif') or 'inconnu'}. "
                "Ce n'est pas « il reste de la place », "
                "c'est « on ne sait pas »."]

    if etat_risque.get("desarme"):
        return [titre, "⚪ Plafond de risque *désarmé* chez ce courtier — "
                       "il n'y a pas de marge à consommer."]

    out = [titre]

    if etat_risque.get("indecidable"):
        if etat_risque.get("nues"):
            out.append(f"🚨 *{etat_risque['nues']} position(s) SANS STOP* — "
                       "risque non borné, admission fermée.")
        else:
            out.append(f"⚠️ *{etat_risque.get('non_mesurables', 0)} position(s) "
                       "non mesurable(s)* — total impossible, "
                       "on ne conclut pas.")
        return out

    engage = etat_risque.get("engage_eur")
    pct = etat_risque.get("pct")
    restant = etat_risque.get("restant_eur")

    # 1. La part de CE trade dans l'engagé.
    if risque_trade_eur and engage:
        part = 100.0 * risque_trade_eur / engage
        out.append(f"Ce trade : {_fr(risque_trade_eur)} € — *{part:.0f} %* "
                   "du risque engagé")
    elif apres_cloture:
        out.append("Position refermée — voici ce qui reste engagé :")

    # 2. L'engagé global, en pourcentage du plafond.
    #
    # ⚠️ Avec deux poches, l'engagé TOTAL et le pourcentage ne parlent pas du
    # même objet : 80 € au total, mais 74 % de la poche « autres » qui, elle,
    # plafonne à 27 €. Les coller sur la même ligne avec un tiret se lit
    # « 80 € = 74 % », ce qui est faux. On les sépare donc explicitement.
    multi = bool(etat_risque.get("metaux"))
    if engage is not None and pct is not None:
        poche = etat_risque.get("poche")
        if multi and poche:
            # La poche annoncée est celle qui MORD : c'est elle qui refusera
            # le prochain ordre. Une moyenne diluerait une poche pleine dans
            # une poche vide, et se tairait.
            out.append(f"Engagé : *{_fr(engage)} €* au total · poche "
                       f"« {poche} » à *{pct:.0f} %* de son plafond")
        else:
            out.append(f"Engagé : *{_fr(engage)} €* — *{pct:.0f} %* "
                       "du plafond")
    elif engage is not None:
        out.append(f"Engagé : *{_fr(engage)} €* — plafond inconnu")

    # 3. La marge encore libre chez CE courtier.
    if restant is not None:
        ou = " dans cette poche" if multi else ""
        out.append(f"Marge libre : *{_fr(restant)} €*{ou}")

    # 4. L'or peut-il encore passer — CÔTÉ RISQUE seulement.
    out += _ligne_or(etat_risque, restant)

    if etat_risque.get("converti"):
        note = ("converti en euros" if etat_risque.get("taux_vivant")
                else "⚠️ converti sur un taux de *repli*, pas un taux mesuré")
        out.append(f"_Montants d'origine en dollars — {note}._")
    return out


def _ligne_or(etat_risque: dict, restant: float | None) -> list[str]:
    """« Un trade or passerait-il ? » — sur la seule porte du risque.

    ⛔ Ne jamais écrire « l'or passe ». Le 26/08, l'or était bloqué par la
    CORRÉLATION (XAU/AUD à 0,607 contre un seuil de 0,600) avec une unique
    position à 0,01 lot : la marge de risque était large et rien ne passait.
    """
    m = etat_risque.get("metaux")
    libre = m.get("libre_eur") if m else restant
    if libre is None:
        return ["🥇 Or : place *inconnue* — la poche n'est pas mesurable."]
    ou = "poche or/argent" if m else "plafond commun"
    typique = f"{RISQUE_TRADE_TYPIQUE_EUR:.0f}"
    verdict = (f"✅ un trade or type ({typique} €) tient, côté risque"
               if libre >= RISQUE_TRADE_TYPIQUE_EUR
               else f"⛔ un trade or type ({typique} €) serait REFUSÉ")
    return [f"🥇 Or : *{_fr(libre)} €* libres ({ou}) — {verdict}"]
