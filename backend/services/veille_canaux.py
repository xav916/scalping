"""Plusieurs fils Telegram → un triage DETERMINISTE → des notions a eprouver.

Demande de Xavier le 2026-10-03 : brancher plusieurs canaux Telegram sur une
analyse, et recevoir les idees exploitables dans un canal dedie, « pour piocher
les bonnes idees et pouvoir ensuite les formaliser ».

## 🔑 La separation qui rend un LLM admissible ici

C'est celle de `lecteur_journaux`, et elle n'est pas negociable :

    `classer()` et `triage()`  →  deterministe, teste, sans reseau
    `analyser()`               →  le modele, qui ne voit QUE du texte

⛔ Le modele ne compte rien, ne mesure rien, ne juge aucune performance. Il
**extrait** ce qu'un message dit, dans la forme de `notions_vivien.CHAMPS`, et
laisse `None` tout ce que le message ne dit pas. Un champ devine serait une
invention — c'est la porte que Xavier a demande de tenir fermee : « notre
automate ne prendrait aucun trade tant qu'on n'a pas formalise la cinquieme
condition ».

## ⛔ Ce module ne decide RIEN

Aucune sortie n'entre dans le scoring, le dispatch ou l'admission. Il produit
des **candidats a pre-enregistrer**, qui passent ensuite par la chaine
existante : declaration dans `docs/concepts-trading.md`, commit SEUL, puis le
banc. Le raccourci n'existe pas.

## ⚠️ La cadence attendue, mesuree

Le 2026-10-02, sur **35 messages** d'un seul canal : **4** ont passe le filtre,
**1** a ete arme (l'exposant de Hurst), et le laboratoire n'a **rien** trouve.
Ce fil produit des candidats, pas des avantages. Il retire un goulot — lire les
canaux a la main — il ne change pas le taux de reussite.

## Le filtre, et POURQUOI il est ce qu'il est

Il reprend le raisonnement deja commite pour Hurst (`docs/concepts-trading.md`,
« LE REGIME DE MARCHE PAR L'EXPOSANT DE HURST ») :

1. ⛔ **Un oscillateur n'est pas un declencheur.** RSI, stochastique, RAVI,
   DeMarker, TSI… rendent une **valeur continue**. En faire un motif exige
   d'inventer le seuil ET la regle, c'est-a-dire fabriquer NOTRE regle sous SON
   nom. Les deux tiers du canal MQL5 sont de cette famille.
2. ✅ **Un predicat vaut mieux qu'un motif neuf.** Il conditionne ce qu'on a
   deja au lieu d'ajouter un pari independant — et ajouter un pari RELEVE le
   plafond du hasard pour tout le monde.
3. ✅ **Ce qui arrive avec son propre seuil** est recevable : `H = 0,5` est la
   marche aleatoire par construction, pas un reglage choisi au doigt.
4. ⚠️ **Sans echelle nommee, c'est incomplet** : `echelle` est l'un des six
   champs obligatoires d'une notion.

⚠️ Le triage ne JETTE rien. Il classe, il explique son classement, et il
ordonne. Un filtre qui supprime en silence fait disparaitre ce qu'il n'a pas
comprs — et personne ne peut le relire.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Les six champs d'une notion formalisable. ⛔ Importes, jamais recopies : une
# copie deriverait, et le banc eprouverait une forme que le code ne connait pas.
try:
    from backend.services.notions_vivien import CHAMPS
except Exception:  # noqa: BLE001 — module absent d'un deploiement partiel
    CHAMPS = ("declencheur", "invalidation", "sens", "echelle", "stop", "cible")


# ─── Les familles, par ordre de recevabilite decroissante ─────────────────
PREDICAT = "predicat"        # conditionne les motifs existants → le meilleur
MOTIF = "motif"              # un declencheur net, mais un pari de plus
GESTION = "gestion"          # stop, cible, sortie : agit sur ce qu'on a deja
OSCILLATEUR = "oscillateur"  # ⛔ valeur continue : seuil et regle a inventer
OUTIL = "outil"             # un robot, un script, une offre : rien a eprouver
BRUIT = "bruit"              # promotion, salutation, lien nu

_RANG = {PREDICAT: 0, GESTION: 1, MOTIF: 2, OSCILLATEUR: 3, OUTIL: 4, BRUIT: 5}

# ⛔ Les deux tiers du canal MQL5 sont de cette famille. Mesure le 2026-10-02.
_OSCILLATEURS = (
    "rsi", "stochastic", "stochastique", "demarker", "ravi", "yaanna",
    "demand index", "zigzag", "psar", "parabolic", "rvi", "emv", "tsi",
    "cci", "williams", "momentum oscillator", "awesome oscillator", "macd",
    "moyenne mobile", "moving average", "ema", "sma", "wma", "bollinger",
    "atr indicator", "oscillateur",
)
_PREDICATS = (
    "regime", "régime", "hurst", "volatilite", "volatilité", "persistance",
    "retour a la moyenne", "retour à la moyenne", "mean reversion",
    "autocorrelation", "autocorrélation", "entropie", "fractal",
    "sessions", "killzone", "heure", "filtre", "condition",
)
_MOTIFS = (
    "pin bar", "engulfing", "avalement", "order block", "fair value gap",
    "fvg", "sweep", "balayage", "breakout", "cassure", "divergence",
    "double top", "double bottom", "head and shoulders", "triangle",
    "gap", "liquidite", "liquidité", "imbalance", "bos", "choch",
)
_GESTION = (
    "stop loss", "stop suiveur", "trailing", "take profit", "break even",
    "breakeven", "sortie partielle", "partial close", "money management",
    "sizing", "risk per trade", "risque par trade", "ratio",
)
_OUTILS = (
    "expert advisor", " ea ", "robot", "indicateur a telecharger", "mql5.com",
    "achetez", "gratuit", "promo", "abonnement", "telecharger", "télécharger",
    "code source", "script",
)

# ⚠️ Les echelles telles que le radar les nomme. Une echelle inconnue du radar
# n'est pas une echelle utilisable.
_ECHELLES = {
    "1min": ("m1", "1 min", "1min", "une minute"),
    "5min": ("m5", "5 min", "5min", "cinq minutes"),
    "15min": ("m15", "15 min", "15min"),
    "30min": ("m30", "30 min", "30min"),
    "1h": ("h1", "1h", "1 h", "une heure", "60min", "60 min", "horaire"),
    "4h": ("h4", "4h", "4 h", "quatre heures"),
    "1day": ("d1", "daily", "journalier", "quotidien", "1 jour"),
}

_SEUIL_PROPRE = (
    # Ce qui arrive avec son propre seuil, non choisi au doigt.
    r"\b0[.,]5\b", r"\bzero\b", r"\bzéro\b", r"\bmarche aleatoire\b",
    r"\bmarche aléatoire\b", r"\brandom walk\b", r"\bpar construction\b",
    r"\bseuil\s+(?:de|a|à)\s+\d", r"\b50\s*%",
)

_INSTRUMENTS = (
    "xau", "or ", "gold", "wti", "petrole", "pétrole", "oil", "eur/usd",
    "eurusd", "gbp", "usd/jpy", "usdjpy", "btc", "bitcoin", "eth", "indice",
    "nasdaq", "sp500", "spx", "dax", "cac",
)


def _sans_accent(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn")


def _contient(texte: str, aiguilles) -> list[str]:
    """Les aiguilles presentes, en MOTS ENTIERS.

    ⛔ Une recherche de sous-chaine est fausse, et le test l'a attrape :
    « pe**rsi**stance » contient « rsi », donc le predicat de Hurst — le seul
    des 35 messages du 2026-10-02 a avoir ete retenu — etait classe
    OSCILLATEUR et ecarte. Le filtre aurait jete exactement ce qu'il devait
    garder, en expliquant serieusement pourquoi.
    """
    bas = " " + _sans_accent(texte.lower()) + " "
    out = []
    for a in aiguilles:
        motif = re.escape(_sans_accent(a.lower()).strip())
        if re.search(rf"(?<![a-z0-9]){motif}(?![a-z0-9])", bas):
            out.append(a)
    return out


def echelle_nommee(texte: str) -> str | None:
    """L'echelle du radar nommee par le message, ou `None`.

    ⚠️ `echelle` est l'un des six champs obligatoires. Un message qui n'en
    nomme aucune produit une notion incomplete — ce n'est pas disqualifiant,
    c'est a dire.
    """
    bas = " " + _sans_accent(texte.lower()) + " "
    for canon, formes in _ECHELLES.items():
        for f in formes:
            if re.search(rf"(?<![a-z0-9]){re.escape(f)}(?![a-z0-9])", bas):
                return canon
    return None


def classer(texte: str) -> dict:
    """Classe un message. ⛔ Ne jette RIEN : il explique et il ordonne.

    Un filtre qui supprime en silence fait disparaitre ce qu'il n'a pas
    compris, et personne ne peut le relire.
    """
    t = (texte or "").strip()
    if not t:
        return {"famille": BRUIT, "rang": _RANG[BRUIT], "pourquoi": ["vide"],
                "echelle": None, "instrument": None, "porte_son_seuil": False}

    pourquoi: list[str] = []
    osc = _contient(t, _OSCILLATEURS)
    pred = _contient(t, _PREDICATS)
    mot = _contient(t, _MOTIFS)
    ges = _contient(t, _GESTION)
    out = _contient(t, _OUTILS)

    # ⛔ L'outil commercial d'abord : « EA gratuit utilisant le RSI » n'est pas
    # une idee d'oscillateur, c'est une publicite.
    if out and not (pred or mot or ges):
        famille, pourquoi = OUTIL, [f"outil/offre : {', '.join(out[:3])}"]
    elif pred and not osc:
        famille = PREDICAT
        pourquoi.append(f"predicat : {', '.join(pred[:3])}")
    elif ges and not osc:
        famille = GESTION
        pourquoi.append(f"gestion de position : {', '.join(ges[:3])}")
    elif mot and not osc:
        famille = MOTIF
        pourquoi.append(f"declencheur : {', '.join(mot[:3])}")
    elif osc:
        famille = OSCILLATEUR
        pourquoi.append(
            f"⛔ oscillateur ({', '.join(osc[:3])}) : valeur continue, "
            "le seuil ET la regle seraient les NOTRES")
    else:
        famille = BRUIT
        pourquoi.append("aucun declencheur, aucun predicat, aucune gestion")

    ech = echelle_nommee(t)
    if ech is None:
        pourquoi.append("⚠️ aucune echelle nommee — champ obligatoire manquant")
    inst = (_contient(t, _INSTRUMENTS) or [None])[0]
    if inst is None:
        pourquoi.append("⚠️ aucun instrument nomme")

    seuil = any(re.search(p, _sans_accent(t.lower())) for p in _SEUIL_PROPRE)
    if seuil:
        pourquoi.append("✅ arrive avec son propre seuil")

    rang = _RANG[famille]
    # Un predicat qui porte son seuil ET une echelle passe devant tout.
    if famille == PREDICAT and seuil and ech:
        rang = -1
        pourquoi.append("✅ predicat + seuil propre + echelle : recevable tel quel")

    return {"famille": famille, "rang": rang, "pourquoi": pourquoi,
            "echelle": ech, "instrument": inst, "porte_son_seuil": seuil}


def recevable(c: dict) -> bool:
    """Ce qui vaut d'etre soumis au modele pour extraction.

    ⚠️ Volontairement LARGE : le triage ordonne, c'est le modele qui extrait et
    c'est le banc qui tranche. Ecarter trop tot ferait perdre des idees que le
    vocabulaire du filtre ne connait pas encore.
    """
    return c["famille"] in (PREDICAT, GESTION, MOTIF)


# ─── Le stockage, agnostique de la SOURCE ────────────────────────────────

def _db_path() -> str:
    from backend.services.pair_admission_controller import _db_path as p
    return p()


def _schema(conn: sqlite3.Connection) -> None:
    """⚠️ `UNIQUE (canal, message_id)` : l'idempotence est native. Relire un
    canal deux fois ne doit pas doubler ses messages."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages_canaux (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            canal         TEXT NOT NULL,
            message_id    TEXT NOT NULL,
            publie_a      TEXT,
            texte         TEXT NOT NULL,
            famille       TEXT,
            rang          INTEGER,
            echelle       TEXT,
            instrument    TEXT,
            pourquoi      TEXT,
            vu_a          TEXT NOT NULL,
            analyse_a     TEXT,
            notion_json   TEXT,
            UNIQUE (canal, message_id)
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mc_rang "
                 "ON messages_canaux (rang, publie_a)")


def verser(messages: list[dict]) -> dict:
    """Range des messages bruts et les classe. Idempotent.

    Chaque message : `{canal, message_id, texte, publie_a?}`. La SOURCE n'est
    pas l'affaire de ce module — session Telegram, export, fichier : il range.
    """
    vus = ignores = 0
    maintenant = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(_db_path()) as c:
        _schema(c)
        for m in messages or []:
            canal = str(m.get("canal") or "").strip()
            mid = str(m.get("message_id") or "").strip()
            texte = str(m.get("texte") or "").strip()
            if not canal or not mid or not texte:
                ignores += 1
                continue
            cl = classer(texte)
            try:
                cur = c.execute(
                    "INSERT OR IGNORE INTO messages_canaux "
                    "(canal, message_id, publie_a, texte, famille, rang, "
                    " echelle, instrument, pourquoi, vu_a) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (canal, mid, m.get("publie_a"), texte, cl["famille"],
                     cl["rang"], cl["echelle"], cl["instrument"],
                     " | ".join(cl["pourquoi"]), maintenant))
                vus += cur.rowcount
            except sqlite3.Error as e:
                logger.warning("veille_canaux: %s/%s non range (%s)",
                               canal, mid, e)
                ignores += 1
    return {"ranges": vus, "ignores": ignores,
            "deja_vus": len(messages or []) - vus - ignores}


def triage(limite: int = 40, non_analyses_seulement: bool = True) -> dict:
    """Le relevé DETERMINISTE : des comptes, et les messages a soumettre.

    ⛔ Aucun appel reseau, aucun modele. C'est la couche qui doit etre juste —
    le modele ne verra que ce qu'elle lui donne.
    """
    with sqlite3.connect(_db_path()) as c:
        c.row_factory = sqlite3.Row
        _schema(c)
        par_famille = {r["famille"]: r["n"] for r in c.execute(
            "SELECT famille, COUNT(*) n FROM messages_canaux GROUP BY famille")}
        par_canal = {r["canal"]: r["n"] for r in c.execute(
            "SELECT canal, COUNT(*) n FROM messages_canaux GROUP BY canal")}
        cond = "WHERE analyse_a IS NULL" if non_analyses_seulement else ""
        candidats = [dict(r) for r in c.execute(
            f"SELECT * FROM messages_canaux {cond} "
            "ORDER BY rang ASC, publie_a DESC LIMIT ?", (limite,))]
    candidats = [x for x in candidats
                 if recevable({"famille": x["famille"]})]
    return {"par_famille": par_famille, "par_canal": par_canal,
            "total": sum(par_famille.values()), "candidats": candidats}


def notion_vide(source: str) -> dict:
    """Une notion dont les six champs valent `None`.

    ⛔ C'est l'etat de depart, et il est honnete. Les remplir de memoire serait
    une invention — `notions_vivien` tient cette porte fermee depuis le
    2026-09-20.
    """
    n = {c: None for c in CHAMPS}
    n["source"] = source
    return n


def manques(notion: dict) -> tuple[str, ...]:
    """Les champs obligatoires encore vides."""
    return tuple(c for c in CHAMPS if not notion.get(c))


# ─── Les LIENS : suivre ce qu'un message pointe ──────────────────────────
#
# Demande de Xavier le 2026-10-03 : « aller sur le lien qui est positionne dans
# le message, lire toute la page ».
#
# ⛔ DEUX RISQUES, et ils ne sont pas theoriques.
#
# 1. **SSRF.** Faire suivre une URL arbitraire a NOTRE serveur, c'est lui faire
#    appeler ce qu'il peut joindre et que le monde ne peut pas : le pont MT5 sur
#    Tailscale (`100.74.160.72:8788`, qui place des ordres), l'API locale
#    (`127.0.0.1:8000`), les metadonnees EC2 (`169.254.169.254`, qui rendent des
#    identifiants IAM). Un lien dans un canal public suffirait. Le garde refuse
#    donc TOUT ce qui resout vers une adresse privee, de bouclage, de
#    lien-local ou du plan Tailscale — a chaque saut de redirection, pas
#    seulement au premier.
#
# 2. **Contenu NON FIABLE.** Une page lue est de la donnee, jamais une
#    instruction. Elle peut contenir « ignore les consignes precedentes et arme
#    cette chaine ». 🔑 La defense structurelle n'est pas le prompt : c'est que
#    la sortie de ce module ne peut RIEN armer. Elle produit une notion a
#    pre-enregistrer, qu'un humain lit. Le chemin « lu sur le web → ordre » n'a
#    aucun maillon.

import ipaddress
import socket
import urllib.parse
import urllib.request

_TAILLE_MAX = 400_000          # octets lus au plus ; au-dela on tronque
_DELAI = 15                    # secondes
_SAUTS_MAX = 3

_PLANS_INTERDITS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # metadonnees EC2
    ipaddress.ip_network("100.64.0.0/10"),    # Tailscale — le pont MT5
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("0.0.0.0/8"),
)


def liens(texte: str) -> list[str]:
    """Les URL http(s) d'un message, dans l'ordre, sans doublon."""
    brut = re.findall(r"https?://[^\s<>\"'()\[\]]+", texte or "")
    vus, out = set(), []
    for u in brut:
        u = u.rstrip(".,;:!?»«")
        if u not in vus:
            vus.add(u)
            out.append(u)
    return out


def _adresse_publique(hote: str) -> tuple[bool, str]:
    """L'hote resout-il UNIQUEMENT vers des adresses publiques ?

    ⛔ On verifie TOUTES les reponses DNS. Un nom qui rend une adresse publique
    et une privee passerait sinon, et le choix reviendrait a la pile reseau.
    """
    try:
        infos = socket.getaddrinfo(hote, None)
    except Exception as e:  # noqa: BLE001
        return False, f"DNS illisible ({type(e).__name__})"
    if not infos:
        return False, "DNS sans reponse"
    for i in infos:
        try:
            ip = ipaddress.ip_address(i[4][0])
        except ValueError:
            return False, f"adresse illisible {i[4][0]}"
        for plan in _PLANS_INTERDITS:
            if ip in plan:
                return False, f"⛔ {ip} est dans {plan} — adresse interne"
        if not ip.is_global:
            return False, f"⛔ {ip} n'est pas une adresse publique"
    return True, "publique"


def url_autorisee(url: str) -> tuple[bool, str]:
    """Peut-on aller chercher cette URL sans exposer le reseau interne ?"""
    try:
        p = urllib.parse.urlparse(url)
    except Exception as e:  # noqa: BLE001
        return False, f"URL illisible ({type(e).__name__})"
    if p.scheme not in ("http", "https"):
        return False, f"⛔ schema {p.scheme or 'absent'} refuse"
    if not p.hostname:
        return False, "⛔ aucun hote"
    return _adresse_publique(p.hostname)


def _en_texte(html: str) -> str:
    """Le texte lisible d'une page. Pas un navigateur : un degrossissage."""
    t = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?is)<br\s*/?>|</(p|div|li|tr|h[1-6])>", "\n", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    import html as _h
    t = _h.unescape(t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return t.strip()


# Une ligne de prose fait plus de mots qu'un element de menu.
_MOTS_MINIMUM = 6


def densifier(texte: str, mots_minimum: int = _MOTS_MINIMUM) -> str:
    """Retire le chrome de navigation et garde la prose.

    ⛔ MESURE DU 2026-10-03 sur une vraie page `mql5.com/en/articles` : 24 365
    caracteres lus, dont le debut est integralement du menu — « Forum / Market
    / Signals / Freelance / VPS / Quotes / MetaTrader… ». Envoyer cela au
    modele, c'est payer des jetons pour de la navigation ET diluer le signal
    dans du bruit repete sur chaque page du site.

    🔑 Heuristique volontairement simple et sans dictionnaire de domaine : une
    ligne de PROSE fait plusieurs mots, un element de menu en fait un ou deux.
    On garde donc les lignes assez longues, et les titres courts suivis de
    prose sont de toute facon repris dans le corps de l'article.

    ⚠️ Elle ne devine aucune structure de site. Un site dont le contenu
    tiendrait en lignes de trois mots serait vide apres passage — et c'est
    `caracteres_densifies` qui le dira, au lieu de le cacher.
    """
    gardees = [l.strip() for l in (texte or "").splitlines()
               if len(l.split()) >= mots_minimum]
    return "\n".join(gardees).strip()


def lire_page(url: str) -> dict:
    """Le texte d'une page, ou le motif du refus. ⚠️ Contenu NON FIABLE.

    ⛔ Chaque saut de redirection est re-verifie : une URL publique qui
    redirige vers `127.0.0.1` est le contournement evident du garde.
    """
    courant, sauts = url, 0
    while sauts <= _SAUTS_MAX:
        ok, motif = url_autorisee(courant)
        if not ok:
            return {"url": url, "refus": motif}
        req = urllib.request.Request(courant, headers={
            "User-Agent": "ScalpingRadar/veille (lecture de concepts)",
            "Accept": "text/html,text/plain;q=0.9"})

        class _SansRedirection(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise _Redirige(newurl)

        try:
            ouvreur = urllib.request.build_opener(_SansRedirection)
            with ouvreur.open(req, timeout=_DELAI) as r:
                type_mime = (r.headers.get("Content-Type") or "").lower()
                if not any(x in type_mime for x in ("text/html", "text/plain",
                                                    "application/xhtml")):
                    return {"url": courant, "refus": f"type {type_mime or '?'}"}
                brut = r.read(_TAILLE_MAX + 1)
            tronque = len(brut) > _TAILLE_MAX
            texte = _en_texte(brut[:_TAILLE_MAX].decode("utf-8", "replace"))
            dense = densifier(texte)
            return {"url": courant, "texte": dense, "texte_brut": texte,
                    "tronque": tronque, "caracteres": len(texte),
                    "caracteres_densifies": len(dense)}
        except _Redirige as r:
            courant = urllib.parse.urljoin(courant, str(r))
            sauts += 1
        except Exception as e:  # noqa: BLE001
            return {"url": courant, "refus": f"{type(e).__name__}: {e}"[:160]}
    return {"url": url, "refus": f"⛔ plus de {_SAUTS_MAX} redirections"}


class _Redirige(Exception):
    """Porte la cible d'une redirection pour la re-verifier avant de la suivre."""
