# Risque engagé multi-destinations — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** que la commande Telegram `risque` couvre les cinq destinations (MT5 démo, MT5 réel, Kraken Futures, Kraken Spot, IBKR) en euros, sans jamais publier un chiffre non mesuré.

**Architecture :** un module `backend/services/risque_engage.py` rassemble un **dialecte par type de bridge**. Chaque dialecte rend la même structure d'évaluation ; `backend/app.py` ne connaît plus que cette structure. MT5 garde sa dérivation par le profit ; Kraken et IBKR utilisent `|entrée − stop| × taille`. Une conversion EUR/USD unique, faillible sans dommage.

**Tech Stack :** Python 3.12, FastAPI, pytest, `urllib.request` (les scripts n'ont pas `requests`), Flask côté bridges, Docker sur EC2.

**Spec :** `docs/superpowers/specs/2026-08-25-risque-engage-multi-destinations-design.md`

## Contraintes globales

- **Aucun zéro qui ne soit pas mesuré.** Bridge muet ⇒ `illisible` ; position pile à l'entrée ⇒ `non mesurable` ; position sans stop ⇒ `indécidable` ; stop à l'équilibre ⇒ un vrai `0.0`. Ces quatre-là ne se confondent jamais.
- **Le total ne s'annonce que si TOUTES les destinations sont mesurées ET converties.** Sinon `Total tous comptes : impossible`.
- **Lecture seule stricte.** Aucune écriture de `/app/data/saturation_risque.json`, aucun cooldown consommé.
- **Entrée et stop se lisent chez le COURTIER**, jamais dans nos tables.
- **Ne jamais réécrire la mesure MT5** : `_lire_destination` / `verdict` de `scripts/notify_saturation_risque.py` sont importés tels quels.
- Formatage des montants : virgule décimale, espace de milliers (`_eur` existant dans `backend/app.py`).
- Déploiement backend = **reconstruction d'image** (`docker cp` ne survit pas au restart), puis `sudo systemctl restart scalping`, puis attendre ~25 s.
- SSH EC2 : `ssh -i scalping-key.pem ec2-user@100.103.107.75`.

---

## Structure des fichiers

| fichier | responsabilité |
|---|---|
| `backend/services/risque_engage.py` **(créer)** | dialectes de mesure, un par type de bridge, plus la conversion de devise |
| `backend/app.py` **(modifier)** | `_mesurer_risque_destinations` délègue au module ; `_formater_risque` gère les blocs sans plafond |
| `backend/tests/test_risque_engage_dialectes.py` **(créer)** | dialectes Kraken/IBKR + conversion, fonctions pures |
| `backend/tests/test_commande_risque_telegram.py` **(modifier)** | mise en mots des nouveaux blocs, branchement des 5 destinations |
| `kraken-spot-bridge/bridge.py` **(modifier)** | ajouter `entry` au registre des watchers |
| `ibkr-bridge/bridge.py` **(modifier)** | ajouter `GET /openorders` |
| `backend/services/mt5_bridge.py` **(modifier)** | persister `risk_money` avec le push |

---

## Task 1 : Extraire la mesure dans un module à dialectes

Refactor pur — aucun changement de comportement. Il crée le point d'accroche des tâches suivantes.

**Files:**
- Create: `backend/services/risque_engage.py`
- Modify: `backend/app.py` (fonction `_mesurer_risque_destinations`)
- Test: `backend/tests/test_commande_risque_telegram.py` (existant, doit rester vert)

**Interfaces:**
- Produces : `mesurer(destination_ids: tuple[str, ...]) -> list[dict]` — rend une liste de `{"id": str, "badge": str, "evaluation": dict, "verdict": str}`. `evaluation` porte au minimum les clés `lisible`, `indecidable`, `risque_total`, `plafond`, `pct`, `restant`, `nues`, `non_mesurables`, `positions`, `candidats`, `liberable`, `login`, et désormais `devise` (`"EUR"` ou `"USD"`).
- Produces : `DIALECTES: dict[str, callable]` — clé = `Destination.bridge_type`, valeur = `f(dest) -> dict` rendant une `evaluation`.

- [ ] **Step 1 : Écrire le test qui verrouille l'aiguillage par dialecte**

Dans `backend/tests/test_risque_engage_dialectes.py` :

```python
"""Aiguillage des dialectes de mesure du risque engagé (2026-08-25).

Chaque type de bridge parle un dialecte différent. Ce qui est verrouillé ici,
c'est qu'une destination ne puisse pas être mesurée par le mauvais dialecte —
ni, pire, être silencieusement sautée.
"""
from __future__ import annotations

import pytest


def test_chaque_type_de_bridge_a_un_dialecte():
    from backend.services.risque_engage import DIALECTES
    from backend.services.destinations_registry import DESTINATIONS

    attendus = {DESTINATIONS[d].bridge_type
                for d in ("admin_legacy", "admin_live", "admin_kraken",
                          "admin_kraken_spot", "admin_ibkr_us")}
    manquants = attendus - set(DIALECTES)
    assert not manquants, f"types sans dialecte : {manquants}"


def test_un_type_inconnu_rend_illisible_et_ne_leve_PAS():
    """⛔ Une destination ajoutée demain ne doit pas faire planter la commande —
    ni se faire compter pour zéro. `illisible` est le seul repli honnête."""
    from backend.services.risque_engage import mesurer_destination

    class _Faux:
        id = "inconnue"
        badge = "?"
        bridge_type = "type_qui_nexiste_pas"

    e = mesurer_destination(_Faux())
    assert e["lisible"] is False
    assert e["risque_total"] is None
```

- [ ] **Step 2 : Lancer le test, vérifier qu'il échoue**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risque_engage_dialectes.py -q
```
Attendu : `ModuleNotFoundError: No module named 'backend.services.risque_engage'`

- [ ] **Step 3 : Créer le module avec le seul dialecte MT5**

`backend/services/risque_engage.py` :

```python
"""Mesure du risque engagé, un dialecte par type de bridge (2026-08-25).

Chaque courtier rend ses positions dans une forme différente. MT5 porte le
stop DANS la position et permet de dériver le risque du profit rapporté ;
Kraken et IBKR n'ont ni profit ni prix courant dans leur charge de position,
et leur stop vit dans un ordre séparé.

⛔ La mesure MT5 n'est PAS réécrite ici : elle est importée de
`scripts/notify_saturation_risque.py`, couverte par 24 tests et vérifiée au
centime près contre les positions réelles du 23/08. Une seconde
implémentation serait l'endroit exact où les deux chiffres divergeraient.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DESTINATIONS_MESUREES = (
    "admin_live", "admin_legacy", "admin_kraken",
    "admin_kraken_spot", "admin_ibkr_us",
)


def evaluation_illisible(devise: str = "EUR") -> dict:
    """⛔ Muet n'est pas sain. Un bridge injoignable ne vaut pas « 0 € »."""
    return {
        "lisible": False, "indecidable": True,
        "risque_total": None, "plafond": None, "pct": None, "restant": None,
        "nues": 0, "non_mesurables": 0, "positions": 0,
        "candidats": 0, "liberable": 0.0, "login": None, "devise": devise,
    }


def _dialecte_mt5(dest) -> dict:
    from scripts.notify_saturation_risque import _lire_destination
    e = _lire_destination(dest)
    e["devise"] = "EUR"
    return e


DIALECTES = {"mt5": _dialecte_mt5}


def mesurer_destination(dest) -> dict:
    """Mesure une destination via son dialecte. Toute panne ⇒ `illisible`."""
    dialecte = DIALECTES.get(getattr(dest, "bridge_type", ""))
    if dialecte is None:
        logger.warning("risque_engage: aucun dialecte pour bridge_type=%r "
                       "(destination %s)", getattr(dest, "bridge_type", None),
                       getattr(dest, "id", "?"))
        return evaluation_illisible()
    try:
        return dialecte(dest)
    except Exception:
        logger.exception("risque_engage: dialecte en échec sur %s",
                         getattr(dest, "id", "?"))
        return evaluation_illisible()


def mesurer(destination_ids: tuple[str, ...] = DESTINATIONS_MESUREES) -> list[dict]:
    """Une mesure par destination, dans l'ordre donné. Bloquant."""
    from backend.services.destinations_registry import DESTINATIONS
    from scripts.notify_saturation_risque import SEUIL_PCT, verdict

    mesures = []
    for did in destination_ids:
        dest = DESTINATIONS.get(did)
        if dest is None:
            continue
        evaluation = mesurer_destination(dest)
        mesures.append({
            "id": did, "badge": dest.badge,
            "evaluation": evaluation,
            "verdict": verdict(evaluation, SEUIL_PCT),
        })
    return mesures
```

- [ ] **Step 4 : Ajouter les quatre dialectes manquants en bouchon `illisible`**

Toujours dans `risque_engage.py`, juste avant `DIALECTES` :

```python
def _dialecte_kraken_futures(dest) -> dict:
    return evaluation_illisible("USD")      # Task 2


def _dialecte_kraken_spot(dest) -> dict:
    return evaluation_illisible("USD")      # Task 5


def _dialecte_ibkr(dest) -> dict:
    return evaluation_illisible("USD")      # Task 6
```

et remplacer la table :

```python
# Clés = `Destination.bridge_type`, relevées dans le registre le 2026-08-25 :
#   admin_legacy / admin_live -> "mt5"      admin_kraken      -> "kraken"
#   admin_kraken_spot         -> "kraken_spot"  admin_ibkr_us -> "ibkr"
DIALECTES = {
    "mt5": _dialecte_mt5,
    "kraken": _dialecte_kraken_futures,
    "kraken_spot": _dialecte_kraken_spot,
    "ibkr": _dialecte_ibkr,
}
```

Le premier test de Task 1 (`test_chaque_type_de_bridge_a_un_dialecte`) reverrouille cette correspondance contre le registre : il tombera si un `bridge_type` change ou si une destination est ajoutée sans dialecte.

- [ ] **Step 5 : Faire déléguer `backend/app.py`**

Remplacer le corps de `_mesurer_risque_destinations` par :

```python
def _mesurer_risque_destinations() -> list[dict]:
    """Lit les bridges et rend une mesure par destination.

    ⛔ **Lecture seule stricte.** Aucune écriture de
    `saturation_risque.json`, aucun cooldown consommé.

    Bloquant : l'appelant doit le sortir de la boucle d'événements.
    """
    from backend.services.risque_engage import mesurer
    return mesurer()
```

Supprimer la constante `_RISQUE_DESTINATIONS` devenue inutilisée.

- [ ] **Step 6 : Lancer les deux suites**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risque_engage_dialectes.py backend/tests/test_commande_risque_telegram.py -q
```
Attendu : tout passe. Les 21 tests existants **ne doivent pas être modifiés** — s'ils cassent, c'est le refactor qui est faux.

- [ ] **Step 7 : Commit**

```bash
git add backend/services/risque_engage.py backend/app.py backend/tests/test_risque_engage_dialectes.py
git commit -m "refactor(risque): un dialecte de mesure par type de bridge

Aucun changement de comportement : MT5 garde sa dérivation par le profit,
importée telle quelle. Les quatre autres types rendent illisible en bouchon.

⛔ Un bridge_type sans dialecte rend illisible et JOURNALISE — il ne se fait
ni compter pour zéro, ni sauter en silence."
```

---

## Task 2 : Dialecte Kraken Futures

Aucun changement de bridge : `/openorders` expose déjà `stopPrice`, `reduceOnly` et `orderType`.

**Files:**
- Modify: `backend/services/risque_engage.py`
- Test: `backend/tests/test_risque_engage_dialectes.py`

**Interfaces:**
- Consumes : `evaluation_illisible(devise)` de Task 1.
- Produces : `risque_position_stop(entree, stop, taille) -> float | None` — `None` si l'un des trois manque ou si `entree == stop`.
- Produces : `_stops_reduce_only(charge_openorders: dict) -> dict[str, float]` — `{symbole: prix_de_declenchement}`.

- [ ] **Step 1 : Écrire les tests des fonctions pures**

Ajouter à `backend/tests/test_risque_engage_dialectes.py` :

```python
# --------------------------------------------------------------------------
# Kraken Futures — |entrée − stop| × taille
# --------------------------------------------------------------------------

def test_le_cas_REEL_du_25_08_DOT():
    """PF_DOTUSD : entrée 0,9507, stop 0,7136, taille 2,2 ⇒ 0,5216 USD.
    Mesuré en production le 25/08."""
    from backend.services.risque_engage import risque_position_stop
    assert risque_position_stop(0.9507, 0.7136, 2.2) == pytest.approx(0.5216, abs=1e-4)


def test_le_cas_REEL_du_25_08_PAXG():
    from backend.services.risque_engage import risque_position_stop
    assert risque_position_stop(4608.0, 4312.2, 0.003) == pytest.approx(0.8874, abs=1e-4)


def test_un_stop_A_L_ENTREE_est_un_VRAI_zero():
    """Le stop ramené au prix d'entrée : la position ne peut plus perdre.
    C'est une mesure, pas une faute de mesure."""
    from backend.services.risque_engage import risque_position_stop
    assert risque_position_stop(1.2345, 1.2345, 10.0) == 0.0


@pytest.mark.parametrize("entree,stop,taille", [
    (None, 0.7, 2.2), (0.95, None, 2.2), (0.95, 0.7, None),
    (0.95, 0.7, 0.0), (0.0, 0.7, 2.2),
])
def test_une_donnee_manquante_rend_None_JAMAIS_zero(entree, stop, taille):
    """⛔ Zéro dirait « aucun risque ». None dit « on ne sait pas »."""
    from backend.services.risque_engage import risque_position_stop
    assert risque_position_stop(entree, stop, taille) is None


def test_seuls_les_stops_reduceOnly_comptent():
    """Un ordre d'ENTRÉE en attente sur le même symbole n'est pas une
    protection — le compter en ferait une, et la position passerait pour
    bornée alors qu'elle ne l'est pas."""
    from backend.services.risque_engage import _stops_reduce_only
    charge = {"orders": [
        {"symbol": "PF_DOTUSD", "orderType": "stp", "reduceOnly": True,
         "stopPrice": 0.7136},
        {"symbol": "PF_SOLUSD", "orderType": "stp", "reduceOnly": False,
         "stopPrice": 100.0},
        {"symbol": "PF_ETHUSD", "orderType": "lmt", "reduceOnly": True,
         "stopPrice": None},
    ]}
    assert _stops_reduce_only(charge) == {"PF_DOTUSD": 0.7136}


def test_une_position_sans_stop_rend_le_compte_INDECIDABLE():
    from backend.services.risque_engage import evaluer_positions_stop
    e = evaluer_positions_stop(
        positions=[{"symbol": "PF_DOTUSD", "price": 0.9507, "size": 2.2}],
        stops={}, devise="USD")
    assert e["nues"] == 1
    assert e["indecidable"] is True
    assert e["pct"] is None


def test_sans_plafond_il_n_y_a_ni_pct_ni_restant():
    """⛔ Kraken n'a pas de garde-fou de risque engagé. Inventer un
    pourcentage donnerait un chiffre comparable à celui de MT5 sans mesurer
    la même chose."""
    from backend.services.risque_engage import evaluer_positions_stop
    e = evaluer_positions_stop(
        positions=[{"symbol": "PF_DOTUSD", "price": 0.9507, "size": 2.2}],
        stops={"PF_DOTUSD": 0.7136}, devise="USD")
    assert e["risque_total"] == pytest.approx(0.5216, abs=1e-4)
    assert e["plafond"] is None
    assert e["pct"] is None
    assert e["restant"] is None
    assert e["indecidable"] is False
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risque_engage_dialectes.py -q
```
Attendu : `ImportError: cannot import name 'risque_position_stop'`

- [ ] **Step 3 : Implémenter**

Dans `backend/services/risque_engage.py` :

```python
import json
import os
import urllib.error
import urllib.request

DELAI = 10


def _appel(dest, chemin: str):
    """GET sur un bridge. Rend `(charge, lecture_reussie)`."""
    url = os.environ.get(getattr(dest, "url_env", "") or "", "")
    if not url:
        return None, False
    cle = os.environ.get(getattr(dest, "key_env", "") or "", "")
    entete = getattr(dest, "key_header", "") or ""
    entetes = {entete: cle} if cle and entete else {}
    try:
        rq = urllib.request.Request(url.rstrip("/") + chemin, headers=entetes)
        with urllib.request.urlopen(rq, timeout=DELAI) as r:
            if r.status != 200:
                return None, False
            return json.load(r), True
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        logger.info("risque_engage: %s injoignable (%s)", chemin, e)
        return None, False


def risque_position_stop(entree, stop, taille) -> float | None:
    """`|entrée − stop| × taille`, en devise de cotation.

    ⛔ Rend `None`, jamais `0.0`, dès qu'une donnée manque : zéro dirait
    « aucun risque » quand la vérité est « on ne sait pas ». Seul un stop
    EXACTEMENT à l'entrée rend un vrai zéro — la position ne peut plus perdre,
    et c'est une mesure.
    """
    try:
        e, s, t = float(entree), float(stop), float(taille)
    except (TypeError, ValueError):
        return None
    if e <= 0 or t <= 0 or s < 0:
        return None
    return abs(e - s) * t


def _stops_reduce_only(charge: dict) -> dict:
    """`{symbole: prix de déclenchement}` depuis les ordres vivants.

    ⛔ Un ordre ne protège une position que s'il la RÉDUIT. Un ordre d'entrée
    en attente sur le même symbole n'est pas une protection ; le compter ferait
    passer pour bornée une position qui ne l'est pas.
    """
    stops = {}
    for o in (charge or {}).get("orders") or []:
        if not o.get("reduceOnly"):
            continue
        if (o.get("orderType") or "").lower() not in ("stp", "stop"):
            continue
        sym, prix = o.get("symbol"), o.get("stopPrice")
        if sym and prix is not None:
            try:
                stops[sym] = float(prix)
            except (TypeError, ValueError):
                continue
    return stops


def evaluer_positions_stop(positions, stops, devise,
                           cle_symbole="symbol", cle_entree="price",
                           cle_taille="size") -> dict:
    """Somme les risques de positions dont le stop vit dans un ordre séparé.

    ⛔ Pas de plafond sur ces destinations : `plafond`, `pct` et `restant`
    valent `None`. Inventer un pourcentage donnerait un chiffre d'apparence
    comparable à MT5 sans mesurer la même chose.
    """
    total, nues, non_mesurables = 0.0, 0, 0
    for p in positions or []:
        sym = p.get(cle_symbole)
        if sym not in stops:
            nues += 1
            continue
        r = risque_position_stop(p.get(cle_entree), stops[sym], p.get(cle_taille))
        if r is None:
            non_mesurables += 1
            continue
        total += r
    return {
        "lisible": True,
        "indecidable": bool(nues or non_mesurables),
        "risque_total": total, "plafond": None, "pct": None, "restant": None,
        "nues": nues, "non_mesurables": non_mesurables,
        "positions": len(positions or []),
        "candidats": 0, "liberable": 0.0, "login": None, "devise": devise,
        "sans_plafond": True,
    }
```

Puis remplacer le bouchon :

```python
def _dialecte_kraken_futures(dest) -> dict:
    pos, ok = _appel(dest, "/positions")
    if not ok or not isinstance(pos, dict):
        return evaluation_illisible("USD")
    oo, ok = _appel(dest, "/openorders")
    if not ok or not isinstance(oo, dict):
        return evaluation_illisible("USD")
    return evaluer_positions_stop(pos.get("positions"), _stops_reduce_only(oo),
                                  devise="USD")
```

- [ ] **Step 4 : Lancer les tests**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risque_engage_dialectes.py -q
```
Attendu : tout passe.

- [ ] **Step 5 : Vérifier contre le bridge RÉEL**

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  'sudo docker exec -e PYTHONPATH=/app -w /app scalping-radar python -c "
from backend.services.risque_engage import mesurer_destination
from backend.services.destinations_registry import DESTINATIONS
print(mesurer_destination(DESTINATIONS[\"admin_kraken\"]))"'
```
Attendu : `risque_total` ≈ **1,4090 USD** sur les 2 positions vivantes (0,5216 + 0,8874), `nues=0`, `plafond=None`.

⚠️ Ce contrôle exige que l'image soit reconstruite d'abord (Task 8 en donne la recette). Si les positions ont changé depuis le 25/08, recalculer à la main depuis `/positions` et `/openorders` avant de conclure.

- [ ] **Step 6 : Commit**

```bash
git add backend/services/risque_engage.py backend/tests/test_risque_engage_dialectes.py
git commit -m "feat(risque): dialecte Kraken Futures, sans toucher au bridge

/openorders expose déjà stopPrice et reduceOnly. risque = |entrée − stop| ×
taille — les tailles PF_* sont en actif de base direct, donc aucun
multiplicateur de contrat.

⛔ Seuls les ordres reduceOnly comptent : un ordre d'entrée en attente ferait
passer pour bornée une position nue. Et aucun pourcentage n'est publié —
Kraken n'a pas de plafond de risque engagé."
```

---

## Task 3 : Conversion EUR/USD, faillible sans dommage

**Files:**
- Modify: `backend/services/risque_engage.py`
- Test: `backend/tests/test_risque_engage_dialectes.py`

**Interfaces:**
- Produces : `taux_eurusd() -> float | None` — `None` si illisible.
- Produces : `en_euros(montant: float | None, devise: str, taux: float | None) -> float | None`.

- [ ] **Step 1 : Écrire les tests**

```python
# --------------------------------------------------------------------------
# Conversion — elle a le droit d'échouer, pas de mentir
# --------------------------------------------------------------------------

def test_l_euro_ne_se_convertit_pas():
    from backend.services.risque_engage import en_euros
    assert en_euros(12.34, "EUR", None) == 12.34


def test_l_usd_se_divise_par_le_taux():
    """1,08 USD pour 1 EUR ⇒ 10,80 USD valent 10,00 EUR."""
    from backend.services.risque_engage import en_euros
    assert en_euros(10.80, "USD", 1.08) == pytest.approx(10.0)


@pytest.mark.parametrize("taux", [None, 0.0, -1.2])
def test_un_taux_ABSENT_ou_ABSURDE_rend_None(taux):
    """⛔ Pas de repli sur un taux « à peu près ». Un total crédible et faux
    est pire qu'une absence de total."""
    from backend.services.risque_engage import en_euros
    assert en_euros(10.80, "USD", taux) is None


def test_un_montant_absent_reste_absent():
    from backend.services.risque_engage import en_euros
    assert en_euros(None, "USD", 1.08) is None
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risque_engage_dialectes.py -q -k euros
```
Attendu : `ImportError: cannot import name 'en_euros'`

- [ ] **Step 3 : Implémenter**

```python
def taux_eurusd() -> float | None:
    """Combien d'USD pour 1 EUR, lu sur un bridge MT5 déjà authentifié.

    ⛔ Rend `None` sur toute lecture ratée. L'appelant refuse alors de
    convertir et de sommer : un taux approximatif produirait un total
    crédible et faux.
    """
    from backend.services.destinations_registry import DESTINATIONS
    for did in ("admin_live", "admin_legacy"):
        dest = DESTINATIONS.get(did)
        if dest is None:
            continue
        charge, ok = _appel(dest, "/tick/EUR/USD")
        if not ok or not isinstance(charge, dict):
            continue
        try:
            bid, ask = float(charge["bid"]), float(charge["ask"])
        except (TypeError, ValueError, KeyError):
            continue
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
    return None


def en_euros(montant, devise: str, taux) -> float | None:
    """Convertit en euros. `None` dès que la conversion n'est pas sûre."""
    if montant is None:
        return None
    if (devise or "EUR").upper() == "EUR":
        return montant
    try:
        t = float(taux)
    except (TypeError, ValueError):
        return None
    if t <= 0:
        return None
    return montant / t
```

- [ ] **Step 4 : Lancer les tests**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risque_engage_dialectes.py -q
```
Attendu : tout passe.

- [ ] **Step 5 : Commit**

```bash
git add backend/services/risque_engage.py backend/tests/test_risque_engage_dialectes.py
git commit -m "feat(risque): conversion EUR/USD, qui refuse plutôt que d'approximer

Taux lu sur un bridge MT5 déjà authentifié. ⛔ Taux absent ou absurde ⇒ None,
donc pas de conversion et pas de total. Un total crédible et faux est plus
dangereux qu'une absence de total : personne ne se méfie d'un chiffre qui
s'affiche."
```

---

## Task 4 : Le message et le total étendus

**Files:**
- Modify: `backend/app.py` (`_formater_risque`, `_build_risque_text`)
- Test: `backend/tests/test_commande_risque_telegram.py`

**Interfaces:**
- Consumes : `taux_eurusd()`, `en_euros()` de Task 3.
- Produces : `_formater_risque(mesures: list[dict], taux: float | None = None) -> str`.

- [ ] **Step 1 : Écrire les tests de mise en mots**

Ajouter à `backend/tests/test_commande_risque_telegram.py` :

```python
# --------------------------------------------------------------------------
# Destinations SANS plafond — des euros, jamais un pourcentage
# --------------------------------------------------------------------------

def _eval_sans_plafond(total=1.409, devise="USD", positions=2):
    return {
        "lisible": True, "indecidable": False,
        "risque_total": total, "plafond": None, "pct": None, "restant": None,
        "nues": 0, "non_mesurables": 0, "positions": positions,
        "candidats": 0, "liberable": 0.0, "login": None,
        "devise": devise, "sans_plafond": True,
    }


def _kraken(evaluation, verdict="ok"):
    return {"id": "admin_kraken", "badge": "🐙 Kraken Futures",
            "evaluation": evaluation, "verdict": verdict}


def test_sans_plafond_on_montre_des_euros_et_AUCUN_pourcentage():
    from backend.app import _formater_risque
    texte = _formater_risque([_kraken(_eval_sans_plafond())], taux=1.08)
    assert "1,30" in texte, texte          # 1,409 USD / 1,08
    assert "%" not in texte, texte
    assert "aucun plafond" in texte.lower(), texte


def test_l_absence_de_plafond_est_DITE_pas_laissee_vide():
    """⛔ Un tiret muet à la place du pourcentage se lirait « 0 % »."""
    from backend.app import _formater_risque
    texte = _formater_risque([_kraken(_eval_sans_plafond())], taux=1.08)
    assert "—" not in texte.replace("Total", ""), texte


def test_sans_TAUX_la_destination_USD_devient_non_convertible():
    from backend.app import _formater_risque
    texte = _formater_risque([_kraken(_eval_sans_plafond())], taux=None)
    assert "convert" in texte.lower(), texte
    assert "1,30" not in texte, texte


def test_le_total_MELANGE_les_devises_seulement_apres_conversion():
    from backend.app import _formater_risque
    texte = _formater_risque([
        _live(_eval_ok(total=28.75, plafond=33.54), "sature"),
        _kraken(_eval_sans_plafond(total=1.08)),
    ], taux=1.08)
    assert "29,75" in texte, texte        # 28,75 EUR + 1,00 EUR


def test_sans_taux_le_total_est_IMPOSSIBLE_meme_si_tout_est_lisible():
    """⛔ Sommer des euros et des dollars donnerait un nombre, pas une mesure."""
    from backend.app import _formater_risque
    texte = _formater_risque([
        _live(_eval_ok(total=28.75, plafond=33.54), "sature"),
        _kraken(_eval_sans_plafond(total=1.08)),
    ], taux=None)
    assert "total tous comptes : impossible" in texte.lower(), texte
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_commande_risque_telegram.py -q -k "plafond or taux or devises"
```
Attendu : `TypeError: _formater_risque() got an unexpected keyword argument 'taux'`

- [ ] **Step 3 : Modifier `_formater_risque`**

Changer la signature et ajouter le bloc sans plafond. Dans `backend/app.py` :

```python
def _formater_risque(mesures: list[dict], taux: float | None = None) -> str:
```

Puis, dans la boucle, **juste après** le bloc `if e.get("desarme"):` et **avant** `if v == "indecidable":`, insérer :

```python
        if e.get("sans_plafond"):
            from backend.services.risque_engage import en_euros
            if e.get("nues"):
                complet = False
                lignes += [
                    f"🚨 <b>{e['nues']} position(s) SANS STOP</b> — risque non "
                    "borné.",
                    "Aucune somme n'a de sens tant qu'elles sont là.",
                ]
                continue
            montant = en_euros(e["risque_total"], e.get("devise", "USD"), taux)
            if montant is None:
                complet = False
                lignes.append(
                    f"❓ <b>Non convertible</b> — {_eur(e['risque_total'])} "
                    f"{_html.escape(e.get('devise', '?'))} mesurés, mais le "
                    "taux EUR/USD est illisible. On ne convertit pas au jugé.")
                continue
            total += montant
            lignes += [
                f"✅ <b>{_eur(montant)} €</b> engagés · {e['positions']} "
                "position(s)",
                "⚪ <b>Aucun plafond de risque</b> n'est armé sur cette "
                "destination : il n'y a pas de pourcentage à en tirer.",
            ]
            continue
```

⚠️ `_html` est déjà importé en tête de `_formater_risque` (`import html as _html`).

- [ ] **Step 4 : Faire passer le taux depuis `_build_risque_text`**

```python
async def _build_risque_text() -> str:
    """Le message complet. Sort le calcul bloquant de la boucle d'événements."""
    from backend.services.risque_engage import taux_eurusd
    mesures = await asyncio.to_thread(_mesurer_risque_destinations)
    taux = await asyncio.to_thread(taux_eurusd)
    return _formater_risque(mesures, taux=taux)
```

- [ ] **Step 5 : Lancer toute la suite de la commande**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_commande_risque_telegram.py backend/tests/test_risque_engage_dialectes.py -q
```
Attendu : tout passe, **y compris les 21 tests d'origine** — la valeur par défaut `taux=None` les laisse intacts.

- [ ] **Step 6 : Mutation — vérifier que les tests mordent**

Remplacer temporairement dans `_formater_risque` :

```python
            montant = en_euros(e["risque_total"], e.get("devise", "USD"), taux)
```
par
```python
            montant = e["risque_total"]          # MUTATION : somme USD et EUR
```

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_commande_risque_telegram.py -q
```
Attendu : `test_sans_taux_le_total_est_IMPOSSIBLE_meme_si_tout_est_lisible` et `test_sans_TAUX_la_destination_USD_devient_non_convertible` **échouent**. Restaurer ensuite.

- [ ] **Step 7 : Commit**

```bash
git add backend/app.py backend/tests/test_commande_risque_telegram.py
git commit -m "feat(risque): blocs sans plafond, et un total qui refuse de mélanger

Les destinations sans garde-fou affichent des euros convertis et DISENT qu'il
n'y a pas de plafond — un tiret muet se lirait « 0 % ».

⛔ Taux EUR/USD illisible ⇒ la destination devient non convertible et le total
tombe sur « impossible ». Sommer des euros et des dollars donnerait un nombre,
pas une mesure."
```

---

## Task 5 : Kraken Spot — exposer le prix d'entrée du watcher

⚠️ **Le spot ne pose AUCUN ordre stop chez Kraken.** Il lance un watcher logiciel (`_start_watcher`, `kraken-spot-bridge/bridge.py:368`) qui vend au marché quand le niveau est touché. `/positions` expose déjà `active_watchers` avec `sl`, `qty` et `pair` — **il manque le prix d'entrée**.

⛔ **Un stop logiciel et un stop courtier ne sont pas le même objet.** Le premier meurt avec le processus : `_watchers` est un `dict` en mémoire, sans persistance. Le message doit le marquer, sans quoi une position protégée par un thread passerait pour aussi sûre qu'une position protégée par le carnet d'ordres.

**Files:**
- Modify: `kraken-spot-bridge/bridge.py` (`_start_watcher` et son appelant)
- Modify: `backend/services/risque_engage.py` (`_dialecte_kraken_spot`)
- Test: `backend/tests/test_risque_engage_dialectes.py`

**Interfaces:**
- Consumes : `evaluer_positions_stop` de Task 2.
- Produces : le watcher porte désormais `entry: float`.

- [ ] **Step 1 : Écrire le test du dialecte spot**

```python
# --------------------------------------------------------------------------
# Kraken Spot — le stop vit dans un WATCHER, pas dans le carnet d'ordres
# --------------------------------------------------------------------------

def test_le_dialecte_spot_lit_les_watchers():
    from backend.services.risque_engage import evaluation_spot
    charge = {"positions": [{"asset": "XBT", "qty": 0.001, "price_usd": 60000.0}],
              "active_watchers": [
                  {"pair": "BTC/USD", "kraken_pair": "XBTUSD", "qty": 0.001,
                   "entry": 61000.0, "sl": 59000.0, "tp": 65000.0}]}
    e = evaluation_spot(charge)
    assert e["risque_total"] == pytest.approx(2.0)      # |61000−59000| × 0,001
    assert e["stop_logiciel"] is True
    assert e["plafond"] is None


def test_un_watcher_SANS_entree_est_non_mesurable_pas_zero():
    """Un bridge spot pas encore mis à jour ne porte pas `entry`. ⛔ Le compter
    pour zéro rabaisserait le total et cacherait le risque."""
    from backend.services.risque_engage import evaluation_spot
    charge = {"positions": [{"asset": "XBT", "qty": 0.001}],
              "active_watchers": [
                  {"pair": "BTC/USD", "qty": 0.001, "sl": 59000.0}]}
    e = evaluation_spot(charge)
    assert e["non_mesurables"] == 1
    assert e["risque_total"] == 0.0
    assert e["indecidable"] is True


def test_zero_watcher_et_zero_position_est_un_VRAI_zero():
    """Le spot est vide aujourd'hui. Vide mesuré ≠ illisible."""
    from backend.services.risque_engage import evaluation_spot
    e = evaluation_spot({"positions": [], "active_watchers": []})
    assert e["lisible"] is True
    assert e["indecidable"] is False
    assert e["risque_total"] == 0.0
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risque_engage_dialectes.py -q -k spot
```
Attendu : `ImportError: cannot import name 'evaluation_spot'`

- [ ] **Step 3 : Implémenter le dialecte**

Dans `backend/services/risque_engage.py` :

```python
def evaluation_spot(charge: dict) -> dict:
    """Risque du spot Kraken, dont le stop vit dans un watcher LOGICIEL.

    ⚠️ `stop_logiciel=True` n'est pas cosmétique : un watcher est un thread du
    bridge, pas un ordre du carnet. Il meurt avec le processus. Le présenter
    comme un stop courtier surestimerait la protection.
    """
    watchers = (charge or {}).get("active_watchers") or []
    total, non_mesurables = 0.0, 0
    for w in watchers:
        r = risque_position_stop(w.get("entry"), w.get("sl"), w.get("qty"))
        if r is None:
            non_mesurables += 1
            continue
        total += r
    positions = (charge or {}).get("positions") or []
    # Une position sans watcher n'a AUCUN stop : risque non borné.
    nues = max(0, len(positions) - len(watchers))
    return {
        "lisible": True,
        "indecidable": bool(nues or non_mesurables),
        "risque_total": total, "plafond": None, "pct": None, "restant": None,
        "nues": nues, "non_mesurables": non_mesurables,
        "positions": len(positions),
        "candidats": 0, "liberable": 0.0, "login": None, "devise": "USD",
        "sans_plafond": True, "stop_logiciel": True,
    }


def _dialecte_kraken_spot(dest) -> dict:
    charge, ok = _appel(dest, "/positions")
    if not ok or not isinstance(charge, dict):
        return evaluation_illisible("USD")
    return evaluation_spot(charge)
```

- [ ] **Step 4 : Lancer les tests**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risque_engage_dialectes.py -q
```
Attendu : tout passe.

- [ ] **Step 5 : Faire DIRE au message que le stop est logiciel**

Test à ajouter dans `backend/tests/test_commande_risque_telegram.py` :

```python
def test_un_stop_LOGICIEL_est_signale_comme_tel():
    """⛔ Un watcher est un thread du bridge, pas un ordre du carnet : il meurt
    avec le processus. Le présenter comme un stop courtier surestimerait la
    protection — et cette différence-là ne se voit nulle part ailleurs."""
    from backend.app import _formater_risque

    e = _eval_sans_plafond(total=2.0)
    e["stop_logiciel"] = True
    texte = _formater_risque(
        [{"id": "admin_kraken_spot", "badge": "🪙 Kraken Spot",
          "evaluation": e, "verdict": "ok"}], taux=1.08)

    assert "logiciel" in texte.lower(), texte
```

Le lancer, vérifier qu'il échoue, puis compléter le bloc `sans_plafond` de `_formater_risque` (écrit en Task 4) en insérant, **juste après** la ligne `"⚪ <b>Aucun plafond de risque</b>…"` :

```python
            if e.get("stop_logiciel"):
                lignes.append(
                    "⚠️ Stop <b>logiciel</b> : il vit dans un thread du bridge, "
                    "pas dans le carnet d'ordres. Un redémarrage le perd — "
                    "cette protection n'a pas la solidité d'un stop courtier.")
```

Relancer : le test passe.

- [ ] **Step 6 : Ajouter `entry` côté bridge spot**

Dans `kraken-spot-bridge/bridge.py`, changer la signature de `_start_watcher` (ligne ~368) :

```python
def _start_watcher(txid: str, pair: str, kraken_pair: str, qty: float,
                   sl: float, tp: float, entry: float = 0.0) -> None:
```

et, dans le corps, ajouter `entry` au dict enregistré (ligne ~377) :

```python
        _watchers[txid] = {
            "pair": pair,
            "kraken_pair": kraken_pair,
            "qty": qty,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "thread": th,
        }
```

⚠️ Conserver les clés existantes à l'identique — `/positions` les republie telles quelles, et `_watcher_loop` les lit.

⛔ **`AddOrder` ne rend PAS le prix obtenu.** Sa réponse ne porte que `txid` et `descr` — vérifié dans `/order`. Il faut donc le demander au courtier, ce qui est de toute façon la règle : l'entrée se lit chez lui, jamais chez nous.

Ajouter, juste avant l'appel à `_start_watcher` (ligne ~681) :

```python
def _prix_de_remplissage(txid: str) -> float:
    """Prix moyen réellement obtenu, demandé au courtier.

    ⛔ Rend `0.0` si Kraken ne l'a pas encore consolidé — un ordre au marché
    peut être `pending` une fraction de seconde. Le dialecte traduira ce zéro
    en NON MESURABLE, jamais en « risque nul ». Deviner un prix d'entrée
    fausserait le risque sans que rien ne le dise.
    """
    try:
        d = _signed_post("/0/private/QueryOrders", {"txid": txid})
        o = ((d.get("result") or {}).get(txid) or {})
        return float(o.get("price") or 0.0)
    except Exception as e:
        logger.warning("prix de remplissage indisponible pour %s : %s", txid, e)
        return 0.0
```

puis passer le résultat :

```python
        _start_watcher(txid, pair, sym, qty, sl_val, tp_val,
                       entry=_prix_de_remplissage(txid))
```

⚠️ `_signed_post` et `logger` existent déjà dans ce fichier — ne pas les réimporter.

- [ ] **Step 7 : Déployer le bridge spot et vérifier**

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  'cd /home/ec2-user/scalping && git pull --ff-only && \
   sudo cp kraken-spot-bridge/bridge.py /opt/kraken-spot-bridge/bridge.py && \
   sudo systemctl restart kraken-spot-bridge && sleep 5 && \
   curl -s -H "X-API-Key: $KRAKEN_SPOT_BRIDGE_KEY" http://127.0.0.1:8791/positions'
```

⚠️ Vérifier d'abord le nom exact du service et le chemin de déploiement :

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  'systemctl list-units --type=service | grep -i "kraken\|spot"'
```

Attendu : `active_watchers` porte désormais `entry`. **Le spot a 0 position aujourd'hui** — la liste sera vide, ce qui ne prouve que l'absence de régression. Le noter comme tel.

- [ ] **Step 8 : Commit**

```bash
git add kraken-spot-bridge/bridge.py backend/services/risque_engage.py backend/tests/test_risque_engage_dialectes.py
git commit -m "feat(risque): dialecte Kraken Spot, dont le stop est LOGICIEL

Le spot ne pose aucun ordre stop chez Kraken : un watcher (thread du bridge)
surveille le prix et vend au marché. /positions publiait déjà sl et qty, il
manquait le prix d'entrée — ajouté au registre des watchers.

⛔ stop_logiciel=True est porté jusqu'au message. Un watcher meurt avec le
processus ; le présenter comme un stop courtier surestimerait la protection.

⛔ Un watcher sans entrée est NON MESURABLE, jamais zéro."
```

---

## Task 6 : IBKR — `/openorders`, écrit mais non vérifiable en marche

⚠️ **Le bridge IBKR refuse les connexions** (armé et fermé depuis la décision du 10/08 de rester à 100 USD). Ce qui suit est testé sur bouchons et **ne sera pas exercé en production**. Ne pas le compter comme vérifié.

**Files:**
- Modify: `ibkr-bridge/bridge.py`
- Modify: `backend/services/risque_engage.py` (`_dialecte_ibkr`)
- Test: `backend/tests/test_risque_engage_dialectes.py`

**Interfaces:**
- Consumes : `evaluer_positions_stop` de Task 2.
- Produces : `GET /openorders` rendant `{"ok": true, "orders": [{"symbol", "conId", "orderType", "auxPrice", "totalQuantity", "action"}]}`.

- [ ] **Step 1 : Écrire le test du dialecte IBKR**

```python
# --------------------------------------------------------------------------
# IBKR — le stop est l'ordre enfant d'un bracket
# --------------------------------------------------------------------------

def test_le_dialecte_ibkr_apparie_par_symbole():
    from backend.services.risque_engage import evaluation_ibkr
    positions = {"positions": [
        {"symbol": "XLU", "position": 2.0, "avg_cost": 43.60, "currency": "USD"}]}
    ordres = {"orders": [
        {"symbol": "XLU", "orderType": "STP", "auxPrice": 41.00,
         "totalQuantity": 2.0, "action": "SELL"}]}
    e = evaluation_ibkr(positions, ordres)
    assert e["risque_total"] == pytest.approx(5.20)     # |43,60−41,00| × 2
    assert e["plafond"] is None


def test_une_action_SANS_stop_est_indecidable():
    from backend.services.risque_engage import evaluation_ibkr
    positions = {"positions": [
        {"symbol": "XLU", "position": 2.0, "avg_cost": 43.60}]}
    e = evaluation_ibkr(positions, {"orders": []})
    assert e["nues"] == 1
    assert e["indecidable"] is True


def test_un_ordre_d_ACHAT_ne_protege_rien():
    """⛔ Seul un ordre qui RÉDUIT la position la protège."""
    from backend.services.risque_engage import evaluation_ibkr
    positions = {"positions": [
        {"symbol": "XLU", "position": 2.0, "avg_cost": 43.60}]}
    ordres = {"orders": [
        {"symbol": "XLU", "orderType": "STP", "auxPrice": 41.00,
         "totalQuantity": 2.0, "action": "BUY"}]}
    e = evaluation_ibkr(positions, ordres)
    assert e["nues"] == 1
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risque_engage_dialectes.py -q -k ibkr
```
Attendu : `ImportError: cannot import name 'evaluation_ibkr'`

- [ ] **Step 3 : Implémenter le dialecte**

```python
def _stops_ibkr(charge: dict, sens_position: dict) -> dict:
    """`{symbole: prix de déclenchement}` pour les ordres qui RÉDUISENT.

    ⛔ Un ordre de même sens que la position l'agrandit, il ne la protège pas.
    Une position longue est protégée par un stop `SELL`, et l'inverse.
    """
    stops = {}
    for o in (charge or {}).get("orders") or []:
        if (o.get("orderType") or "").upper() not in ("STP", "STP LMT"):
            continue
        sym = o.get("symbol")
        if not sym or sym not in sens_position:
            continue
        reduit = ((o.get("action") or "").upper() == "SELL"
                  if sens_position[sym] > 0
                  else (o.get("action") or "").upper() == "BUY")
        if not reduit:
            continue
        prix = o.get("auxPrice")
        if prix is None:
            continue
        try:
            stops[sym] = float(prix)
        except (TypeError, ValueError):
            continue
    return stops


def evaluation_ibkr(positions_charge: dict, ordres_charge: dict) -> dict:
    positions = (positions_charge or {}).get("positions") or []
    sens = {}
    for p in positions:
        try:
            sens[p.get("symbol")] = float(p.get("position") or 0.0)
        except (TypeError, ValueError):
            continue
    stops = _stops_ibkr(ordres_charge, sens)
    normalisees = [
        {"symbol": p.get("symbol"), "price": p.get("avg_cost"),
         "size": abs(float(p.get("position") or 0.0))}
        for p in positions
    ]
    return evaluer_positions_stop(normalisees, stops, devise="USD")


def _dialecte_ibkr(dest) -> dict:
    pos, ok = _appel(dest, "/positions")
    if not ok or not isinstance(pos, dict):
        return evaluation_illisible("USD")
    oo, ok = _appel(dest, "/openorders")
    if not ok or not isinstance(oo, dict):
        return evaluation_illisible("USD")
    return evaluation_ibkr(pos, oo)
```

- [ ] **Step 4 : Lancer les tests**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risque_engage_dialectes.py -q
```
Attendu : tout passe.

- [ ] **Step 5 : Ajouter `/openorders` au bridge IBKR**

Dans `ibkr-bridge/bridge.py`, après la route `/positions` (ligne ~330), insérer :

```python
@app.route("/openorders", methods=["GET"])
@require_bridge_key
def openorders():
    """Ordres vivants, dont les enfants de bracket qui portent les stops.

    Ajouté le 2026-08-25 pour la mesure du risque engagé : `/positions` ne
    porte ni stop ni prix courant, donc le risque d'une position n'y est pas
    dérivable. Le stop d'un bracket IBKR est un ordre ENFANT, jamais un champ
    de la position.
    """
    try:
        worker.ensure_connected()
        trades = worker.call(lambda: worker.ib.reqAllOpenOrdersAsync())
        cleaned = []
        for t in trades or []:
            o, c = t.order, t.contract
            cleaned.append({
                "order_id": o.orderId,
                "symbol": c.symbol,
                "conId": c.conId,
                "sec_type": c.secType,
                "action": o.action,
                "orderType": o.orderType,
                "totalQuantity": float(o.totalQuantity or 0.0),
                "auxPrice": (float(o.auxPrice)
                             if o.auxPrice not in (None, "") else None),
                "lmtPrice": (float(o.lmtPrice)
                             if o.lmtPrice not in (None, "") else None),
                "parentId": o.parentId,
            })
        return jsonify({"ok": True, "count": len(cleaned), "orders": cleaned})
    except Exception as e:
        logger.warning(f"openorders error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
```

⚠️ `reqAllOpenOrdersAsync()` rend des `Trade`. Si la version d'`ib_insync` installée ne l'expose pas, utiliser `worker.ib.openTrades()` (synchrone) via `worker.call`. Vérifier avant d'écrire :

```bash
grep -n "ib_insync\|ib-insync" ibkr-bridge/requirements.txt
```

- [ ] **Step 6 : Constater que le bridge est injoignable, et le DIRE**

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  'sudo docker exec -e PYTHONPATH=/app -w /app scalping-radar python -c "
from backend.services.risque_engage import mesurer_destination
from backend.services.destinations_registry import DESTINATIONS
print(mesurer_destination(DESTINATIONS[\"admin_ibkr_us\"]))"'
```
Attendu : `lisible: False` — **c'est le verdict juste**, pas un échec. Consigner dans le message de commit que le chemin `/openorders` n'a **pas** été exercé.

- [ ] **Step 7 : Commit**

```bash
git add ibkr-bridge/bridge.py backend/services/risque_engage.py backend/tests/test_risque_engage_dialectes.py
git commit -m "feat(risque): dialecte IBKR + /openorders sur le bridge

Le stop d'un bracket IBKR est un ordre ENFANT ; /positions ne le porte pas.
Appariement par symbole ET par sens : ⛔ un ordre de même sens que la
position l'agrandit, il ne la protège pas.

⚠️ NON VÉRIFIÉ EN MARCHE. Le bridge IBKR refuse les connexions depuis la
décision du 10/08 de rester à 100 USD. Testé sur bouchons uniquement ; en
production la destination rend illisible, ce qui est le verdict juste."
```

---

## Task 7 : Persister `risk_money` avec le push

Prérequis du contrôle de réciprocité (spec §4 et §9). Aujourd'hui `risk_money` n'existe nulle part de durable : `journalctl` ne tient qu'un jour et `mt5_pushes.bridge_response` ne le porte pas — il a fallu le reconstruire par arithmétique inverse.

**Files:**
- Modify: `backend/services/mt5_pushes_service.py` (`_ensure_schema` ligne 37, `update_push_result` ligne 110)
- Modify: `backend/services/mt5_bridge.py` (appels `update_push_result` lignes 1124 et 1439)
- Test: `backend/tests/test_risk_money_persiste.py` (créer)

**Interfaces:**
- Produces : la colonne `mt5_pushes.risk_money` (`REAL`, nullable).
- Produces : `update_push_result(..., *, ok, response=None, risk_money=None)` — nouveau paramètre **nommé et optionnel**, pour que les cinq appelants existants (`binance_bridge_client.py:230`, `bridge_push_ledger.py:97` et `:110`, `mt5_bridge.py:1124` et `:1439`) continuent de fonctionner sans modification.
- Produces : `_risk_money_pour_persistance(sz: dict) -> float | None` dans `mt5_bridge.py`.

- [ ] **Step 1 : Écrire le test**

`backend/tests/test_risk_money_persiste.py` :

```python
"""`risk_money` doit survivre au trade (2026-08-25).

Sans lui, vérifier qu'une position risque bien ce qu'on voulait exige de
reconstruire le chiffre par arithmétique inverse — ce qui a été nécessaire le
25/08 et n'est pas tenable en routine. C'est aussi ce qui manquait pour
détecter les positions placebo du démo, où 455 trades sur 610 risquaient un
millième du voulu sans qu'aucun contrôle ne le voie.
"""
from __future__ import annotations

import sqlite3


def test_la_colonne_existe(tmp_path, monkeypatch):
    from backend.services import mt5_pushes_service as svc
    db = tmp_path / "t.db"
    monkeypatch.setattr(svc, "_db_path", lambda: str(db))
    svc._ensure_schema()
    cols = {r[1] for r in sqlite3.connect(db).execute(
        "PRAGMA table_info(mt5_pushes)")}
    assert "risk_money" in cols


def test_une_base_ANCIENNE_recoit_la_colonne_sans_perdre_ses_lignes(tmp_path,
                                                                    monkeypatch):
    """⛔ La migration doit être idempotente ET non destructive : `mt5_pushes`
    porte l'historique des ordres réels."""
    from backend.services import mt5_pushes_service as svc
    db = tmp_path / "t.db"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE mt5_pushes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, destination_id TEXT NOT NULL,
            date TEXT NOT NULL, pair TEXT NOT NULL, direction TEXT NOT NULL,
            entry_price_5dp TEXT NOT NULL, pushed_at TEXT NOT NULL,
            ok INTEGER NOT NULL, bridge_response TEXT,
            UNIQUE(destination_id, date, pair, direction, entry_price_5dp))""")
        c.execute("""INSERT INTO mt5_pushes (destination_id, date, pair,
            direction, entry_price_5dp, pushed_at, ok)
            VALUES ('admin_kraken','2026-08-23','PAXG/USD','buy','4607.60986',
                    '2026-08-23T18:45:31+00:00', 1)""")
    monkeypatch.setattr(svc, "_db_path", lambda: str(db))
    svc._ensure_schema()
    svc._ensure_schema()          # deux fois : idempotence
    with sqlite3.connect(db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(mt5_pushes)")}
        n = c.execute("SELECT COUNT(*) FROM mt5_pushes").fetchone()[0]
        val = c.execute("SELECT risk_money FROM mt5_pushes").fetchone()[0]
    assert "risk_money" in cols
    assert n == 1, "la migration a perdu des lignes"
    assert val is None, "une ligne ancienne doit rester NULL, pas devenir 0"


def test_une_valeur_ABSENTE_reste_NULL_et_ne_devient_pas_zero():
    """⛔ Zéro dirait « on a voulu risquer zéro ». NULL dit « on ne sait pas ».
    Les confondre rendrait tout contrôle de réciprocité ininterprétable."""
    from backend.services.mt5_bridge import _risk_money_pour_persistance
    assert _risk_money_pour_persistance({}) is None
    assert _risk_money_pour_persistance({"risk_money": None}) is None
    assert _risk_money_pour_persistance({"risk_money": 0.0}) == 0.0
    assert _risk_money_pour_persistance({"risk_money": "1.55"}) == 1.55
    assert _risk_money_pour_persistance({"risk_money": "illisible"}) is None
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risk_money_persiste.py -q
```
Attendu : `AssertionError: assert 'risk_money' in cols`

- [ ] **Step 3 : Ajouter la colonne, en migration idempotente**

Dans `backend/services/mt5_pushes_service.py`, à la fin de `_ensure_schema()` (après la création de l'index, ligne ~62), à l'intérieur du même `with sqlite3.connect(...) as c:` :

```python
        # risk_money (2026-08-25) : le risque VOULU, pour pouvoir le comparer
        # au risque réellement engagé. Le 25/08 il a fallu le reconstruire par
        # arithmétique inverse — journalctl ne tient qu'un jour et
        # bridge_response ne le porte pas.
        #
        # ⛔ NULLABLE, et ajouté par ALTER pour ne pas toucher aux lignes
        # existantes : `mt5_pushes` porte l'historique des ordres réels. Un
        # risk_money inconnu ne vaut pas zéro — les confondre rendrait tout
        # contrôle de réciprocité ininterprétable.
        try:
            c.execute("ALTER TABLE mt5_pushes ADD COLUMN risk_money REAL")
        except sqlite3.OperationalError:
            pass        # colonne déjà présente — migration idempotente
```

Puis, dans `update_push_result`, ajouter le paramètre nommé et l'écrire :

```python
def update_push_result(
    destination_id: str,
    push_date: str,
    pair: str,
    direction: str,
    entry_price_5dp: str,
    *,
    ok: bool,
    response: dict[str, Any] | None = None,
    risk_money: float | None = None,
) -> None:
```

et remplacer le `UPDATE` par :

```python
            c.execute(
                """
                UPDATE mt5_pushes
                SET ok = ?, bridge_response = ?,
                    risk_money = COALESCE(?, risk_money)
                WHERE destination_id = ? AND date = ? AND pair = ?
                  AND direction = ? AND entry_price_5dp = ?
                """,
                (
                    1 if ok else 0,
                    body,
                    risk_money,
                    destination_id,
                    push_date,
                    pair,
                    direction,
                    entry_price_5dp,
                ),
            )
```

⚠️ `COALESCE` : un appelant qui ne fournit pas `risk_money` **ne doit pas effacer** une valeur déjà écrite. Les cinq appelants existants passent donc `None` sans dommage.

- [ ] **Step 4 : Écrire le convertisseur défensif**

Dans `backend/services/mt5_bridge.py` :

```python
def _risk_money_pour_persistance(sz: dict):
    """`risk_money` prêt pour la base. ⛔ `None` plutôt que zéro sur l'inconnu.

    La valeur peut arriver en chaîne depuis un JSON. Une valeur illisible ne
    vaut pas « zéro risque » : elle vaut « on ne sait pas ».
    """
    v = (sz or {}).get("risk_money")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
```

Puis, aux **deux** appels de `update_push_result` dans `mt5_bridge.py` (lignes 1124 et 1439), ajouter l'argument. `sz` est en portée dans les deux cas (`sz = sizing.compute_risk_money(setup, dest)` juste au-dessus) :

```python
        mt5_pushes_service.update_push_result(
            ...,                                    # arguments existants inchangés
            risk_money=_risk_money_pour_persistance(sz),
        )
```

⚠️ **Ne pas toucher** aux appels de `binance_bridge_client.py:230` ni de `bridge_push_ledger.py:97`/`:110` : `sz` n'y est pas en portée, et le `COALESCE` fait qu'ils n'effacent rien. Ces lignes-là garderont `risk_money` à NULL, ce qui est la vérité — mieux qu'un zéro inventé.

- [ ] **Step 5 : Lancer les tests**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/test_risk_money_persiste.py -q
```
Attendu : tout passe.

- [ ] **Step 6 : Commit**

```bash
git add backend/services/mt5_bridge.py backend/tests/test_risk_money_persiste.py
git commit -m "feat(mesure): persister risk_money avec le push

Le risque VOULU n'existait nulle part de durable : journalctl ne tient qu'un
jour et bridge_response ne le porte pas. Le 25/08 il a fallu le reconstruire
par arithmétique inverse pour expliquer un écart — pas tenable en routine.

⛔ Colonne NULLABLE. Un risk_money inconnu ne vaut pas zéro ; les confondre
rendrait tout contrôle de réciprocité ininterprétable. C'est exactement ce
qui manquait pour voir les positions placebo du démo."
```

---

## Task 8 : Déployer et prouver

**Files:** aucun — déploiement et vérification.

- [ ] **Step 1 : Pousser et tirer**

```bash
git push origin main
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  'cd /home/ec2-user/scalping && git pull --ff-only && git log --oneline -1'
```

- [ ] **Step 2 : Reconstruire l'image et redémarrer**

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  'cd /home/ec2-user/scalping && sudo docker build -q -t scalping-radar:latest . && \
   sudo systemctl restart scalping && sleep 30 && \
   sudo docker ps --filter name=scalping-radar --format "{{.Status}}"'
```
⚠️ `docker cp` ne survit pas au restart — la reconstruction est obligatoire.

- [ ] **Step 3 : Mesurer les cinq destinations**

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  'sudo docker exec -e PYTHONPATH=/app -w /app scalping-radar python -c "
import re
from backend.app import _mesurer_risque_destinations, _formater_risque
from backend.services.risque_engage import taux_eurusd
print(re.sub(r\"</?b>\", \"\", _formater_risque(_mesurer_risque_destinations(),
                                               taux=taux_eurusd())))"'
```

Attendu : cinq blocs. MT5 avec pourcentage, Kraken Futures avec des euros et « aucun plafond », Kraken Spot à zéro mesuré, IBKR `illisible`.

- [ ] **Step 4 : Contre-vérifier Kraken par un chemin indépendant**

Recalculer à la main depuis `/positions` et `/openorders`, et comparer au bloc Kraken du message. Les deux doivent coïncider au centième. Si les positions ont changé depuis, refaire le calcul sur les positions du moment — **ne jamais comparer à une valeur figée dans ce plan**.

- [ ] **Step 5 : Prouver l'arrivée du message Telegram**

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  'set -a; . /opt/scalping/.env >/dev/null 2>&1; set +a; \
   curl -s -X POST "https://app.scalping-radar.online/api/telegram/sales-webhook" \
     -H "Content-Type: application/json" \
     -H "X-Telegram-Bot-Api-Secret-Token: $TELEGRAM_SALES_WEBHOOK_SECRET" \
     -d "{\"message\":{\"chat\":{\"id\":$SALES_TELEGRAM_CHAT_ID},\"text\":\"risque\"}}"'
```

puis :

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  'sudo docker logs --since 3m scalping-radar 2>&1 | \
   grep -oE "api\.telegram\.org.*sendMessage \"[^\"]+\"" | tail -2'
```

⛔ La preuve est le **200 d'`api.telegram.org`**, jamais le 200 de notre propre API. Un `sent: true` sans cette ligne ne prouve rien — c'est le défaut qui a laissé le moniteur muet trois mois.

- [ ] **Step 6 : Vérifier que rien n'a été déplacé**

```bash
ssh -i scalping-key.pem ec2-user@100.103.107.75 \
  'sudo docker exec scalping-radar cat /app/data/saturation_risque.json'
```
Attendu : identique à avant la manipulation. ⛔ Interroger le système ne doit pas faire taire son alerte suivante.

- [ ] **Step 7 : Suite complète, contre la base de référence**

```bash
./venv/Scripts/python.exe -m pytest backend/tests/ -q \
  --ignore=backend/tests/test_mt5_bridge_controle_risque.py \
  --ignore=backend/tests/test_mt5_bridge_margin_fit.py
```

⚠️ **Base de référence au 2026-08-25 : 7 échecs et 54 erreurs préexistants**, sans rapport avec ce chantier (`MetaTrader5` absent du venv local, plus un test instable `test_run_shadow_log_ne_score_qu_une_fois_par_bougie_reellement_nouvelle`). Comparer les **noms** des tests en échec, pas seulement leur nombre.

---

## Ce que ce plan ne fait PAS

- **Aucun plafond de risque n'est posé sur Kraken.** Ce serait une porte de trading qui refuse des ordres, pas une mesure — décision distincte, à trancher par Xavier (spec §10).
- **Le chemin `/openorders` d'IBKR n'est pas exercé.** Le bridge est fermé ; il rendra `illisible` en production.
- **Le contrôle de réciprocité n'est pas automatisé.** Task 7 en pose le prérequis (persister `risk_money`) ; le contrôle lui-même reste à écrire.
- **Les watchers du spot ne sont pas persistés.** Un redémarrage du bridge spot perd ses stops logiciels et laisse les positions nues. Constaté en écrivant ce plan, hors périmètre — **à traiter séparément, c'est un risque réel.**
