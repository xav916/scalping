"""La soupape d'équilibre est-elle JUGEABLE ? (2026-08-24)

Elle appartient à la famille mesurée à −0,329 R, elle a été armée contre ma
recommandation et son seuil abaissé à 0,40 R. Une décision prise contre la
mesure doit au minimum rester **révisable sur des mesures**.

> **Un mécanisme qu'on ne peut pas compter est un mécanisme auquel on ne peut
> que croire.**

Ce que ces tests verrouillent :

1. ⛔ **un bridge muet ne vaut pas « aucune activation »** — le sort du
   moniteur muet ; `([], False)` et `([], True)` sont deux verdicts ;
2. la sortie **à l'équilibre** est comptée à part : c'est le **coût** du
   mécanisme, le trade neutralisé avant d'avoir payé. La confondre avec un
   stop ordinaire effacerait précisément ce qu'on cherche ;
3. ⛔ **on ne conclut pas sur une poignée** — le message dit combien
   d'activations il manque avant que la question se pose. C'est le piège du
   groupe à 27, appliqué à l'avance.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "notify_activations_equilibre.py")


@pytest.fixture()
def s():
    spec = importlib.util.spec_from_file_location("activ", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _act(ticket, libere=7.66, marge=1.20):
    return {"status": "equilibre", "ticket": ticket, "symbol": "GBPUSD",
            "message": f"marge={marge:.2f}R libere={libere:.2f} "
                       f"reste=0.00000 sl_avant=1.35117"}


# --------------------------------------------------------------------------
# L'agrégat
# --------------------------------------------------------------------------

def test_le_risque_libere_est_relu_depuis_le_message(s):
    r = s.resumer([_act(1, libere=7.66), _act(2, libere=4.45)], {})
    assert r["total"] == 2
    assert r["libere"] == pytest.approx(12.11)


def test_un_message_abime_ne_fait_pas_tomber_la_sonde(s):
    """Une sonde qui plante sur une ligne bizarre cesse de surveiller."""
    r = s.resumer([{"status": "equilibre", "ticket": 1, "message": "libere=xx"},
                   {"status": "equilibre", "ticket": 2, "message": None}], {})
    assert r["total"] == 2 and r["libere"] == 0.0


def test_la_sortie_A_L_EQUILIBRE_est_comptee_A_PART(s):
    """⛔ Le cœur de la mesure. Un stop touché APRÈS remontée à l'entrée, ce
    n'est pas une perte : c'est un trade **neutralisé avant d'avoir payé** —
    le coût exact que le mécanisme est soupçonné d'infliger."""
    devenirs = {1: ("SL", 0.02, "CLOSED"), 2: ("TP1", 14.2, "CLOSED")}
    s_ = s.resumer([_act(1), _act(2)], devenirs)["sorties"]
    assert s_["a_l_equilibre"] == 1
    assert s_["objectif"] == 1


def test_une_position_encore_OUVERTE_n_est_pas_un_resultat(s):
    """La compter comme un succès ou un échec inventerait une issue."""
    r = s.resumer([_act(1)], {1: (None, None, "OPEN")})
    assert r["sorties"]["encore_ouvert"] == 1
    assert r["sorties"]["objectif"] == 0 and r["sorties"]["a_l_equilibre"] == 0


def test_un_ticket_INTROUVABLE_est_dit_inconnu(s):
    """⛔ Jamais rangé dans une catégorie par défaut : une issue absente n'est
    pas une issue neutre."""
    assert s.resumer([_act(99)], {})["sorties"]["inconnu"] == 1


def test_une_cloture_MANUELLE_ne_compte_ni_pour_ni_contre(s):
    """Xavier ferme des positions à la main : ces sorties ne disent rien du
    mécanisme et ne doivent polluer aucune des deux colonnes."""
    s_ = s.resumer([_act(1)], {1: ("MANUAL", 3.2, "CLOSED")})["sorties"]
    assert s_["autre"] == 1
    assert s_["objectif"] == 0 and s_["a_l_equilibre"] == 0


def test_aucune_activation_rend_un_agregat_VIDE_et_valide(s):
    r = s.resumer([], {})
    assert r["total"] == 0 and r["libere"] == 0.0


# --------------------------------------------------------------------------
# ⛔ Muet n'est pas « rien ne s'est passé »
# --------------------------------------------------------------------------

def test_un_bridge_illisible_est_un_verdict_DISTINCT(s, monkeypatch):
    """Le sort du moniteur muet : une absence lue comme un « tout va bien »."""
    monkeypatch.setattr(s, "_appel", lambda dest, chemin: (None, False))
    lignes, ok = s.activations(object())
    assert lignes == [] and ok is False


# ⛔ Ces deux tests simulaient une lecture de `/audit`. La sonde ne lit PLUS
# `/audit` : le bridge y plafonne `limit` a 500 SANS le dire, si bien qu'une
# demande de 5 000 rendait les 500 lignes les plus ANCIENNES et concluait « la
# soupape n'a jamais agi » — pendant 13 jours, alors que l'unique activation
# siege a l'id 3904. La source est desormais le journal persiste.
#
# 🔑 Les tests suivent la source, sinon ils verrouillent le defaut.


def _journal(tmp_path, monkeypatch, lignes, did="admin_live"):
    """Pointe le journal sur une base jetable et y depose des activations."""
    from backend.services import motif_interne_cloture as mi
    monkeypatch.setattr(mi, "_DB", tmp_path / "j.db")
    import sqlite3
    c = sqlite3.connect(str(tmp_path / "j.db"), isolation_level=None)
    c.execute("CREATE TABLE IF NOT EXISTS personal_trades (mt5_ticket TEXT)")
    c.close()
    mi.enregistrer_activations(did, lignes, dernier_id=99)


def test_un_journal_lisible_SANS_activation_est_un_autre_verdict(
        s, tmp_path, monkeypatch):
    """⛔ `([], False)` et `([], True)` sont deux verdicts distincts : « on n'a
    pas pu lire » n'est pas « il ne s'est rien passe »."""
    _journal(tmp_path, monkeypatch, [])
    lignes, ok = s.activations(object(), "admin_live")
    assert lignes == [] and ok is True


def test_le_journal_ne_rend_QUE_la_destination_demandee(
        s, tmp_path, monkeypatch):
    """⚠️ Melanger les comptes gonflerait le denominateur — et la soupape a
    ete armee sur le reel seulement."""
    _journal(tmp_path, monkeypatch, [
        {"id": 1, "status": "equilibre", "ticket": 2, "pair": "XAU/USD",
         "sl": 4475.2, "created_at": "2026-08-31T02:48:35+00:00"}])
    lignes, ok = s.activations(object(), "admin_live")
    assert ok is True and len(lignes) == 1 and str(lignes[0]["ticket"]) == "2"
    autres, ok = s.activations(object(), "admin_legacy")
    assert ok is True and autres == []


def test_sans_identifiant_la_sonde_rend_un_ECHEC_de_lecture(
        s, tmp_path, monkeypatch):
    """⛔ Le premier correctif lisait `str(dest)` — un repr d'objet qui ne
    correspondait a aucune ligne. La sonde rendait encore zero, corrigee mais
    toujours fausse. Un identifiant manquant doit se DIRE."""
    _journal(tmp_path, monkeypatch, [])
    lignes, ok = s.activations(object(), None)
    assert lignes == [] and ok is False
