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

    Le cas indécidable — coût ou edge inconnu — se tranche différemment selon
    qu'il y a de l'argent en jeu :

    - ``auto_exec=True`` → **bloque**. Une route dont on ne sait pas mesurer
      la rentabilité ne prend pas d'argent réel. C'est exactement ce qui
      manquait quand la crypto a tourné 876 fois à perte.
    - ``auto_exec=False`` → **laisse passer**. En observation, rien n'est
      engagé et la porte n'a rien à arbitrer ; la bloquer priverait de la
      mesure qui permettra un jour d'ouvrir la route.
    """
    if cost_r is None or edge_r is None:
        return auto_exec
    if edge_r <= 0:
        return True
    return cost_r > EDGE_COST_MAX_SHARE * edge_r
