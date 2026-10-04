"""L'appareil du banc « DERIVE APRES SURPRISE ECONOMIQUE ».

⛔ **TOUT CE QUI SUIT A ETE DECLARE AVANT CE FICHIER**, dans
`docs/concepts-trading.md`, commit SEUL (`c536a2c`). Aucun seuil n'est choisi
ici : ils sont recopies de la declaration, et les y changer apres avoir vu un
resultat serait fabriquer l'avantage qu'on pretend mesurer.

## Ce que l'appareil fait

Pour un evenement de haute importance sur la devise `D`, publie a l'instant
`t` et portant `actual` et `forecast` :

    b   = actual - forecast                 surprise brute
    s   = b / ecart-type des |b| PASSES du MEME event_code
    S   = polarite x s                      surprise signee

Si `|S| >= 1,5`, on entre a l'ouverture de la **premiere bougie H1
strictement posterieure** a `t`, dans le sens de `S`, et on sort a
`+1 / 2 / 4 / 8 h`. Le R vaut l'`ATR(14)` H1 a l'entree, le spread est
facture.

## 🔑 Pourquoi le H1 et pas le 5 min

Mesure du 2026-10-05 sur le pont : H1 et H4 remontent au **2021-01-04**, M5
seulement a **mai 2025**. Le H1 est la seule echelle qui couvre l'historique du
calendrier. Ce n'etait pas un choix.

## ⚠️ Pourquoi l'entree arrive jusqu'a 60 min apres

Notre chaine regarde le marche toutes les **180 s**. La course a l'instant de
la publication est perdue d'avance contre des acteurs colocalises. On ne teste
pas le choc, on teste la **derive**.
"""
from __future__ import annotations

import math
import random
from datetime import datetime

from backend.services.laboratoire_or import plafond_hasard

# ─── Les constantes DECLAREES, recopiees et jamais ajustees ─────────────────

SEUIL_S = 1.5            # declenchement
MIN_OCCURRENCES = 12     # minimum d'occurrences passees pour estimer l'ecart-type
MAX_S = 10.0             # au-dela, la donnee est jugee aberrante et ECARTEE
MIN_N_OOS = 200          # en dessous, le verdict est INDECIDABLE
HORIZONS_H = (1, 2, 4, 8)

# 🔑 La barre vient du LABORATOIRE, elle n'est pas recopiee : une constante
# dupliquee finit par diverger de sa source.
BARRE_UN_TEST = plafond_hasard(1)

# ⛔ Les six familles declarees, et rien d'autre. Un `event_code` absent est
# ECARTE — deviner une polarite serait ajouter un degre de liberte apres coup.
POLARITES: dict[str, int] = {
    "nonfarm-payrolls": +1,
    "employment-change": +1,
    "gdp": +1,
    "retail-sales": +1,
    "core-cpi": +1,     # avant `cpi` : le plus long prefixe doit gagner
    "cpi": +1,
    "unemployment-rate": -1,
    "unemployment-claims": -1,
}


def polarite(event_code: str | None) -> int | None:
    """La polarite declaree, ou `None` si le code n'est pas dans la table.

    ⚠️ Correspondance par PREFIXE : les codes du terminal portent des suffixes
    de variante (`employment-change-s-a`). Le plus LONG prefixe gagne, sinon
    `core-cpi` serait capte par `cpi`.

    ⛔ `adp-nonfarm-employment-change` ne commence par aucun code de la table
    et reste donc ECARTE — c'est precisement la ligne dont la declaration dit
    qu'elle porte une prevision aberrante.
    """
    c = (event_code or "").strip().lower()
    if not c:
        return None
    meilleur = None
    for cle, p in POLARITES.items():
        if c.startswith(cle) and (meilleur is None or len(cle) > len(meilleur[0])):
            meilleur = (cle, p)
    return None if meilleur is None else meilleur[1]


def _ecart_type(valeurs) -> float:
    """Ecart-type d'echantillon. 0.0 si indefini — l'appelant decide."""
    n = len(valeurs)
    if n < 2:
        return 0.0
    moy = sum(valeurs) / n
    return math.sqrt(sum((v - moy) ** 2 for v in valeurs) / (n - 1))


def surprise_normalisee(brute: float, passees) -> float | None:
    """`brute / ecart-type des surprises PASSEES`, ou `None`.

    ⛔ `passees` ne doit contenir que des occurrences ANTERIEURES a
    l'evenement. Le regard vers l'avenir est l'erreur qui fabrique des edges —
    l'appelant en est responsable, et `banc_surprise.trades()` le garantit en
    parcourant les evenements dans l'ordre.

    Rend `None` dans trois cas, et jamais une estimation :
    - moins de `MIN_OCCURRENCES` occurrences passees ;
    - ecart-type nul (toutes identiques) ;
    - **resultat aberrant** : `|s| > MAX_S`. L'ADP du 2021-11-03 porte
      `forecast = -663` quand le consensus reel etait ~+400. Sans ce seuil, le
      banc mesurerait des fautes de frappe et les prendrait pour des chocs.
    """
    if passees is None or len(passees) < MIN_OCCURRENCES:
        return None
    sigma = _ecart_type(list(passees))
    if sigma <= 0:
        return None
    s = brute / sigma
    if abs(s) > MAX_S:
        return None
    return s


def sens_pour_paire(signee: float, devise: str, paire: str) -> str | None:
    """Le sens a prendre sur `paire` pour une surprise signee sur `devise`.

    🔑 La declaration disait « pour l'or, l'argent et le WTI, cotes en dollar,
    une surprise USD s'applique INVERSEE ». C'est exactement la regle generique
    de la devise de COTATION : le cas particulier se dissout. Dollar fort ⇒ or
    en baisse, sans une ligne de plus.

    Rend `None` si la surprise est sous le seuil, ou si la devise n'est pas
    dans la paire.
    """
    if signee is None or abs(signee) < SEUIL_S:
        return None
    parties = (paire or "").upper().split("/")
    if len(parties) != 2:
        return None
    base, cotation = parties
    d = (devise or "").upper()
    if d == base:
        return "buy" if signee > 0 else "sell"
    if d == cotation:
        return "sell" if signee > 0 else "buy"
    return None


def entree_apres(bougies, instant: datetime) -> int | None:
    """L'index de la premiere bougie STRICTEMENT posterieure a `instant`.

    ⛔ La bougie qui CONTIENT l'evenement est exclue : son ouverture precede la
    publication mais sa cloture la suit, et l'utiliser serait lire l'avenir.
    """
    if not bougies or instant is None:
        return None
    for i, b in enumerate(bougies):
        if b.timestamp > instant:
            return i
    return None


def rendement_r(bougies, i_entree: int, horizon_bougies: int, sens: str,
                atr: float, spread: float) -> float | None:
    """Le rendement en R : `(sortie - entree) x sens - spread`, divise par l'ATR.

    ⛔ Rend `None` plutot que d'extrapoler quand la bougie de sortie manque :
    un trade dont on ne connait pas la fin n'existe pas.
    """
    if atr is None or atr <= 0 or sens not in ("buy", "sell"):
        return None
    j = i_entree + horizon_bougies
    if i_entree < 0 or j >= len(bougies):
        return None
    signe = 1.0 if sens == "buy" else -1.0
    brut = (bougies[j].close - bougies[i_entree].open) * signe
    return (brut - (spread or 0.0)) / atr


def controle_apparie(trades, graine: int) -> list[dict]:
    """Les MEMES trades, avec le sens tire au hasard.

    ⛔ Un controle NON apparie mesurerait le cout, pas la direction. Le
    `+8,60 contre le hasard` du 2026-10-01 a ete retire pour cette raison : un
    controle au risque median global ne compare pas ce qu'on croit.

    🔑 Memes instants, memes horizons, meme nombre de trades, meme ATR, meme
    spread. Seul le SENS change, et le tirage est reproductible par graine.
    """
    tirage = random.Random(graine)
    return [{**t, "sens": ("buy" if tirage.random() < 0.5 else "sell")}
            for t in (trades or [])]


def verdict(r_moyen: float, t_vs_hasard: float, n: int,
            signes_par_horizon) -> dict:
    """Applique les QUATRE predictions declarees, dans l'ordre, telles quelles.

    ⛔ P4 d'abord : un echantillon trop petit rend INDECIDABLE, **jamais
    positif**. Lire un petit n comme un succes est la facon la plus commune de
    se mentir.
    """
    signes = [s for s in (signes_par_horizon or []) if s]
    if n < MIN_N_OOS:
        return {"verdict": "INDECIDABLE",
                "motif": f"n={n} hors echantillon, il en faut {MIN_N_OOS} "
                         f"(P4). Ni positif ni refute : on ne sait pas."}
    if r_moyen <= 0:
        return {"verdict": "REFUTE",
                "motif": f"R moyen {r_moyen:+.4f} <= 0 (P1)."}
    if t_vs_hasard <= BARRE_UN_TEST:
        return {"verdict": "REFUTE",
                "motif": f"t_vs_hasard {t_vs_hasard:+.3f} ne franchit pas la "
                         f"barre d'un test {BARRE_UN_TEST:.3f} (P1)."}
    dominant = 1 if sum(1 for s in signes if s > 0) >= sum(1 for s in signes if s < 0) else -1
    accord = sum(1 for s in signes if s == dominant)
    if accord < 3:
        return {"verdict": "REFUTE",
                "motif": f"le signe ne tient que sur {accord} horizon(s) sur "
                         f"{len(signes)} ; il en faut 3 (P2)."}
    return {"verdict": "CANDIDAT",
            "motif": f"R {r_moyen:+.4f}, t {t_vs_hasard:+.3f} > "
                     f"{BARRE_UN_TEST:.3f}, signe stable sur {accord}/"
                     f"{len(signes)} horizons, n={n}. ⛔ P3 (controle apparie) "
                     f"se juge a part."}
