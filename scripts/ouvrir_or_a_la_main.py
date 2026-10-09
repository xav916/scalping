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

## 🔑 LA DIRECTION NE VIENT PAS DE MOI

Elle est lue dans le **dernier signal d'or détecté par le radar** parmi les
motifs autorisés sur la paire. Choisir moi-même le sens serait prendre une
décision de marché à la place de Xavier ; là, c'est le système qui parle et
l'outil ne fait que l'exécuter hors de sa fenêtre horaire.

## 🔑 ÉTIQUETÉ pour ne PAS polluer la mesure

Le commentaire porte `MANUEL-CLAUDE`. Le suivi de l'expérience du TP à 2 €
compte les trades `is_auto=1` de l'or : un ordre posé ici entrerait dans cette
moyenne comme s'il avait passé toutes les portes. L'étiquette permet de l'en
exclure — sans elle, la prédiction de −0,80 €/trade deviendrait illisible.

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
ETIQUETTE = "MANUEL-CLAUDE"

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


def main() -> int:
    sec = "--vrai" in sys.argv
    print("=== OUVRIR DE L'OR PAR LE PONT ===")
    print(f"    mode : {'ORDRE REEL' if sec else 'CONTROLE SEUL (aucun ordre)'}")

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

    choix = sens_du_radar()
    if choix is None:
        print("  ⛔ AUCUN signal d'or autorise recent : pas de direction.")
        print("     Je n'en invente pas — un trade sans signal est un tirage.")
        return 1
    sens, origine = choix
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
              "comment": ETIQUETTE}
    if not sec:
        rep, code = _appel("/order_check", charge, "POST")
        print("")
        print(f"    /order_check -> {code}")
        print("    " + json.dumps(rep, indent=1)[:900].replace("\n", "\n    "))
        print("")
        print("    (relancer avec --vrai pour envoyer l'ordre)")
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
