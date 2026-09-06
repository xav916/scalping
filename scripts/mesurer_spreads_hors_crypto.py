#!/usr/bin/env python3
"""Kraken vs MT5 sur les instruments HORS CRYPTO — mesure en séance.

Posé le 2026-09-06 pour trancher une question restée ouverte : *Kraken ne
sert-il que pour de la crypto ?*

Le 06/09 j'ai comparé les spreads un **dimanche**, MT5 fermé depuis 33 heures.
Kraken ressortait 3 à 21 fois plus cher, et les devises affichaient un volume
nul — mais c'étaient des chiffres de week-end, et j'en avais tiré une
conclusion pour la semaine. Ce script mesure ce qu'il fallait mesurer.

⛔ **Un instantané classe, il ne tranche pas.** Le spread bouge d'heure en
heure : `XMR` est passé de 0,077 % à 0,175 % en une heure le 06/09. On collecte
donc toute la séance et on conclut sur la **médiane**, jamais sur un relevé.

⛔ **Le garde-fou jour+heure vit dans CE fichier, pas dans le cron.** Un fichier
de `cron.d` se copie, s'édite, se duplique en `.bak` — et `cron.d` charge les
`.bak`. Un script qui mesure doit savoir seul s'il a le droit de parler.

Deux modes :
    --collecte   un relevé, ajouté au journal JSONL. Silencieux.
    --bilan      lit le journal du jour, calcule les médianes, poste le verdict.

`FORCER=1` lève la fenêtre horaire **et le dit dans le message** — une
exception qui ne se voit pas est une règle qui n'en est plus une.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import urllib.request
from datetime import datetime, timezone

# ⛔ PAS `/var/log/scalping` : ce chemin est monté en LECTURE SEULE dans le
# conteneur (`-v /var/log/scalping:/var/log/scalping:ro`). Un relevé qui ne
# s'écrit pas est un bilan vide le soir venu, sans que rien ne l'annonce.
# Trouvé en lançant le premier relevé, pas en relisant le code.
JOURNAL = "/app/data/spreads_hors_crypto.jsonl" if os.path.isdir("/app/data")     else "spreads_hors_crypto.jsonl"
TICKERS = "https://futures.kraken.com/derivatives/api/v3/tickers"

# (paire radar, symbole Kraken). Seules celles cotées DES DEUX CÔTÉS permettent
# une comparaison ; les autres sont mesurées pour information.
COMPARABLES = [
    ("XAU/USD", "PF_XAUUSD"),
    ("XAG/USD", "PF_XAGUSD"),
    ("WTI/USD", "PF_WTIOILUSD"),
    ("EUR/USD", "PF_EURUSD"),
    ("GBP/USD", "PF_GBPUSD"),
]
KRAKEN_SEUL = [("SPY", "PF_SPYXUSD"), ("AAPL", "PF_AAPLXUSD")]

# Fenêtre de séance : le chevauchement Londres/New-York, là où l'or, le pétrole
# et l'euro sont le plus liquides. Mesurer à 3 h du matin dirait autre chose,
# et pas ce qu'on veut savoir.
JOUR_CIBLE = 0          # lundi
HEURE_DEBUT_UTC = 8
HEURE_FIN_UTC = 20


def _dans_la_fenetre(maintenant: datetime) -> tuple[bool, str]:
    if os.environ.get("FORCER") == "1":
        return True, "FORCÉ (hors fenêtre normale)"
    if maintenant.weekday() != JOUR_CIBLE:
        return False, f"pas lundi ({maintenant.strftime('%A')})"
    if not (HEURE_DEBUT_UTC <= maintenant.hour < HEURE_FIN_UTC):
        return False, f"hors séance ({maintenant.hour}h UTC)"
    return True, "en séance"


def _kraken() -> dict:
    req = urllib.request.Request(TICKERS, headers={"User-Agent": "scalping-radar/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    return {t.get("symbol"): t for t in data.get("tickers", [])}


def _spread_relatif(bid, ask) -> float | None:
    """⛔ ``None``, jamais 0.0 : un carnet illisible n'est pas un spread nul."""
    try:
        b, a = float(bid), float(ask)
    except (TypeError, ValueError):
        return None
    if b <= 0 or a <= 0 or a < b:
        return None
    return (a - b) / ((a + b) / 2) * 100.0


def _mt5_tick(pair: str) -> dict | None:
    """Tick du bridge MT5 réel. ``None`` si injoignable — jamais un prix inventé."""
    url = os.environ.get("MT5_BRIDGE_LIVE_URL", "")
    cle = os.environ.get("MT5_BRIDGE_LIVE_API_KEY", "")
    if not url:
        return None
    try:
        req = urllib.request.Request(url.rstrip("/") + "/tick/" + pair,
                                     headers={"X-API-Key": cle})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        return None


def collecte() -> int:
    maintenant = datetime.now(timezone.utc)
    ok, motif = _dans_la_fenetre(maintenant)
    if not ok:
        print(f"{maintenant.isoformat()} — {motif}, rien fait")
        return 0

    kr = _kraken()
    releve = {"t": maintenant.isoformat(), "motif": motif, "mesures": {}}
    for paire, sym in COMPARABLES + KRAKEN_SEUL:
        t = kr.get(sym) or {}
        sp_k = _spread_relatif(t.get("bid"), t.get("ask"))
        try:
            notionnel = float(t.get("vol24h") or 0) * float(t.get("indexPrice") or 0)
        except (TypeError, ValueError):
            notionnel = None
        entree = {"kraken_spread_pct": sp_k, "kraken_notionnel_24h": notionnel}

        if (paire, sym) in COMPARABLES:
            tick = _mt5_tick(paire)
            sp_m = _spread_relatif((tick or {}).get("bid"), (tick or {}).get("ask"))
            entree["mt5_spread_pct"] = sp_m
            # ⚠️ L'horodatage du tick MT5 dit si le marché est VRAIMENT ouvert.
            # Un tick de vendredi soir servi le lundi ressemble à un tick frais.
            entree["mt5_tick_time"] = (tick or {}).get("time")
        releve["mesures"][paire] = entree

    os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(releve, ensure_ascii=False) + "\n")
    print(f"{maintenant.isoformat()} — relevé écrit ({len(releve['mesures'])} instruments)")
    return 0


def _mediane(valeurs) -> float | None:
    v = [x for x in valeurs if x is not None]
    return statistics.median(v) if v else None


def bilan() -> int:
    maintenant = datetime.now(timezone.utc)
    jour = maintenant.date().isoformat()
    lignes = []
    try:
        with open(JOURNAL, encoding="utf-8") as f:
            for ligne in f:
                try:
                    d = json.loads(ligne)
                except Exception:
                    continue
                if str(d.get("t", "")).startswith(jour):
                    lignes.append(d)
    except FileNotFoundError:
        pass

    if not lignes:
        # ⛔ Pas de relevé n'est PAS « pas d'écart » : c'est une mesure qui n'a
        # pas eu lieu, et le dire est le minimum.
        corps = ("Aucun relevé aujourd'hui — la mesure n'a pas tourné.\n"
                 "Le verdict « Kraken hors crypto » reste donc SANS RÉPONSE, "
                 "et non « pas d'écart ».")
        return _poster("⚠️ Spreads hors crypto : aucune mesure", corps)

    par_paire: dict = {}
    for d in lignes:
        for paire, m in (d.get("mesures") or {}).items():
            par_paire.setdefault(paire, {"k": [], "m": [], "n": []})
            par_paire[paire]["k"].append(m.get("kraken_spread_pct"))
            par_paire[paire]["m"].append(m.get("mt5_spread_pct"))
            par_paire[paire]["n"].append(m.get("kraken_notionnel_24h"))

    corps = [f"{len(lignes)} relevés en séance, médianes :", ""]
    verdicts = []
    for paire, s in par_paire.items():
        mk, mm, mn = _mediane(s["k"]), _mediane(s["m"]), _mediane(s["n"])
        if mk is None:
            corps.append(f"• {paire} : Kraken illisible")
            continue
        if mm is None:
            corps.append(f"• {paire} : Kraken {mk:.4f} % · notionnel {mn or 0:,.0f} "
                         f"(pas de contrepartie MT5)")
            continue
        rapport = mk / mm if mm > 0 else None
        corps.append(f"• {paire} : Kraken {mk:.4f} % vs MT5 {mm:.4f} % "
                     + (f"— {rapport:.1f}× " + ("pire" if rapport > 1 else "MIEUX")
                        if rapport else ""))
        if rapport is not None:
            verdicts.append(rapport)

    corps.append("")
    if verdicts and min(verdicts) < 1.0:
        corps.append("🔑 Au moins un instrument est MOINS cher sur Kraken en séance : "
                     "la conclusion du 06/09 (« doublon plus cher ») ne tient pas "
                     "pour lui. À rejuger.")
    elif verdicts:
        corps.append(f"Verdict : Kraken reste plus cher partout ({min(verdicts):.1f}× "
                     f"à {max(verdicts):.1f}×). Le sujet « élargir Kraken hors crypto » "
                     "est clos pour la semaine — il ne reste que le WEEK-END, où MT5 "
                     "est fermé et Kraken seul ouvert.")
    corps.append("")
    corps.append("⚠️ Le spread ne dit pas tout : le funding et la distance de stop "
                 "comptent autant. Un coût en R comparé entre classes sans corriger "
                 "la distance de stop est faux.")
    return _poster("📊 Kraken vs MT5 hors crypto — mesure en séance", "\n".join(corps))


def _poster(titre: str, corps: str) -> int:
    jeton = os.environ.get("NOTIFY_TOKEN", "shdw_diaY5ZBXM1b4CjdwzN8kd572-ylWcbIg")
    url = ("https://app.scalping-radar.online/api/admin/notify-infra-telegram"
           f"?token={jeton}&channel=sales")
    charge = json.dumps({"title": titre, "body": corps,
                         "dedup_key": "spreads_hors_crypto",
                         "cooldown_seconds": 3600}).encode()
    if os.environ.get("DRY_RUN") == "1":
        print(f"[DRY_RUN] {titre}\n{corps}\n")
        return 0
    try:
        req = urllib.request.Request(url, data=charge,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"bilan posté, HTTP {r.status}")
        return 0
    except Exception as e:
        # ⛔ Un bilan qui n'arrive pas est un bilan qui n'existe pas. On le DIT.
        print(f"⚠️ ENVOI DU BILAN ÉCHOUÉ : {e}")
        print(f"{titre}\n{corps}")
        return 1


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--collecte"
    sys.exit(bilan() if mode == "--bilan" else collecte())
