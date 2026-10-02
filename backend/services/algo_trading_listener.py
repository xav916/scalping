"""Écoute et analyse le flux Algo Trading, remonte les modules à implémenter.

Messages forwarded du canal Algo Trading (@MQL5_EN ou similaire) sont reçus,
analysés pour extraire :
- Stratégie/indicator name
- Paires tradées
- Type (scalp, swing, hedge, etc.)
- Statistiques (win rate, drawdown, Sharpe)

Classés par :
- Utilité (nos paires? nos patterns? pertinent?)
- Faisabilité (effort, dépendances)
- Priorité (impact potentiel)

Remontés via Telegram si implémentation recommandée.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Paires et patterns qu'on trade activement (du CLAUDE.md Phase 1)
OUR_PAIRS = {
    "EUR/USD", "GBP/USD", "USD/JPY", "EUR/GBP", "USD/CHF", "AUD/USD", "USD/CAD",
    "EUR/JPY", "GBP/JPY", "XAU/USD", "XAG/USD", "BTC/USD", "ETH/USD",
    "SPX", "NDX", "WTI/USD",
}

OUR_ASSET_CLASSES = {"forex", "metal", "crypto", "equity_index", "energy"}

# Patterns qu'on maîtrise
OUR_PATTERNS = {
    "breakout", "momentum", "range", "mean_reversion", "engulfing",
    "pin_bar", "chaine", "cme_gap", "fvg", "bos",
}

# Indicateurs que nous utilisons
OUR_INDICATORS = {
    "atr", "rsi", "sma", "ema", "adx", "macd", "bollinger",
    "vix", "funding_rate", "funding", "cme", "gap",
}


class AlgoTradingMessage:
    """Structure d'un message Algo Trading analysé."""

    def __init__(self):
        self.raw_text: str = ""
        self.title: str = ""
        self.description: str = ""
        self.pairs_detected: set[str] = set()
        self.patterns_detected: set[str] = set()
        self.indicators_detected: set[str] = set()
        self.stats: dict[str, Any] = {}
        self.url: str = ""
        self.received_at: datetime = datetime.now(timezone.utc)

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "pairs": list(self.pairs_detected),
            "patterns": list(self.patterns_detected),
            "indicators": list(self.indicators_detected),
            "stats": self.stats,
            "url": self.url,
            "received_at": self.received_at.isoformat(),
        }


def analyze_algo_trading_message(text: str, url: str = "") -> AlgoTradingMessage:
    """Parse et analyse un message Algo Trading.

    Extrait :
    - Title (1ère ligne ou 1er phrase)
    - Pairs mentionnées (EUR/USD, BTC, XAU, etc.)
    - Patterns (breakout, momentum, etc.)
    - Indicateurs (RSI, ATR, Bollinger, etc.)
    - Stats (win rate %, drawdown, Sharpe, etc.)
    """
    msg = AlgoTradingMessage()
    msg.raw_text = text
    msg.url = url

    # Extraction du titre (1ère ligne non vide ou 1er capitalized phrase)
    lines = text.strip().split("\n")
    for line in lines:
        if line.strip() and len(line.strip()) > 5:
            msg.title = line.strip()[:100]
            break

    # Détection des paires (fuzzy matching)
    text_upper = text.upper()
    for pair in OUR_PAIRS:
        if pair.replace("/", "").upper() in text_upper or pair.upper() in text_upper:
            msg.pairs_detected.add(pair)

    # Détection des patterns (case-insensitive)
    for pattern in OUR_PATTERNS:
        if re.search(rf"\b{pattern}\b", text, re.IGNORECASE):
            msg.patterns_detected.add(pattern)

    # Détection des indicateurs
    for indicator in OUR_INDICATORS:
        if re.search(rf"\b{indicator}\b", text, re.IGNORECASE):
            msg.indicators_detected.add(indicator)

    # Extraction des stats (win rate, drawdown, Sharpe, etc.)
    stats = {}

    # Win rate (xx% ou xx.xx%)
    wr_match = re.search(r"(?:win\s*rate|wr|winrate)[:\s]+(\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE)
    if wr_match:
        stats["win_rate_pct"] = float(wr_match.group(1))

    # Drawdown (xx% ou xx.xx%)
    dd_match = re.search(r"(?:drawdown|dd|max\s*dd)[:\s]+(\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE)
    if dd_match:
        stats["max_drawdown_pct"] = float(dd_match.group(1))

    # Sharpe ratio
    sharpe_match = re.search(r"(?:sharpe|sharpe\s*ratio)[:\s]+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if sharpe_match:
        stats["sharpe_ratio"] = float(sharpe_match.group(1))

    # Profit factor
    pf_match = re.search(r"(?:profit\s*factor|pf)[:\s]+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if pf_match:
        stats["profit_factor"] = float(pf_match.group(1))

    # Return (% ou pct)
    ret_match = re.search(r"(?:return|return\s*rate|roi)[:\s]+(\d+(?:\.\d+)?)\s*%", text, re.IGNORECASE)
    if ret_match:
        stats["return_pct"] = float(ret_match.group(1))

    msg.stats = stats
    return msg


def evaluate_relevance(msg: AlgoTradingMessage) -> dict[str, Any]:
    """Évalue si le module devrait être implémenté.

    Scoring:
    - Utilité (nôtre pairs? patterns? priorité)
    - Faisabilité (effort estimé)
    - Impact potentiel
    """
    score = {
        "relevance": 0,  # 0-100
        "utility": 0,
        "feasibility": 0,
        "impact": 0,
        "recommendation": "skip",
        "reason": [],
    }

    # ─ Utilité : nos paires?
    if msg.pairs_detected:
        overlapping = msg.pairs_detected & OUR_PAIRS
        if overlapping:
            score["utility"] += 50
            score["reason"].append(f"Paires nôtres détectées: {overlapping}")

    # ─ Utilité : nos patterns?
    if msg.patterns_detected:
        overlapping = msg.patterns_detected & OUR_PATTERNS
        if overlapping:
            score["utility"] += 30
            score["reason"].append(f"Patterns connus: {overlapping}")

    # ─ Utilité : nos indicateurs?
    if msg.indicators_detected:
        overlapping = msg.indicators_detected & OUR_INDICATORS
        if overlapping:
            score["utility"] += 20
            score["reason"].append(f"Indicateurs utilisés: {overlapping}")

    # ─ Faisabilité : stats fortes = plus simple à implémenter
    if msg.stats:
        win_rate = msg.stats.get("win_rate_pct", 0)
        sharpe = msg.stats.get("sharpe_ratio", 0)
        dd = msg.stats.get("max_drawdown_pct", 100)

        if win_rate > 60:
            score["feasibility"] += 30
            score["reason"].append(f"Win rate fort: {win_rate}%")

        if sharpe > 1.0:
            score["feasibility"] += 20
            score["reason"].append(f"Sharpe ratio bon: {sharpe}")

        if dd < 20:
            score["feasibility"] += 20
            score["reason"].append(f"Drawdown contrôlé: {dd}%")

    # ─ Impact potentiel : asset classes new?
    if "cme_gap" in msg.patterns_detected or "gap" in msg.indicators_detected:
        score["impact"] += 40
        score["reason"].append("CME gap = nouveaux données utiles")

    if "funding" in msg.indicators_detected:
        score["impact"] += 25
        score["reason"].append("Funding rate = pertinent pour crypto")

    # ─ Score final
    score["relevance"] = min(100, score["utility"] + score["feasibility"] + score["impact"] // 2)

    # ─ Recommandation
    if score["relevance"] >= 70:
        score["recommendation"] = "implement"
    elif score["relevance"] >= 40:
        score["recommendation"] = "evaluate"
    else:
        score["recommendation"] = "skip"

    return score


def generate_implementation_prompt(msg: AlgoTradingMessage, eval: dict) -> str:
    """Génère un prompt prêt-à-coller pour Claude Code.

    Format Markdown que l'utilisateur peut copier/coller directement dans Claude Code
    pour implémenter le module.
    """
    title = msg.title or "Unknown Module"
    pairs = ", ".join(sorted(msg.pairs_detected)) if msg.pairs_detected else "N/A"
    patterns = ", ".join(sorted(msg.patterns_detected)) if msg.patterns_detected else "N/A"
    indicators = ", ".join(sorted(msg.indicators_detected)) if msg.indicators_detected else "N/A"

    # Stats summary
    stats_parts = []
    if msg.stats.get("win_rate_pct"):
        stats_parts.append(f"Win Rate: {msg.stats['win_rate_pct']:.1f}%")
    if msg.stats.get("max_drawdown_pct"):
        stats_parts.append(f"Max Drawdown: {msg.stats['max_drawdown_pct']:.1f}%")
    if msg.stats.get("sharpe_ratio"):
        stats_parts.append(f"Sharpe Ratio: {msg.stats['sharpe_ratio']:.2f}")
    if msg.stats.get("profit_factor"):
        stats_parts.append(f"Profit Factor: {msg.stats['profit_factor']:.2f}")
    stats_summary = " | ".join(stats_parts) if stats_parts else "No stats available"

    prompt = f"""# Implémentation: {title}

## Contexte
Source: MQL5 Trading Algorithmique (@mql5fr)
Relevance Score: {eval['relevance']}/100
Recommendation: {eval['recommendation'].upper()}

## Spécifications du module

### Pairs à supporter
{pairs}

### Patterns/Stratégies
{patterns}

### Indicateurs/Signaux
{indicators}

### Performances observées
{stats_summary}

## Description détaillée
{msg.raw_text[:500]}...

## Implémentation requise

### Architecture
- Intégrer dans le pipeline d'analyse existant (scheduler.py)
- Créer un service dédié dans backend/services/
- Passer par les portes de filtrage existantes (admission, whitelist, confiance, etc.)
- Envoyer via send_setup() vers les bridges MT5

### Features à implémenter
1. Détecteur de pattern/signal pour {patterns or 'ce pattern'}
2. Calculateur de score de confiance basé sur les statistiques observées
3. Intégration avec ml_predictor (si applicable)
4. Tests unitaires pour les cas nominaux et limites
5. Logging et monitoring

### Considérations de sécurité
- ✅ Tous les setups passent par les portes existantes (admission, whitelist, confiance)
- ✅ Demo-only au démarrage (mode paper)
- ✅ Validation des données entrantes
- ✅ Fail-safe si données manquantes

### Documentation requise
- Docstring complet du service
- Exemple d'utilisation dans les commentaires
- Notes sur les limitations et hypothèses

## Validation avant production
- [ ] Tests passent (100% coverage pour la logique de détection)
- [ ] Fonctionne sur 50+ candles historiques
- [ ] Score de confiance cohérent avec les stats observées
- [ ] Logging adéquat pour le troubleshooting
- [ ] Code review complétée

## Prochaines étapes
1. Implémenter le service
2. Écrire les tests
3. Intégrer au scheduler
4. Valider en démo
5. Monitoring sur 100+ trades avant production

---

### Notes additionnelles
- Relevance Score breakdown: {', '.join(eval['reason'])}
- Seuil de confiance recommandé: 60-70% pour démo, 95% pour live
- Horizon de trade: 5min (scalp) sauf indication contraire"""

    return prompt


async def format_telegram_alert(msg: AlgoTradingMessage, eval: dict) -> str:
    """Formate une alerte Telegram pour remontée.

    Exemple :
    🔧 MODULE TO IMPLEMENT: CME Gap Tracker
    Pairs: XAU/USD, BTC/USD
    Pattern: CME Gap
    Stats: Win Rate 83%, Drawdown 12%, Sharpe 1.45
    Relevance Score: 78/100
    ---
    Recommendation: IMPLEMENT
    Reason: ...
    """
    lines = []

    if eval["recommendation"] == "implement":
        lines.append("🔧 MODULE TO IMPLEMENT")
    elif eval["recommendation"] == "evaluate":
        lines.append("📋 MODULE TO EVALUATE")
    else:
        return ""  # Skip

    lines.append(f"**{msg.title}**\n")

    if msg.pairs_detected:
        lines.append(f"**Pairs:** {', '.join(sorted(msg.pairs_detected))}")

    if msg.patterns_detected:
        lines.append(f"**Patterns:** {', '.join(sorted(msg.patterns_detected))}")

    if msg.indicators_detected:
        lines.append(f"**Indicators:** {', '.join(sorted(msg.indicators_detected))}")

    if msg.stats:
        stats_str = ", ".join([
            f"WR {msg.stats.get('win_rate_pct', 0):.0f}%"
            if msg.stats.get("win_rate_pct") else "",
            f"DD {msg.stats.get('max_drawdown_pct', 0):.0f}%"
            if msg.stats.get("max_drawdown_pct") else "",
            f"Sharpe {msg.stats.get('sharpe_ratio', 0):.2f}"
            if msg.stats.get("sharpe_ratio") else "",
        ])
        stats_str = ", ".join([s for s in stats_str.split(", ") if s])
        if stats_str:
            lines.append(f"**Stats:** {stats_str}")

    lines.append(f"\n**Relevance:** {eval['relevance']}/100")
    lines.append(f"**Recommendation:** {eval['recommendation'].upper()}")

    if eval["reason"]:
        lines.append(f"\n**Reasons:**\n" + "\n".join(f"• {r}" for r in eval["reason"]))

    if msg.url:
        lines.append(f"\n[Source]({msg.url})")

    return "\n".join(lines)
