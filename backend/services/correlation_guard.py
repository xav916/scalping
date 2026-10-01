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
import time

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


# ⛔ OU vivent les mesures (2026-09-09). Avant, un seul chemin :
# `os.path.dirname(__file__)`, c'est-a-dire DANS L'IMAGE. Un fichier regenere
# par un cron y aurait ete efface au premier `docker build`, sans que rien ne
# le dise — et le cron aurait produit une mesure MORTE.
#
# Le volume persistant prime donc, l'instantane versionne reste le REPLI : il
# couvre le premier demarrage, un volume vide, et tout environnement sans cron.
# Retirer une protection existante pour en poser une neuve n'est pas un progres.
_DOSSIER_PERSISTANT = os.environ.get("CORRELATIONS_DIR", "/app/data")
_DOSSIER_SOURCE = os.path.dirname(__file__)


def _charger_fichier(nom: str) -> dict[tuple[str, str], tuple[float, int]]:
    """Couples mesures, ou dict vide si le fichier manque ou est illisible.

    Cherche d'abord dans le volume PERSISTANT (ou ecrit le cron), puis dans
    l'instantane versionne. Silencieux sur l'absence : « pas de mesure » est
    exactement l'etat d'avant, et une table de correlations ne doit pas
    empecher le service de demarrer.
    """
    import json
    for dossier, origine in ((_DOSSIER_PERSISTANT, "persistant"),
                             (_DOSSIER_SOURCE, "instantane")):
        chemin = os.path.join(dossier, nom)
        if not os.path.exists(chemin):
            continue
        try:
            with open(chemin, encoding="utf-8") as f:
                data = json.load(f)
            table = {(c["a"], c["b"]): (float(c["r"]), int(c["n"]))
                     for c in data.get("couples", [])}
            if table:
                logger.debug("correlation_guard: %s lu (%s, %d couples)",
                             nom, origine, len(table))
                return table
        except Exception as e:  # noqa: BLE001
            # ⚠️ On DIT, et on essaie la source suivante : un fichier abime
            # ecrit par un cron interrompu ne doit pas coûter la protection.
            logger.warning("correlation_guard: mesure %s illisible en %s (%s)",
                           nom, origine, e)
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

# ⛔ Sans relecture, la table restait figee a l'IMPORT : un cron hebdomadaire
# aurait mis jusqu'a une semaine — ou un redeploiement — a produire le moindre
# effet. Meme raison que le cache de `reglage_or.fermetures` : « une decision
# qui exigerait un redeploiement pour s'appliquer ne s'appliquerait pas ».
#
# 5 min : la mesure change une fois par semaine, l'aller-retour disque est
# negligeable, et aucune decision ne doit attendre plus que ca.
_TTL_MESURE_S = float(os.environ.get("CORRELATIONS_TTL_S", "300"))
_derniere_lecture = [0.0]


def _rafraichir_mesures(force: bool = False) -> None:
    """Relit les mesures si le cache a expire. Met a jour EN PLACE.

    ⚠️ En place, et non par reaffectation : `CORRELATIONS_MESUREES` est
    reference ailleurs et dans les tests ; le remplacer casserait ces
    references en silence.

    ⛔ Fail-CLOSED sur la protection : une lecture qui rend une table VIDE
    (fichier absent, JSON tronque par un cron interrompu) ne remplace pas la
    table connue. Se desarmer sur une panne d'ecriture serait le pire des
    comportements pour un garde-fou.
    """
    maintenant = time.monotonic()
    if not force and maintenant - _derniere_lecture[0] < _TTL_MESURE_S:
        return
    _derniere_lecture[0] = maintenant
    fraiche = _charger_mesure()
    if not fraiche:
        if CORRELATIONS_MESUREES:
            logger.warning(
                "correlation_guard: relecture VIDE — on garde les %d couples "
                "connus. Verifier le cron de regeneration.",
                len(CORRELATIONS_MESUREES))
        return
    CORRELATIONS_MESUREES.clear()
    CORRELATIONS_MESUREES.update(fraiche)


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
    _rafraichir_mesures()
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


def _config_du_pont(destination_id: str):
    """Le `BridgeConfig` de ce compte, ou `None` s'il n'a pas de pont HTTP.

    ⚠️ `destinations_registry.get()` ne convient PAS : son `Destination` ne
    porte ni `bridge_url` ni clé d'API. C'est la confusion de type déjà payée
    le 08/09 — ici elle rendrait `None` et désarmerait la lecture du courtier.

    Les destinations `user:N` et `admin_binance` sont absentes de cette liste,
    et c'est sans effet : elles déclarent `max_correlated_positions = 0`, donc
    `limite()` rend 0 et cette fonction n'est jamais appelée pour elles.
    """
    try:
        from backend.services.bridge_destinations import admin_destinations
        for d in admin_destinations():
            if (str(getattr(d, "destination_id", "")) == str(destination_id)
                    and getattr(d, "bridge_url", "")):
                return d
    except Exception as e:  # noqa: BLE001 — registre illisible : on ne sait pas
        logger.debug("correlation_guard: registre des ponts illisible (%s)", e)
    return None


# Les deux formes du champ `type` d'une position. Le pont sert aujourd'hui des
# chaînes ; MT5 code le sens en entier. Les deux sont acceptées, et rien
# d'autre : un sens qu'on ne sait pas lire fait replier la lecture entière.
_SENS_COURTIER = {"buy": "buy", "sell": "sell", "0": "buy", "1": "sell"}


def _paires_connues() -> set[str]:
    """Les paires pour lesquelles une corrélation est mesurée.

    C'est exactement la population utile : une position sur une paire absente
    de la table est de corrélation INCONNUE, et `_trier` la compte déjà comme
    telle. Pas de seconde liste d'univers à tenir à jour.
    """
    _rafraichir_mesures()
    connues: set[str] = set()
    for a, b in CORRELATIONS_MESUREES:
        connues.add(a)
        connues.add(b)
    return connues


def _paire_pour(symbole: str, dest) -> str:
    """La paire du radar derrière un symbole du courtier, ou le symbole brut.

    ⛔ Rendre le symbole brut plutôt que de jeter la position : `XTIUSD` sans
    correspondance doit remonter comme couple NON MESURÉ — tracé, non bloquant
    — et non disparaître du carnet. Un carnet incomplet qui a l'air complet est
    précisément le défaut du 01/10.
    """
    from backend.services.mt5_bridge import _symbole_courtier_pour
    cible = (symbole or "").upper()
    for p in sorted(_paires_connues()):
        if _symbole_courtier_pour(p, dest).upper() == cible:
            return p
    return symbole


def _positions_du_courtier(destination_id: str) -> list[tuple[str, str]] | None:
    """``(paire, sens)`` lues CHEZ LE COURTIER, ou `None` si indécidable.

    `None` couvre trois cas, et jamais « rien d'ouvert » : pas de pont pour ce
    compte, `/positions` injoignable, ou une position dont le sens est
    illisible. L'appelant replie alors sur `personal_trades`.
    """
    dest = _config_du_pont(destination_id)
    if dest is None:
        return None
    from backend.services.mt5_bridge import _positions_courtier
    # ⛔ `sans_cache` : le cap par paire a lu /positions quelques
    # millisecondes plus tôt dans la même porte et l'a mis en cache pour dix
    # secondes. Les trois ordres du 01/10 sont partis en 1,8 s — s'en servir
    # relirait le carnet d'AVANT le premier, et ce correctif ne serait qu'un
    # aller-retour HTTP de plus pour le même carnet vide.
    positions = _positions_courtier(dest, sans_cache=True)
    if positions is None:
        return None
    sortie: list[tuple[str, str]] = []
    for p in positions:
        brut = (p or {}).get("type")
        sens = _SENS_COURTIER.get(str(brut).strip().lower())
        symbole = str((p or {}).get("symbol") or "")
        if sens is None or not symbole:
            logger.warning(
                "correlation_guard[%s]: position illisible (symbol=%r type=%r) "
                "— repli sur personal_trades plutot qu'un carnet incomplet",
                destination_id, symbole, brut)
            return None
        sortie.append((_paire_pour(symbole, dest), sens))
    return sortie


def positions_ouvertes(destination_id: str) -> list[tuple[str, str]]:
    """``(paire, sens)`` des positions encore ouvertes sur ce compte.

    ⛔ **LE COURTIER D'ABORD** (2026-10-01). Ce garde lisait `personal_trades`
    — sa propre mémoire —, alimentée par `mt5_sync` toutes les **60 secondes**.
    Aucun chemin de push n'y écrit. Le 01/10 à 01h06, trois ordres corrélés
    sont donc partis dans le même cycle sur l'argent réel, dont deux fois le
    même pari (short yen) : les lignes n'ont existé qu'à 01h07:06, et pendant
    trente secondes le garde lisait un carnet vide.

    > **Une porte qui compte dans sa propre mémoire ne compte pas le monde.**

    C'est le titre sous lequel le cap par paire a été migré le 2026-08-28
    (`_compter_positions_courtier`). Sa jumelle ne l'avait jamais été.

    ⚠️ Le courtier rend AUSSI les positions ouvertes à la main : ce sont de
    vraies positions simultanées, donc une vraie concentration. Même lecture
    que le cap par paire, assumée pour la même raison.

    ⚠️ **Le repli garde son rôle.** Si le pont est injoignable ou sa réponse
    illisible, on relit `personal_trades` : c'est l'état d'avant, incomplet
    mais réel. Répondre « carnet vide » à une panne réseau recréerait le
    défaut qu'on corrige.

    Repli : ``personal_trades`` ne porte pas de ``destination_id``, chaque
    position est rattachée à son compte par son ticket, via la résolution déjà
    utilisée par les notifications de clôture.
    """
    chez_le_courtier = _positions_du_courtier(destination_id)
    if chez_le_courtier is not None:
        return chez_le_courtier

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


# Dérogation par COUPLE (compte, paire) — 2026-09-08, demandée par Xavier.
#
# ⛔ Pas un relèvement global : `max_correlated_positions` vaut 1 sur les
# quatre comptes, et le passer à 2 partout doublerait la concentration sur le
# forex et la crypto, où rien ne le justifie. Ce qu'on assume doit se lire
# ligne par ligne — la règle des exemptions de coût du 29/08.
#
# 🔑 Motif mesuré : sur 14 séances, l'or n'a tradé que 7 jours, et
# `correlated_exposure` explique 2 des 7 journées perdues. À une place, une
# position or ouverte plusieurs heures interdit le signal suivant. Ce n'est
# pas un edge négatif qui refuse, c'est une file d'attente à une place.
#
# ⚠️ Cette dérogation N'A DE SENS qu'avec le plafond de risque par trade
# (`porte_risque_par_trade`) : sans lui, deux positions or simultanées
# portaient le pire cas de 9,2 % à 18 % du capital, pour une limite de perte
# journalière de 3 %. Les deux ont été posées ensemble, exprès.
# ⛔ **PORTEE A 6 LE 2026-10-01**, demande explicite de Xavier : « tous les
# horizons ouverts pour l'or, et que ça ne rétrécisse pas ».
#
# 🔑 Les six horizons de l'or ont été ouverts sur `admin_live`
# (`MT5_BRIDGE_HORIZON_OVERRIDES`) et une place par échelle posée
# (`MT5_BRIDGE_PLACES_PAR_HORIZON`). Sans ce relèvement, l'or contre l'or dans
# le MÊME sens vaut une exposition de **1,0** et la troisième échelle se
# faisait refuser en `correlated_exposure` quoi qu'on fasse au cap par paire.
# Ouvrir six horizons pour en servir deux n'aurait pas été les ouvrir.
#
# ⚠️ **Ce que ça coûte, mesuré, et assumé.** Six positions or simultanées
# engagent la somme de leurs risques. Au lot minimum, le 01/10 :
#
#     5 min 8,77 € + 15 min 15,38 € + 30 min 23,53 € + 1 h 31,69 € = 79,37 €
#     soit 12,2 % d'un capital de 650 €, contre un PLAFOND JOURNALIER de
#     3 % = 19,50 €.
#
# ⇒ Le plafond journalier devient la protection qui tranche : il est franchi
# par le PREMIER stop de 30 min. Il n'est pas touché, et il ne doit pas l'être.
# Les horizons 4 h et 1 j restent par ailleurs refusés en amont par
# `porte_risque_par_trade` (65,03 €, 10 % du capital).
#
# ⛔ La borne n'est pas retirée, elle est déplacée : la 7e position or est
# toujours refusée, et toute autre paire garde sa limite de 1.
LIMITE_PAR_PAIRE: dict[tuple[str, str], int] = {
    ("admin_live", "XAU/USD"): 6,
}


# ⛔ Ce que rend une destination QU'ON NE SAIT PAS identifier (2026-09-08).
#
# Avant : `0`, c'est-à-dire ILLIMITÉ — le garde-fou se désarmait tout seul, en
# silence, sur un chemin d'argent réel. Découvert en passant par erreur un
# `Destination` du registre (qui porte `id`) là où le code attend un
# `BridgeConfig` (qui porte `destination_id`) : `limite()` rendait 0 pour les
# six comptes, et rien ne le disait.
#
# 🔑 Les deux destinations réellement illimitées — `user:N` et `admin_binance`
# — sont DÉCLARÉES à 0 et passent par le registre. Le chemin « inconnu » ne
# sert donc qu'aux bugs : le fermer ne peut rien casser de légitime.
#
# ⚠️ `dest is None` garde son 0 : c'est le contrat documenté de ce module —
# il réduit la concentration, il ne protège pas d'une panne et ne doit pas
# bloquer sur une panne.
LIMITE_INCONNUE = 1


def _identifiant(dest) -> str | None:
    """L'identifiant de la destination, quel que soit l'objet reçu.

    ⛔ Le piège : `BridgeConfig` porte `destination_id`, le `Destination` du
    registre porte `id`. Les deux circulent dans ce dépôt, et confondre les
    deux désarmait le garde-fou sans lever la moindre erreur.
    """
    did = getattr(dest, "destination_id", None)
    if did:
        return str(did)
    autre = getattr(dest, "id", None)
    if autre:
        # Ce n'est pas une panne, c'est une confusion de type : on la NOMME
        # au lieu de la rattraper en silence.
        logger.warning(
            "correlation_guard: objet sans `destination_id` (%s) — repli sur "
            "`id`=%s ; un BridgeConfig etait attendu",
            type(dest).__name__, autre)
        return str(autre)
    return None


def limite(dest, pair: str | None = None) -> int:
    """Nombre maximum de positions constituant un même pari. ``0`` ⇒ illimité.

    ``pair`` consulte d'abord `LIMITE_PAR_PAIRE` : une dérogation nommée prime
    sur le réglage du compte.
    """
    if dest is None:
        return 0
    did = _identifiant(dest)
    if pair:
        derogation = LIMITE_PAR_PAIRE.get((str(did or ""), str(pair)))
        if derogation is not None:
            return int(derogation)
    from backend.services import destinations_registry as _reg
    d = _reg.get(did)
    if d is None:
        logger.warning(
            "correlation_guard: destination inconnue (%s) — on retient %d "
            "position(s) par pari, jamais l'illimite", did, LIMITE_INCONNUE)
        return LIMITE_INCONNUE
    return int(d.max_correlated_positions)


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
    if dest is None or limite(dest, pair) <= 0:
        return []
    ouvertes = positions_ouvertes(_identifiant(dest) or "")
    # ⛔ `_identifiant`, pas `getattr(dest, "destination_id")` : les deux
    # formes d'objet circulent, et lire la mauvaise rendait `""` — donc
    # AUCUNE position ouverte, donc aucun pari en cause, donc rien de
    # bloque. `limite()` a ete durci le 08/09 ; ces deux jumelles ne
    # l'avaient pas ete. Un correctif ne se propage pas seul.
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
    maxi = limite(dest, pair)
    if maxi <= 0 or dest is None:
        return False, []

    ouvertes = positions_ouvertes(_identifiant(dest) or "")
    # ⛔ `_identifiant`, pas `getattr(dest, "destination_id")` : les deux
    # formes d'objet circulent, et lire la mauvaise rendait `""` — donc
    # AUCUNE position ouverte, donc aucun pari en cause, donc rien de
    # bloque. `limite()` a ete durci le 08/09 ; ces deux jumelles ne
    # l'avaient pas ete. Un correctif ne se propage pas seul.
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
