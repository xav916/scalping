#!/usr/bin/env python3
"""La BOUCLE LEGERE : voir la figure SE CONSTRUIRE, et ne reveiller la chaine
lourde que quand il y a quelque chose a decider.

> Xavier, 2026-10-11 : « Separe en deux boucles. » Puis : « la detection de
> pattern doit etre faite en live sur les tics et pas sur les bougies », et
> « pourquoi le cycle de 5 secondes ? IC Markets, on ne peut pas faire ca en
> live, ou en tout cas proche du live ? »

## LE DEFAUT QU'ELLE RETIRE, et c'est tout ce qu'elle fait

Aujourd'hui le cycle de l'or tourne aux 5 s, mais il redecide chaque fois sur
LES MEMES bougies : le cache valait 200 s, et elles venaient de Twelve Data.
Le travail utile par passage etait donc NUL 39 fois sur 40, et la 40e decidait
sur une photo de plus de trois minutes, prise ailleurs qu'a l'execution.

## LES DEUX BOUCLES, et le budget MESURE de chacune

    BOUCLE LEGERE, aux ~200 ms            cout mesure par passage
      /tick/XAU-USD chez le courtier               5,8 ms
      mise a jour EN MEMOIRE de la bougie en cours  ~0 ms
      detect_patterns sur 49 fermees + 1 en cours   1,40 ms
                                                 --------
                                                  ~7,2 ms  =  3,6 % de charge

    BOUCLE LOURDE, sur REVEIL seulement   0,5 a 1,9 s (l'or seul)
      admission, sizing, risque, ordre

=> La chaine lourde ne tourne plus au rythme de l'horloge mais au rythme des
FIGURES. Sur l'or, les setups qualifies arrivent 33 fois par jour (un toutes
les ~25 min), la ou l'ancien cycle lançait 17 280 passages quotidiens.

## 🔑 LES 49 FERMEES NE SONT RELUES QU'UNE FOIS PAR BOUGIE

Et le seau de la bougie EN COURS est derive de l'ETIQUETTE DE LA DERNIERE
FERMEE, jamais de l'horloge murale. C'est deliberé : les etiquettes du pont
portent un decalage serveur qui DERIVE (93 min en une heure, mesure le
2026-10-10), donc tout calcul partant de `utcnow()` se desynchroniserait des
bougies qu'il complete. En partant de la derniere fermee, la question ne se
pose pas.

## ⛔ CE QU'ELLE NE FAIT PAS : creer un avantage

Sept zeros independants, mesures le 2026-10-11, disent que la direction
n'existe a aucune echelle et a aucun instant :

    les motifs        0/22 · 0/28 · 2/30 ANTI-predictifs
    l'echelle         jusqu'au tick, 0/16
    l'instant         live contre cloture, 0/4
    la microstructure series de ticks, 0/16

Dont un banc dedie a CETTE question — decider au tick contre decider a la
cloture : **0 cellule retenue sur 4**. Cette boucle retire donc une LATENCE et
un GASPILLAGE reels ; elle ne rend pas les motifs predictifs. Qui l'arme doit
le savoir.

## ⛔ INERTE PAR DEFAUT

`BOUCLE_LEGERE_SEC` vide ou 0 ⇒ rien ne demarre, et le cycle rapide d'avant
continue a l'identique. Les deux ne doivent PAS tourner ensemble : la boucle
legere remplace le cycle rapide, elle ne s'y ajoute pas.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os

from backend.models.schemas import Candle

logger = logging.getLogger(__name__)

# Minutes par echelle, pour deriver le seau de la bougie en cours.
_MINUTES = {"1min": 1, "5min": 5, "15min": 15, "30min": 30, "1h": 60,
            "4h": 240, "1day": 1440}


# ─── La configuration, en fonctions PURES ────────────────────────────────

def config() -> tuple[float, list[str]]:
    """``(secondes, paires)`` de la boucle legere. ``(0.0, [])`` = desarmee.

    ⛔ Une valeur illisible DESARME plutot que de prendre un defaut : un
    `BOUCLE_LEGERE_SEC=deux-cents-ms` ne doit pas armer un rythme que personne
    n'a demande. Meme convention que `config_cycle_rapide`, et pour la meme
    raison — le `.env` tronque du 2026-10-02.

    ⚠️ Et un plancher de 50 ms : en dessous, on inonde le pont sans gagner de
    fraicheur (le tick de l'or arrive ~3 fois par seconde, mesure sur
    3 298 970 ticks).
    """
    brut = os.getenv("BOUCLE_LEGERE_SEC", "").strip()
    if not brut:
        return (0.0, [])
    try:
        secondes = float(brut)
    except (TypeError, ValueError):
        logger.warning("BOUCLE_LEGERE_SEC illisible (%r) — boucle legere "
                       "DESARMEE", brut)
        return (0.0, [])
    if secondes <= 0:
        return (0.0, [])
    if secondes < 0.05:
        logger.warning("BOUCLE_LEGERE_SEC=%.3f sous le plancher de 50 ms — "
                       "ramene a 0,05 s (le tick de l'or arrive ~3 fois par "
                       "seconde : plus vite n'apporte aucune fraicheur)",
                       secondes)
        secondes = 0.05
    brut_p = os.getenv("BOUCLE_LEGERE_PAIRS")
    if brut_p is None:
        brut_p = os.getenv("MT5_BRIDGE_LIVE_WHITELIST_PAIRS", "")
    paires = [p.strip().upper() for p in brut_p.split(",") if p.strip()]
    return (secondes, paires)


# ─── Le seau de la bougie EN COURS ───────────────────────────────────────

def seau_en_cours(derniere_fermee: dt.datetime, interval: str,
                  ) -> dt.datetime | None:
    """L'etiquette du seau qui SUIT la derniere bougie fermee.

    🔑 On part de l'ETIQUETTE, pas de l'horloge. Les etiquettes du pont
    portent un decalage serveur qui derive (93 min en une heure, mesure le
    2026-10-10) : un seau calcule depuis `utcnow()` tomberait a cote des
    bougies qu'il est censé completer, et `detect_patterns` verrait un trou
    ou un doublon sans qu'une seule erreur ne remonte.

    ``None`` si l'echelle est inconnue — on ne DEVINE pas une duree de seau.
    """
    minutes = _MINUTES.get(str(interval))
    if minutes is None:
        logger.warning("boucle_legere: echelle %r inconnue — pas de bougie en "
                       "cours", interval)
        return None
    try:
        return derniere_fermee + dt.timedelta(minutes=minutes)
    except (TypeError, AttributeError):
        return None


def bougie_en_cours(etiquette: dt.datetime, prix) -> Candle | None:
    """La bougie EN COURS, a partir des prix vus depuis le debut du seau.

    `prix` est soit un AGREGAT (`Agregat`), soit une liste de prix — la liste
    reste acceptee parce qu'elle est lisible dans un test et qu'un banc peut
    rejouer une serie connue.

    ``None`` si aucun prix : une bougie sans prix n'existe pas, et en fabriquer
    une a partir de la derniere cloture ferait voir a `detect_patterns` une
    bougie DOJI qui n'a jamais eu lieu.
    """
    if isinstance(prix, Agregat):
        return prix.bougie(etiquette)
    if not prix:
        return None
    return Candle(timestamp=etiquette, open=prix[0], high=max(prix),
                  low=min(prix), close=prix[-1], volume=0.0)


class Agregat:
    """Ouverture, haut, bas, cloture — tenus EN COURANT, sans garder les prix.

    ⛔ POURQUOI PAS UNE LISTE, et le defaut est serieux. Mon premier jet
    empilait chaque prix dans `etat.prix` et recalculait `max()`/`min()` sur
    toute la liste a chaque passage. A 5 releves par seconde c'est 1 500
    entrees par bougie de 5 min — supportable — SAUF que le seau n'avance que
    quand une bougie FERME. Marche ferme (un week-end fait ~50 h), la
    derniere bougie close ne change plus, le seau ne tourne jamais, et la
    liste grimpe a **900 000 entrees** avec un `max()` dessus cinq fois par
    seconde.

    ⇒ Trois flottants et un compteur. O(1) par passage, memoire CONSTANTE, et
    exactement la meme bougie en sortie.
    """

    __slots__ = ("ouvert", "haut", "bas", "dernier", "n")

    def __init__(self) -> None:
        self.ouvert: float | None = None
        self.haut: float = float("-inf")
        self.bas: float = float("inf")
        self.dernier: float | None = None
        self.n: int = 0

    def ajouter(self, p: float) -> None:
        if self.ouvert is None:
            self.ouvert = p
        if p > self.haut:
            self.haut = p
        if p < self.bas:
            self.bas = p
        self.dernier = p
        self.n += 1

    def vide(self) -> bool:
        return self.n == 0

    def bougie(self, etiquette: dt.datetime) -> Candle | None:
        if self.vide() or self.ouvert is None or self.dernier is None:
            return None
        return Candle(timestamp=etiquette, open=self.ouvert, high=self.haut,
                      low=self.bas, close=self.dernier, volume=0.0)


# ─── Le reveil ───────────────────────────────────────────────────────────

def motifs_nouveaux(detections, deja_vus: set[str]) -> set[str]:
    """Les motifs de `detections` qui ne sont PAS dans `deja_vus`.

    🔑 La cle est `(nom, sens)` : `pin_bar_down` et `pin_bar_up` sur le meme
    seau sont deux evenements, pas un. Mais le MEME motif revu au passage
    suivant n'en est qu'un seul — sinon la chaine lourde serait reveillee
    cinq fois par seconde tant que la figure dure, soit exactement le
    gaspillage qu'on retire.
    """
    vus = set()
    for d in (detections or []):
        nom = getattr(d, "pattern_type", None) or getattr(d, "pattern", None)
        sens = getattr(d, "direction", None) or getattr(d, "side", None)
        if nom is None:
            continue
        vus.add(f"{nom}:{sens}")
    return vus - set(deja_vus or ())


class EtatPaire:
    """Ce que la boucle legere retient d'une paire, entre deux passages.

    ⛔ Volontairement en memoire et volontairement minuscule : les 49 fermees,
    l'etiquette du seau courant, les prix vus dans ce seau, et les motifs deja
    annonces. Rien de persistant — au redemarrage on relit les fermees, et le
    seau courant repart vide. Un etat persistant ici serait un etat de PLUS a
    tenir d'accord avec le courtier.
    """

    __slots__ = ("fermees", "etiquette", "prix", "vus", "dernier_reveil",
                 "dernier_rates")

    def __init__(self) -> None:
        self.fermees: list[Candle] = []
        self.etiquette: dt.datetime | None = None
        self.prix = Agregat()
        self.vus: set[str] = set()
        self.dernier_reveil: float = 0.0
        self.dernier_rates: float = float("-inf")

    def nouveau_seau(self, etiquette: dt.datetime) -> None:
        """Le seau change : on oublie les prix ET les motifs deja annonces.

        ⛔ Oublier les prix sans oublier les motifs rendrait la boucle MUETTE
        pour le reste de la session sur toute figure deja vue une fois.
        """
        self.etiquette = etiquette
        self.prix = Agregat()
        self.vus = set()


# ─── La boucle ───────────────────────────────────────────────────────────

async def _tick_mid(pair: str) -> float | None:
    """Le milieu du tick courant chez le COURTIER, hors de la boucle d'evenements.

    ⛔ `prix_courant` est SYNCHRONE et fait un appel reseau bloquant. Appele
    directement dans un job async, il gele l'ordonnanceur entier — le defaut
    exact que j'ai introduit puis corrige sur `protection_perte_or` le
    2026-10-11. D'ou l'executeur.
    """
    from backend.services import bougies_du_pont as BP
    boucle = asyncio.get_running_loop()
    return await boucle.run_in_executor(None, BP.prix_courant, pair)


def rates_sec(interval: str) -> float:
    """Le rythme auquel on relit les bougies FERMEES, en secondes.

    ⛔ POURQUOI PAS << UNE FOIS PAR BOUGIE >>, qui etait mon premier dessin.
    Il ne marche pas, et le defaut est silencieux : rien dans la reponse du
    pont ne dit << la bougie vient de fermer >>. On ne peut le constater
    qu'en relisant et en voyant l'etiquette avancer. Mon premier jet ne
    relisait que si `fermees` etait VIDE — donc jamais, donc le seau
    n'avançait jamais et la bougie en cours grossissait indefiniment.

    ⚠️ Et on ne peut pas non plus deriver la frontiere de l'horloge murale :
    les etiquettes du pont portent un decalage serveur qui DERIVE (93 min en
    une heure, mesure le 2026-10-10).

    ⇒ On relit a cadence fixe, et le roulement est vu dans ce delai. A 5 s
    c'est exactement ce que le cycle rapide d'aujourd'hui paie deja
    (53 ms par appel, soit 1,1 % de charge), et le retard maximum sur une
    bougie de 5 min vaut 1,7 % de sa duree.
    """
    brut = os.getenv("BOUCLE_LEGERE_RATES_SEC", "").strip()
    if brut:
        try:
            v = float(brut)
            if v > 0:
                return v
        except (TypeError, ValueError):
            logger.warning("BOUCLE_LEGERE_RATES_SEC illisible (%r) — defaut",
                           brut)
    return 5.0


async def un_passage(pair: str, etat: EtatPaire, interval: str,
                     combien: int, maintenant: float = 0.0) -> set[str]:
    """Un passage de la boucle legere. Rend les motifs NOUVEAUX a annoncer.

    `maintenant` est une horloge MONOTONE (jamais murale) : elle ne sert qu'a
    espacer les relectures de bougies, et une horloge murale la rendrait
    sensible a un changement d'heure.

    Ne reveille rien lui-meme : il DIT ce qui est nouveau, et l'appelant
    decide. C'est ce qui rend ce coeur testable sans ordonnanceur ni reseau.
    """
    from backend.services import bougies_du_pont as BP

    # ① Les fermees, a cadence fixe — PAS a chaque passage.
    if not etat.fermees or maintenant - etat.dernier_rates >= rates_sec(interval):
        fraiches = await BP.fetch_candles(pair, interval, combien)
        etat.dernier_rates = maintenant
        if fraiches:
            etat.fermees = fraiches
        elif not etat.fermees:
            # ⛔ Pas de bougies ⇒ pas de detection. On ne decide pas sur un
            # historique partiel : `detect_patterns` rend deja vide sous
            # 20 bougies, mais il rendrait des motifs FAUX sur 25.
            return set()
        # ⚠️ Une relecture VIDE sur un etat deja garni ne jette pas
        # l'historique : un hoquet du pont ne doit pas aveugler la boucle.
        # Mais elle ne le rajeunit pas non plus, et c'est pourquoi la
        # peremption ci-dessous est mesuree sur `dernier_rates`.

    derniere = etat.fermees[-1].timestamp
    etiquette = seau_en_cours(derniere, interval)
    if etiquette is None:
        return set()
    if etat.etiquette != etiquette:
        etat.nouveau_seau(etiquette)

    # ② Le prix courant, chez le courtier.
    prix = await _tick_mid(pair)
    if prix is None or prix <= 0:
        # ⛔ Tick illisible : on ne rejoue pas le dernier prix connu. Une
        # bougie qui n'avance plus ressemble a un marche calme, et ce
        # mensonge-la ne remonte nulle part.
        return set()
    etat.prix.ajouter(float(prix))

    # ③ La bougie en cours, et la detection.
    courante = bougie_en_cours(etiquette, etat.prix)
    if courante is None:
        return set()
    serie = list(etat.fermees[-(combien - 1):]) + [courante]

    from backend.services.pattern_detector import detect_patterns
    detections = detect_patterns(serie, pair)
    nouveaux = motifs_nouveaux(detections, etat.vus)
    etat.vus |= nouveaux
    return nouveaux


def reveil_du(nouveaux: set[str], etat: EtatPaire, maintenant: float,
              repos_sec: float = 2.0) -> bool:
    """``True`` s'il faut reveiller la chaine LOURDE maintenant.

    ⛔ LE REPOS N'EST PAS UNE COQUETTERIE. La chaine lourde prend 0,5 a 1,9 s
    sur l'or seul. Sans repos, deux motifs nouveaux a 200 ms d'intervalle
    lanceraient deux chaines qui se chevauchent, et le second ordre
    deciderait sur un etat de positions que le premier n'a pas encore ecrit —
    c'est la fabrique a doublons, et elle a deja coute huit copies du meme
    message le 2026-10-07.
    """
    if not nouveaux:
        return False
    if maintenant - etat.dernier_reveil < repos_sec:
        logger.info("boucle_legere: %s nouveaux mais repos (%.2f s < %.2f s)",
                    sorted(nouveaux), maintenant - etat.dernier_reveil,
                    repos_sec)
        return False
    return True


async def boucle(pair: str, interval: str, combien: int, periode: float,
                 reveiller, arret=None) -> None:
    """La boucle, pour de vrai. `reveiller(pair, motifs)` est appele sur reveil.

    `arret` est un predicat sans argument : des qu'il rend vrai, on sort. Il
    existe pour que les tests n'aient pas besoin d'annuler une tache.

    ⛔ AUCUNE EXCEPTION NE SORT D'ICI. Un `asyncio` job qui leve meurt en
    silence, et la boucle legere serait morte sans que rien ne le dise — le
    defaut exact du `asyncio.gather(return_exceptions=True)` qui avalait tout
    le 2026-10-09. On journalise et on continue.
    """
    etat = EtatPaire()
    boucle_evt = asyncio.get_running_loop()
    logger.info("boucle_legere: %s demarre — %.0f ms, %s x%d, /rates aux %.1f s",
                pair, periode * 1000, interval, combien, rates_sec(interval))
    while not (arret and arret()):
        debut = boucle_evt.time()
        try:
            nouveaux = await un_passage(pair, etat, interval, combien, debut)
            if reveil_du(nouveaux, etat, debut):
                etat.dernier_reveil = debut
                logger.info("boucle_legere: %s REVEIL sur %s", pair,
                            sorted(nouveaux))
                await reveiller(pair, nouveaux)
        except asyncio.CancelledError:
            logger.info("boucle_legere: %s arretee", pair)
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("boucle_legere: %s passage en echec (%s) — on "
                           "continue", pair, e, exc_info=True)
        reste = periode - (boucle_evt.time() - debut)
        await asyncio.sleep(max(0.0, reste))
