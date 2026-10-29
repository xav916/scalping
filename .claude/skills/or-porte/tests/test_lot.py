import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import lot as L  # noqa: E402

# Le bucket REEL XAU/USD buy de admin_live, releve le 2026-10-29 :
# il est AUTO_EXEC par une ligne specifique a la destination (id=376,
# manuel Xavier du 08/09) qui domine l'auto-pause du 06/10.
SETUP = {
    "pair": "XAU/USD", "direction": "buy",
    "entry_price": 2412.50, "stop_loss": 2404.10,
    "confidence_score": 71, "pattern": "range_bounce",
    "horizon": "30min", "chaine": None, "shadow_system_id": None,
    "is_simulated": False, "verdict_blockers": [],
    "risk_pct": 0.35,
}


def test_les_onze_champs_sont_exactement_ceux_que_les_portes_lisent():
    assert L.CHAMPS_PORTES == frozenset({
        "chaine", "confidence_score", "direction", "entry_price", "horizon",
        "is_simulated", "pair", "pattern", "shadow_system_id", "stop_loss",
        "verdict_blockers"})
    assert L.CHAMPS_ADMIS == L.CHAMPS_PORTES | {"risk_pct"}


def test_empreinte_stable_et_longue_de_douze():
    e = L.empreinte_setup(SETUP)
    assert len(e) == 12
    assert e == L.empreinte_setup(dict(reversed(list(SETUP.items()))))


@pytest.mark.parametrize("champ", sorted(L.CHAMPS_PORTES))
def test_modifier_un_champ_lu_perime_l_empreinte(champ):
    autre = dict(SETUP)
    autre[champ] = "AUTRE" if not isinstance(autre[champ], (int, float)) \
        or isinstance(autre[champ], bool) else autre[champ] + 1
    assert L.empreinte_setup(autre) != L.empreinte_setup(SETUP)


def test_modifier_risk_pct_ne_perime_PAS_l_empreinte():
    autre = dict(SETUP, risk_pct=99.0)
    assert L.empreinte_setup(autre) == L.empreinte_setup(SETUP)


def test_cle_inconnue_refusee_en_nommant_la_cle():
    mauvais = {"destinations": ["admin_live"],
               "setups": [dict(SETUP, humeur="bonne")]}
    with pytest.raises(L.ErreurLot, match="humeur"):
        L.valider_lot(mauvais)


def test_champ_requis_manquant_refuse_en_nommant_le_champ():
    sans = {k: v for k, v in SETUP.items() if k != "stop_loss"}
    with pytest.raises(L.ErreurLot, match="stop_loss"):
        L.valider_lot({"destinations": ["admin_live"], "setups": [sans]})


def test_lot_sans_destinations_refuse():
    with pytest.raises(L.ErreurLot, match="destinations"):
        L.valider_lot({"setups": [SETUP]})


def test_lot_valide_passe_et_rend_les_setups():
    bon = {"destinations": ["admin_live", "admin_kraken"], "setups": [SETUP]}
    valide = L.valider_lot(bon)
    assert valide["destinations"] == ["admin_live", "admin_kraken"]
    assert valide["setups"][0]["pair"] == "XAU/USD"
