# Modèle de coût par destination — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Le dispatch refuse tout signal dont les frais dépassent 30 % de l'edge brut mesuré de sa destination.

**Architecture:** Un module `cost_model.py` déclare la structure de coût de chaque route (proportionnelle, fixe, ou spread absorbé) et convertit ce coût en unités de risque (R). `BridgeConfig` porte ce modèle et l'edge mesuré de la destination. `_check_rejection` interroge les deux avant tout envoi et renvoie `fees_exceed_edge`.

**Tech Stack:** Python 3, dataclasses gelées, pytest, SQLite.

## Global Constraints

- Aucun code de refus ne commence par un souligné. Les codes privés `_xxx` sont supprimés silencieusement de `signal_rejections` — c'est ce qui a rendu AAPL invisible deux jours.
- Une valeur inconnue vaut `None`, jamais `0.0`. « Inconnu » et « nul » sont deux états distincts.
- Vérifier les seuils par `resolve_destinations`, jamais par les attributs de `config.settings`.
- La suite complète doit passer avant chaque commit — 1489 verts au démarrage de ce plan.
- Commentaires et docstrings en français, comme le reste du dépôt.
- Ne jamais utiliser `rsync --delete` ni réécrire `/opt/scalping/.env` en bloc.

## Provenance des chiffres

Ces trois mesures viennent de la production et servent de tests de référence.
Le modèle est faux s'il ne les reproduit pas.

| route | frais mesurés | edge brut mesuré | verdict rendu en prod |
|---|---|---|---|
| MT5 IC Markets | 0,022 R | 0,129 R (`range_bounce`) | accepté — 17 % de l'edge |
| Kraken crypto | 0,288 R | 0,110 R | refusé — 2,6× l'edge |
| xStocks Kraken | 0,199 R | 0,129 R | refusé — 1,54× l'edge |

Kraken se recalcule : SL médian 0,347 % du prix, 0,05 % de frais par jambe.
`(1 / 0,00347) × 0,0005 × 2 = 0,288 R`. Le risque se simplifie — **le coût
proportionnel en R ne dépend pas de la taille de position.**

⚠️ Ces trois lignes servent de tests unitaires du modèle (tâche 3). Elles ne
sont PAS toutes déclarées comme configuration de destination : seule Kraken
l'est. MT5 reste non déclarée, cf. tâche 4 — sa distance de stop varie d'un
facteur 27 selon la paire, aucun taux unique ne la décrit.

## File Structure

- `backend/services/cost_model.py` — **créé**. Structure de coût et conversion en R. Aucune dépendance à la base ni au réseau : pure fonction, donc testable sans fixture.
- `backend/services/bridge_destinations.py` — **modifié**. Deux champs sur `BridgeConfig`, renseignés dans chaque `_admin_*_destination()`.
- `backend/services/mt5_bridge.py` — **modifié** dans `_check_rejection` (ligne 214), à la suite des portes existantes.
- `backend/tests/test_cost_model.py` — **créé**.
- `backend/tests/test_dispatch_porte_de_cout.py` — **créé**.

---

### Task 1 : Le coût proportionnel

**Files:**
- Create: `backend/services/cost_model.py`
- Test: `backend/tests/test_cost_model.py`

**Interfaces:**
- Consomme : rien.
- Produit : `CostModel(proportional_rate_per_leg, fixed_per_order, min_per_order)` et `cost_in_r(entry, stop_loss, model, risk_money=None) -> float | None`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# backend/tests/test_cost_model.py
"""Le modèle de coût doit reproduire les mesures faites en production."""
from __future__ import annotations

import pytest


def test_le_cout_proportionnel_reproduit_la_mesure_kraken():
    """SL médian 0,347 % du prix, 0,05 % de frais par jambe → 0,288 R.

    Chiffre mesuré le 2026-08-04 sur 876 trades réels.
    """
    from backend.services.cost_model import CostModel, cost_in_r

    kraken = CostModel(proportional_rate_per_leg=0.0005)
    entry = 1000.0
    stop_loss = 1000.0 * (1 - 0.00347)

    cout = cost_in_r(entry=entry, stop_loss=stop_loss, model=kraken)

    assert cout == pytest.approx(0.288, abs=0.002)


def test_le_cout_proportionnel_ne_depend_pas_de_la_taille():
    """Le risque se simplifie : c'est ce qui rend Kraken insauvable par le capital."""
    from backend.services.cost_model import CostModel, cost_in_r

    kraken = CostModel(proportional_rate_per_leg=0.0005)
    entry, stop_loss = 1000.0, 996.53

    petit = cost_in_r(entry=entry, stop_loss=stop_loss, model=kraken, risk_money=10.0)
    gros = cost_in_r(entry=entry, stop_loss=stop_loss, model=kraken, risk_money=10_000.0)

    assert petit == pytest.approx(gros)


def test_un_stop_nul_ne_produit_pas_une_division_par_zero():
    from backend.services.cost_model import CostModel, cost_in_r

    assert cost_in_r(entry=100.0, stop_loss=100.0,
                     model=CostModel(proportional_rate_per_leg=0.0005)) is None
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `python -m pytest backend/tests/test_cost_model.py -q`
Expected: FAIL avec `ModuleNotFoundError: No module named 'backend.services.cost_model'`

- [ ] **Step 3: Écrire l'implémentation minimale**

```python
# backend/services/cost_model.py
"""Structure de coût par destination, exprimée en unités de risque (R).

Jusqu'au 2026-08-04, aucun modèle de coût n'existait dans le chemin de
trading : `commission` n'apparaissait que dans le programme de parrainage,
`maker`/`taker` seulement comme features de scoring. Le dispatch décidait
sans jamais consulter un prix de revient.

Trois incidents en découlent directement — 876 trades crypto perdants, la
route xStocks construite puis mesurée, la Voie C forex codée entièrement
avant de découvrir que la commission valait 383 % du TP visé.

Deux structures de coût, qui ne se comportent pas pareil :

- **proportionnelle** (crypto) — un pourcentage du notionnel par jambe.
  Exprimée en R, elle **ne dépend pas de la taille de position** : le
  risque se simplifie. C'est la raison mathématique pour laquelle plus de
  capital ne sauvera jamais la crypto chez Kraken.
- **fixe** (IBKR) — un montant par ordre, avec un plancher broker. En R,
  elle décroît quand le risque par trade grandit : elle s'améliore donc
  mécaniquement avec le capital.

Module volontairement pur : ni base, ni réseau, ni horloge.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Coût d'un aller-retour sur une destination.

    proportional_rate_per_leg
        Fraction du notionnel prélevée **par jambe** (0,0005 = 0,05 %).
    fixed_per_order
        Montant fixe par ordre, dans la devise du compte.
    min_per_order
        Plancher broker par ordre. Le coût fixe retenu est le plus grand
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
    """Coût de l'aller-retour, exprimé en unités de risque.

    Retourne ``None`` — jamais ``0.0`` — quand le coût n'est pas calculable :
    entrée absente, stop collé à l'entrée, ou composante fixe déclarée sans
    que le risque en devise soit connu. « Inconnu » et « nul » sont deux
    états distincts, et les confondre ferait passer une route non mesurée
    pour une route gratuite.
    """
    if not entry or entry <= 0:
        return None
    distance = abs(entry - stop_loss)
    if distance <= 0:
        return None

    # Part proportionnelle : (notionnel / risque) × taux × 2 jambes.
    # notionnel / risque = entry / distance — le risque en devise se
    # simplifie, d'où l'indépendance à la taille de position.
    cout = (entry / distance) * model.proportional_rate_per_leg * 2.0

    return cout
```

- [ ] **Step 4: Lancer le test pour vérifier qu'il passe**

Run: `python -m pytest backend/tests/test_cost_model.py -q`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/services/cost_model.py backend/tests/test_cost_model.py
git commit -m "Modele de cout : composante proportionnelle en unites de risque"
```

---

### Task 2 : La composante fixe

**Files:**
- Modify: `backend/services/cost_model.py`
- Test: `backend/tests/test_cost_model.py`

**Interfaces:**
- Consomme : `CostModel`, `cost_in_r` de la tâche 1.
- Produit : `cost_in_r` gère désormais `fixed_per_order` et `min_per_order`, et exige `risk_money` dès qu'une composante fixe est déclarée.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# à ajouter dans backend/tests/test_cost_model.py

def test_le_cout_fixe_decroit_quand_le_risque_grandit():
    """C'est ce qui rend IBKR débloquable par le capital, contrairement à Kraken."""
    from backend.services.cost_model import CostModel, cost_in_r

    ibkr = CostModel(fixed_per_order=1.0, min_per_order=1.0)

    petit = cost_in_r(entry=100.0, stop_loss=99.0, model=ibkr, risk_money=5.0)
    gros = cost_in_r(entry=100.0, stop_loss=99.0, model=ibkr, risk_money=50.0)

    assert petit == pytest.approx(0.4)   # 2 USD sur 5 de risque
    assert gros == pytest.approx(0.04)   # 2 USD sur 50 de risque
    assert gros < petit


def test_le_plancher_broker_l_emporte_sur_le_montant_par_ordre():
    from backend.services.cost_model import CostModel, cost_in_r

    modele = CostModel(fixed_per_order=0.20, min_per_order=1.0)
    cout = cost_in_r(entry=100.0, stop_loss=99.0, model=modele, risk_money=10.0)

    assert cout == pytest.approx(0.2)  # 2 × 1,0 sur 10 de risque


def test_un_cout_fixe_sans_risque_connu_vaut_inconnu():
    """Ne jamais retourner 0.0 : une route non mesurable n'est pas gratuite."""
    from backend.services.cost_model import CostModel, cost_in_r

    modele = CostModel(fixed_per_order=1.0)
    assert cost_in_r(entry=100.0, stop_loss=99.0, model=modele, risk_money=None) is None


def test_les_deux_composantes_s_additionnent():
    from backend.services.cost_model import CostModel, cost_in_r

    modele = CostModel(proportional_rate_per_leg=0.0005, fixed_per_order=1.0)
    cout = cost_in_r(entry=100.0, stop_loss=99.0, model=modele, risk_money=10.0)

    # proportionnel : (100/1) × 0,0005 × 2 = 0,1 R ; fixe : 2/10 = 0,2 R
    assert cout == pytest.approx(0.3)
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest backend/tests/test_cost_model.py -q`
Expected: FAIL — le coût fixe est ignoré, `test_le_cout_fixe_decroit_quand_le_risque_grandit` retourne `0.0`.

- [ ] **Step 3: Écrire l'implémentation**

Remplacer la fin de `cost_in_r` (le bloc `cout = ...` puis `return cout`) par :

```python
    # Part proportionnelle : (notionnel / risque) × taux × 2 jambes.
    # notionnel / risque = entry / distance — le risque en devise se
    # simplifie, d'où l'indépendance à la taille de position.
    cout = (entry / distance) * model.proportional_rate_per_leg * 2.0

    # Part fixe : deux ordres (entrée + sortie), plancher broker appliqué.
    par_ordre = max(model.fixed_per_order, model.min_per_order)
    if par_ordre > 0:
        if not risk_money or risk_money <= 0:
            # Une composante fixe est déclarée mais le risque en devise est
            # inconnu : le coût n'est pas calculable. Retourner la seule part
            # proportionnelle sous-estimerait la route.
            return None
        cout += (par_ordre * 2.0) / risk_money

    return cout
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest backend/tests/test_cost_model.py -q`
Expected: PASS — 7 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/services/cost_model.py backend/tests/test_cost_model.py
git commit -m "Modele de cout : composante fixe, sensible au capital"
```

---

### Task 3 : La décision

**Files:**
- Modify: `backend/services/cost_model.py`
- Test: `backend/tests/test_cost_model.py`

**Interfaces:**
- Consomme : `cost_in_r` des tâches 1 et 2.
- Produit : `EDGE_COST_MAX_SHARE: float = 0.30` et `exceeds_edge(cost_r: float | None, edge_r: float | None, auto_exec: bool) -> bool`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# à ajouter dans backend/tests/test_cost_model.py

def test_les_trois_verdicts_rendus_en_production_sont_reproduits():
    """MT5 accepté, Kraken refusé, xStocks refusée — mesures du 2026-08-04."""
    from backend.services.cost_model import exceeds_edge

    assert exceeds_edge(0.022, 0.129, auto_exec=True) is False   # MT5, 17 %
    assert exceeds_edge(0.288, 0.110, auto_exec=True) is True    # Kraken, 262 %
    assert exceeds_edge(0.199, 0.129, auto_exec=True) is True    # xStocks, 154 %


def test_le_seuil_est_bien_a_trente_pour_cent():
    from backend.services.cost_model import EDGE_COST_MAX_SHARE, exceeds_edge

    assert EDGE_COST_MAX_SHARE == 0.30
    assert exceeds_edge(0.0299, 0.10, auto_exec=True) is False
    assert exceeds_edge(0.0301, 0.10, auto_exec=True) is True


def test_un_edge_inconnu_bloque_l_argent_reel():
    """Une destination sans edge mesuré ne peut pas passer en AUTO_EXEC."""
    from backend.services.cost_model import exceeds_edge

    assert exceeds_edge(0.02, None, auto_exec=True) is True


def test_un_edge_inconnu_laisse_passer_l_observation():
    """En TELEGRAM aucun argent n'est engagé : la porte n'a rien à arbitrer."""
    from backend.services.cost_model import exceeds_edge

    assert exceeds_edge(0.02, None, auto_exec=False) is False


def test_un_cout_inconnu_bloque_l_argent_reel():
    from backend.services.cost_model import exceeds_edge

    assert exceeds_edge(None, 0.129, auto_exec=True) is True
    assert exceeds_edge(None, 0.129, auto_exec=False) is False


def test_un_edge_nul_ou_negatif_bloque():
    """Un edge mesuré à zéro n'est pas un edge inconnu : c'est une route morte."""
    from backend.services.cost_model import exceeds_edge

    assert exceeds_edge(0.001, 0.0, auto_exec=True) is True
    assert exceeds_edge(0.001, -0.05, auto_exec=True) is True
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest backend/tests/test_cost_model.py -q`
Expected: FAIL avec `ImportError: cannot import name 'exceeds_edge'`

- [ ] **Step 3: Écrire l'implémentation**

Ajouter à la fin de `backend/services/cost_model.py` :

```python
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
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest backend/tests/test_cost_model.py -q`
Expected: PASS — 13 tests.

- [ ] **Step 5: Lancer la suite complète**

Run: `python -m pytest backend/tests -q`
Expected: 1489 passed minimum, 4 skipped.

- [ ] **Step 6: Commit**

```bash
git add backend/services/cost_model.py backend/tests/test_cost_model.py
git commit -m "Modele de cout : la decision, frais > 30 % de l'edge"
```

---

### Task 4 : Déclarer coût et edge par destination

**Files:**
- Modify: `backend/services/bridge_destinations.py` (dataclass `BridgeConfig`, puis chaque `_admin_*_destination()`)
- Test: `backend/tests/test_dispatch_porte_de_cout.py`

**Interfaces:**
- Consomme : `CostModel` de la tâche 1.
- Produit : `BridgeConfig.cost_model: CostModel | None` et `BridgeConfig.expected_edge_r: float | None`, lisibles depuis `resolve_destinations`.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# backend/tests/test_dispatch_porte_de_cout.py
"""La porte de coût au dispatch (2026-08-04).

Vérifié par `resolve_destinations`, jamais par les attributs de settings :
`MT5_BRIDGE_LEGACY_MIN_CONFIDENCE` passe par `os.getenv` sans `config.settings`,
et le seuil per-user vit en base. Lire les settings donnerait une réponse
fausse.
"""
from __future__ import annotations


def test_les_destinations_portent_un_modele_de_cout():
    from backend.services.bridge_destinations import BridgeConfig

    champs = BridgeConfig.__dataclass_fields__
    assert "cost_model" in champs
    assert "expected_edge_r" in champs


def test_le_defaut_est_inconnu_pas_gratuit():
    """Une destination qui ne déclare rien ne doit pas passer pour gratuite."""
    from backend.services.bridge_destinations import BridgeConfig

    dest = BridgeConfig(
        destination_id="test",
        user_id=None,
        bridge_url="http://x",
        bridge_api_key="k",
        min_confidence=50.0,
        allowed_asset_classes=frozenset({"forex"}),
        auto_exec_enabled=True,
    )
    assert dest.cost_model is None
    assert dest.expected_edge_r is None
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest backend/tests/test_dispatch_porte_de_cout.py -q`
Expected: FAIL — `assert 'cost_model' in champs`

- [ ] **Step 3: Ajouter les deux champs**

Dans `backend/services/bridge_destinations.py`, à la fin des champs de `BridgeConfig` (juste après `leverage: int | None = None`) :

```python
    # ── Coût et edge (2026-08-04) ────────────────────────────────────
    # `cost_model` décrit ce que coûte un aller-retour sur cette route.
    # `expected_edge_r` est l'edge brut MESURÉ de la population admise, en
    # unités de risque. Les deux à None = route non mesurée : elle ne peut
    # pas prendre d'argent réel, mais reste observable en TELEGRAM.
    #
    # ⚠️ Ne jamais mettre 0.0 pour « on ne sait pas ». Un coût nul rendrait
    # n'importe quelle route éligible, un edge nul la condamnerait à tort.
    cost_model: CostModel | None = None
    expected_edge_r: float | None = None
```

Et l'import en tête de fichier :

```python
from backend.services.cost_model import CostModel
```

- [ ] **Step 4: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest backend/tests/test_dispatch_porte_de_cout.py -q`
Expected: PASS — 2 tests.

- [ ] **Step 5: Renseigner les destinations réelles**

**`_admin_live_destination()` et `_admin_legacy_destination()` : ne rien
déclarer.** Laisser `cost_model` et `expected_edge_r` à leur défaut `None`.

La raison est une mesure, pas une prudence de principe. La distance de stop
varie d'un facteur 27 selon la paire — mesuré le 2026-08-04 sur 1 352 trades
auto : EUR/USD 0,073 %, XAU/USD 0,151 %, ETH/USD 0,457 %, DOT/USD 1,99 %.
Or le coût proportionnel en R vaut `(entry / distance) × taux × 2` : à taux
égal, il varie donc dans le même rapport. Un taux unique pour `admin_live`,
qui mélange forex, métaux et actions CFD, décrirait correctement au plus une
de ces classes.

De plus, les 0,022 R d'IC Markets ont été mesurés sur les **actions CFD**
seulement. Les transposer aux paires forex serait extrapoler une mesure hors
de son domaine — exactement l'erreur que ce plan existe pour empêcher.

MT5 est par ailleurs la route dont la viabilité est déjà établie et qui trade
aujourd'hui. La porte existe pour arrêter les routes chères, pas pour rejuger
celle qui fonctionne. La laisser non déclarée garantit qu'elle conserve
exactement son comportement actuel.

⚠️ Ne pas « compléter » ce point en inventant un taux. Un coût par classe
d'actif est un chantier de mesure distinct.

Dans `_admin_kraken_destination()` et `_admin_kraken_spot_destination()` :

```python
        # 0,05 % par jambe (taker). Donne 0,288 R au SL médian mesuré.
        cost_model=CostModel(proportional_rate_per_leg=0.0005),
        expected_edge_r=0.110,  # mesuré sur 876 trades réels le 2026-08-04
```

Dans `_admin_kraken_stocks_destination()` :

```python
        cost_model=CostModel(proportional_rate_per_leg=0.0005),
        expected_edge_r=0.129,  # 0,199 R de frais mesurés > 30 % de cet edge
```

Dans `_admin_binance_destination()`, laisser les deux à leur défaut `None` :
la destination est désactivée depuis le 2026-08-02, et déclarer un coût
non mesuré serait inventer un chiffre.

- [ ] **Step 6: Écrire le test des valeurs réelles**

```python
# à ajouter dans backend/tests/test_dispatch_porte_de_cout.py

def test_kraken_est_refuse_par_ses_propres_chiffres():
    """Le refus doit tomber des valeurs déclarées, sans cas particulier."""
    from backend.services.cost_model import CostModel, cost_in_r, exceeds_edge

    modele = CostModel(proportional_rate_per_leg=0.0005)
    entry = 1000.0
    cout = cost_in_r(entry=entry, stop_loss=entry * (1 - 0.00347), model=modele)

    assert exceeds_edge(cout, 0.110, auto_exec=True) is True


def test_mt5_reste_non_declare_donc_inchange():
    """La route qui trade aujourd'hui ne doit pas changer de comportement.

    Aucun taux unique ne décrit `admin_live`, qui mélange forex, métaux et
    actions CFD : la distance de stop y varie d'un facteur 27 (EUR/USD
    0,073 %, DOT/USD 1,99 %, mesuré le 2026-08-04 sur 1 352 trades auto).
    Déclarer un taux reviendrait à inventer un chiffre.
    """
    from backend.services.bridge_destinations import _admin_live_destination

    dest = _admin_live_destination()
    if dest is None:  # destination non configurée dans cet environnement
        import pytest

        pytest.skip("admin_live non configurée ici")
    assert dest.cost_model is None
    assert dest.expected_edge_r is None
```

- [ ] **Step 7: Lancer la suite complète**

Run: `python -m pytest backend/tests -q`
Expected: PASS, aucun test existant cassé.

- [ ] **Step 8: Commit**

```bash
git add backend/services/bridge_destinations.py backend/tests/test_dispatch_porte_de_cout.py
git commit -m "Chaque destination declare son cout et son edge mesure"
```

---

### Task 5 : La porte au dispatch

**Files:**
- Modify: `backend/services/mt5_bridge.py` — dans `_check_rejection`, après la porte `pattern_not_allowed` (autour de la ligne 407)
- Test: `backend/tests/test_dispatch_porte_de_cout.py`

**Interfaces:**
- Consomme : `cost_in_r`, `exceeds_edge`, `BridgeConfig.cost_model`, `BridgeConfig.expected_edge_r`.
- Produit : `_cost_rejection(setup, dest) -> str | None`, appelée par `_check_rejection`, et le code de refus `fees_exceed_edge` enregistré dans `signal_rejections` avec sa `destination_id`.

**Pourquoi une fonction séparée.** `_check_rejection` traverse d'abord les
portes d'admission, de whitelist et d'heures de marché — qui lisent la base.
Un test unitaire qui l'appellerait directement recevrait `_not_admitted` et
n'atteindrait jamais la porte de coût. La logique de coût est donc extraite
dans `_cost_rejection`, testable sans base, sans réseau et sans horloge ; un
test distinct vérifie qu'elle est bien appelée.

- [ ] **Step 1: Écrire le test qui échoue**

```python
# à ajouter dans backend/tests/test_dispatch_porte_de_cout.py
import inspect
from types import SimpleNamespace


def _setup_factice(entry: float = 1000.0, ecart_pct: float = 0.00347):
    return SimpleNamespace(
        pair="ETH/USD",
        direction=SimpleNamespace(value="sell"),
        entry_price=entry,
        stop_loss=entry * (1 - ecart_pct),
        take_profit_1=entry * (1 + ecart_pct),
        confidence_score=90.0,
        signal_pattern="range_bounce_down",
    )


def _dest_factice(dest_id, cost_model=None, edge=None, auto_exec=True):
    from backend.services.bridge_destinations import BridgeConfig

    return BridgeConfig(
        destination_id=dest_id,
        user_id=None,
        # bridge_url vide : évite que la validation de tick pré-push tente
        # un appel HTTP pendant les tests.
        bridge_url="",
        bridge_api_key="k",
        min_confidence=50.0,
        allowed_asset_classes=frozenset({"crypto"}),
        auto_exec_enabled=auto_exec,
        allowed_patterns=frozenset(),
        cost_model=cost_model,
        expected_edge_r=edge,
    )


def test_la_porte_refuse_un_signal_trop_cher():
    from backend.services.cost_model import CostModel
    from backend.services.mt5_bridge import _cost_rejection

    dest = _dest_factice("admin_kraken",
                         CostModel(proportional_rate_per_leg=0.0005), 0.110)

    assert _cost_rejection(_setup_factice(), dest) == "fees_exceed_edge"


def test_le_code_de_refus_n_est_pas_prive():
    """Un code commençant par `_` serait supprimé silencieusement."""
    from backend.services.cost_model import CostModel
    from backend.services.mt5_bridge import _cost_rejection

    dest = _dest_factice("admin_kraken",
                         CostModel(proportional_rate_per_leg=0.0005), 0.110)

    code = _cost_rejection(_setup_factice(), dest)
    assert code is not None and not code.startswith("_")


def test_une_route_bon_marche_passe_la_porte():
    from backend.services.cost_model import CostModel
    from backend.services.mt5_bridge import _cost_rejection

    dest = _dest_factice("admin_live",
                         CostModel(proportional_rate_per_leg=0.00011), 0.129)

    assert _cost_rejection(_setup_factice(), dest) is None


def test_une_destination_sans_modele_declare_ne_change_pas_de_comportement():
    """Rétro-compatibilité : les destinations non renseignées passent comme avant."""
    from backend.services.mt5_bridge import _cost_rejection

    assert _cost_rejection(_setup_factice(), _dest_factice("user:2")) is None


def test_l_observation_n_est_pas_bloquee_faute_d_edge_connu():
    from backend.services.cost_model import CostModel
    from backend.services.mt5_bridge import _cost_rejection

    dest = _dest_factice("admin_kraken_stocks",
                         CostModel(proportional_rate_per_leg=0.0005),
                         edge=None, auto_exec=False)

    assert _cost_rejection(_setup_factice(), dest) is None


def test_la_porte_est_reellement_appelee_par_le_dispatch():
    """Une fonction qui existe sans être appelée ne protège de rien.

    C'est la leçon des douze patches posés sur un import mort le 2026-08-04 :
    onze tests passaient par hasard, et le garde n'était plus testé du tout.
    """
    from backend.services import mt5_bridge

    src = inspect.getsource(mt5_bridge._check_rejection)
    assert "_cost_rejection(" in src
```

- [ ] **Step 2: Lancer les tests pour vérifier qu'ils échouent**

Run: `python -m pytest backend/tests/test_dispatch_porte_de_cout.py -q`
Expected: FAIL avec `AttributeError: module 'backend.services.mt5_bridge' has no attribute '_cost_rejection'`

- [ ] **Step 3: Écrire la fonction**

Dans `backend/services/mt5_bridge.py`, juste avant `def _check_rejection`
(ligne 214) :

```python
def _cost_rejection(setup, dest) -> str | None:
    """Refuse un signal dont les frais consomment plus de 30 % de l'edge brut.

    Extraite de `_check_rejection` pour être testable sans base ni réseau :
    les portes d'admission et de whitelist qui la précèdent lisent la base,
    et un test unitaire ne les atteindrait jamais.

    Une destination qui ne déclare pas de `cost_model` garde exactement son
    comportement d'avant le 2026-08-04.
    """
    if dest is None or getattr(dest, "cost_model", None) is None:
        return None

    from backend.services.cost_model import cost_in_r, exceeds_edge

    risk_money = None
    try:
        from backend.services.sizing import compute_risk_money

        risk_money = compute_risk_money(setup, dest).get("risk_money")
    except Exception:
        # Sizing indisponible : `risk_money` reste None. `cost_in_r` renverra
        # None si une composante fixe est déclarée, et `exceeds_edge` bloquera
        # l'argent réel — jamais l'inverse.
        risk_money = None

    cout_r = cost_in_r(
        entry=getattr(setup, "entry_price", 0) or 0,
        stop_loss=getattr(setup, "stop_loss", 0) or 0,
        model=dest.cost_model,
        risk_money=risk_money,
    )
    if exceeds_edge(
        cout_r,
        getattr(dest, "expected_edge_r", None),
        auto_exec=bool(getattr(dest, "auto_exec_enabled", False)),
    ):
        return "fees_exceed_edge"
    return None
```

- [ ] **Step 4: Brancher la porte**

Dans `_check_rejection`, immédiatement après le bloc `pattern_not_allowed`
(qui se termine par `return "pattern_not_allowed"`) :

```python
    # Porte de coût (2026-08-04). Placée APRÈS les filtres bon marché
    # (confidence, pattern) : elle appelle le sizing, qui peut interroger le
    # solde du bridge. Inutile de payer ce coût pour un signal déjà écarté.
    cost_reason = _cost_rejection(setup, dest)
    if cost_reason:
        return cost_reason
```

- [ ] **Step 5: Lancer les tests pour vérifier qu'ils passent**

Run: `python -m pytest backend/tests/test_dispatch_porte_de_cout.py -q`
Expected: PASS — 10 tests.

- [ ] **Step 6: Vérifier par mutation**

Commenter temporairement l'appel `cost_reason = _cost_rejection(setup, dest)`
dans `_check_rejection` et relancer : `test_la_porte_est_reellement_appelee_par_le_dispatch`
doit échouer. Puis remettre l'appel, commenter `return "fees_exceed_edge"`
dans `_cost_rejection` : `test_la_porte_refuse_un_signal_trop_cher` doit
échouer. Un test qui passe dans les deux cas ne teste rien. Tout rétablir.

- [ ] **Step 7: Lancer la suite complète**

Run: `python -m pytest backend/tests -q`
Expected: PASS, aucun test existant cassé.

- [ ] **Step 8: Commit**

```bash
git add backend/services/mt5_bridge.py backend/tests/test_dispatch_porte_de_cout.py
git commit -m "Porte de cout au dispatch : frais > 30 % de l'edge, refus trace"
```

---

### Task 6 : Vérification en production

**Files:**
- Aucun fichier modifié. Déploiement et observation.

**Interfaces:**
- Consomme : tout ce qui précède.
- Produit : la preuve que `KRAKEN_BRIDGE_ENABLED=true` ne suffit plus à faire trader la crypto à perte.

- [ ] **Step 1: Pousser et déployer**

```bash
git push origin main
bash deploy-v2.sh
```

Le push est obligatoire avant le déploiement : `deploy-v2.sh` fait un
`git pull` côté serveur, donc déployer sans pousser reconstruit à l'identique.

- [ ] **Step 2: Réactiver Kraken pour éprouver la porte**

```bash
ssh -i scalping-key.pem ec2-user@13.63.77.180 \
  "sudo cp /opt/scalping/.env /opt/scalping/.env.bak-porte-cout && \
   sudo sed -i 's/^KRAKEN_BRIDGE_ENABLED=false/KRAKEN_BRIDGE_ENABLED=true/' /opt/scalping/.env && \
   sudo systemctl restart scalping"
```

C'est le test décisif : la crypto est rallumée **exprès**, pour vérifier
qu'elle ne trade pas malgré tout.

- [ ] **Step 3: Observer les refus pendant une heure**

```bash
ssh -i scalping-key.pem ec2-user@13.63.77.180 \
  "sudo docker exec scalping-radar python3 -c \"
import sqlite3
c=sqlite3.connect('/app/data/trades.db')
for r in c.execute('''SELECT destination_id, reason_code, COUNT(*)
                        FROM signal_rejections
                       WHERE created_at >= datetime('now','-1 hour')
                         AND reason_code='fees_exceed_edge'
                       GROUP BY destination_id, reason_code'''):
    print(r)
\""
```

Attendu : au moins une ligne `admin_kraken | fees_exceed_edge | n`.

⚠️ Piège de dates : `datetime('now')` rend `YYYY-MM-DD HH:MM:SS` avec un
espace, alors que certaines colonnes sont en ISO avec un `T`. Si le compte
revient à zéro, comparer sur `substr(created_at, 1, 10)` avant de conclure
que la porte ne fonctionne pas.

- [ ] **Step 4: Vérifier qu'aucun ordre crypto n'est parti**

```bash
ssh -i scalping-key.pem ec2-user@13.63.77.180 \
  "sudo docker exec scalping-radar python3 -c \"
import sqlite3
c=sqlite3.connect('/app/data/trades.db')
print(c.execute('''SELECT COUNT(*) FROM mt5_pushes
                    WHERE destination_id LIKE '%kraken%'
                      AND pushed_at >= datetime('now','-1 hour')''').fetchone())
\""
```

Attendu : `(0,)`.

- [ ] **Step 5: Vérifier que MT5 n'est pas affecté**

```bash
ssh -i scalping-key.pem ec2-user@13.63.77.180 \
  "sudo docker exec scalping-radar python3 -c \"
import sqlite3
c=sqlite3.connect('/app/data/trades.db')
for r in c.execute('''SELECT reason_code, COUNT(*) FROM signal_rejections
                       WHERE destination_id='admin_live'
                         AND created_at >= datetime('now','-1 hour')
                       GROUP BY reason_code'''):
    print(r)
\""
```

Attendu : **aucune** ligne `fees_exceed_edge` sur `admin_live`. Si MT5 se
met à refuser, le coût déclaré ou l'edge déclaré est faux — revenir à la
tâche 4 avant toute autre chose.

- [ ] **Step 6: Consigner le résultat**

Écrire le verdict dans la mémoire projet : la porte tient, ou elle ne tient
pas et pourquoi. Si elle tient, `KRAKEN_BRIDGE_ENABLED` peut rester à `true`
— c'est précisément l'objectif : la route reste branchée, et c'est la
mesure qui décide, plus un drapeau qu'on oublie de remettre.

---

## Ce que ce plan ne fait pas

- Le **portage** (funding Kraken, swap MT5) n'est pas modélisé : il ne devient
  matériel qu'à horizon long, donc il appartient au plan 2.
- Le **routage par horizon** n'est pas touché.
- Les **ordres maker** sur Kraken ne sont pas introduits : ils diviseraient
  peut-être les frais par deux, mais mélanger ce changement avec la porte de
  coût rendrait impossible d'attribuer l'effet.
- L'edge par destination est **déclaré à partir d'une mesure**, pas recalculé
  en continu. Un service de mesure automatique est un chantier distinct.
