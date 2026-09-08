"""L'envoi Telegram interne : un seul endroit qui sait appeler l'endpoint.

## ⛔ Le défaut que ces tests figent

Trois appelants Python postaient le jeton dans un EN-TÊTE `X-Admin-Token` et
`channel` dans le CORPS. L'endpoint lit les deux en **paramètres d'URL**, et
la variable `INFRA_TELEGRAM_TOKEN` n'existe dans aucun `.env`.

Conséquence : requête sans jeton ⇒ **403**, avalé par un `except` large.

🔑 L'alerte de rétrogradation de l'or — écrite le matin même du 2026-09-08 pour
réparer « l'or a cessé de s'auto-exécuter et **rien ne l'a dit** » — était donc
elle-même MUETTE. Les scripts shell, eux, avaient toujours raison :
`?token=${TOKEN}&channel=infra`.
"""
from __future__ import annotations

import hashlib
import io

import pytest

from backend.services import canaux_telegram as ct


class _Reponse:
    status_code = 200

    @staticmethod
    def raise_for_status():
        return None


@pytest.fixture
def envoi(monkeypatch):
    vus: list[dict] = []
    import httpx
    monkeypatch.setattr(httpx, "post",
                        lambda url, params=None, json=None, timeout=None:
                        (vus.append({"url": url, "params": params or {},
                                     "json": json or {}}), _Reponse())[1])
    monkeypatch.setenv("SHADOW_LOG_TOKEN", "un-jeton")
    return vus


def test_le_jeton_et_le_canal_partent_en_PARAMETRES_D_URL(envoi):
    """⛔ LE défaut. En en-tête, l'endpoint ne les voit pas."""
    assert ct.notifier("ic_markets", "titre", "corps") is True
    assert envoi[0]["params"]["token"] == "un-jeton"
    assert envoi[0]["params"]["channel"] == "ic_markets"
    assert "channel" not in envoi[0]["json"]


def test_le_corps_ne_porte_que_le_titre_et_le_texte(envoi):
    ct.notifier("infra", "t", "c")
    assert envoi[0]["json"] == {"title": "t", "body": "c"}


def test_un_jeton_ABSENT_est_DIT_pas_avale(envoi, monkeypatch, caplog):
    """⛔ Un envoi silencieusement raté est pire que pas d'envoi : on croit
    être prévenu. C'est très exactement ce qui s'est passé."""
    import logging
    monkeypatch.delenv("SHADOW_LOG_TOKEN", raising=False)
    with caplog.at_level(logging.WARNING, logger=ct.__name__):
        assert ct.notifier("infra", "titre", "corps") is False
    assert any("SHADOW_LOG_TOKEN absent" in r.getMessage() for r in caplog.records)
    assert envoi == []


def test_un_echec_reseau_rend_False_et_le_DIT(monkeypatch, caplog):
    import logging
    import httpx

    def _casse(*a, **k):
        raise RuntimeError("reseau HS")

    monkeypatch.setattr(httpx, "post", _casse)
    monkeypatch.setenv("SHADOW_LOG_TOKEN", "x")
    with caplog.at_level(logging.WARNING, logger=ct.__name__):
        assert ct.notifier("infra", "titre", "corps") is False
    assert any("échoué" in r.getMessage() for r in caplog.records)


def test_le_JETON_choisi_est_celui_que_l_endpoint_attend():
    """🔑 L'endpoint compare une empreinte SHA256 figée. `SHADOW_LOG_TOKEN` est
    le seul nom dont la valeur y correspond en production — vérifié le
    2026-09-08. Ce test fige le NOM, la valeur restant hors du dépôt."""
    src = io.open("backend/services/canaux_telegram.py", encoding="utf-8").read()
    assert 'os.getenv("SHADOW_LOG_TOKEN"' in src
    app = io.open("backend/app.py", encoding="utf-8").read()
    assert "SHADOW_PUBLIC_TOKEN_HASH" in app
    # et l'endpoint lit bien `token` en parametre, pas en en-tete
    i = app.index('@app.post("/api/admin/notify-infra-telegram")')
    entete = app[i:i + 400]
    assert "token: str" in entete
    assert "Header" not in entete


def test_PLUS_AUCUN_appelant_n_utilise_l_en_tete():
    """⚠️ Le test qui empêche la rechute. Trois copies s'étaient alignées sur
    la même erreur ; une quatrième la reproduirait.

    ⛔ Le filtre passe par l'AST, pas par un préfixe `#` : ma première version
    signalait la docstring qui EXPLIQUE le défaut. Un test qui échoue sur son
    propre commentaire est un test qu'on finit par désactiver.
    """
    import ast
    import glob
    fautifs = []
    for f in glob.glob("backend/services/*.py"):
        src = io.open(f, encoding="utf-8").read()
        arbre = ast.parse(src)
        # Les lignes qui appartiennent à un littéral texte — docstrings
        # comprises — ne sont pas du code.
        texte = set()
        for n in ast.walk(arbre):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                texte.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
        for i, ligne in enumerate(src.splitlines(), 1):
            if i in texte or ligne.strip().startswith("#"):
                continue
            if "X-Admin-Token" in ligne or 'getenv("INFRA_TELEGRAM_TOKEN"' in ligne:
                fautifs.append(f"{f}:{i}")
    assert fautifs == [], fautifs


def test_les_deux_notificateurs_du_moteur_passent_par_le_helper():
    src = io.open("backend/services/promotion_engine.py", encoding="utf-8").read()
    assert src.count("notifier(") >= 2
    assert "httpx.post" not in src
