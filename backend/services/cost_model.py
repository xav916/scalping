"""Structure de cout par destination, exprimee en unites de risque (R).

Jusqu'au 2026-08-04, aucun modele de cout n'existait dans le chemin de
trading : `commission` n'apparaissait que dans le programme de parrainage,
`maker`/`taker` seulement comme features de scoring. Le dispatch decidait
sans jamais consulter un prix de revient.

Trois incidents en decoulent directement — 876 trades crypto perdants, la
route xStocks construite puis mesuree, la Voie C forex codee entierement
avant de decouvrir que la commission valait 383 % du TP vise.

Deux structures de cout, qui ne se comportent pas pareil :

- **proportionnelle** (crypto) — un pourcentage du notionnel par jambe.
  Exprimee en R, elle **ne depend pas de la taille de position** : le
  risque se simplifie. C'est la raison mathematique pour laquelle plus de
  capital ne sauvera jamais la crypto chez Kraken.
- **fixe** (IBKR) — un montant par ordre, avec un plancher broker. En R,
  elle decroit quand le risque par trade grandit : elle s'ameliore donc
  mecaniquement avec le capital.

Module volontairement pur : ni base, ni reseau, ni horloge.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Cout d'un aller-retour sur une destination.

    proportional_rate_per_leg
        Fraction du notionnel prelevee **par jambe** (0,0005 = 0,05 %).
    fixed_per_order
        Montant fixe par ordre, dans la devise du compte.
    min_per_order
        Plancher broker par ordre. Le cout fixe retenu est le plus grand
        des deux.
    """

    proportional_rate_per_leg: float = 0.0
    fixed_per_order: float = 0.0
    min_per_order: float = 0.0
    funding_interval_hours: float = 0.0
    """Périodicité de l'échéance de funding, en heures. ``0.0`` = route sans
    funding (CFD MT5, compte cash IBKR). Kraken Futures : 1,0."""


def cost_in_r(
    entry: float,
    stop_loss: float,
    model: CostModel,
    risk_money: float | None = None,
) -> float | None:
    """Cout de l'aller-retour, exprime en unites de risque.

    Retourne ``None`` — jamais ``0.0`` — quand le cout n'est pas calculable :
    entree absente, stop colle a l'entree, ou composante fixe declaree sans
    que le risque en devise soit connu. « Inconnu » et « nul » sont deux
    etats distincts, et les confondre ferait passer une route non mesuree
    pour une route gratuite.
    """
    if not entry or entry <= 0:
        return None
    distance = abs(entry - stop_loss)
    if distance <= 0:
        return None

    # Part proportionnelle : (notionnel / risque) × taux × 2 jambes.
    # notionnel / risque = entry / distance — le risque en devise se
    # simplifie, d'ou l'independance a la taille de position.
    cout = (entry / distance) * model.proportional_rate_per_leg * 2.0

    # Part fixe : deux ordres (entree + sortie), plancher broker applique.
    par_ordre = max(model.fixed_per_order, model.min_per_order)
    if par_ordre > 0:
        if not risk_money or risk_money <= 0:
            # Une composante fixe est declaree mais le risque en devise est
            # inconnu : le cout n'est pas calculable. Retourner la seule part
            # proportionnelle sous-estimerait la route.
            return None
        cout += (par_ordre * 2.0) / risk_money

    return cout


def holding_cost_in_r(
    entry: float,
    stop_loss: float,
    rate_per_interval: float | None,
    interval_hours: float,
    holding_hours: float | None,
) -> float | None:
    """Coût de **détention** d'une position, exprimé en unités de risque.

    Le scalping ne payait pas ce coût : une position ouverte et fermée dans
    la même heure ne traverse aucune échéance de funding. À 4h et 1d, si.

    Même structure que la part proportionnelle de ``cost_in_r`` — le risque
    en devise se simplifie, donc le coût **ne dépend pas de la taille de
    position**. Plus de capital ne sauve pas une route dont le portage est
    trop cher.

    ⚠️ **Plancher à zéro.** Un funding négatif rapporte au détenteur d'une
    position longue. Le compter comme un gain financerait une position sur
    une recette qui peut s'inverser d'une heure à l'autre. On ne facture pas
    un crédit, on l'ignore.

    Retourne ``None`` — jamais ``0.0`` — dès qu'une composante manque. Une
    durée de détention inconnue est le cas nominal tant qu'aucun échantillon
    propre postérieur au 2026-08-04 n'existe.
    """
    if rate_per_interval is None or holding_hours is None:
        return None
    if not entry or entry <= 0:
        return None
    distance = abs(entry - stop_loss)
    if distance <= 0:
        return None
    if interval_hours is None or interval_hours <= 0:
        return None
    if holding_hours < 0:
        return None

    echeances = holding_hours / interval_hours
    cout = (entry / distance) * rate_per_interval * echeances
    return max(0.0, cout)


# Échantillon minimal pour qu'une durée de détention médiane veuille dire
# quelque chose. Même ordre de grandeur que les autres seuils d'échantillon
# du projet, et volontairement au-dessus du bruit d'une poignée de trades.
HOLDING_MIN_SAMPLE = 30

# Tout le shadow antérieur à cette date est à écarter : la déduplication
# comptait un même setup jusqu'à 960 fois (corrigé le 2026-08-04). L'inclure
# biaiserait toute médiane vers le comportement des setups sur-représentés.
SHADOW_CLEAN_SINCE = "2026-08-05"


def median_holding_hours(
    system_id: str,
    min_sample: int = HOLDING_MIN_SAMPLE,
    db_path=None,
) -> float | None:
    """Durée de détention médiane observée pour un système, en heures.

    Mesurée sur les setups shadow **résolus** et **postérieurs à
    l'échantillon propre**. Retourne ``None`` sous ``min_sample`` : une
    médiane sur trois trades n'est pas une mesure, et l'inventer ferait
    passer une route non mesurée pour une route évaluable.
    """
    import sqlite3
    from pathlib import Path

    chemin = db_path
    if chemin is None:
        chemin = Path("/app/data/trades.db") if Path("/app").exists() else Path("trades.db")
    try:
        with sqlite3.connect(chemin) as c:
            rows = c.execute(
                """SELECT (julianday(exit_at) - julianday(bar_timestamp)) * 24.0
                     FROM shadow_setups
                    WHERE system_id = ?
                      AND outcome IS NOT NULL
                      AND exit_at IS NOT NULL
                      AND substr(bar_timestamp, 1, 10) >= ?
                 ORDER BY 1""",
                (system_id, SHADOW_CLEAN_SINCE),
            ).fetchall()
    except Exception:
        return None

    durees = [r[0] for r in rows if r[0] is not None and r[0] >= 0]
    if len(durees) < min_sample:
        return None
    n = len(durees)
    milieu = n // 2
    if n % 2:
        return float(durees[milieu])
    return float((durees[milieu - 1] + durees[milieu]) / 2.0)


# Part maximale de l'edge brut que les frais peuvent consommer.
#
# Règle posée par Xavier le 2026-08-04 après la mesure xStocks, et vérifiée
# a posteriori sur les trois routes déjà arbitrées : MT5 passe à 17 %,
# Kraken échoue à 262 %, xStocks échoue à 154 %.
EDGE_COST_MAX_SHARE = 0.30


def exceeds_edge(
    cost_r: float | None,
    edge_r: float | None,
    auto_exec: bool,
) -> bool:
    """``True`` si les frais interdisent d'envoyer ce signal.

    L'ordre d'évaluation garantit que :

    1. **Route morte** — edge mesuré à zéro ou négatif → toujours bloquer,
       quel que soit le coût ou l'argent en jeu. Une route sans rentabilité
       observée n'est pas un edge inconnu.
    2. **Cas indécidable** — coût ou edge inconnu → trancher selon l'argent réel :
       ``auto_exec=True`` bloque (aucune route non mesurable sans argent réel),
       ``auto_exec=False`` laisse passer (observation ne risque rien).
    3. **Route normale** — coût et edge connus et positifs → bloquer si coût
       dépasse 30 % de l'edge.
    """
    if edge_r is not None and edge_r <= 0:
        return True                    # route morte : bloque toujours
    if cost_r is None or edge_r is None:
        return auto_exec               # indécidable : argent réel = bloque
    return cost_r > EDGE_COST_MAX_SHARE * edge_r
