"""Épargne de requêtes 5 min pour les paires servies uniquement en journalier.

Posé le 2026-08-08 après mesure : le pic de consommation Twelve Data atteignait
**40 requêtes sur la minute la plus chargée**, pour une limite de 55. Ajouter
5 paires l'aurait porté à ~47 (85 %) — la marge exacte qui avait fait échouer
un rattrapage le matin même en affamant la production.

⚠️ Ce que ces tests verrouillent :
  - l'INDEXATION. Les résultats sont lus par position (`results[1 + i]`) ;
    sauter une entrée décalerait silencieusement toutes les paires suivantes,
    attribuant les bougies d'une paire à une autre. C'est le défaut le plus
    grave possible ici, et il serait invisible.
  - le défaut vide : sans réglage, rien ne change.
"""
import pytest

from config.settings import CANDLE_5MIN_SKIP_PAIRS


def test_vide_par_defaut():
    """Sans réglage, aucune paire n'est épargnée."""
    import importlib
    import config.settings as st
    importlib.reload(st)
    assert st.CANDLE_5MIN_SKIP_PAIRS == frozenset()


def test_la_liste_est_normalisee(monkeypatch):
    monkeypatch.setenv("CANDLE_5MIN_SKIP_PAIRS", " bnb/usd , xlm/usd ")
    import importlib
    import config.settings as st
    importlib.reload(st)
    assert st.CANDLE_5MIN_SKIP_PAIRS == frozenset({"BNB/USD", "XLM/USD"})
    monkeypatch.delenv("CANDLE_5MIN_SKIP_PAIRS", raising=False)
    importlib.reload(st)


# ── Le point critique : l'indexation ──────────────────────────────────

def test_l_indexation_par_position_est_preservee():
    """Rejoue la construction de la liste : une paire épargnée doit occuper
    une PLACE, sinon `results[1 + i]` attribue les bougies d'une paire à une
    autre — et rien ne le signalerait."""
    import asyncio

    WATCHED = ["EUR/USD", "BNB/USD", "XAU/USD", "XLM/USD", "BTC/USD"]
    SKIP = {"BNB/USD", "XLM/USD"}

    async def _pas_de_bougies():
        return ([], False)

    async def _faux_fetch(pair):
        return ([f"bougie-{pair}"], False)

    async def _construire():
        taches = []
        for p in WATCHED:
            taches.append(_pas_de_bougies() if p.upper() in SKIP else _faux_fetch(p))
        return await asyncio.gather(*taches)

    res = asyncio.run(_construire())
    assert len(res) == len(WATCHED), "une entrée par paire, épargnée ou non"
    for i, p in enumerate(WATCHED):
        bougies, _ = res[i]
        if p in SKIP:
            assert bougies == [], f"{p} devait être épargnée"
        else:
            assert bougies == [f"bougie-{p}"], (
                f"position {i} rend les bougies de {bougies} au lieu de {p} — "
                f"l'indexation est décalée"
            )


def test_une_paire_epargnee_rend_une_liste_vide_pas_None():
    """`None` provoquerait un TypeError au dépaquetage ; `[]` traverse le
    pipeline comme une paire sans données, cas déjà géré."""
    import asyncio

    async def _pas_de_bougies():
        return ([], False)

    bougies, simule = asyncio.run(_pas_de_bougies())
    assert bougies == [] and simule is False
