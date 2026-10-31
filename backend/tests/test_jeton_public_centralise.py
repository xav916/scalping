"""Le jeton public : une seule lecture, aucune valeur par défaut (audit S-1).

## Le défaut corrigé

Le hash du jeton était écrit **EN DUR à neuf endroits** de `backend/app.py`
(l. 2375, 2410, 2472, 2566, 2949, 3652, 4348, 4459, 4856), et le jeton en
clair servait de valeur par défaut dans 36 scripts, 2 sondes, 6 tests et
4 documents. Le dépôt étant cloné dans des environnements d'agents, le secret
était de fait diffusé.

🔑 Neuf copies ne donnent pas neuf chances d'être juste : elles donnent neuf
chances de **diverger**. Elles étaient identiques par copie, pas par
construction — rien ne l'imposait.

## Ce que ces tests gardent

1. **Aucune valeur par défaut.** Variable absente ⇒ erreur explicite.
2. **Un défaut de configuration rend 500, pas 403.** « Je ne sais pas
   authentifier » n'est pas « tu n'es pas autorisé » : confondre les deux
   ferait chercher le problème chez l'appelant alors qu'il est chez nous.
3. **L'application refuse de démarrer** sans le secret.
4. **Le hash ne revient pas en dur** dans `app.py`.
"""
from __future__ import annotations

import hashlib
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from backend.tests.jeton_de_test import JETON_PUBLIC_DE_TEST
from config import settings

_APP_PY = pathlib.Path(__file__).resolve().parents[1] / "app.py"
_ANCIEN_HASH = "e980b1ed0b45ca6873caa3f2d6ddcf27f4d8a1d0aa87cf9072f6e3e0909b31ec"


# --- aucune valeur par defaut --------------------------------------------

def test_sans_la_variable_la_lecture_LEVE(monkeypatch):
    """⛔ LE test qui compte. La recommandation de l'audit, mot pour mot :
    « retirer toute valeur par défaut (échec explicite si la variable
    d'environnement est absente) »."""
    monkeypatch.delenv("SHADOW_PUBLIC_TOKEN_HASH", raising=False)
    with pytest.raises(RuntimeError, match="SHADOW_PUBLIC_TOKEN_HASH"):
        settings.exiger_jeton_public()


@pytest.mark.parametrize("vide", ["", "   ", "\t"])
def test_une_variable_VIDE_vaut_absente(monkeypatch, vide):
    """Une variable posée mais vide est une configuration manquante, pas un
    jeton vide — sinon `compare_digest` comparerait à la chaîne vide."""
    monkeypatch.setenv("SHADOW_PUBLIC_TOKEN_HASH", vide)
    with pytest.raises(RuntimeError):
        settings.exiger_jeton_public()


def test_le_message_dit_QUOI_FAIRE(monkeypatch):
    """Une erreur de configuration doit dire comment la réparer."""
    monkeypatch.delenv("SHADOW_PUBLIC_TOKEN_HASH", raising=False)
    with pytest.raises(RuntimeError) as e:
        settings.exiger_jeton_public()
    msg = str(e.value)
    assert ".env" in msg and "sha256" in msg.lower()


def test_la_valeur_posee_est_rendue_telle_quelle(monkeypatch):
    monkeypatch.setenv("SHADOW_PUBLIC_TOKEN_HASH", "  abc123  ")
    assert settings.exiger_jeton_public() == "abc123"


def test_jeton_public_configure_ne_leve_PAS(monkeypatch):
    """C'est une QUESTION, pas une exigence : une sonde doit pouvoir
    demander sans risquer de tomber."""
    monkeypatch.delenv("SHADOW_PUBLIC_TOKEN_HASH", raising=False)
    assert settings.jeton_public_configure() is False
    monkeypatch.setenv("SHADOW_PUBLIC_TOKEN_HASH", "x" * 64)
    assert settings.jeton_public_configure() is True


# --- le point d'entree : 500 et non 403 ----------------------------------

def test_une_config_MANQUANTE_rend_500_et_pas_403(monkeypatch):
    """🔑 La distinction qui compte pour qui diagnostique : 403 accuse
    l'appelant, 500 nous accuse. Rendre 403 ici enverrait chercher un
    mauvais jeton côté client alors que le serveur est mal configuré."""
    from backend.app import app
    monkeypatch.delenv("SHADOW_PUBLIC_TOKEN_HASH", raising=False)
    c = TestClient(app)
    r = c.get("/api/shadow/v2_core_long/public-summary?token=peu-importe")
    assert r.status_code == 500
    assert "misconfigured" in r.json()["detail"]


def test_un_jeton_ABSENT_rend_toujours_403(monkeypatch):
    """Le comportement d'origine est préservé : les scripts en dépendent."""
    from backend.app import app
    monkeypatch.setenv("SHADOW_PUBLIC_TOKEN_HASH",
                       hashlib.sha256(JETON_PUBLIC_DE_TEST.encode()).hexdigest())
    r = TestClient(app).get("/api/shadow/v2_core_long/public-summary")
    assert r.status_code == 403
    assert "token required" in r.json()["detail"]


def test_un_jeton_FAUX_rend_toujours_403(monkeypatch):
    from backend.app import app
    monkeypatch.setenv("SHADOW_PUBLIC_TOKEN_HASH",
                       hashlib.sha256(JETON_PUBLIC_DE_TEST.encode()).hexdigest())
    r = TestClient(app).get("/api/shadow/v2_core_long/public-summary?token=faux")
    assert r.status_code == 403
    assert "invalid token" in r.json()["detail"]


# --- l'APPLICATION refuse de demarrer ------------------------------------

def test_l_application_REFUSE_DE_DEMARRER_sans_le_secret(monkeypatch):
    """⛔ « Refuser de démarrer » vise le SERVEUR. Entrer dans le contexte du
    TestClient déclenche `lifespan`, donc le contrôle."""
    from backend.app import app
    monkeypatch.delenv("SHADOW_PUBLIC_TOKEN_HASH", raising=False)
    with pytest.raises(RuntimeError, match="SHADOW_PUBLIC_TOKEN_HASH"):
        with TestClient(app):
            pass


def test_mais_IMPORTER_la_configuration_ne_leve_jamais(monkeypatch):
    """🔑 Le choix de conception. `config.settings` est importé par les
    6 300 tests, les bancs et les scripts : lever à l'import exigerait un
    secret de production pour lancer un test qui ne touche à aucun point
    d'entrée. Le contrôle est donc au DÉMARRAGE, pas à l'import."""
    monkeypatch.delenv("SHADOW_PUBLIC_TOKEN_HASH", raising=False)
    import importlib
    importlib.reload(settings)          # ne doit pas lever
    assert settings.jeton_public_configure() is False


# --- garde de DERIVE : le hash ne revient pas en dur ---------------------

def test_aucun_hash_en_dur_dans_app_py():
    """⛔ Le garde-fou contre le retour du défaut. Si ce test échoue,
    quelqu'un a recopié le hash au lieu d'appeler le helper."""
    src = _APP_PY.read_text(encoding="utf-8")
    assert _ANCIEN_HASH not in src, "l'ancien hash est revenu en dur"
    # Un hash SHA-256 litteral de 64 hex, assigne a cette variable
    assert not re.search(r"SHADOW_PUBLIC_TOKEN_HASH\s*=\s*[\"'][0-9a-f]{64}", src)


def test_un_seul_controle_de_jeton_dans_app_py():
    """La centralisation doit TENIR : neuf appels au helper, zéro
    `compare_digest` recopié sur un hash local."""
    src = _APP_PY.read_text(encoding="utf-8")
    appels = src.count("_verifier_jeton_public(token)")
    assert appels >= 9, "attendu au moins 9 sites, trouve %d" % appels
    # une seule definition
    assert src.count("def _verifier_jeton_public(") == 1
