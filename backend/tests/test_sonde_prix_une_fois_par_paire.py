"""La sonde des trades OPEN interroge le prix UNE FOIS PAR PAIRE (2026-09-05).

Mesure de prod, samedi 05/09 à 22:55 Paris — **marché fermé**, donc pas un
seul prix ne bouge :

    appels /price              1 020 en 30 min   (~34 / minute)
    refus 429                    ~240 / heure
    pic d'appels dans la minute  147             (limite du plan : 55)
    lignes OPEN dans backtest.db 593  sur  23 paires distinctes

🔑 `check_open_trades` boucle sur les **lignes**, pas sur les **paires**. Les
593 lignes ouvertes ne portent que 23 marchés : le même prix est redemandé des
dizaines de fois par cycle.

⛔ Le cache prix (TTL 5 s) ne rattrape rien : parcourir 593 lignes en série à
~150 ms l'appel prend plus d'une minute, donc la copie a **expiré** bien avant
qu'on revienne sur la même paire. Un cache plus court que le parcours qu'il
doit couvrir n'est pas un cache.

⚠️ Ce que ces tests verrouillent :
  - un appel réseau par paire distincte et par passage, jamais par ligne ;
  - toutes les lignes d'une paire sont évaluées avec le MÊME prix — une sonde
    est un instantané, deux lignes de la même paire ne peuvent pas voir deux
    marchés différents ;
  - une paire dont le prix est indisponible laisse ses lignes intactes, elle
    n'en ferme aucune.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.services import backtest_service as bs


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Base neuve, isolée : `_conn` relit `_DB_PATH` à chaque appel."""
    chemin = tmp_path / "backtest.db"
    monkeypatch.setattr(bs, "_DB_PATH", chemin)
    bs._init_schema()
    return chemin


def _ouvrir(chemin, pair: str, n: int) -> None:
    """n lignes OPEN sur la même paire, toutes loin du SL et du TP."""
    c = sqlite3.connect(str(chemin), isolation_level=None)
    for _ in range(n):
        c.execute(
            "INSERT INTO trades (pair, direction, entry_price, stop_loss, "
            "take_profit_1, take_profit_2, emitted_at, outcome) "
            "VALUES (?, 'buy', 100.0, 90.0, 110.0, 120.0, '2026-09-05T00:00:00Z', 'OPEN')",
            (pair,),
        )
    c.close()


def _compteur(monkeypatch, prix: dict[str, float | None]):
    """Remplace le fetch réseau et compte les appels PAR paire."""
    appels: list[str] = []

    async def _faux(pair: str):
        appels.append(pair)
        return prix.get(pair)

    monkeypatch.setattr(bs, "fetch_current_price", _faux)
    return appels


@pytest.mark.asyncio
async def test_un_seul_appel_reseau_par_paire(base, monkeypatch):
    """Le défaut mesuré : 6 lignes sur 2 paires ne valent que 2 appels."""
    _ouvrir(base, "EUR/USD", 4)
    _ouvrir(base, "GBP/USD", 2)
    appels = _compteur(monkeypatch, {"EUR/USD": 101.0, "GBP/USD": 101.0})

    await bs.check_open_trades()

    assert sorted(appels) == ["EUR/USD", "GBP/USD"], (
        f"un appel par PAIRE, pas par ligne — reçu {len(appels)} appels : {appels}"
    )


@pytest.mark.asyncio
async def test_les_lignes_d_une_paire_voient_le_MEME_prix(base, monkeypatch):
    """Une sonde est un instantané : deux lignes jumelles finissent pareil."""
    _ouvrir(base, "XAU/USD", 3)
    _compteur(monkeypatch, {"XAU/USD": 111.0})   # au-dessus de TP1 = 110

    await bs.check_open_trades()

    c = sqlite3.connect(str(base))
    sorties = [r[0] for r in c.execute("SELECT exit_price FROM trades")]
    issues = {r[0] for r in c.execute("SELECT outcome FROM trades")}
    c.close()
    assert sorties == [111.0, 111.0, 111.0], "un seul prix pour tout le passage"
    assert issues == {"WIN_TP1"}, f"les trois lignes suivent le même sort, vu {issues}"


@pytest.mark.asyncio
async def test_une_paire_sans_prix_ne_ferme_rien(base, monkeypatch):
    """⛔ Prix indisponible ⇒ on ne décide RIEN, on ne devine pas une sortie."""
    _ouvrir(base, "EUR/USD", 2)
    _ouvrir(base, "WTI/USD", 2)
    appels = _compteur(monkeypatch, {"EUR/USD": 111.0, "WTI/USD": None})

    await bs.check_open_trades()

    c = sqlite3.connect(str(base))
    restants = {
        r[0] for r in c.execute("SELECT outcome FROM trades WHERE pair='WTI/USD'")
    }
    c.close()
    assert restants == {"OPEN"}, "un marché muet laisse ses lignes ouvertes"
    assert sorted(appels) == ["EUR/USD", "WTI/USD"], "la paire muette est sondée une fois"
