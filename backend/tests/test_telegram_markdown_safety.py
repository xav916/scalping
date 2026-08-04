"""Markdown legacy Telegram — échecs silencieux de notification (2026-08-04).

Telegram `parse_mode="Markdown"` fait échouer **tout** le message avec un 400
« can't parse entities » dès qu'un caractère actif non apparié apparaît dans
une entité. Les envois étant best-effort (`try/except`), la notification
disparaît sans bruit.

Cas constaté : les raisons de transition d'admission sont interpolées dans
`_Raison : ...._`, or elles contiennent presque toujours un underscore —
`pnl_pct`, `_not_admitted`, `auto_demote`, `VALID_DESTINATIONS`. Le message
`auto-demote: pnl_pct -103.71` qui a rétrogradé trois paires equity le
2026-08-04 n'est jamais arrivé.

Second cas : `mean_reversion_up` et `mean_reversion_down` n'avaient pas de
libellé FR. Le repli affichait la valeur brute, underscores compris, ce qui
cassait le message de setup principal.
"""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from backend.models.schemas import PatternType
from backend.services.telegram_service import (
    _PATTERN_EXPLAIN_FR,
    md_safe,
)

ACTIFS = "_*`[]"


def _entites_appariees(text: str) -> bool:
    """Approximation : aucun caractère actif ne subsiste dans le texte libre."""
    return not any(c in text for c in ACTIFS)


# --- le neutraliseur -------------------------------------------------------

@pytest.mark.parametrize("brut", [
    "auto-demote: pnl_pct -103.71 < 2.0",
    "_not_admitted sur 34 des 40 signaux",
    "correctif VALID_DESTINATIONS appliqué",
    "ratio *important* et [note] et `code`",
])
def test_les_caracteres_actifs_disparaissent(brut):
    assert _entites_appariees(md_safe(brut))


def test_le_texte_reste_lisible():
    """Substitution et non suppression : l'information doit survivre."""
    out = md_safe("auto-demote: pnl_pct -103.71")
    assert "pnl-pct" in out and "-103.71" in out


def test_vide_et_none():
    assert md_safe(None) == ""
    assert md_safe("") == ""


def test_le_texte_sans_caractere_actif_est_inchange():
    s = "Paire rétrogradée : résultats insuffisants sur 30 trades."
    assert md_safe(s) == s


def test_accents_et_emoji_preserves():
    s = "🚨 Pétrole rétrogradé — écart trop élevé"
    assert md_safe(s) == s


# --- la notification de transition ----------------------------------------

def _capture_envoi(monkeypatch):
    """Intercepte le payload réellement posté à Telegram.

    ⚠️ Construire la ligne à la main dans le test ne prouverait rien : c'est
    la chaîne de production qu'il faut exercer.
    """
    from backend.services import telegram_service as ts
    envoyes: list[dict] = []

    class _Resp:
        status_code = 200
        text = "ok"

    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, **kw):
            envoyes.append(json)
            return _Resp()

    monkeypatch.setattr(ts, "is_configured", lambda: True)
    monkeypatch.setattr(ts, "_destinataires", lambda: [("xav", "123")])
    monkeypatch.setattr(ts, "TELEGRAM_BOT_TOKEN", "T", raising=False)
    monkeypatch.setattr(ts.httpx, "AsyncClient", lambda *a, **k: _Client())
    return ts, envoyes


def test_la_transition_nenvoie_plus_rien(monkeypatch):
    """`send_pac_transition_user` est un no-op depuis le 2026-08-04.

    Les transitions vont au récap quotidien — ~26/jour envoyés en double sur
    user et infra, sans décision associée. Ce test existe pour qu'une
    réactivation soit un choix explicite et non un accident : si quelqu'un
    remet un envoi ici, il devra le justifier en supprimant ce test.

    ⚠️ Si la fonction est réactivée, `md_safe` redevient indispensable sur
    la raison : elle contient presque toujours un underscore (`pnl_pct`,
    `_not_admitted`), qui casse l'entité italique et fait perdre TOUT le
    message en silence.
    """
    import asyncio
    ts, envoyes = _capture_envoi(monkeypatch)
    asyncio.run(ts.send_pac_transition_user(
        "MSFT", "sell", "TELEGRAM", "OBSERVED",
        "auto-demote: pnl_pct -103.71 < 2.0"))
    assert envoyes == [], "la transition ne doit plus rien envoyer"


# --- le message de setup ---------------------------------------------------

def test_tous_les_patterns_ont_un_libelle_fr():
    """Sans libellé, le repli affiche la valeur brute et ses underscores."""
    manquants = [p.value for p in PatternType if p.value not in _PATTERN_EXPLAIN_FR]
    assert manquants == [], f"patterns sans libellé FR : {manquants}"


@pytest.mark.parametrize("value", [p.value for p in PatternType])
def test_aucun_libelle_ne_contient_de_caractere_actif(value):
    assert _entites_appariees(_PATTERN_EXPLAIN_FR[value])


def test_le_repli_pattern_est_neutralise():
    """Un pattern ajouté à l'enum sans libellé ne doit plus casser le message.

    Exerce `_format_setup` avec un pattern absent de la table FR — c'est le
    chemin de repli réel, pas une expression recopiée.
    """
    from backend.services import telegram_service as ts
    setup = _setup_minimal(pattern=NS(value="nouveau_pattern_exotique"))
    text = ts._format_setup(setup)
    assert text.count("_") % 2 == 0, f"underscores impairs : {text!r}"
    assert "nouveau-pattern-exotique" in text


def _setup_minimal(verdict_summary=None, pattern=PatternType.RANGE_BOUNCE_UP):
    return NS(
        pair="EUR/USD", direction=NS(value="buy"),
        pattern=NS(pattern=pattern, confidence=0.8, description="rebond"),
        confidence_score=75.0, verdict_action="TAKE",
        verdict_summary=verdict_summary, verdict_reasons=[], verdict_warnings=[],
        verdict_blockers=[],
        entry_price=1.1000, stop_loss=1.0950, take_profit_1=1.1090,
        take_profit_2=1.1140, risk_pips=50.0, reward_pips_1=90.0,
        reward_pips_2=140.0, risk_reward_1=1.8, risk_reward_2=2.8,
        detected_at=None, asset_class="forex", is_simulated=False,
    )


def test_le_verdict_summary_est_neutralise():
    """Texte libre du moteur de scoring, interpolé en italique.

    Exerce `_format_setup`, pas une ligne reconstruite : une vérification
    faite à la main ne prouverait pas que la production applique md_safe.
    """
    from backend.services import telegram_service as ts
    text = ts._format_setup(
        _setup_minimal("score bridé par macro_veto et vix_high"))
    assert text.count("_") % 2 == 0, f"underscores impairs : {text!r}"
    assert "macro-veto" in text


def test_le_message_de_setup_survit_a_un_resume_hostile():
    from backend.services import telegram_service as ts
    text = ts._format_setup(
        _setup_minimal("veto _macro_ et *vix* et [ref] et `pnl_pct`"))
    assert text.count("_") % 2 == 0 and text.count("*") % 2 == 0
