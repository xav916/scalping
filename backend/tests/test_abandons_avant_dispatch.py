"""Le trou de journal entre la construction d'un setup et son dispatch.

⛔ Le constat qui l'a rendu visible (08/09) : sur l'or du compte réel,
**353 achats évalués et ZÉRO vente** depuis le 04/09, alors que le détecteur
produit **399 setups vendeurs pour 164 acheteurs** sur 950 fenêtres, et
qu'aucun filtre de direction n'est configuré. Les autres paires, elles,
restent équilibrées.

L'écart naissait donc entre la construction du setup et l'arrivée aux portes —
et **aucun journal ne couvrait cet intervalle**. `filter_high_confidence_setups`
tourne avant `resolve_destinations` : ce qu'il écarte ne produit aucun refus.

🔑 « Aucun signal » et « signal écarté en silence » se lisaient pareil. C'est
la forme même du défaut que ce dépôt passe son temps à réparer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from backend.services import analysis_engine as ae


@dataclass
class _Motif:
    value: str = "momentum_down"


@dataclass
class _Detection:
    pattern: _Motif = field(default_factory=_Motif)


@dataclass
class _Sens:
    value: str = "sell"


@dataclass
class SetupFictif:
    confidence_score: float
    pair: str = "XAU/USD"
    direction: _Sens = field(default_factory=_Sens)
    pattern: _Detection = field(default_factory=_Detection)
    horizon: str = "5min"


@pytest.fixture
def journal(monkeypatch):
    """Capture ce que le filtre enregistre, sans toucher à la base."""
    lignes: list[dict] = []
    import backend.services.rejection_service as rs
    monkeypatch.setattr(rs, "record_rejection",
                        lambda **kw: lignes.append(kw))
    return lignes


# ── Le comportement du filtre ne change PAS ──────────────────────────

def test_le_filtre_garde_EXACTEMENT_ce_qu_il_gardait(journal):
    """⚠️ Instrumenter ne doit rien changer à ce qui passe. Un journal qui
    modifie ce qu'il observe ne mesure plus rien."""
    seuil = ae.MIN_CONFIDENCE_SCORE
    setups = [SetupFictif(seuil - 1), SetupFictif(seuil), SetupFictif(seuil + 10)]
    gardes = ae.filter_high_confidence_setups(setups)
    assert [s.confidence_score for s in gardes] == [seuil + 10, seuil]


def test_le_tri_par_score_DECROISSANT_est_preserve(journal):
    """⚠️ Scores DÉRIVÉS du seuil, jamais écrits en dur : `MIN_CONFIDENCE_SCORE`
    vaut 25 en production mais pas forcément ici, et une valeur inventée
    testerait mon invention plutôt que le tri."""
    s = ae.MIN_CONFIDENCE_SCORE
    setups = [SetupFictif(s + 5), SetupFictif(s + 30), SetupFictif(s + 15)]
    gardes = ae.filter_high_confidence_setups(setups)
    assert [x.confidence_score for x in gardes] == [s + 30, s + 15, s + 5]


# ── Ce qui est écarté laisse désormais une trace ─────────────────────

def test_un_setup_ECARTE_est_journalise(journal):
    ae.filter_high_confidence_setups([SetupFictif(ae.MIN_CONFIDENCE_SCORE - 5)])
    assert len(journal) == 1
    ligne = journal[0]
    assert ligne["reason_code"] == ae.MOTIF_ABANDON_AVANT_DISPATCH
    assert ligne["pair"] == "XAU/USD"
    assert ligne["direction"] == "sell"


def test_la_trace_porte_le_MOTIF_et_l_HORIZON(journal):
    """🔑 Sans eux, on saurait qu'un setup a été écarté sans pouvoir dire
    lequel — donc sans pouvoir répondre à la question posée."""
    ae.filter_high_confidence_setups([SetupFictif(1.0)])
    d = journal[0]["details"]
    assert d["signal_pattern"] == "momentum_down"
    assert d["horizon"] == "5min"
    assert d["seuil"] == ae.MIN_CONFIDENCE_SCORE


def test_la_trace_n_impute_l_abandon_a_AUCUN_compte(journal):
    """⛔ L'abandon PRÉCÈDE `resolve_destinations`. L'imputer à une destination
    serait faux, et fausserait tous les comptages par compte."""
    ae.filter_high_confidence_setups([SetupFictif(1.0)])
    assert journal[0]["destination_id"] is None


def test_RIEN_n_est_journalise_quand_rien_n_est_ecarte(journal):
    """⚠️ Une sonde qui écrit à chaque passage noie ce qu'elle doit montrer."""
    ae.filter_high_confidence_setups([SetupFictif(ae.MIN_CONFIDENCE_SCORE + 1)])
    assert journal == []


def test_une_liste_VIDE_ne_journalise_rien(journal):
    assert ae.filter_high_confidence_setups([]) == []
    assert journal == []


# ── La sonde ne casse jamais ce qu'elle observe ──────────────────────

def test_une_base_en_ECHEC_ne_casse_pas_le_pipeline(monkeypatch):
    """⛔ Best-effort strict. Le 20/08, un garde-fou qui masquait un `NameError`
    ne protégeait rien ; ici c'est l'inverse qu'on veut : observer ne doit
    jamais empêcher de trader."""
    import backend.services.rejection_service as rs

    def _casse(**kw):
        raise RuntimeError("base indisponible")

    monkeypatch.setattr(rs, "record_rejection", _casse)
    gardes = ae.filter_high_confidence_setups(
        [SetupFictif(1.0), SetupFictif(ae.MIN_CONFIDENCE_SCORE + 5)])
    assert len(gardes) == 1


def test_un_setup_MAL_FORME_ne_casse_pas_le_filtre(monkeypatch, journal):
    """⚠️ Les setups viennent de plusieurs provenances (rejeux, essais) et
    n'ont pas tous un `pattern` exploitable."""
    s = SetupFictif(1.0)
    s.pattern = None
    gardes = ae.filter_high_confidence_setups([s])
    assert gardes == []
    assert journal[0]["details"]["signal_pattern"] is None


def test_le_motif_est_TRADUIT():
    """Un code non traduit s'affiche brut dans les récaps."""
    from backend.services.rejection_service import REASON_LABELS_FR
    assert ae.MOTIF_ABANDON_AVANT_DISPATCH in REASON_LABELS_FR


# ── La rétrogradation part dans le fil de SON compte (2026-09-08) ────
#
# ⛔ Le vrai coupable, trouvé en cherchant où mourait la vente or : deux
# rétrogradations automatiques ont éteint l'or sur `admin_live` — la vente le
# 03/09, l'achat le 08/09 à 03:00 — et **rien ne l'a dit**. Le récapitulatif
# du moteur partait sur `infra`, où un événement touchant l'argent réel d'un
# compte se noie. Motif de la sauvegarde S3 : *l'alerte arrivait, elle s'est
# noyée dans le bruit.*

def _demotion(destination="admin_live", pair="XAU/USD", direction="buy"):
    return {"pair": pair, "direction": direction, "destination": destination,
            "trigger": "dd_above_10.0%_7d:13.96"}


@pytest.fixture
def envois(monkeypatch):
    """Capture les POST Telegram sans réseau — PARAMÈTRES D'URL compris.

    ## ⛔ Pourquoi cette version-ci

    La première ne gardait que `kw["json"]`, et le test lisait `channel` DANS
    LE CORPS. Or l'endpoint lit `token` et `channel` en **paramètres d'URL** :
    le test passait donc sur du code qui, en production, partait sans jeton et
    recevait un **403** avalé par un `except` large.

    🔑 C'est comme ça que l'alerte écrite le matin du 2026-09-08 pour réparer
    « l'or a cessé de s'auto-exécuter et rien ne l'a dit » est restée MUETTE
    tout en ayant trois tests verts. Un faux qui accepte n'importe quelle forme
    d'appel ne teste pas l'appel — il teste qu'on a appelé quelque chose.
    """
    faits: list[dict] = []

    class _Rep:
        def raise_for_status(self):
            return None

    import httpx
    monkeypatch.setattr(
        httpx, "post",
        lambda url, **kw: (faits.append({**(kw.get("json") or {}),
                                         "_params": kw.get("params") or {}}),
                           _Rep())[1])
    monkeypatch.setenv("SHADOW_LOG_TOKEN", "jeton-de-test")
    return faits


def test_une_retrogradation_part_dans_le_fil_du_COMPTE(envois):
    from backend.services import promotion_engine as pe
    pe._notifier_les_comptes([_demotion()])
    assert len(envois) == 1
    # ⛔ Dans les paramètres d'URL, pas dans le corps : c'est le seul endroit
    # que l'endpoint lit.
    assert envois[0]["_params"]["channel"] == "ic_markets"
    assert envois[0]["_params"]["token"] == "jeton-de-test"


def test_le_message_dit_que_le_SIGNAL_continue(envois):
    """🔑 Sans cette phrase, « rétrogradé » se lit comme « la paire est morte ».
    L'état TELEGRAM produit encore le signal — seule l'exécution s'arrête."""
    from backend.services import promotion_engine as pe
    pe._notifier_les_comptes([_demotion()])
    corps = envois[0]["body"]
    assert "signal continue" in corps
    assert "execution automatique s'arrete" in corps
    assert "Aucune position ouverte" in corps


def test_le_message_porte_le_MOTIF_de_la_retrogradation(envois):
    from backend.services import promotion_engine as pe
    pe._notifier_les_comptes([_demotion()])
    assert "dd_above_10.0%_7d:13.96" in envois[0]["body"]


def test_une_destination_HORS_trading_ne_double_pas_le_recap(envois):
    """⚠️ Le récap infra les couvre déjà. Les envoyer deux fois ferait du bruit
    exactement là où on vient d'en retirer."""
    from backend.services import promotion_engine as pe
    pe._notifier_les_comptes([_demotion(destination=None)])
    assert envois == []


def test_SANS_retrogradation_aucun_message(envois):
    from backend.services import promotion_engine as pe
    pe._notifier_les_comptes([])
    assert envois == []


def test_un_envoi_en_echec_ne_casse_PAS_le_moteur(monkeypatch):
    """⛔ Une notification n'est jamais assez importante pour interrompre le
    cycle de promotion qu'elle décrit."""
    import httpx

    from backend.services import promotion_engine as pe
    monkeypatch.setenv("INFRA_TELEGRAM_TOKEN", "jeton-de-test")
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("reseau")))
    pe._notifier_les_comptes([_demotion()])      # ne doit pas lever
