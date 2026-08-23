"""Garde-fou de corrélation : ne pas prendre deux fois le même pari.

⚠️ **Pourquoi ce module existe.** Le 2026-08-04, le compte Kraken portait
simultanément un short BTC et un short ETH. Ce ne sont pas deux paris
indépendants : sur les données réelles du système, leurs rendements horaires
corrèlent à **0,81**. C'était un seul pari, pris deux fois, pour 33 USD de
marge sur un compte de 103.

Corrélations mesurées, pas supposées
-------------------------------------
Calculées sur les prix d'entrée horodatés de ``backtest.db.signals``,
rendements horaires, du 2026-06-01 au 2026-08-04. Le nombre d'observations
figure en regard : une corrélation sur 237 points ne vaut pas celle sur
1 468.

Le signe compte autant que la valeur
-------------------------------------
``EUR/USD`` et ``USD/CHF`` corrèlent à **−0,80**. Un groupement naïf par
« paniers » les mettrait ensemble et bloquerait deux achats — alors que deux
achats s'y **compensent**. Ce sont les sens *opposés* qui y constituent le
même pari.

D'où la règle, qui traite le signe explicitement :

    exposition = corrélation × (+1 si même sens, −1 si sens opposés)

Deux positions comptent comme le même pari lorsque ``exposition ≥ seuil``.

  BTC vendeur + ETH vendeur    +0,81 × +1 = +0,81  → même pari
  EUR/USD acheteur + USD/CHF vendeur  −0,80 × −1 = +0,80  → même pari
  EUR/USD acheteur + USD/CHF acheteur −0,80 × +1 = −0,80  → se compensent

Pourquoi le garde-fou est désactivé par défaut
-----------------------------------------------
Mesuré sur soixante jours : le compte principal présente **281
chevauchements de paris identiques sur 568 trades**, soit près d'une
position sur deux. Activer ce garde-fou partout changerait massivement un
comportement en place. Il est donc déclaré par destination
(``max_correlated_positions``), à ``0`` — illimité — sauf là où le besoin
est démontré.
"""
from __future__ import annotations

import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

# Au-delà de ce seuil, deux positions sont considérées comme un seul pari.
SEUIL_CORRELATION = float(os.getenv("CORRELATION_THRESHOLD", "0.6"))

# Corrélations des rendements horaires, mesurées le 2026-08-04 sur
# `backtest.db.signals` (2026-06-01 → 2026-08-04). Valeur, puis nombre
# d'observations — conservé pour que la fiabilité de chaque chiffre reste
# lisible sans avoir à relancer la mesure.
CORRELATIONS: dict[tuple[str, str], tuple[float, int]] = {
    ("XAG/USD", "XAU/USD"): (0.82, 237),
    ("BTC/USD", "ETH/USD"): (0.81, 1468),
    ("EUR/USD", "USD/CHF"): (-0.80, 1406),
    ("EUR/JPY", "GBP/JPY"): (0.79, 1360),
    ("ETH/USD", "SOL/USD"): (0.78, 1222),
    ("ETH/USD", "XRP/USD"): (0.77, 1211),
    ("EUR/USD", "GBP/USD"): (0.77, 1412),
    ("BTC/USD", "SOL/USD"): (0.77, 1227),
    ("BTC/USD", "XRP/USD"): (0.77, 1214),
    ("SOL/USD", "XRP/USD"): (0.75, 1206),
    ("GBP/USD", "USD/CHF"): (-0.73, 1418),
    ("DOT/USD", "ETH/USD"): (0.70, 1168),
    ("BTC/USD", "DOT/USD"): (0.69, 1171),
    ("DOT/USD", "XRP/USD"): (0.68, 1151),
    ("DOT/USD", "SOL/USD"): (0.68, 1162),
    ("ADA/USD", "XRP/USD"): (0.67, 1190),
}


# ─── Mesure continue Kraken Futures (2026-08-09) ───────────────────────
#
# La table ci-dessus ne couvrait que SIX paires crypto sur les vingt-trois
# surveillees : pour les autres, `correlation()` rendait None, donc le garde
# ne comptait rien. `max_correlated_positions=1` etait declare sur
# admin_kraken sans jamais pouvoir mordre au-dela de la meme paire.
#
# ⚠️ L'erreur de raisonnement qui avait retarde la mesure : j'avais annonce
# qu'il faudrait attendre plusieurs semaines, en confondant NOTRE historique
# avec celui du MARCHE. La correlation des rendements est une propriete du
# marche — ETHFI, SEI ou CRV cotent chez Kraken depuis des mois, meme si le
# systeme ne les surveille que depuis le 2026-08-08. La donnee existait deja.
#
# Source : endpoint PUBLIC des graphiques Kraken Futures, donc hors quota
# Twelve Data, et sur les perpetuels REELLEMENT trades (PF_*), pas un proxy.
# 1999 rendements log horaires par instrument, 253 couples, aucun
# sous-echantillonne. Regenerable : `scripts/mesurer_correlations_kraken.py`.
_FICHIER_MESURE = "correlations_kraken_1h.json"

# ─── Mesure continue forex et metaux (2026-08-23) ──────────────────────
#
# La table historique ne couvre que CINQ couples forex/metaux. Pour tous les
# autres, `correlation()` rend None et le garde ne compte rien.
#
# ⚠️ Le trou, mesure sur le compte reel : les quatre positions ouvertes
# etaient GBP/USD x2, EUR/GBP et GBP/JPY. Le couple GBP/USD x GBP/JPY n'est
# PAS dans la table — invisible au garde, alors que l'intuition dit « deux
# fois de la livre ».
#
# La mesure dit le contraire : GBP/JPY correle a +0,79 avec USD/JPY et a
# seulement **+0,19** avec GBP/USD. Le yen est 2,3x plus volatil que la livre
# et USD/JPY est anti-correle a GBP/USD, donc le facteur livre partage
# s'annule presque. **GBP/JPY est bien plus un pari sur le yen que sur la
# livre.** Poser ce garde-fou a l'intuition aurait bloque ce couple pour la
# mauvaise raison.
#
# ⚠️ La valeur depend de la FENETRE : -0,06 sur 30 jours, +0,19 sur 44. Les
# deux sont loin du seuil de 0,6, donc la decision ne bouge pas — mais un
# couple vivant PRES du seuil basculerait selon la fenetre. D'ou `n` conserve
# en regard de chaque chiffre.
#
# Source : `<bridge>/rates?timeframe=H1`, donc le COURTIER et les instruments
# reellement trades. Regenerable : `scripts/mesurer_correlations_forex.py`.
_FICHIER_MESURE_FOREX = "correlations_forex_1h.json"


def _charger_fichier(nom: str) -> dict[tuple[str, str], tuple[float, int]]:
    """Couples mesures, ou dict vide si le fichier manque ou est illisible.

    Silencieux a dessein : l'absence de mesure est exactement l'etat d'avant,
    et une table de correlations ne doit pas empecher le service de demarrer.
    """
    import json
    import os
    chemin = os.path.join(os.path.dirname(__file__), nom)
    try:
        with open(chemin, encoding="utf-8") as f:
            data = json.load(f)
        return {(c["a"], c["b"]): (float(c["r"]), int(c["n"]))
                for c in data.get("couples", [])}
    except Exception as e:
        logger.warning(f"correlation_guard: mesure {nom} illisible ({e})")
        return {}


def _charger_mesure() -> dict[tuple[str, str], tuple[float, int]]:
    """Les deux mesures continues, crypto puis forex.

    Les univers sont disjoints — Kraken Futures ne cote pas EUR/USD — donc
    l'ordre de fusion ne peut pas creer de conflit. On fusionne quand meme
    dans un sens explicite plutot que de s'en remettre a cette disjonction.
    """
    fusion = _charger_fichier(_FICHIER_MESURE)
    fusion.update(_charger_fichier(_FICHIER_MESURE_FOREX))
    return fusion


CORRELATIONS_MESUREES: dict[tuple[str, str], tuple[float, int]] = _charger_mesure()


def correlation(a: str, b: str) -> float | None:
    """Corrélation mesurée entre deux paires. ``None`` si jamais mesurée.

    ``None`` plutôt que ``0.0`` : « non mesuré » et « décorrélé » sont deux
    états différents, et les confondre reviendrait à affirmer une
    indépendance qu'on n'a pas vérifiée.

    La **mesure continue prime** sur la table historique quand les deux
    couvrent le couple : échantillon plus large (1 999 contre 1 468 au mieux)
    et surtout continu. Échantillonner des prix d'entrée de signaux, irréguliers
    par construction, **atténue** une corrélation — c'est ce qui explique que
    les onze couples communs ressortent tous plus hauts, jamais plus bas.

    Depuis le 2026-08-23, le forex et les métaux ont eux aussi leur mesure
    continue, lue chez le courtier (``correlations_forex_1h.json``). La table
    historique reste consultée en dernier recours : elle couvre des couples
    que la mesure aurait pu manquer, et la retirer ôterait une protection
    existante.
    """
    if a == b:
        return 1.0
    hit = (CORRELATIONS_MESUREES.get((a, b))
           or CORRELATIONS_MESUREES.get((b, a))
           or CORRELATIONS.get((a, b))
           or CORRELATIONS.get((b, a)))
    return hit[0] if hit else None


def exposition(pair_a: str, sens_a: str, pair_b: str, sens_b: str) -> float | None:
    """Part de pari commun entre deux positions, dans ``[-1, 1]``.

    Positif ⇒ les deux positions parient dans le même sens. Négatif ⇒ elles
    se compensent. ``None`` si la corrélation n'a pas été mesurée.
    """
    r = correlation(pair_a, pair_b)
    if r is None:
        return None
    meme_sens = str(sens_a).lower() == str(sens_b).lower()
    return r if meme_sens else -r


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def positions_ouvertes(destination_id: str) -> list[tuple[str, str]]:
    """``(paire, sens)`` des positions auto encore ouvertes sur ce compte.

    ``personal_trades`` ne porte pas de ``destination_id`` : chaque position
    est rattachée à son compte par son ticket, via la résolution déjà
    utilisée par les notifications de clôture. Un rapprochement par
    paire et sens serait ambigu — il retomberait sur n'importe quel push de
    la même paire, quel qu'en soit le jour ou le compte.

    Le nombre de positions ouvertes se compte sur les doigts : une résolution
    par ticket reste largement moins coûteuse qu'un appel au bridge.
    """
    from backend.services.telegram_service import destination_for_ticket

    try:
        with sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, timeout=5) as c:
            rows = c.execute(
                "SELECT pair, direction, mt5_ticket FROM personal_trades "
                " WHERE is_auto = 1 AND status = 'OPEN' AND mt5_ticket IS NOT NULL"
            ).fetchall()
    except Exception as e:
        logger.debug(f"correlation_guard: lecture impossible : {e}")
        return []

    sortie = []
    for pair, direction, ticket in rows:
        try:
            if destination_for_ticket(ticket) == destination_id:
                sortie.append((pair, direction))
        except Exception:
            continue
    return sortie


def limite(dest) -> int:
    """Nombre maximum de positions constituant un même pari. ``0`` ⇒ illimité."""
    if dest is None:
        return 0
    from backend.services import destinations_registry as _reg
    d = _reg.get(getattr(dest, "destination_id", None))
    return int(d.max_correlated_positions) if d else 0


def _trier(ouvertes, pair: str, direction: str) -> tuple[list[str], list[str]]:
    """``(memes paris, couples non mesures)`` face aux positions ouvertes."""
    en_cause: list[str] = []
    non_mesures: list[str] = []
    for p, s in ouvertes:
        e = exposition(pair, direction, p, s)
        if e is None:
            non_mesures.append(f"{p} {s}")
        elif e >= SEUIL_CORRELATION:
            en_cause.append(f"{p} {s}")
    return en_cause, non_mesures


def couples_non_mesures(dest, pair: str, direction: str) -> list[str]:
    """Positions ouvertes dont la correlation a ce nouvel ordre est INCONNUE.

    Expose le trou sans passer par les logs, pour pouvoir en compter la
    frequence le jour ou l'on tranchera.
    """
    if dest is None or limite(dest) <= 0:
        return []
    ouvertes = positions_ouvertes(getattr(dest, "destination_id", ""))
    return _trier(ouvertes, pair, direction)[1]


def pari_deja_pris(dest, pair: str, direction: str) -> tuple[bool, list[str]]:
    """``(bloqué, positions en cause)`` pour ce nouvel ordre.

    Best-effort : sans destination, sans limite déclarée ou en cas d'erreur
    de lecture, l'ordre passe. Ce garde-fou réduit la concentration ; il ne
    protège pas contre une panne et ne doit pas bloquer sur une panne.

    ⚠️ **Le trou de mesure est journalisé** (2026-08-09). ``CORRELATIONS`` est
    une table de seize couples mesurés le 2026-08-04 : elle couvre six paires
    crypto sur les vingt-quatre surveillées. Pour les autres, ``exposition``
    rend ``None`` et la position n'est pas comptée — ``max_correlated_positions``
    vaut 1 sur ``admin_kraken``, et trois positions crypto y étaient pourtant
    ouvertes en même temps, corrélations croisées toutes inconnues.

    Le repli permissif reste **délibéré** : « non mesuré » et « décorrélé » sont
    deux choses différentes, et fabriquer une corrélation serait pire que de ne
    pas en avoir. Mais un garde qui laisse passer sans le dire est indiscernable
    d'un garde qui a vérifié — et c'est précisément ce qui rendrait la décision
    future impossible à prendre, faute de savoir à quelle fréquence le cas
    survient. On trace donc, on ne bloque pas.
    """
    maxi = limite(dest)
    if maxi <= 0 or dest is None:
        return False, []

    ouvertes = positions_ouvertes(getattr(dest, "destination_id", ""))
    en_cause, non_mesures = _trier(ouvertes, pair, direction)
    if non_mesures:
        logger.warning(
            "correlation_guard[%s]: %s %s — %d position(s) ouverte(s) de "
            "corrélation INCONNUE, non comptées : %s. %d comptée(s) sur une "
            "limite de %d. Le garde laisse passer faute de mesure, pas faute "
            "de risque.",
            getattr(dest, "destination_id", "?"), pair, direction,
            len(non_mesures), ", ".join(non_mesures), len(en_cause), maxi,
        )
    return (len(en_cause) >= maxi), en_cause
