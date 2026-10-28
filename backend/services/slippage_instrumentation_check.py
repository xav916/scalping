"""Surveille que la mesure du coût d'exécution enregistre réellement quelque chose.

Pourquoi ce contrôle existe : `slippage_pips` et `fill_price` étaient présents
au schéma et **vides sur 1581/1581 trades réels** pendant onze mois. Le calcul
existait de bout en bout ; c'est la référence de comparaison qui manquait, et
rien n'a jamais signalé que la colonne restait nulle. Corrigé le 2026-08-06
(`fd369ab`) — ce module est là pour que le silence ne puisse pas se réinstaller.

Il ne surveille PAS le trading. Il surveille l'instrument de mesure.

⛔ ET IL A ETE AVEUGLE ONZE SEMAINES DE PLUS (2026-10-28). Il rendait `OK,
alerte: false` sur un glissement moyen de **-19 082,80 pips** : il verifiait que
les colonnes etaient REMPLIES, jamais que leurs valeurs avaient un SENS. La
cause etait `_pip_size`, sans cas crypto ni energie, qui retombait sur le
facteur forex `0.0001` -- `BTC/USD` sortait a 1 113 350 pips. Un controle vert
sur la mauvaise question rassure a tort.

Depuis, il juge aussi la PLAUSIBILITE, sur `slippage_pct` -- le glissement en
pourcentage du prix, unite qui ne depend d aucune convention par instrument.
Mesures de reference du 28/10 sur 544 trades reels : `BTC/USD` 0,1298 %,
`XAU/USD` 0,0251 %, forex 0,006 a 0,016 %. Au-dela de `MAX_PCT`, c est l echelle
qui est fausse, pas le marche.

Trois pièges qu'il évite volontairement :

- **Ne rien conclure sur trop peu de trades.** Sous `MIN_SAMPLE`, le verdict est
  `INSUFFISANT` et aucune alerte ne part : l'absence de mesure n'est pas
  distinguable de l'absence de trades.
- **Ne compter que les trades postérieurs au correctif.** Les anciens sont vides
  par construction et le resteront — le prix demandé n'a jamais été écrit.
- **Ne pas confondre « pas de glissement » et « glissement non observable ».**
  Quand le bridge se replie sur le prix demandé (`fill_source == "requested"`),
  il renseigne `fill_price` mais pas `slippage_pips`. Une couverture partielle de
  `slippage_pips` est donc normale ; une couverture nulle de `fill_price` ne
  l'est jamais.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

# Instant du redéploiement du bridge portant la mesure. Les trades antérieurs
# sont vides par construction et doivent être exclus, sinon le contrôle se
# déclencherait à vie sur de l'historique irrécupérable.
DEFAULT_SINCE = "2026-08-06T09:21:00+00:00"

# En dessous, on ne conclut pas. 20 trades suffisent à distinguer « la colonne
# ne se remplit jamais » de « il n'y a pas encore eu de trade ».
DEFAULT_MIN_SAMPLE = 20

# Sous ce taux de renseignement de `fill_price`, quelque chose cloche même si
# ce n'est pas totalement mort (bridge partiellement déployé, une destination
# à jour et pas l'autre).
DEFAULT_MIN_COVERAGE = 0.5

# Au-dela de ce glissement MEDIAN en pourcentage du prix, ce n est plus un cout
# d execution : c est une erreur d echelle ou d unite. La pire valeur mesuree
# en production vaut 0,2322 % (`WTI/USD`, n=2) et la mediane toutes paires
# 0,0229 % -- un demi-pourcent laisse donc deux ordres de grandeur de marge.
DEFAULT_MAX_PCT = 0.5

# Il faut au moins ce nombre de `slippage_pct` pour juger la plausibilite. En
# dessous, la colonne vient juste d etre posee et le silence est normal.
DEFAULT_MIN_PCT_SAMPLE = 10


def _since() -> datetime:
    raw = os.getenv("SLIPPAGE_CHECK_SINCE", DEFAULT_SINCE)
    return _parse_dt(raw) or _parse_dt(DEFAULT_SINCE)


def _parse_dt(raw) -> datetime | None:
    """Tolère les formats rencontrés en base (suffixe Z, naïf, décalage)."""
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def _db_path() -> str:
    from backend.services.trade_log_service import _DB_PATH
    return str(_DB_PATH)


def run() -> dict:
    """Rend le rapport de couverture. Ne lève jamais : un contrôle qui plante
    est un contrôle muet, et c'est précisément le mode de défaillance visé."""
    seuil = _since()
    try:
        mini = int(os.getenv("SLIPPAGE_CHECK_MIN_SAMPLE", DEFAULT_MIN_SAMPLE))
    except ValueError:
        mini = DEFAULT_MIN_SAMPLE
    try:
        couv_min = float(os.getenv("SLIPPAGE_CHECK_MIN_COVERAGE", DEFAULT_MIN_COVERAGE))
    except ValueError:
        couv_min = DEFAULT_MIN_COVERAGE
    try:
        max_pct = float(os.getenv("SLIPPAGE_CHECK_MAX_PCT", DEFAULT_MAX_PCT))
    except ValueError:
        max_pct = DEFAULT_MAX_PCT
    try:
        mini_pct = int(os.getenv("SLIPPAGE_CHECK_MIN_PCT_SAMPLE",
                                 DEFAULT_MIN_PCT_SAMPLE))
    except ValueError:
        mini_pct = DEFAULT_MIN_PCT_SAMPLE

    rapport = {
        "depuis": seuil.isoformat(),
        "echantillon_minimum": mini,
        "trades_depuis": 0,
        "avec_fill_price": 0,
        "avec_slippage": 0,
        "couverture_fill": 0.0,
        "couverture_slippage": 0.0,
        "slippage_moyen_pips": None,
        "avec_slippage_pct": 0,
        "couverture_slippage_pct": 0.0,
        "slippage_median_pct": None,
        "plausibilite": "NON_JUGEE",
        "verdict": "INSUFFISANT",
        "alerte": False,
        "message": "",
    }

    try:
        with sqlite3.connect(_db_path()) as c:
            # ⛔ UNE SONDE EN LECTURE SEULE N EXIGE RIEN DU SCHEMA.
            # `slippage_pct` est posee par `mt5_sync`, qui peut ne pas avoir
            # encore tourne sur cette base -- ou ne jamais tourner (base de
            # test, replique). Exiger la colonne ferait planter le controle
            # sur dix bases valides, et un controle qui plante est un controle
            # muet : exactement le mode de defaillance qu il surveille.
            cols = {r[1] for r in c.execute(
                "PRAGMA table_info(personal_trades)")}
            a_pct = "slippage_pct" in cols
            lignes = c.execute(
                "SELECT created_at, fill_price, slippage_pips"
                + (", slippage_pct" if a_pct else ", NULL")
                + " FROM personal_trades WHERE is_auto = 1"
            ).fetchall()
    except Exception as e:
        rapport["verdict"] = "ERREUR"
        rapport["alerte"] = True
        rapport["message"] = f"Lecture de personal_trades impossible : {e}"
        return rapport

    recents = [r for r in lignes if (_parse_dt(r[0]) or seuil) >= seuil]
    n = len(recents)
    rapport["trades_depuis"] = n
    if n == 0:
        rapport["message"] = "Aucun trade automatique depuis le correctif — rien à conclure."
        return rapport

    fills = [r[1] for r in recents if r[1] is not None]
    slips = [r[2] for r in recents if r[2] is not None]
    rapport["avec_fill_price"] = len(fills)
    rapport["avec_slippage"] = len(slips)
    rapport["couverture_fill"] = round(len(fills) / n, 3)
    rapport["couverture_slippage"] = round(len(slips) / n, 3)
    if slips:
        rapport["slippage_moyen_pips"] = round(sum(slips) / len(slips), 2)

    # ⛔ LA PLAUSIBILITE, et pourquoi elle porte sur le POURCENTAGE.
    #
    # Les pips n ont pas d echelle universelle : `_pip_size` retombe sur le
    # facteur forex hors forex/metaux, donc une valeur en pips ne peut pas etre
    # jugee. Le pourcentage du prix, lui, est comparable entre toutes les
    # classes -- c est ce qui permet enfin de distinguer « cout eleve » de
    # « echelle fausse ».
    pcts = [abs(r[3]) for r in recents if r[3] is not None]
    rapport["avec_slippage_pct"] = len(pcts)
    rapport["couverture_slippage_pct"] = round(len(pcts) / n, 3)
    if pcts:
        pcts_tries = sorted(pcts)
        med = pcts_tries[len(pcts_tries) // 2]
        rapport["slippage_median_pct"] = round(med, 6)
        if len(pcts) < mini_pct:
            # ⚠️ La colonne vient d etre posee : trop peu pour conclure, et
            # surtout PAS une alerte -- sinon elle hurlerait a chaque
            # deploiement.
            rapport["plausibilite"] = "INSUFFISANTE"
        elif med > max_pct:
            rapport["plausibilite"] = "INVRAISEMBLABLE"
        else:
            rapport["plausibilite"] = "PLAUSIBLE"

    if n < mini:
        rapport["message"] = (
            f"{n} trade(s) depuis le correctif, seuil de décision à {mini} — "
            f"trop tôt pour conclure."
        )
        return rapport

    if not fills:
        rapport["verdict"] = "MORTE"
        rapport["alerte"] = True
        rapport["message"] = (
            f"{n} trades depuis le correctif et **aucun** `fill_price` enregistré. "
            f"La mesure du coût d'exécution ne fonctionne pas. À vérifier : le bridge "
            f"tourne-t-il bien la version déployée (colonnes `entry_requested`, "
            f"`fill_price`, `fill_source` dans /audit) ?"
        )
    elif rapport["couverture_fill"] < couv_min:
        rapport["verdict"] = "PARTIELLE"
        rapport["alerte"] = True
        rapport["message"] = (
            f"`fill_price` renseigné sur {len(fills)}/{n} trades "
            f"({rapport['couverture_fill']:.0%}) — sous le seuil de {couv_min:.0%}. "
            f"Probablement une destination à jour et pas l'autre."
        )
    elif rapport["plausibilite"] == "INVRAISEMBLABLE":
        # ⛔ LE MODE DE PANNE QUI A SURVECU ONZE SEMAINES : couverture
        # excellente, valeurs absurdes, verdict `OK`. Il ne peut plus arriver.
        rapport["verdict"] = "ECHELLE_FAUSSE"
        rapport["alerte"] = True
        rapport["message"] = (
            f"Couverture correcte ({rapport['couverture_fill']:.0%}) mais "
            f"glissement MEDIAN de {rapport['slippage_median_pct']:.4f} % du "
            f"prix sur {rapport['avec_slippage_pct']} trades — au-dela de "
            f"{max_pct} %, ce n'est plus un cout d'execution mais une erreur "
            f"d'echelle. A verifier : `_pip_size` couvre-t-elle la classe de "
            f"l'instrument, ou retombe-t-elle sur le facteur forex ?"
        )
    else:
        rapport["verdict"] = "OK"
        rapport["message"] = (
            f"`fill_price` sur {len(fills)}/{n} trades. Glissement mesurable sur "
            f"{len(slips)}/{n}"
            + (
                f", moyenne {rapport['slippage_moyen_pips']:+.2f} pips."
                if slips else "."
            )
            + (
                f" Glissement median {rapport['slippage_median_pct']:.4f} % du "
                f"prix sur {rapport['avec_slippage_pct']} trades "
                f"({rapport['plausibilite']})."
                if rapport["slippage_median_pct"] is not None
                else f" Aucun `slippage_pct` encore ({rapport['plausibilite']})."
            )
        )

    return rapport


# ─── le point d entree du scheduler ────────────────────────────────────────
#
# ⛔ POURQUOI IL N EXISTAIT PAS (2026-10-28). `run()` n etait appele par RIEN,
# sauf son propre test. Le module ecrit pour empecher le silence de se
# reinstaller etait lui-meme muet : onze semaines de glissement absurde sans
# que personne ne le sache. Un observateur non cable ne vaut pas mieux que pas
# d observateur -- il vaut moins, parce qu on croit en avoir un.
#
# 🔑 ET IL N ALERTE QU AU CHANGEMENT. Une sonde qui repete devient du bruit, et
# on a deja vu ce que devient une alerte qu on cesse de lire : la sauvegarde S3
# signalait son echec depuis cinq nuits et plus personne ne la voyait. L etat
# n avance QUE sur un envoi confirme -- sinon l alerte disparaitrait sans avoir
# ete recue.

# Le saut de ligne, NOMME. L echappement litteral ecrit dans ce fichier a ete
# desechappe par l outil qui l a pose, et la sequence est devenue un vrai saut
# au milieu d une f-string -- qui ne compilait plus. Le commentaire qui
# expliquait le piege s est casse de la meme facon au passage suivant.
# Un nom, lui, ne peut pas se faire desechapper.
_SAUT = chr(10)

_TABLE_ETAT = "sonde_glissement_etat"


def _init_etat(c) -> None:
    c.execute(
        f"CREATE TABLE IF NOT EXISTS {_TABLE_ETAT} ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " dernier_verdict TEXT, dernier_envoi_at TEXT)")


def _dernier_verdict() -> str | None:
    try:
        with sqlite3.connect(_db_path()) as c:
            _init_etat(c)
            r = c.execute(
                f"SELECT dernier_verdict FROM {_TABLE_ETAT} WHERE id = 1"
            ).fetchone()
            return r[0] if r else None
    except Exception:
        # ⛔ Illisible => on considere qu on n a rien envoye. Mieux vaut une
        # alerte de trop qu une alerte perdue.
        return None


def _memoriser(verdict: str) -> None:
    with sqlite3.connect(_db_path()) as c:
        _init_etat(c)
        c.execute(
            f"INSERT INTO {_TABLE_ETAT} (id, dernier_verdict, dernier_envoi_at)"
            " VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET"
            " dernier_verdict = excluded.dernier_verdict,"
            " dernier_envoi_at = excluded.dernier_envoi_at",
            (verdict, datetime.now(timezone.utc).isoformat()))


def message(rapport: dict, precedent: str | None) -> str | None:
    """Le texte a envoyer, ou `None` s il n y a rien de NEUF a dire."""
    verdict = rapport.get("verdict")
    if rapport.get("alerte"):
        if verdict == precedent:
            return None          # deja dit, et rien n a change
        return (
            f"🔴 <b>Sonde du glissement : {verdict}</b>" + _SAUT
            + f"{rapport.get('message', '')}" + _SAUT
            + f"Couverture <code>fill</code> "
            f"{rapport.get('couverture_fill', 0):.0%} · "
            f"<code>pct</code> {rapport.get('couverture_slippage_pct', 0):.0%} "
            f"sur {rapport.get('trades_depuis', 0)} trades."
        )
    # Retour a la normale : une seule ligne, et seulement si on avait alerte.
    if precedent and precedent not in ("OK", "INSUFFISANT"):
        return (
            f"✅ <b>Sonde du glissement : rentree dans l ordre</b> "
            f"(etait <code>{precedent}</code>, maintenant "
            f"<code>{verdict}</code>)."
        )
    return None


async def executer() -> bool:
    """Job scheduler : alerte au CHANGEMENT de verdict, jamais en boucle."""
    rapport = run()
    precedent = _dernier_verdict()
    texte = message(rapport, precedent)
    if texte is None:
        return False

    from backend.services import telegram_service
    envoye = await telegram_service.send_infra_text(texte)
    if envoye:
        _memoriser(rapport.get("verdict") or "INCONNU")
    else:
        # ⛔ Etat NON avance : l alerte sera retentee au prochain passage.
        pass
    return bool(envoye)


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False, default=str))
