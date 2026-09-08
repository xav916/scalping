"""Surveillance quotidienne de l'objectif sur l'or : le plus haut atteint.

Demandé par Xavier le 2026-09-08 : « implémenter l'amélioration quotidienne des
trades or en fonction de la médiane des valeurs et du lot ».

## Ce que ça surveille, et pourquoi ça n'est PAS un réglage automatique

Mesure du 08/09 sur 11 563 bougies M5 : le R moyen **croît** avec la distance de
l'objectif (0,75 R → −0,004 ; 1,50 R → +0,067 ; 1,80 R → +0,139 ; 2,50 R →
+0,190). L'objectif actuel de 1,8 R est donc **bien placé**, et le raccourcir
coûterait.

⛔ **Ré-optimiser l'objectif à chaque mesure serait du surajustement en boucle**
— l'erreur qui a tué l'étude CAC 40. Ce module ne règle rien : il **affiche** la
distribution du plus haut atteint, pour qu'une dérive DURABLE se voie.

🔑 Le signal de dérive : si la **médiane du plus haut atteint** glisse
durablement sous l'objectif, celui-ci devient inatteignable et il faudra le
rejuger — mais sur plusieurs semaines, pas sur une journée.

## ⚠️ Le lot, et pourquoi il figure ici

Le lot est **subi**, pas choisi : les trades or partent tous à 0,01, le plancher
du courtier. Le même 1,8 R vaut donc des euros très différents selon la distance
du stop. Afficher la médiane en R **et** en euros au lot réel est le seul moyen
de voir ce que l'objectif représente vraiment.
"""
from __future__ import annotations

import json
import logging
import os
import statistics as st
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

PREFIXE_OR = ("XAU",)
OBJECTIF_R = 1.8          # le R:R que pose `calculate_trade_setup`
MAX_TRADES = 60           # borne dure : ce module tourne dans le récap du soir
DELAI = 30


def _instant(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _bougies(base, entetes, symbole, debut, fin, cache):
    cle = (symbole, debut.date())
    if cle in cache:
        return cache[cle]
    q = urllib.parse.urlencode({
        "pair": symbole, "timeframe": "M5",
        "from": debut.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": fin.strftime("%Y-%m-%dT%H:%M:%SZ")})
    try:
        o = json.load(urllib.request.urlopen(
            urllib.request.Request(base + "/rates?" + q, headers=entetes),
            timeout=DELAI))
        b = o.get("bougies") or []
    except Exception as e:  # noqa: BLE001
        logger.debug(f"suivi_objectif_or: bougies indisponibles ({e})")
        b = []
    cache[cle] = b
    return b


def mesurer(jours: int = 30, destination: str = "admin_live") -> dict:
    """Distribution du plus haut atteint sur les trades or clôturés.

    Rend ``{"erreur": ...}`` plutôt qu'un tableau vide : ⛔ une absence de
    données et une absence de trades ne se lisent pas pareil.
    """
    try:
        import sqlite3

        from backend.services.destinations_registry import DESTINATIONS
        from backend.services.risk_eur import calculer
        from backend.services.trade_log_service import _DB_PATH
    except Exception as e:  # noqa: BLE001
        return {"erreur": f"modules indisponibles ({e})"}

    dest = DESTINATIONS.get(destination)
    if dest is None:
        return {"erreur": f"destination inconnue : {destination}"}
    try:
        base = os.environ[dest.url_env].rstrip("/")
        entetes = {getattr(dest, "key_header", None) or "X-API-Key":
                   os.environ[dest.key_env]}
    except KeyError:
        return {"erreur": "bridge non configuré"}

    depuis = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    con = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    # ⛔ Borne au format ISO du stockage (avec `T`) : `datetime('now',...)`
    # rendrait une espace et la fenêtre ne filtrerait rien.
    lignes = con.execute(
        "SELECT pair, direction, entry_price e, stop_loss sl, size_lot v, "
        "       created_at, closed_at "
        "FROM personal_trades WHERE closed_at IS NOT NULL AND created_at >= ? "
        "  AND destination_id = ? AND entry_price > 0 AND stop_loss > 0 "
        "ORDER BY closed_at DESC LIMIT ?",
        (depuis, destination, MAX_TRADES)).fetchall()

    cache: dict = {}
    mfes_r, mfes_eur, lots, risques = [], [], [], []
    for r in lignes:
        pair = (r["pair"] or "").upper()
        if not pair.startswith(PREFIXE_OR):
            continue
        ouvert, ferme = _instant(r["created_at"]), _instant(r["closed_at"])
        dist = abs(r["e"] - r["sl"])
        if not (ouvert and ferme) or dist <= 0:
            continue
        sens = 1 if (r["direction"] or "").lower() == "buy" else -1
        try:
            c = calculer(pair=r["pair"], entry=r["e"], sl=r["sl"],
                         tp=r["e"] + sens * dist * OBJECTIF_R,
                         volume=r["v"] or 0,
                         bridge_type=getattr(dest, "bridge_type", "mt5"))
            risque_eur = c.get("risque_eur")
        except Exception:  # noqa: BLE001
            risque_eur = None

        b = _bougies(base, entetes, pair.replace("/", ""), ouvert,
                     ouvert + timedelta(days=7), cache)
        if not b:
            continue
        # ⛔ On s'arrête au STOP : au-delà, on mesurerait l'amplitude du marché
        # et non le chemin du trade. Défaut vu le 08/09 — il rendait des +13 R
        # sur un objectif à 1,8 R.
        mfe = None
        for x in b:
            q_ = _instant(x["t"])
            if q_ is None or q_ < ouvert:
                continue
            favorable = max(sens * (x["h"] - r["e"]), sens * (x["l"] - r["e"])) / dist
            defavorable = min(sens * (x["h"] - r["e"]), sens * (x["l"] - r["e"])) / dist
            mfe = favorable if mfe is None else max(mfe, favorable)
            if defavorable <= -1.0 or favorable >= OBJECTIF_R or q_ > ferme:
                break
        if mfe is None:
            continue
        mfes_r.append(mfe)
        if risque_eur:
            mfes_eur.append(mfe * risque_eur)
            risques.append(risque_eur)
        if r["v"]:
            lots.append(float(r["v"]))

    if not mfes_r:
        return {"erreur": "aucun trade or mesurable sur la fenêtre",
                "jours": jours}

    n = len(mfes_r)
    return {
        "n": n, "jours": jours, "objectif_R": OBJECTIF_R,
        "mediane_R": st.median(mfes_r),
        "mediane_eur": st.median(mfes_eur) if mfes_eur else None,
        "risque_median_eur": st.median(risques) if risques else None,
        "lot_median": st.median(lots) if lots else None,
        "pct_1R": 100.0 * sum(1 for m in mfes_r if m >= 1.0) / n,
        "pct_objectif": 100.0 * sum(1 for m in mfes_r if m >= OBJECTIF_R) / n,
    }


def lignes(m: dict | None) -> list[str]:
    """Le bloc du récap. Fonction PURE."""
    if not m:
        return []
    titre = "🥇 Or — le plus haut atteint"
    if m.get("erreur"):
        return [titre, f"  ❓ {m['erreur']} — ce n'est pas « rien à signaler »."]

    out = [titre, f"  ({m['n']} trades sur {m['jours']} j)"]
    med = m["mediane_R"]
    ligne = f"• Médiane : {med:+.2f} R"
    if m.get("mediane_eur") is not None:
        ligne += f"  ≈ {m['mediane_eur']:.2f} €"
    if m.get("lot_median") is not None:
        ligne += f"  (lot {m['lot_median']:g}"
        if m.get("risque_median_eur") is not None:
            ligne += f", risque {m['risque_median_eur']:.2f} €"
        ligne += ")"
    out.append(ligne)
    out.append(f"• Atteignent +1,0 R : {m['pct_1R']:.0f} %"
               f"  ·  l'objectif {m['objectif_R']:.1f} R : {m['pct_objectif']:.0f} %")

    # ⛔ Un verdict, jamais un réglage : ré-optimiser l'objectif à chaque
    # mesure serait du surajustement en boucle.
    if med < m["objectif_R"] * 0.55:
        out.append("⚠️ La médiane est loin sous l'objectif. Si ça DURE plusieurs "
                   "semaines, l'objectif sera à rejuger — pas sur un jour.")
    else:
        out.append("✅ Objectif cohérent avec ce que le marché offre. "
                   "Mesuré le 08/09 : le raccourcir coûte.")
    return out
