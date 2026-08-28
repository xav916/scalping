"""`/health` du bridge MT5 doit publier ses garde-fous (2026-08-20).

`MAX_DAILY_LOSS_PCT` valait **10.0** sur les deux bridges MT5 alors que le
défaut du code est 3.0 — un plafond de perte journalière 3,3× trop large,
resté en place des semaines. Le vérifier a exigé une session RDP sur le VPS,
parce que rien ne l'exposait : `/limits` ne rend que `max_lot` et
`max_open_positions`. Le bridge Kraken, lui, publie déjà le sien.

> **Un garde-fou qu'on ne peut pas lire est un garde-fou dont on ne sait
> jamais s'il s'applique.**

Ce qui est verrouillé ici : la présence des valeurs, et la non-régression des
champs historiques que le moniteur et le radar consomment.

`bridge.py` importe MetaTrader5, absent hors du VPS Windows : on extrait la
fonction du source et on l'exécute seule, comme le fait déjà
`test_bridge_drawdown_exclusions`.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"

_REGLAGES = {
    "PAPER_MODE": False,
    "MT5_SERVER": "ICMarketsEU-MT5-5",
    "MT5_LOGIN": 13137475,
    "MAX_LOT": 0.02,
    "MAX_LOT_PER_CLASS": {"forex": 0.02},
    "MAX_DAILY_LOSS_PCT": 3.0,
    "MAX_OPEN_POSITIONS": 3,
    # Fenetre de dedup, publiee depuis le 2026-08-28.
    "DEDUP_WINDOW_SEC": 3600,
    "MAX_RISQUE_ENGAGE_PCT": 5.0,
    # Poche de l'or ET de l'argent, ouverte le 2026-08-28.
    "MAX_RISQUE_ENGAGE_OR_ARGENT_PCT": 15.0,
    "MARGE_LIBRE_MIN_PCT": 30.0,
    # Le garde-fou des positions NUES, publie le 2026-08-28.
    "SLTP_GUARD_ENABLED": True,
    "SLTP_GUARD_ACTIVATED_AT": "2026-08-28T21:00:00+00:00",
    "SLTP_GUARD_FROZEN_TICKETS": frozenset({1353960866}),
    "DEVIATION_POINTS": 20,
    "TRAIL_DISTANCE_POINTS": 0,
    "PARTIAL_CLOSE_PCT": 50.0,
    "EQUILIBRE_AUTO_ENABLED": True,
    "EQUILIBRE_MARGE_R": 1.0,
    # Porte de bruit en ecarts-types journaliers, ajoutee le 2026-08-24 : le
    # seuil en R vaut 1,07 σ sur EUR/GBP et 0,24 σ sur USD/JPY, donc aucune
    # valeur en R ne peut etre bonne partout.
    "EQUILIBRE_MARGE_SIGMA": 1.0,
    "TRADING_HOURS_UTC": "",
    "DAILY_LOSS_EXCLUDED_TICKETS": frozenset(),
    # Empreinte de la source, publiee depuis le 2026-08-25. Constantes de
    # module comme les precedentes : le harnais n execute que `health()`,
    # il doit donc les lui fournir.
    "SOURCE_SHA": "abc123def456",
    "DEMARRE_A": "2026-08-25T18:51:24+00:00",
}


def _appeler_health(**surcharges):
    """Exécute la seule fonction `health()`, extraite du source.

    Le corps est relu à l'exécution : un renommage de constante ou la
    suppression d'un champ fait échouer le test. Ce n'est pas une copie figée.
    """
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("def health():")
    fin = src.index('@app.route("/account"')
    module = types.ModuleType("bridge_health")
    module.__dict__.update(_REGLAGES)
    module.__dict__.update(surcharges)
    module.__dict__["jsonify"] = lambda d: d
    module.__dict__["ensure_mt5_connected"] = lambda: True
    module.__dict__["mt5"] = types.SimpleNamespace(__version__="5.0.5735")
    exec(compile(src[debut:fin], str(_SRC), "exec"), module.__dict__)
    return module.health()


# ── Le bloc attendu ────────────────────────────────────────────────────────

def test_les_garde_fous_sont_publies():
    g = _appeler_health()["garde_fous"]
    assert g["max_daily_loss_pct"] == 3.0
    assert g["max_open_positions"] == 3
    assert g["dedup_window_sec"] == 3600
    assert g["deviation_points"] == 20
    assert g["trail_distance_points"] == 0
    assert g["partial_close_pct"] == 50.0


def test_la_remontee_a_l_equilibre_se_LIT_a_distance():
    """Posée le 2026-08-23 : elle MODIFIE des positions ouvertes.

    Savoir si elle est armée, et sous quel coussin de profit, ne doit pas
    demander une session RDP — c'est tout l'objet de ce fichier.
    """
    g = _appeler_health()["garde_fous"]
    assert g["equilibre_auto_enabled"] is True
    assert g["equilibre_marge_r"] == 1.0


def test_la_remontee_DESARMEE_se_voit_aussi():
    g = _appeler_health(EQUILIBRE_AUTO_ENABLED=False,
                        EQUILIBRE_MARGE_R=2.5)["garde_fous"]
    assert g["equilibre_auto_enabled"] is False
    assert g["equilibre_marge_r"] == 2.5


def test_la_porte_de_BRUIT_est_lisible_a_distance():
    """La porte en écarts-types (2026-08-24).

    ⛔ Sans elle dans `/health`, on ne pourrait pas savoir à distance si le
    seuil qui protège réellement du bruit est armé — et c'est LUI qui décide,
    pas le seuil en R : le même 0,40 R vaut 1,07 σ sur EUR/GBP et 0,24 σ sur
    USD/JPY. Lire `equilibre_marge_r` seul donnerait une fausse assurance.
    """
    g = _appeler_health()["garde_fous"]
    assert g["equilibre_marge_sigma"] == 1.0


def test_la_porte_de_bruit_DESARMEE_se_voit():
    """`0` = désarmée : seul le seuil en R agit, avec l'écart de 4,5× entre
    instruments qu'il laisse passer. Ça doit se voir."""
    g = _appeler_health(EQUILIBRE_MARGE_SIGMA=0.0)["garde_fous"]
    assert g["equilibre_marge_sigma"] == 0.0


def test_les_DEUX_poches_de_risque_se_lisent_a_distance():
    """5 % pour le reste + 15 % pour les metaux (2026-08-28, le soir).

    ⛔ Publier la seule poche des 6 % ferait lire « plafond a 6 % » sur un
    compte qui en autorise 20 au total. Un garde-fou desserre qu'on ne peut
    pas lire est exactement ce que ce fichier existe pour empecher.
    """
    g = _appeler_health()["garde_fous"]
    assert g["max_risque_engage_pct"] == 5.0
    assert g["max_risque_engage_or_argent_pct"] == 15.0


def test_la_poche_des_metaux_DESARMEE_se_voit():
    """`0` = les metaux retombent dans les 6 % communs. Ca doit se voir."""
    g = _appeler_health(MAX_RISQUE_ENGAGE_OR_ARGENT_PCT=0.0)["garde_fous"]
    assert g["max_risque_engage_or_argent_pct"] == 0.0


def test_un_plafond_desserre_se_VOIT():
    """LE cas d'usage : lire 10.0 a distance au lieu d'ouvrir une session RDP."""
    g = _appeler_health(MAX_DAILY_LOSS_PCT=10.0)["garde_fous"]
    assert g["max_daily_loss_pct"] == 10.0


def test_le_suiveur_rearme_se_VOIT():
    """Le suiveur détruisait 0,329 R/trade sur l'or. Il doit rester à 0."""
    g = _appeler_health(TRAIL_DISTANCE_POINTS=150)["garde_fous"]
    assert g["trail_distance_points"] == 150


def test_un_ticket_exclu_residuel_se_VOIT():
    g = _appeler_health(
        DAILY_LOSS_EXCLUDED_TICKETS=frozenset({1353960866}))["garde_fous"]
    assert g["daily_loss_excluded_tickets"] == [1353960866]


def test_heures_vides_rendues_None_et_non_chaine_vide():
    """`""` et `None` se lisent pareil dans un tableau de bord ; `None` est
    explicite sur « aucune restriction »."""
    assert _appeler_health()["garde_fous"]["trading_hours_utc"] is None
    g = _appeler_health(TRADING_HOURS_UTC="07:00-20:00")["garde_fous"]
    assert g["trading_hours_utc"] == "07:00-20:00"


# ── Non-regression : le moniteur et le radar consomment ces champs ─────────

@pytest.mark.parametrize("champ", [
    "ok", "paper_mode", "server", "login",
    "mt5_version", "max_lot", "max_lot_per_class",
])
def test_les_champs_historiques_survivent(champ):
    """Jamais retirés ni renommés — le moniteur lit `ok`, le radar le reste."""
    assert champ in _appeler_health()


def test_health_reste_lisible_sans_authentification():
    """Aucun secret dans la charge utile : `/health` est public par dessein."""
    charge = repr(_appeler_health()).lower()
    for interdit in ("password", "api_key", "token", "secret"):
        assert interdit not in charge


# ── L'empreinte de la source (2026-08-25) ──────────────────────────────────

def test_l_empreinte_de_la_source_est_publiee():
    """Sans elle, on ne peut pas savoir si le bridge execute le code versionne.

    C'est ce trou qui a laisse disparaitre, sans un bruit, le repli de
    resolution de symbole du bridge Kraken — 13 ordres refuses entre le 20 et
    le 24/08 sur des instruments pourtant cotes.
    """
    reponse = _appeler_health()
    assert reponse["source_sha"] == "abc123def456"
    assert reponse["demarre_a"] == "2026-08-25T18:51:24+00:00"


def test_l_empreinte_est_calculee_a_l_IMPORT_pas_a_la_requete():
    """⛔ Le piege que ce test garde fermé.

    Hacher le fichier au moment de la requete annoncerait la NOUVELLE version
    tout en faisant tourner l'ANCIENNE — pire que pas d'empreinte du tout,
    puisqu'on croirait alors le deploiement effectif. `health()` doit se
    contenter de LIRE une constante, jamais d'ouvrir le fichier.
    """
    src = _SRC.read_text(encoding="utf-8")
    corps = src[src.index("def health():"):src.index('@app.route("/account"')]
    assert "SOURCE_SHA" in corps, "le champ a disparu de /health"
    for interdit in ("open(__file__", "_empreinte_source(", "hashlib."):
        assert interdit not in corps, (
            f"`{interdit}` dans health() : l'empreinte serait celle du FICHIER, "
            "pas celle du code charge"
        )


def test_le_garde_fou_des_positions_NUES_se_lit_a_distance():
    """⛔ Il etait armable mais illisible : un redemarrage qui perdait sa
    variable le desarmait EN SILENCE. Une position nue bloque en plus TOUTE
    nouvelle ouverture (son risque n'est pas bornable) — donc le garde-fou
    desarme se manifeste par un compte qui ne trade plus, sans qu'on sache
    pourquoi."""
    g = _appeler_health()["garde_fous"]
    assert g["sltp_guard_enabled"] is True
    assert g["sltp_guard_activated_at"] == "2026-08-28T21:00:00+00:00"
    assert g["sltp_guard_frozen_tickets"] == [1353960866]


def test_un_horodatage_d_activation_VIDE_se_voit():
    """⚠️ `enabled=true` avec un horodatage vide = fail-closed : AUCUNE
    position n'est eligible. Les deux champs se lisent ensemble, jamais l'un
    sans l'autre — sinon on croit le mecanisme arme alors qu'il ne fait rien."""
    g = _appeler_health(SLTP_GUARD_ACTIVATED_AT="")["garde_fous"]
    assert g["sltp_guard_enabled"] is True
    assert g["sltp_guard_activated_at"] is None


def test_le_garde_fou_DESARME_se_voit_aussi():
    g = _appeler_health(SLTP_GUARD_ENABLED=False)["garde_fous"]
    assert g["sltp_guard_enabled"] is False
