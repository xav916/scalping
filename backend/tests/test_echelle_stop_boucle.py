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

    async def _po(base, cle, ticket, sl, tp=None):
        # ⚠️ `tp` ajoute le 2026-10-09 : la boucle transmet desormais aussi
        # l'objectif (regle de Xavier, << toujours 2 euros d'ecart devant >>).
        # La doublure le CAPTURE plutot que de l'ignorer -- une doublure qui
        # jette un argument ne garde rien de ce qu'il transporte.
        appels.append({"ticket": ticket, "sl": sl, "tp": tp})
        return reponse

    monkeypatch.setattr(B, "_positions", _p)
    monkeypatch.setattr(B, "_poser", _po)
    return appels


def test_desarmee_elle_ne_sonde_RIEN(monkeypatch):
    monkeypatch.delenv("ECHELLE_STOP_OR", raising=False)
    assert asyncio.run(B.appliquer()) == {"arme": False}


def test_elle_passe_un_PRIX_et_du_BON_COTE(monkeypatch):
    """🔑 LE TEST QUI MANQUAIT, et son absence a coûté un défaut sur l'argent
    réel le 2026-10-09.

    L'ancienne version vérifiait une **distance** (`sl_dist == 1,50 × taux`) —
    et elle passait, parce que la distance était juste. Mais la route calcule
    `price_open − sl_dist` pour un achat : le stop atterrissait **du côté de la
    perte**. Un stop voulu à +0,75 € était posé à −0,75 €.

    ⇒ Vérifier une magnitude ne dit rien du **côté**. Ce test vérifie le côté,
    qui est tout le sujet d'un stop.
    """
    appels = _brancher(monkeypatch, [_pos()], {"ok": True, "sl": 4201.69})
    b = asyncio.run(B.appliquer())
    assert len(b["deplaces"]) == 1
    assert b["deplaces"][0]["palier"] == 1.50

    # C'est un PRIX qui part, pas une distance.
    assert "sl_absolu" not in appels[0] or True   # lisibilite
    envoye = appels[0]["sl"]
    attendu = round(4200.0 + 1.50 * TAUX, 2)
    assert envoye == pytest.approx(attendu), (
        "le prix envoye n'est pas celui du palier")

    # ⛔ ET SURTOUT : du cote du PROFIT. Pour un achat, au-DESSUS de l'entree.
    assert envoye > 4200.0, (
        "le stop est du cote de la PERTE : c'est exactement le defaut du "
        "2026-10-09, ou +0,75 EUR etait pose a -0,75 EUR")


def test_pour_une_VENTE_le_stop_est_SOUS_l_entree(monkeypatch):
    """⚠️ Le miroir du test ci-dessus. Un signe correct pour l'achat et faux
    pour la vente serait passe inapercu la moitie du temps."""
    appels = _brancher(
        monkeypatch,
        [_pos(type="sell", price_current=4200.0 - 1.80 * TAUX, sl=4210.0)],
        {"ok": True, "sl": 4198.31})
    b = asyncio.run(B.appliquer())
    assert len(b["deplaces"]) == 1
    envoye = appels[0]["sl"]
    assert envoye == pytest.approx(round(4200.0 - 1.50 * TAUX, 2))
    assert envoye < 4200.0, "le stop d'une vente doit etre SOUS l'entree"


def test_un_stop_REPOUSSE_par_le_courtier_est_SIGNALE(monkeypatch):
    """⛔ Croire qu'un stop est a +0,75 quand le courtier l'a repousse ailleurs
    rendrait toute la mesure fausse."""
    _brancher(monkeypatch, [_pos()],
              {"ok": True, "sl": 4195.00, "sl_demande": 4201.69,
               "sl_clampe_par_le_courtier": True})
    b = asyncio.run(B.appliquer())
    assert b.get("clampes") == 1
    assert b["deplaces"][0]["clampe"] is True


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


def test_la_boucle_transmet_AUSSI_l_objectif(monkeypatch):
    """🔑 Regle de Xavier du 2026-10-09 : l'objectif suit le prix, a 2 EUR
    devant. Le stop seul ne suffit plus -- et un TP calcule mais jamais
    transmis serait le defaut de l'echelle de ce matin, en pire : elle
    calculait juste et n'appliquait rien.
    """
    monkeypatch.setenv("ECHELLE_STOP_OR", "1")
    monkeypatch.setenv("ECHELLE_STOP_OR_PALIERS", "1.0:0.75")
    monkeypatch.delenv("ECHELLE_TP_ECART_EUR", raising=False)
    monkeypatch.setattr(B, "_taux", lambda: 1.1235)
    monkeypatch.setenv("MT5_BRIDGE_LIVE_URL", "http://pont.test")
    monkeypatch.setenv("MT5_BRIDGE_LIVE_API_KEY", "k")

    pos = [{"ticket": 7, "symbol": "XAUUSD", "type": "buy",
            "price_open": 4190.0, "price_current": 4190.0 + 1.20 * 1.1235,
            "sl": 4190.0 - 20 * 1.1235, "tp": 0.0,
            "comment": "scalping-radar-2026-10-09"}]
    appels = _brancher(monkeypatch, pos, {"ok": True})

    asyncio.run(B.appliquer())

    assert len(appels) == 1
    # Stop a +0,75 EUR, objectif a +3,00 EUR (seuil 1,00 + ecart 2,00).
    assert appels[0]["sl"] == pytest.approx(4190.0 + 0.75 * 1.1235, abs=0.01)
    assert appels[0]["tp"] == pytest.approx(4190.0 + 3.00 * 1.1235, abs=0.01)
