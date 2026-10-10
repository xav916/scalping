#!/usr/bin/env python3
"""Protection des pertes : resserrer le stop d'un trade durablement negatif.

    python scripts/protection_perte_or.py --essai   # calcule, n'envoie RIEN
    python scripts/protection_perte_or.py           # applique
    python scripts/protection_perte_or.py --bilan   # dit l'etat, n'agit pas

## La regle, dictee par Xavier le 2026-10-09

> « Laisser le trade evoluer pendant 5 min apres l'ouverture. Sur la liste de
> trades negatifs a 5 minutes, si le trade est negatif depuis la moitie de la
> fourchette des 5 min, alors updater le SL a la valeur
> `SL + distance(ouverture, cours XAU/USD) / 2`.
> Exemple : SL initial a 20 EUR, negatif depuis plus de 2 min 30, cours a
> -5 EUR => nouveau SL a `(20 + 5) / 2`. Operation toutes les 5 min. »

🔑 LECTURE VERIFIEE SUR SON EXEMPLE : `(20 + 5)/2 = 12,5`. C'est le POINT
MILIEU entre le stop actuel et le cours actuel. Le risque restant passe de
20 EUR a 12,5 EUR, en laissant 7,5 EUR de marge sous le prix.

## ⚠️ LA CONVERGENCE, MESUREE AVANT D'ETRE CODEE

Le courtier n'impose AUCUNE distance minimale sur l'or
(`trade_stops_level = 0`). Rien n'arrete donc la formule appliquee en boucle,
sur un trade qui reste a -5 EUR :

     5 min  12,50   marge 7,50        25 min   5,47   marge 0,47
    15 min   6,88   marge 1,88        35 min   5,12   marge 0,12

=> le stop COLLE AU PRIX en ~25 min, et comme une oscillation normale de l'or
vaut ~0,25 EUR, le trade serait coupe par le BRUIT : une fermeture deguisee en
stop, indistinguable d'un vrai stop dans la mesure.

⇒ DECISION DE XAVIER APRES CETTE MESURE : plancher de 2 EUR de marge. On
resserre tant qu'il reste au moins 2 EUR entre le stop et le prix.

## 🔑 POURQUOI CETTE REGLE A BESOIN DE LA SONDE

<< Negatif depuis 2 min 30 >> demande une HISTOIRE, pas un instantane. La sonde
de l'echelle (`sonde_echelle_or.py`, aux 5 s) tient `negatif_depuis`. Cette
regle la LIT au lieu de la deviner.

⛔ Et si la sonde ne tourne pas, `negatif_depuis` est absent => ON NE FAIT
RIEN. << Je ne sais pas depuis quand >> n'est pas << ca fait plus de 2 min 30 >>.

## Perimetre : trades du RADAR seulement

Decision de Xavier. Meme convention que l'echelle de gains : on ne touche pas
aux stops qu'il a poses lui-meme dans le terminal.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/app")

logger = logging.getLogger("protection_perte_or")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

# La fourchette de la regle, et sa moitie.
FENETRE_SEC = int(os.environ.get("PROTECTION_PERTE_FENETRE_SEC", "300"))
MOITIE_SEC = FENETRE_SEC / 2.0
# Plancher decide par Xavier apres la mesure de convergence.
MARGE_MIN_EUR = float(os.environ.get("PROTECTION_PERTE_MARGE_MIN_EUR", "2.0"))
ARME = os.environ.get("PROTECTION_PERTE_OR", "0").strip() in ("1", "true", "on")


def _db_path() -> str:
    from backend.services.mt5_sync import _db_path as p
    return p()


# ─── La regle, en fonctions PURES ────────────────────────────────────────

def nouveau_stop_eur(stop_eur: float, perte_eur: float,
                     marge_min_eur: float = MARGE_MIN_EUR) -> float | None:
    """Nouvelle distance de stop en EUR, ou ``None`` s'il n'y a rien a faire.

    `stop_eur` et `perte_eur` sont des distances POSITIVES depuis l'entree.

    🔑 La formule de Xavier est le point milieu : `(stop + perte) / 2`.

    ⛔ DEUX REFUS, et ils comptent autant que le calcul :
      - on ne rend jamais une distance qui laisserait MOINS que le plancher
        entre le stop et le prix (sinon le bruit coupe le trade) ;
      - on ne rend jamais une distance PLUS GRANDE que l'actuelle. Desserrer un
        stop est l'inverse exact d'une protection, et c'est le defaut qui ne se
        voit qu'une fois qu'il a coute.
    """
    try:
        stop_eur = float(stop_eur)
        perte_eur = float(perte_eur)
        marge_min_eur = float(marge_min_eur)
    except (TypeError, ValueError):
        return None

    plancher = perte_eur + marge_min_eur
    # Deja au plancher (ou plus serre) : rien a faire, et surtout pas desserrer.
    if stop_eur <= plancher:
        return None

    vise = (stop_eur + perte_eur) / 2.0
    # Le plancher mord : on s'y arrete plutot que de le franchir.
    if vise < plancher:
        vise = plancher
    # Garde du cliquet, meme apres le clampage.
    if vise >= stop_eur:
        return None
    return vise


def eligible(ouvert_depuis_sec: float | None, perte_eur: float,
             negatif_depuis_sec: float | None) -> tuple[bool, str]:
    """``(eligible, motif_du_refus)``. Le motif est vide quand c'est eligible."""
    if ouvert_depuis_sec is None:
        return (False, "age de la position inconnu")
    if ouvert_depuis_sec < FENETRE_SEC:
        return (False, f"ouvert depuis {ouvert_depuis_sec:.0f} s : on laisse "
                       f"le trade evoluer {FENETRE_SEC:.0f} s (5 min)")
    if perte_eur <= 0:
        return (False, f"en profit ou a l'equilibre ({-perte_eur:+.2f} EUR) : "
                       "c'est le domaine de l'echelle de GAINS")
    if negatif_depuis_sec is None:
        # ⛔ FAIL-CLOSED : sans l'histoire, on s'abstient.
        return (False, "duree de negativite INCONNUE (la sonde ne tourne pas ?) "
                       "— on s'abstient plutot que de supposer")
    if negatif_depuis_sec < MOITIE_SEC:
        return (False, f"negatif depuis {negatif_depuis_sec:.0f} s, il en faut "
                       f"{MOITIE_SEC:.0f} (2 min 30)")
    return (True, "")


def stop_vise_prix(position: dict, taux_eur_usd: float | None,
                   marge_min_eur: float = MARGE_MIN_EUR) -> float | None:
    """Le PRIX du stop a poser, ou ``None``. Ne juge pas l'eligibilite dans le
    temps (c'est `eligible` qui le fait) : seulement la geometrie.

    ⚠️ On transmet un PRIX, jamais une distance : c'est le contrat de la route
    `/position/sltp` depuis le correctif de signe du 2026-10-09.
    """
    try:
        from backend.services import echelle_stop_or as E

        if not taux_eur_usd or float(taux_eur_usd) <= 0:
            return None
        taux = float(taux_eur_usd)

        sym = str(position.get("symbol") or "").upper()
        if "XAU" not in sym and "GOLD" not in sym:
            return None
        # ⛔ Trades du RADAR seulement (decision de Xavier du 2026-10-09). On
        # reutilise la marque de l'echelle plutot que d'en recopier une.
        #
        # 🔑 EXCEPTION ARMEE PAR XAVIER le 2026-10-10 (`EQUIPER_TRADES_MAIN`).
        # Mesure du 09/10 : ses trois pires trades du terminal (258 min,
        # 296 min, 19 min) font -41,72 EUR a eux seuls -- exactement le profil
        # que cette protection attrape. Sans cette adoption, les equiper d'un
        # stop initial ne servirait qu'a moitie : il ne se resserrerait jamais.
        #
        # ⚠️ Desarme, le comportement d'avant est EXACTEMENT conserve.
        if E.MARQUE_RADAR not in str(position.get("comment") or ""):
            try:
                from backend.services import equiper_trades_main as _eq
                if not _eq.concerne(position):
                    return None
            except Exception:  # noqa: BLE001
                # ⛔ Un import qui echoue ne doit pas ELARGIR la portee : on
                # retombe sur le comportement strict.
                return None

        sens = str(position.get("type") or "").lower()
        if sens not in ("buy", "sell"):
            return None
        entree = float(position.get("price_open") or 0)
        courant = float(position.get("price_current") or 0)
        sl = position.get("sl")
        sl = float(sl) if sl else None
        if entree <= 0 or courant <= 0 or sl is None:
            # ⚠️ Pas de stop = rien a resserrer, et on n'en INVENTE pas un :
            # proteger une position nue est le travail du garde-fou SL/TP.
            return None

        signe = 1 if sens == "buy" else -1
        perte_eur = signe * (entree - courant) / taux
        stop_eur = signe * (entree - sl) / taux
        # ⛔ LE PIEGE : si l'echelle de GAINS a deja remonte le stop dans le
        # profit, `stop_eur` est negatif. La formule de perte calculerait alors
        # un stop PLUS LOIN du prix — elle DESSERRERAIT une protection acquise.
        if stop_eur <= 0:
            return None

        vise_eur = nouveau_stop_eur(stop_eur, perte_eur, marge_min_eur)
        if vise_eur is None:
            return None
        return round(entree - signe * vise_eur * taux, 2)
    except Exception as e:  # noqa: BLE001 — ne leve jamais, appelee en boucle
        logger.warning("protection perte : position %s illisible (%s: %s)",
                       position.get("ticket"), type(e).__name__, e)
        return None


# ─── La lecture de l'histoire, et l'action ───────────────────────────────

def _histoire(ticket: int) -> tuple[float | None, float | None]:
    """``(ouvert_depuis_sec, negatif_depuis_sec)`` lus chez la SONDE.

    ⛔ Rend ``(None, None)`` si la sonde n'a rien : l'appelant s'abstiendra.
    """
    try:
        with sqlite3.connect(_db_path()) as c:
            c.row_factory = sqlite3.Row
            r = c.execute(
                "SELECT negatif_depuis, ouvert_depuis FROM echelle_or_suivi "
                "WHERE ticket = ?", (int(ticket),)).fetchone()
    except Exception as e:  # noqa: BLE001
        logger.warning("protection perte : sonde illisible (%s)", e)
        return (None, None)
    if r is None:
        return (None, None)

    def _age(iso):
        if not iso:
            return None
        try:
            t = datetime.fromisoformat(str(iso))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - t).total_seconds()
        except Exception:  # noqa: BLE001
            return None

    return (_age(r["ouvert_depuis"]), _age(r["negatif_depuis"]))


def _poser(ticket: int, prix: float) -> dict:
    import httpx
    base = (os.getenv("MT5_BRIDGE_LIVE_URL", "") or "").rstrip("/")
    cle = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "") or ""
    try:
        r = httpx.post(f"{base}/position/sltp",
                       headers={"X-API-Key": cle},
                       json={"ticket": int(ticket), "sl_absolu": float(prix),
                             "deplacer": True},
                       timeout=12)
        corps = r.json() if r.headers.get("content-type", "").startswith(
            "application/json") else {"texte": r.text[:200]}
        return {"status": r.status_code, **corps}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _positions() -> list[dict] | None:
    import httpx
    base = (os.getenv("MT5_BRIDGE_LIVE_URL", "") or "").rstrip("/")
    cle = os.getenv("MT5_BRIDGE_LIVE_API_KEY", "") or ""
    if not base:
        return None
    try:
        r = httpx.get(base + "/positions", headers={"X-API-Key": cle}, timeout=8)
        if r.status_code != 200:
            logger.warning("protection perte : /positions a rendu %s", r.status_code)
            return None
        return (r.json() or {}).get("positions") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("protection perte : pont muet (%s)", e)
        return None


def appliquer(a_blanc: bool = False) -> dict:
    """Un passage. Rend un bilan lisible, ne leve jamais."""
    from backend.services import echelle_stop_boucle as B

    if not ARME and not a_blanc:
        logger.info("protection perte : DESARMEE (PROTECTION_PERTE_OR=1 pour "
                    "l'armer) — aucun stop touche")
        return {"arme": False}

    taux = None
    try:
        taux = B._taux()
    except Exception as e:  # noqa: BLE001
        logger.warning("protection perte : taux illisible (%s)", e)
    if not taux or taux <= 0:
        return {"arme": True, "erreur": "taux illisible"}

    pos = _positions()
    if pos is None:
        return {"arme": True, "erreur": "positions illisibles"}

    bilan = {"arme": True, "a_blanc": a_blanc, "positions": len(pos),
             "resserres": [], "ecartes": [], "echecs": []}
    for p in pos:
        ticket = p.get("ticket")
        prix = stop_vise_prix(p, taux)
        if prix is None:
            continue
        ouvert, negatif = _histoire(int(ticket))
        signe = 1 if str(p.get("type")).lower() == "buy" else -1
        perte = signe * (float(p["price_open"]) - float(p["price_current"])) / taux
        ok, motif = eligible(ouvert, perte, negatif)
        if not ok:
            bilan["ecartes"].append({"ticket": ticket, "motif": motif})
            logger.info("protection perte : ticket %s ecarte — %s", ticket, motif)
            continue
        logger.warning(
            "protection perte : ticket %s perte %+.2f EUR depuis %.0f s, stop "
            "resserre de %s a %s", ticket, perte, negatif, p.get("sl"), prix)
        if a_blanc:
            bilan["resserres"].append({"ticket": ticket, "sl": prix,
                                       "a_blanc": True})
            continue
        r = _poser(int(ticket), prix)
        if r.get("ok"):
            bilan["resserres"].append({"ticket": ticket, "sl": prix,
                                       "clampe": r.get("sl_clampe_par_le_courtier")})
        else:
            bilan["echecs"].append({"ticket": ticket, "reponse": r})
            logger.warning("protection perte : ticket %s NON resserre — %s",
                           ticket, str(r)[:200])
    return bilan


def main() -> int:
    a_blanc = "--essai" in sys.argv
    if "--bilan" in sys.argv:
        b = appliquer(a_blanc=True)
        print(f"protection perte (bilan) : {b}")
        return 0
    b = appliquer(a_blanc=a_blanc)
    print(f"protection perte{' [ESSAI]' if a_blanc else ''} : "
          f"{len(b.get('resserres', []))} resserre(s), "
          f"{len(b.get('ecartes', []))} ecarte(s), "
          f"{len(b.get('echecs', []))} echec(s)"
          f"{' — DESARMEE' if not b.get('arme') else ''}")
    for e in b.get("ecartes", []):
        print(f"   ticket {e['ticket']} : {e['motif']}")
    for r in b.get("resserres", []):
        print(f"   ticket {r['ticket']} -> stop {r['sl']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
