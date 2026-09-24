"""Le point d'entrée des signaux d'un bot tiers.

⛔ Deux exigences qui ne se négocient pas :

1. **Un `source` inconnu est refusé**, jamais accepté au cas où. Un jeton valide
   pour un fournisseur ne vaut pas pour un autre.
2. **Le motif du refus est TOUJOURS rendu.** Un fournisseur qui ne sait pas
   pourquoi il est filtré croit qu'on l'ignore — et de notre côté, « il n'émet
   rien » deviendrait indiscernable de « on jette tout ». C'est la forme de
   silence que ce dépôt a déjà payée quatre fois.

Conception : `docs/superpowers/specs/2026-08-26-bot-externe-demo-design.md`
"""
from __future__ import annotations

import sqlite3

import pytest


CHARGE = {
    "source": "bot_x",
    "external_id": "abc-123",
    "pair": "XAU/USD",
    "direction": "sell",
    "entry_price": 3400.0,
    "stop_loss": 3410.0,
    "take_profit": 3380.0,
    "horizon": "4h",
    "pattern": "momentum_up",
    "confidence": 71.0,
    "emitted_at": "2026-08-26T10:00:00+00:00",
}


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    from backend.services import trade_log_service
    monkeypatch.setattr(trade_log_service, "_DB_PATH", db_path)
    from backend.services import external_signals
    monkeypatch.setattr(external_signals, "_SCHEMA_ENSURED", False)
    yield db_path


@pytest.fixture
def fournisseurs(monkeypatch):
    import config.settings as st
    monkeypatch.setattr(st, "EXTERNAL_SIGNAL_TOKENS",
                        {"bot_x": "jeton_x", "bot_y": "jeton_y"}, raising=False)


# ── L'authentification ────────────────────────────────────────────────────

def test_un_signal_valide_est_accepte(fournisseurs):
    from backend.services.external_signals import valider

    ok, motif = valider(CHARGE, "jeton_x")
    assert ok is True, motif


def test_une_source_inconnue_est_refusee(fournisseurs):
    """⛔ Jamais « au cas où » : un fournisseur non déclaré n'existe pas."""
    from backend.services.external_signals import valider

    ok, motif = valider(dict(CHARGE, source="bot_inconnu"), "jeton_x")
    assert ok is False
    assert "source" in motif.lower()


def test_le_jeton_d_un_fournisseur_ne_vaut_pas_pour_un_autre(fournisseurs):
    """⛔ Sinon un fournisseur pourrait poster sous le nom d'un autre, et
    l'attribution — donc tout le dispositif de mesure — s'effondre."""
    from backend.services.external_signals import valider

    ok, motif = valider(CHARGE, "jeton_y")
    assert ok is False
    assert "jeton" in motif.lower()


def test_sans_fournisseur_declare_rien_ne_passe(monkeypatch):
    """Vide par défaut : une installation qui n'a rien configuré n'ingère rien."""
    import config.settings as st
    from backend.services.external_signals import valider

    monkeypatch.setattr(st, "EXTERNAL_SIGNAL_TOKENS", {}, raising=False)
    ok, _ = valider(CHARGE, "jeton_x")
    assert ok is False


# ── La validation du contenu ──────────────────────────────────────────────

@pytest.mark.parametrize("champ", ["pair", "direction", "entry_price",
                                    "stop_loss", "external_id"])
def test_un_champ_obligatoire_manquant_est_refuse(fournisseurs, champ):
    from backend.services.external_signals import valider

    charge = {k: v for k, v in CHARGE.items() if k != champ}
    ok, motif = valider(charge, "jeton_x")
    assert ok is False
    assert champ in motif


def test_un_sens_inconnu_est_refuse(fournisseurs):
    from backend.services.external_signals import valider

    ok, motif = valider(dict(CHARGE, direction="peut-etre"), "jeton_x")
    assert ok is False
    assert "direction" in motif


def test_un_prix_non_numerique_est_refuse(fournisseurs):
    from backend.services.external_signals import valider

    ok, motif = valider(dict(CHARGE, entry_price="trois-mille"), "jeton_x")
    assert ok is False
    assert "entry_price" in motif


def test_le_motif_est_toujours_rendu(fournisseurs):
    """⛔ Un refus muet rend « il n'émet rien » indiscernable de « on jette »."""
    from backend.services.external_signals import valider

    for charge, jeton in ((dict(CHARGE, source="x"), "jeton_x"),
                          (CHARGE, "mauvais"),
                          (dict(CHARGE, direction="?"), "jeton_x")):
        ok, motif = valider(charge, jeton)
        assert ok is False
        assert motif and len(motif) > 10, f"motif trop pauvre : {motif!r}"


# ── L'idempotence ─────────────────────────────────────────────────────────

def test_le_meme_signal_deux_fois_ne_compte_qu_une(fournisseurs):
    """⛔ Un fournisseur qui rejoue sa file ne doit pas doubler les ordres."""
    from backend.services.external_signals import enregistrer

    assert enregistrer(CHARGE) is True
    assert enregistrer(CHARGE) is False


def test_deux_signaux_distincts_passent_tous_les_deux(fournisseurs):
    from backend.services.external_signals import enregistrer

    assert enregistrer(CHARGE) is True
    assert enregistrer(dict(CHARGE, external_id="abc-124")) is True


def test_le_meme_external_id_chez_deux_fournisseurs_ne_collisionne_pas(fournisseurs):
    """L'unicité porte sur le COUPLE (source, external_id) : deux bots peuvent
    numéroter leurs signaux à partir de 1 sans s'écraser."""
    from backend.services.external_signals import enregistrer

    assert enregistrer(CHARGE) is True
    assert enregistrer(dict(CHARGE, source="bot_y")) is True


# ── Le setup construit ────────────────────────────────────────────────────

def test_le_setup_porte_sa_source_et_son_horizon(fournisseurs):
    """Sans ça, ni le verrou du résolveur ni l'essai du banc ne fonctionnent."""
    from backend.services.external_signals import construire_setup

    s = construire_setup(CHARGE)
    assert s.source == "bot_x"
    assert s.horizon == "4h"
    assert s.pair == "XAU/USD"
    assert s.direction.value == "sell"
    assert s.entry_price == pytest.approx(3400.0)


def test_le_setup_construit_est_refuse_par_le_verrou(fournisseurs):
    """Bout en bout : le setup issu de l'ingestion n'atteint pas l'argent réel."""
    from backend.services import bridge_destinations as bd
    from backend.services.external_signals import construire_setup

    assert bd._est_externe(construire_setup(CHARGE)) is True


# ── La porte de confiance voit-elle la confiance ? (2026-09-24) ───────────

def _dest(min_conf: float):
    from types import SimpleNamespace
    return SimpleNamespace(
        destination_id="admin_legacy", min_confidence=min_conf, user_id=None,
        allowed_asset_classes=frozenset({"metal"}), watched_pairs=frozenset(),
        excluded_pairs=frozenset(), symbol_map=None, auto_exec_enabled=True,
        bridge_url="", bridge_api_key="")


@pytest.mark.parametrize("confiance,refuse", [(92.0, False), (45.0, True)])
def test_la_porte_de_confiance_lit_bien_la_confiance_du_signal(confiance, refuse):
    """⛔ LE défaut que ce test fige, et qui a rendu tout le chemin inerte.

    Toute la chaîne de refus lit `setup.confidence_score`, jamais `confidence` :
    `getattr(setup, "confidence_score", None) or 0`. `ExternalSetup` ne posait
    que `confidence`. L'attribut manquant valait donc **0**, et un signal
    annonçant 92 était refusé en `below_confidence` contre un seuil de 60 — en
    silence, et depuis la conception du 2026-08-26.

    Un mécanisme écrit, testé en isolation, et inerte en composition : la
    famille de défauts que ce dépôt a déjà nommée quatre fois.
    """
    from backend.services.external_signals import ExternalSetup
    from backend.services.mt5_bridge import _check_rejection
    setup = ExternalSetup({**CHARGE, "confidence": confiance})
    motif = _check_rejection(setup, _dest(60.0))
    assert (motif == "below_confidence") is refuse, motif


def test_un_signal_sans_confiance_est_refuse_A_L_ENTREE(fournisseurs):
    """⚠️ Bruyamment, à la porte — pas silencieusement au septième portillon.

    Un canal ne publie pas de score : la confiance est ce que l'exploitant
    ATTRIBUE à une source. Sans elle, on refuse en `forme`, avec le motif.
    """
    from backend.services.external_signals import valider_detaille
    charge = {k: v for k, v in CHARGE.items() if k != "confidence"}
    ok, motif, cause = valider_detaille(charge, "jeton_x")
    assert ok is False and cause == "forme" and "confidence" in motif
