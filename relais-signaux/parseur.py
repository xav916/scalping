"""Interpréter un message de canal en signal structuré — ou refuser.

Écrit le 2026-09-24 pour le canal MQL5 `Orvion` (« Trading XAUUSD »), mais rien
ici ne lui est propre : la sortie est le contrat de `POST /api/signals/external`,
identique pour Telegram, Discord ou un relevé à la main.

## ⛔ La règle qui gouverne tout ce fichier : REFUSER PLUTÔT QUE DEVINER

Le texte d'un canal est une **entrée non fiable qui produit des ordres**. Deux
risques distincts : l'ambiguïté (« stop sous le range » n'est pas un nombre) et
l'adversaire (un canal usurpé, un message piégé). Contre les deux, une seule
défense tient : quand la lecture n'est pas certaine, on ne rend rien, et on dit
pourquoi.

Un message refusé coûte un signal. Un message mal lu coûte un ordre à l'envers.

## Ce que ce module NE fait PAS

Il ne devine pas un stop absent. Il ne « corrige » pas un sens improbable. Il ne
prend pas le milieu d'une zone d'entrée — voir `_ENTREE_ZONE` plus bas, c'est le
choix le moins évident du fichier et il est motivé.

## Conception

`docs/superpowers/specs/2026-09-24-canal-telegram-vers-signaux.md`
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, asdict
from typing import Any

# ⛔ Whitelist STRICTE. Un symbole inconnu est un refus, jamais une
# approximation : « GOLD » et « XAUUSD » désignent la même chose, « GOLDs » chez
# un courtier peut désigner un contrat différent (cf. R-19, la divergence de prix
# du WTI née d'un symbole voisin mais pas identique).
# ⛔ « OR » et « ARGENT » ont été ÉCARTÉS, et c'est délibéré. Ce sont des mots
# français ordinaires : « SELL OR BUY », « je n'ai pas d'ARGENT ». Les garder
# ferait naître un signal sur l'or à partir d'un message qui n'en parle pas —
# et comme ils pointent vers la même paire, le contrôle d'ambiguïté (plusieurs
# instruments cités) ne les rattraperait PAS. Un canal francophone qui écrit
# « OR » se traite avec `--paire`, explicitement.
SYMBOLES: dict[str, str] = {
    "XAUUSD": "XAU/USD", "XAU/USD": "XAU/USD", "XAU": "XAU/USD", "GOLD": "XAU/USD",
    "XAGUSD": "XAG/USD", "XAG/USD": "XAG/USD", "XAG": "XAG/USD", "SILVER": "XAG/USD",
    "EURUSD": "EUR/USD", "EUR/USD": "EUR/USD",
    "GBPUSD": "GBP/USD", "GBP/USD": "GBP/USD",
    "USDJPY": "USD/JPY", "USD/JPY": "USD/JPY",
    "BTCUSD": "BTC/USD", "BTC/USD": "BTC/USD",
    "WTIUSD": "WTI/USD", "WTI/USD": "WTI/USD", "WTI": "WTI/USD",
}

_ACHAT = ("buy", "long", "achat", "acheter")
_VENTE = ("sell", "short", "vente", "vendre")

# Un nombre décimal, virgule ou point. Pas de séparateur de milliers : « 3 900 »
# est ambigu avec deux nombres, et l'ambiguïté se refuse.
_NOMBRE = r"(\d+(?:[.,]\d+)?)"

_RE_SL = re.compile(rf"\b(?:sl|s/l|stop(?:\s*loss)?|stoploss)\b\D{{0,12}}{_NOMBRE}", re.I)
_RE_TP = re.compile(rf"\b(?:tp\d?|t/p|take\s*profit|target|objectif|cible)\b\D{{0,12}}{_NOMBRE}", re.I)
_RE_ENTREE = re.compile(rf"\b(?:entry|entr[ée]e|@|prix|price)\b\D{{0,12}}{_NOMBRE}", re.I)
# ⚠️ Une ZONE d'entrée (« 3900-3902 », « 3900/3902 ») est très fréquente dans ces
# canaux. On la DÉTECTE pour la refuser explicitement plutôt que de la rater.
_ENTREE_ZONE = re.compile(rf"{_NOMBRE}\s*[-–/]\s*{_NOMBRE}")


class Refus(Exception):
    """Le message n'est pas interprétable avec certitude. Le motif est le message."""


@dataclass(frozen=True)
class Signal:
    source: str
    external_id: str
    pair: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit: float | None = None

    def charge(self) -> dict[str, Any]:
        """La charge utile attendue par `POST /api/signals/external`."""
        return {k: v for k, v in asdict(self).items() if v is not None}


def _nombre(brut: str) -> float:
    return float(brut.replace(",", "."))


def _sens(texte: str) -> str:
    bas = texte.lower()
    achat = any(re.search(rf"\b{m}\b", bas) for m in _ACHAT)
    vente = any(re.search(rf"\b{m}\b", bas) for m in _VENTE)
    # ⛔ Les deux présents = message qui commente un autre trade, ou qui annonce
    # une clôture. Ce n'est pas un signal, et trancher au petit bonheur serait
    # l'erreur la plus chère du fichier.
    if achat and vente:
        raise Refus("les deux sens sont présents dans le message")
    if achat:
        return "buy"
    if vente:
        return "sell"
    raise Refus("aucun sens de trade identifiable (buy/sell/achat/vente)")


def _paire(texte: str) -> str:
    haut = texte.upper()
    trouvees = {v for k, v in SYMBOLES.items()
                if re.search(rf"(?<![A-Z/]){re.escape(k)}(?![A-Z/])", haut)}
    if len(trouvees) > 1:
        raise Refus(f"plusieurs instruments cités : {sorted(trouvees)}")
    if not trouvees:
        raise Refus("aucun instrument connu (voir SYMBOLES)")
    return trouvees.pop()


def _identifiant(source: str, paire: str, sens: str, entree: float,
                 stop: float, ref: str | None) -> str:
    """⛔ Déterministe par défaut, et c'est voulu.

    L'unicité côté serveur porte sur `(source, external_id)`. En saisie manuelle,
    un identifiant dérivé du CONTENU rend la double saisie inoffensive : retaper
    le même appel ne produit pas un second ordre. Un identifiant aléatoire ferait
    exactement l'inverse.

    ⚠️ `ref` (l'horodatage du message, par exemple) prime quand il est fourni :
    deux appels identiques émis à deux heures différentes SONT deux signaux.
    """
    if ref:
        return f"{ref}"
    graine = f"{source}|{paire}|{sens}|{entree:.5f}|{stop:.5f}"
    return hashlib.sha256(graine.encode()).hexdigest()[:24]


def construire(source: str, paire: str, sens: str, entree: float, stop: float,
               objectif: float | None = None, ref: str | None = None) -> Signal:
    """Valide des champs DÉJÀ structurés. Le chemin sûr, sans interprétation.

    ⛔ Le contrôle qui compte : le stop du bon côté de l'entrée. Une inversion
    est l'erreur de saisie la plus coûteuse — elle transforme un stop en
    objectif, donc un risque borné en risque ouvert.
    """
    if paire not in SYMBOLES.values():
        raise Refus(f"instrument hors whitelist : {paire}")
    if sens not in ("buy", "sell"):
        raise Refus(f"sens invalide : {sens}")
    if entree <= 0 or stop <= 0:
        raise Refus("prix nul ou négatif")
    if sens == "buy" and stop >= entree:
        raise Refus(f"achat : le stop ({stop}) doit être SOUS l'entrée ({entree})")
    if sens == "sell" and stop <= entree:
        raise Refus(f"vente : le stop ({stop}) doit être AU-DESSUS de l'entrée ({entree})")
    if objectif is not None:
        if objectif <= 0:
            raise Refus("objectif nul ou négatif")
        if sens == "buy" and objectif <= entree:
            raise Refus(f"achat : l'objectif ({objectif}) doit être AU-DESSUS de l'entrée ({entree})")
        if sens == "sell" and objectif >= entree:
            raise Refus(f"vente : l'objectif ({objectif}) doit être SOUS l'entrée ({entree})")
    return Signal(source=source,
                  external_id=_identifiant(source, paire, sens, entree, stop, ref),
                  pair=paire, direction=sens, entry_price=entree,
                  stop_loss=stop, take_profit=objectif)


def lire(texte: str, source: str, ref: str | None = None) -> Signal:
    """Interprète un message brut. Lève `Refus` dès que la lecture est incertaine.

    ⛔ L'ENTRÉE EN ZONE EST REFUSÉE. « XAU sell 3900-3902 » est très fréquent, et
    prendre le milieu serait tentant. On ne le fait pas : le prix d'entrée
    détermine `R`, donc toutes les mesures qui suivront — contrefactuel, banc,
    `dd_R`. Une entrée devinée rend chacune d'elles fausse d'un écart inconnu.
    L'opérateur tranche avec `--entree`, et ce qu'il a tranché se lit.
    """
    if not texte or not texte.strip():
        raise Refus("message vide")
    paire = _paire(texte)
    sens = _sens(texte)

    m_sl = _RE_SL.search(texte)
    if not m_sl:
        raise Refus("aucun stop chiffré — un conseil sans stop n'est pas un signal")
    stop = _nombre(m_sl.group(1))

    m_tp = _RE_TP.search(texte)
    objectif = _nombre(m_tp.group(1)) if m_tp else None

    # L'entrée : d'abord étiquetée, sinon le premier nombre qui n'est ni le stop
    # ni l'objectif. Toute autre heuristique deviendrait du devinement.
    m_en = _RE_ENTREE.search(texte)
    if m_en:
        entree = _nombre(m_en.group(1))
    else:
        deja = {m_sl.group(1)} | ({m_tp.group(1)} if m_tp else set())
        restants = [n for n in re.findall(_NOMBRE, texte) if n not in deja]
        if not restants:
            raise Refus("aucun prix d'entrée identifiable")
        if _ENTREE_ZONE.search(texte):
            raise Refus("entrée donnée en ZONE — préciser le prix avec --entree")
        entree = _nombre(restants[0])

    return construire(source, paire, sens, entree, stop, objectif, ref)
