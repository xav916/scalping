"""Pourquoi l'or ne part pas : l'état des portes, des positions, des refus.

Demandé par Xavier le 2026-10-10. Il a posé **trois fois** la question
*« pourquoi je n'ai plus de trades lancés »*. Un `/trade` qui répond « rien ne
s'est passé » la contourne ; celui-ci y répond en **nommant** le blocage.

## ⛔ POURQUOI CE MODULE VIT DANS LE RADAR, ET PLUS DANS LE MONITEUR

Première version écrite dans `mt5-bridge-monitor`, qui interrogeait Telegram en
`getUpdates`. Mesuré le 2026-10-10 : le bot « IC MARKETS Trades » porte **déjà
un webhook** (`/api/telegram/sales-webhook`), et Telegram **refuse**
`getUpdates` tant qu'un webhook est actif :

```
409 Conflict: can't use getUpdates method while webhook is active
```

⇒ L'écouteur ne pouvait **rien** recevoir. Les messages de Xavier partaient
dans le webhook, c'est-à-dire **dans le radar**. Le diagnostic doit donc vivre
là où les messages arrivent.

⚠️ Et supprimer ce webhook pour faire marcher mon `getUpdates` aurait casse
une fonction existante (`recap`, `risque`, `gele`/`continue` y arrivent).

## Ce qu'il rend, et pourquoi chaque ligne

1. **l'état des deux portes horaires** — marché du courtier, fenêtre
   hebdomadaire. ⛔ Sans elles, le diagnostic remontait `verdict_blocker` un
   samedi, alors que la seule chose à savoir était « le marché est fermé » ;
2. **les positions en vie, RADAR et MAIN séparément** — les mélanger
   masquerait le signal : sa main gagne, le radar perd ;
3. **l'âge du dernier ordre du radar** ;
4. **le blocage dominant** des 30 dernières minutes, traduit en français.

⛔ Un courtier illisible **se dit** au lieu de valoir zéro : afficher « 0 »
quand on ne *peut pas* compter ferait croire que la place est libre. C'est le
défaut `max_positions_per_pair_indecidable`, qui a refusé **593** signaux le
09/10.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

MARQUE_TERMINAL = "MANUEL-TERM"
PAIRE = "XAU/USD"
DESTINATION = "admin_live"
FENETRE_REFUS_MIN = 30

MOTIFS_FR: dict[str, str] = {
    "heure_spread_defavorable": "hors des heures autorisees pour la paire",
    "pattern_not_allowed": "motif detecte non autorise sur cet horizon",
    "horizon_not_allowed": "horizon non autorise",
    "pair_not_whitelisted": "paire hors liste blanche du reel",
    "max_positions_per_pair": "plafond de positions atteint",
    "max_positions_per_pair_indecidable": "positions du courtier ILLISIBLES "
                                          "(defaut, pas un plafond)",
    "execution_globale_fermee": "execution desarmee (REM-002)",
    "below_confidence": "score sous le seuil",
    "market_closed": "marche ferme chez le courtier",
    "hors_fenetre_hebdo": "hors de ta fenetre hebdomadaire",
    "bridge_marge_insuffisante": "marge insuffisante chez le courtier",
    "bridge_plafond_risque": "plafond de risque du pont",
    "sl_too_close": "stop trop proche du cours",
    "price_divergence": "divergence de prix entre les sources",
    "pair_auto_paused": "paire mise en pause automatiquement",
    "chaine_non_armee": "chaine non armee",
    "verdict_blocker": "verdict de la chaine d'admission",
    "energy_pre_weekend_freeze": "gel energie avant le week-end",
    "bridge_doublon": "ordre en doublon",
    "daily_loss_cap": "plafond de perte journaliere du courtier",
}


def formater(live: dict | None, blocages: list | None,
             minutes_dernier: float | None, portes: dict | None = None) -> str:
    """Le texte du diagnostic. **Fonction pure** : c'est elle qu'on teste.

    ⛔ TEXTE BRUT, aucune emphase. Les codes de refus sont en snake_case
    (`verdict_blocker`) et le Markdown de Telegram lit un `_` comme le début
    d'une italique : l'envoi rendait `400 Can't find end of the entity` et
    Xavier **ne recevait rien**.
    """
    L: list[str] = []
    p = portes or {}
    if p.get("marche") is not None:
        L.append("- Marche de l'or : %s"
                 % ("ouvert" if p["marche"] else "FERME chez le courtier"))
    if p.get("fenetre") is not None:
        L.append("- Ta fenetre hebdo : %s"
                 % ("ouverte" if p["fenetre"] else "FERMEE"))
    if p.get("execution") is not None:
        L.append("- Execution (REM-002) : %s"
                 % ("armee" if p["execution"] else "DESARMEE"))

    tot = (live or {}).get("total")
    if tot is None:
        L.append("- Positions en vie : illisibles (courtier injoignable)")
    else:
        L.append("- Positions en vie : %s (radar %s, a la main %s)"
                 % (tot, (live or {}).get("radar", "?"),
                    (live or {}).get("main", "?")))

    if minutes_dernier is None:
        L.append("- Dernier ordre du radar : aucun enregistre")
    elif minutes_dernier < 60:
        L.append("- Dernier ordre du radar : il y a %d min"
                 % round(minutes_dernier))
    else:
        L.append("- Dernier ordre du radar : il y a %.1f h"
                 % (minutes_dernier / 60.0))

    if not blocages:
        L.append("- Aucun refus dans les %d dernieres minutes."
                 % FENETRE_REFUS_MIN)
    else:
        code, n = blocages[0]
        L.append("- Blocage dominant (%d min) : %s - %s, %s fois"
                 % (FENETRE_REFUS_MIN, code,
                    MOTIFS_FR.get(code, "motif non traduit"), n))
        if len(blocages) > 1:
            L.append("  puis " + ", ".join("%s (%s)" % (c, k)
                                           for c, k in blocages[1:3]))
    return "\n".join(L)


def portes() -> dict:
    """L'état des portes. ⛔ Illisible se TAIT au lieu d'inventer."""
    out: dict = {}
    maintenant = datetime.now(timezone.utc)
    try:
        from backend.services.market_hours import is_market_open_for
        out["marche"] = bool(is_market_open_for(PAIRE, maintenant))
    except Exception as e:  # noqa: BLE001
        logger.warning("diagnostic_or: horaires de marche illisibles (%s)", e)
    try:
        from backend.services import fenetre_hebdo
        out["fenetre"] = bool(fenetre_hebdo.ouverte())
    except Exception as e:  # noqa: BLE001
        logger.warning("diagnostic_or: fenetre hebdo illisible (%s)", e)
    try:
        from backend.services import global_execution_switch as g
        out["execution"] = str(g.status().get("decision")) == "ALLOW"
    except Exception as e:  # noqa: BLE001
        logger.warning("diagnostic_or: interrupteur illisible (%s)", e)
    return out


def lire(db: str) -> tuple[dict, list, float | None]:
    """`(live, blocages, minutes_depuis_dernier_ordre)`. Ne lève jamais."""
    live: dict = {}
    blocages: list = []
    minutes: float | None = None
    try:
        with sqlite3.connect(f"file:{Path(db)}?mode=ro", uri=True,
                             timeout=3) as c:
            r = c.execute(
                "SELECT SUM(CASE WHEN COALESCE(notes,'') = ? THEN 0 ELSE 1 END), "
                "       SUM(CASE WHEN COALESCE(notes,'') = ? THEN 1 ELSE 0 END), "
                "       COUNT(*) FROM personal_trades "
                "WHERE closed_at IS NULL AND destination_id = ? AND pair = ?",
                (MARQUE_TERMINAL, MARQUE_TERMINAL, DESTINATION, PAIRE)
            ).fetchone()
            if r is not None:
                live = {"radar": int(r[0] or 0), "main": int(r[1] or 0),
                        "total": int(r[2] or 0)}
            # ⛔ Borne calculee EN PYTHON : `created_at` est de l'ISO AVEC
            # fuseau, le comparer a datetime('now') ne filtrerait RIEN. Ce
            # depot a deja paye ce piege (`test_fenetres_sqlite`).
            borne = (datetime.now(timezone.utc)
                     - timedelta(minutes=FENETRE_REFUS_MIN)).isoformat()
            blocages = [(str(a), int(b)) for a, b in c.execute(
                "SELECT reason_code, COUNT(*) n FROM signal_rejections "
                "WHERE pair = ? AND created_at >= ? "
                "GROUP BY reason_code ORDER BY n DESC LIMIT 4",
                (PAIRE, borne))]
            r = c.execute(
                "SELECT MAX(created_at) FROM personal_trades "
                "WHERE destination_id = ? AND pair = ? "
                "  AND COALESCE(notes,'') <> ?",
                (DESTINATION, PAIRE, MARQUE_TERMINAL)).fetchone()
            if r and r[0]:
                t = datetime.fromisoformat(str(r[0]).replace("Z", "+00:00"))
                minutes = (datetime.now(timezone.utc)
                           - t).total_seconds() / 60.0
    except Exception as e:  # noqa: BLE001
        logger.warning("diagnostic_or: base illisible (%s)", e)
    return live, blocages, minutes


def chemin_base() -> str:
    """La base des trades. Même résolution que `journal_sondes` et les autres :
    une seule convention dans tout le dépôt."""
    return str(Path("/app/data/trades.db") if Path("/app").exists()
               else Path("data/trades.db"))


def texte(db: str | None = None) -> str:
    """Le diagnostic complet, prêt à envoyer."""
    live, blocages, minutes = lire(db or chemin_base())
    return formater(live, blocages, minutes, portes())
