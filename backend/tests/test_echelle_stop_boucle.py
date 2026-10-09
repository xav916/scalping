"""La boucle qui applique l'échelle, et le nouveau comportement du pont.

🔑 Le test le plus important de ce fichier est
`test_already_protected_est_compte_A_PART` : `/position/sltp` était un **no-op**
dès que la position avait un stop. Sans le paramètre `deplacer`, cette boucle
aurait tourné en rendant `already_protected: true` à chaque passage — elle
aurait eu **l'air de fonctionner sans jamais rien déplacer**. C'est la forme de
silence que ce dépôt a déjà payée plusieurs fois.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.services import echelle_stop_boucle as B
from backend.services import echelle_stop_or as E

_PONT = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"
TAUX = 1.1235


def _pos(**kw):
    base = {"symbol": "XAUUSD", "type": "buy", "price_open": 4200.0,
            "price_current": 4200.0 + 1.80 * TAUX, "sl": 4190.0,
            "ticket": 777, "comment": "scalping-radar-2026-10-09"}
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("MT5_BRIDGE_LIVE_URL", "http://pont")
    monkeypatch.setenv("MT5_BRIDGE_LIVE_API_KEY", "k")
    monkeypatch.setattr(B, "_taux", lambda: TAUX)


def _brancher(monkeypatch, positions, reponse):
    appels = []

    async def _p(base, cle):
        return positions

    async def _po(base, cle, ticket, sl_dist):
        appels.append({"ticket": ticket, "sl_dist": sl_dist})
        return reponse

    monkeypatch.setattr(B, "_positions", _p)
    monkeypatch.setattr(B, "_poser", _po)
    return appels


def test_desarmee_elle_ne_sonde_RIEN(monkeypatch):
    monkeypatch.delenv("ECHELLE_STOP_OR", raising=False)
    assert asyncio.run(B.appliquer()) == {"arme": False}


def test_elle_deplace_et_passe_une_DISTANCE(monkeypatch):
    """⚠️ Le contrat de la route est une DISTANCE depuis `price_open`. Lui
    passer un prix absolu placerait le stop à des milliers de dollars."""
    appels = _brancher(monkeypatch, [_pos()], {"ok": True, "sl": 4201.69})
    b = asyncio.run(B.appliquer())
    assert len(b["deplaces"]) == 1
    assert b["deplaces"][0]["palier"] == 1.50
    # +1,50 EUR au-dessus de l'entree, mais le PRIX du stop est arrondi a
    # 2 decimales (precision de l'or) : la distance en decoule.
    # ⛔ Ma premiere version exigeait 1,50 x taux exactement. Elle etait
    # FAUSSE : arrondir le prix PUIS en deduire la distance est correct, car
    # un stop doit tomber sur un prix que le courtier accepte.
    sl_attendu = round(4200.0 + 1.50 * TAUX, 2)
    assert appels[0]["sl_dist"] == pytest.approx(abs(4200.0 - sl_attendu))
    assert abs(appels[0]["sl_dist"] - 1.50 * TAUX) < 0.01, "arrondi aberrant"
    assert appels[0]["ticket"] == 777


def test_already_protected_est_compte_A_PART(monkeypatch):
    """🔑 LE test qui compte. Si la route refuse de déplacer, la boucle doit le
    DIRE — pas le confondre avec un succès."""
    _brancher(monkeypatch, [_pos()],
              {"ok": True, "already_protected": True,
               "motif_no_op": "SLTP_DEPLACEMENT_ENABLED=false"})
    b = asyncio.run(B.appliquer())
    assert b["deja_protege"] == 1
    assert b["deplaces"] == [], "un refus a ete compte comme un succes"


def test_refus_du_cliquet_est_compte_A_PART(monkeypatch):
    _brancher(monkeypatch, [_pos()], {"ok": False, "refus_cliquet": True})
    b = asyncio.run(B.appliquer())
    assert b["refus_cliquet"] == 1 and b["deplaces"] == []


def test_un_pont_MUET_ne_fait_pas_conclure_a_zero_position(monkeypatch):
    """⛔ `None` et non `[]` : « je ne sais pas » n'est pas « il n'y a rien »."""
    async def _p(base, cle):
        return None
    monkeypatch.setattr(B, "_positions", _p)
    b = asyncio.run(B.appliquer())
    assert b.get("erreur") == "positions illisibles"


def test_taux_ILLISIBLE_bloque_tout(monkeypatch):
    monkeypatch.setattr(B, "_taux", lambda: None)
    b = asyncio.run(B.appliquer())
    assert b.get("erreur") == "taux illisible"


def test_une_position_A_LA_MAIN_n_est_jamais_touchee(monkeypatch):
    appels = _brancher(monkeypatch, [_pos(comment="")], {"ok": True})
    b = asyncio.run(B.appliquer())
    assert appels == [] and b["deplaces"] == []


# ─── Le PONT : ce que le patch du 2026-10-09 garantit ───────────────────

def test_le_pont_REFUSE_le_deplacement_par_defaut():
    ligne = next(l for l in _PONT.read_text(encoding="utf-8").splitlines()
                 if "SLTP_DEPLACEMENT_ENABLED" in l and "getenv" in l)
    src = _PONT.read_text(encoding="utf-8")
    i = src.index("SLTP_DEPLACEMENT_ENABLED = os.getenv")
    assert '"false"' in src[i:i + 160], f"le defaut n'est plus refuse : {ligne!r}"


def test_le_pont_exige_que_le_client_DEMANDE_le_deplacement():
    """⛔ Un appel du garde-fou nu ne doit jamais bouger un stop par effet de
    bord : les deux conditions se cumulent."""
    src = _PONT.read_text(encoding="utf-8")
    assert 'deplacer = bool(data.get("deplacer")) and SLTP_DEPLACEMENT_ENABLED' in src


def test_le_pont_a_son_PROPRE_cliquet():
    """🔑 Un cliquet côté client SEUL laisse passer tout autre appelant — et
    reculer un stop est le geste qui élargit une perte."""
    src = _PONT.read_text(encoding="utf-8")
    i = src.index("LE CLIQUET, cote SERVEUR")
    bloc = src[i:i + 900]
    assert "recule" in bloc and "refus_cliquet" in bloc
    assert "409" in bloc


def test_le_pont_distingue_les_deux_usages_dans_sa_trace():
    src = _PONT.read_text(encoding="utf-8")
    assert '"sltp-deplacement" if deplacer else "sltp-guard"' in src
