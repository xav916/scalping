#!/usr/bin/env python3
"""Ouvrir une position d'or PAR LE PONT, sur demande explicite de Xavier.

Demandé trois fois le 2026-10-09 : *« lance maintenant »*, *« je veux que tu
lances des trades or maintenant »*, *« non lance comme ça »*. Les réserves
ci-dessous lui ont été dites avant, il les a levées.

## ⛔ CE QUE CET OUTIL CONTOURNE, ET QUI DOIT ÊTRE SU

Un ordre posé ici saute les **13 portes du radar** : motif autorisé, horizon,
confiance, fenêtre horaire du spread, frais contre edge, plafond de positions,
délai entre ordres, divergence de prix, tick périmé, blackout d'événement,
chaîne armée, verdict, risque par trade.

✅ Les **4 portes du PONT** s'appliquent toujours — `TRADING_HOURS_UTC`,
plafond journalier du courtier, `MAX_LOT`, contrôle du risque réalisé — et je
n'y touche pas.

## 🔑 LA DIRECTION : au radar par défaut, à Xavier s'il la demande

Sans argument, elle est lue dans le **dernier signal d'or détecté par le
radar** parmi les motifs autorisés — je ne choisis pas le sens à sa place.

Avec `--sens buy|sell`, **Xavier impose** la direction (ajouté le 2026-10-09
à sa demande : *« pourquoi je n'ai pas le droit de faire des trades
manuels ? »* — il en a le droit, et rien ne l'en empêchait).

⚠️ Dans ce cas l'outil affiche **aussi ce que le radar pensait**, et dit
`EN DÉSACCORD` le cas échéant : s'il va contre son propre système, il doit le
voir **avant** d'envoyer, pas après.

⛔ Un `--sens` illisible **lève** au lieu de retomber sur le radar : taper
`--sens by` et voir partir une VENTE serait le pire des silences sur un ordre
d'argent réel.

## 🔑 ÉTIQUETÉ pour ne PAS polluer la mesure

`MANUEL-RAD` quand le radar donne le sens, `MANUEL-XAV` quand Xavier
l'impose. **La distinction compte** : relire dans un mois « MANUEL » sans
savoir qui a décidé la direction rendrait l'analyse impossible.

Le suivi de l'expérience compte les trades `is_auto=1` de l'or ; un ordre posé
ici y entrerait comme s'il avait passé les 13 portes. Le préfixe `MANUEL`
permet de l'exclure — sans lui, la prédiction de −0,80 €/trade deviendrait
illisible.

## La géométrie est CELLE DE SA CONFIGURATION

Stop `XAU_SL_FIXE_EUR` (20 €), cible `XAU_TP_FIXE_EUR` (2 €), converties au
taux EUR/USD **vivant**, au lot minimum (0,01 = une once).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("MT5_BRIDGE_LIVE_URL", "http://100.74.160.72:8788")
CLE = (os.environ.get("MT5_BRIDGE_LIVE_API_KEY")
       or os.environ.get("MT5_BRIDGE_API_KEY") or "")
PAIRE = "XAU/USD"
LOT = 0.01
# 🔑 DEUX etiquettes, et la distinction compte. Quand Xavier choisit le sens,
# la trace doit le dire : relire dans un mois << MANUEL >> sans savoir QUI a
# decide la direction rendrait l'analyse impossible.
ETIQUETTE_RADAR = "MANUEL-RAD"
ETIQUETTE_XAVIER = "MANUEL-XAV"

SL_EUR = float(os.environ.get("XAU_SL_FIXE_EUR", "20"))
TP_EUR = float(os.environ.get("XAU_TP_FIXE_EUR", "2"))


def _appel(chemin: str, charge: dict | None = None, methode: str = "GET"):
    donnees = json.dumps(charge).encode() if charge is not None else None
    rq = urllib.request.Request(
        BASE.rstrip("/") + chemin, data=donnees, method=methode,
        headers={"X-API-Key": CLE, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(rq, timeout=30) as r:
            return json.load(r), r.status
    except urllib.error.HTTPError as e:
        corps = e.read().decode(errors="replace")
        try:
            return json.loads(corps), e.code
        except Exception:
            return {"erreur_brute": corps}, e.code


def taux_eur_usd() -> float | None:
    """⛔ Le taux VIVANT. Un taux figé à 1,155 avait surévalué tous les euros
    du système de 2,7 % (corrigé le 02/10)."""
    try:
        sys.path.insert(0, "/app")
        from backend.services.pattern_detector import _eur_usd_courant
        return _eur_usd_courant()
    except Exception as e:  # noqa: BLE001
        print(f"  (taux illisible : {type(e).__name__}: {e})")
        return None


def sens_du_radar() -> tuple[str, str] | None:
    """Le sens du dernier signal d'or détecté, parmi les motifs AUTORISÉS.

    ⛔ Rend `None` plutôt qu'un sens par défaut : sans signal, l'outil ne doit
    pas inventer une direction. Un trade sans signal est un tirage, et pour un
    prix sans tendance la géométrie 2/20 rend exactement son seuil de
    rentabilité — donc négatif après frais.
    """
    import sqlite3
    autorises = set()
    try:
        brut = os.environ.get("MT5_BRIDGE_PATTERN_OVERRIDES", "")
        if brut:
            for paire, par_h in json.loads(brut).items():
                if "XAU" in paire.upper():
                    for motifs in par_h.values():
                        autorises.update(m.lower() for m in motifs)
    except Exception:
        pass
    c = sqlite3.connect("file:/app/data/trades.db?mode=ro", uri=True)
    for qd, d, det in c.execute(
            "SELECT created_at, direction, details FROM signal_rejections "
            "WHERE pair LIKE '%XAU%' ORDER BY created_at DESC LIMIT 120"):
        try:
            j = json.loads(det or "{}")
        except Exception:
            continue
        motif = str(j.get("signal_pattern") or "").lower()
        if autorises and motif not in autorises:
            continue
        if d in ("buy", "sell"):
            return d, f"{motif}/{j.get('horizon')} a {str(qd)[11:19]}"
    return None


def _sens_demande() -> str | None:
    """Le sens passe en ligne de commande, ou ``None``.

    ⛔ Un `--sens` illisible LEVE au lieu de retomber sur le radar : taper
    `--sens by` par erreur et voir partir une VENTE serait le pire des
    silences sur un ordre d'argent reel.
    """
    if "--sens" not in sys.argv:
        return None
    i = sys.argv.index("--sens")
    if i + 1 >= len(sys.argv):
        raise SystemExit("⛔ --sens attend une valeur : buy ou sell")
    v = sys.argv[i + 1].strip().lower()
    if v not in ("buy", "sell"):
        raise SystemExit(f"⛔ --sens doit valoir buy ou sell, pas {v!r}")
    return v


def main() -> int:
    sec = "--vrai" in sys.argv
    impose = _sens_demande()
    print("=== OUVRIR DE L'OR PAR LE PONT ===")
    print(f"    mode : {'ORDRE REEL' if sec else 'CONTROLE SEUL (aucun ordre)'}")
    if impose:
        print(f"    sens IMPOSE par Xavier : {impose.upper()}")

    tick, _ = _appel(f"/tick/{PAIRE}")
    if "ask" not in tick:
        print(f"  ⛔ tick illisible : {tick}")
        return 1
    ask, bid = float(tick["ask"]), float(tick["bid"])
    print(f"    tick : ask {ask:.2f}  bid {bid:.2f}  "
          f"spread {ask-bid:.3f} $")

    taux = taux_eur_usd()
    if not taux or taux <= 0:
        print("  ⛔ taux EUR/USD illisible — on n'invente pas un stop.")
        return 1
    sl_usd, tp_usd = SL_EUR * taux, TP_EUR * taux
    print(f"    taux EUR/USD LU : {taux:.5f}")
    print(f"    stop  {sl_usd:.3f} $ = {SL_EUR:.2f} EUR")
    print(f"    cible {tp_usd:.3f} $ = {TP_EUR:.2f} EUR")

    if impose:
        sens, origine = impose, "choix de Xavier"
        etiquette = ETIQUETTE_XAVIER
        # ⚠️ On dit AUSSI ce que le radar pensait : si Xavier va contre son
        # propre systeme, il doit le voir avant d'envoyer, pas apres.
        vu = sens_du_radar()
        if vu:
            accord = "D'ACCORD" if vu[0] == sens else "EN DESACCORD"
            print(f"    le radar dit {vu[0].upper()} ({vu[1]}) — {accord}")
        else:
            print("    le radar n'a AUCUN signal autorise recent")
    else:
        choix = sens_du_radar()
        if choix is None:
            print("  ⛔ AUCUN signal d'or autorise recent : pas de direction.")
            print("     Je n'en invente pas — un trade sans signal est un")
            print("     tirage. Utiliser --sens buy|sell pour decider.")
            return 1
        sens, origine = choix
        etiquette = ETIQUETTE_RADAR
        print(f"    🔑 sens pris du RADAR : {sens.upper()}  ({origine})")

    entree = ask if sens == "buy" else bid
    signe = 1 if sens == "buy" else -1
    sl = round(entree - signe * sl_usd, 2)
    tp = round(entree + signe * tp_usd, 2)
    print("")
    print(f"    entree {entree:.2f}   sl {sl:.2f}   tp {tp:.2f}   lot {LOT}")
    # ⛔ Verification d'ORDRE avant d'envoyer : le pont refuse deja un
    #    sl/tp mal ordonne, mais une inversion de signe ici donnerait un
    #    ordre valide ET faux.
    if sens == "buy" and not (sl < entree < tp):
        print("  ⛔ ordre des niveaux incoherent pour un achat")
        return 1
    if sens == "sell" and not (tp < entree < sl):
        print("  ⛔ ordre des niveaux incoherent pour une vente")
        return 1
    print("    ✅ ordre des niveaux coherent")

    charge = {"pair": PAIRE, "direction": sens, "entry": entree,
              "sl": sl, "tp": tp, "lots": LOT,
              "comment": etiquette}
    if not sec:
        rep, code = _appel("/order_check", charge, "POST")
        print("")
        print(f"    /order_check -> {code}")
        print("    " + json.dumps(rep, indent=1)[:900].replace("\n", "\n    "))
        print("")
        print("    (relancer avec --vrai pour envoyer l'ordre)")
        print("    (--sens buy|sell pour imposer la direction)")
        return 0

    rep, code = _appel("/order", charge, "POST")
    print("")
    print(f"    /order -> {code}")
    print("    " + json.dumps(rep, indent=1)[:1200].replace("\n", "\n    "))
    if rep.get("ok"):
        print("")
        print(f"    ✅ ticket {rep.get('ticket')}  prix {rep.get('price')}  "
              f"volume {rep.get('volume')}")
        print(f"       stop pose : {rep.get('sl_applied')}   "
              f"cible posee : {rep.get('tp_applied')}   "
              f"protege : {rep.get('protected')}")
        if not rep.get("protected"):
            print("    ⛔ POSITION NON PROTEGEE : le stop n'est pas confirme.")
    return 0 if rep.get("ok") or not sec else 1


if __name__ == "__main__":
    raise SystemExit(main())
