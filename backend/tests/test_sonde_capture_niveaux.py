"""La sonde qui garde la capture des niveaux vivants.

Elle surveille un mécanisme dont la panne serait **silencieuse** : si le bridge
cesse de retenir les SL/TP réellement portés, les colonnes restent vides, les
clôtures continuent d'arriver, et l'analyse repart sur les niveaux d'origine —
faux dans 44 % des cas (mesuré le 2026-08-24). Rien ne crierait.

Ces tests portent donc surtout sur ce que la sonde REFUSE de conclure.

Cf. [[project_analyse_clotures_main_2026_08_24]] · [[feedback_detection_par_absence]]
"""
import importlib.util
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "scripts" / "notify_capture_niveaux.py"


def _charger(db, etat, **env):
    """Importe le script avec ses chemins détournés vers le bac à sable."""
    import os
    anciens = dict(os.environ)
    os.environ.update({"TRADES_DB": str(db), "ETAT_SONDE": str(etat), **env})
    spec = importlib.util.spec_from_file_location("sonde_niveaux", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    envois = []
    mod._notifier = lambda titre, corps, dedup: envois.append(
        {"titre": titre, "corps": corps, "dedup": dedup})
    os.environ.clear()
    os.environ.update(anciens)
    return mod, envois


@pytest.fixture
def bac(tmp_path):
    db = tmp_path / "trades.db"
    c = sqlite3.connect(db)
    c.execute("""CREATE TABLE personal_trades (
        id INTEGER PRIMARY KEY, pair TEXT, direction TEXT, status TEXT,
        mt5_ticket INTEGER, destination_id TEXT, close_reason TEXT,
        closed_at TEXT, stop_loss REAL, take_profit REAL,
        sl_at_close REAL, tp_at_close REAL, niveaux_source TEXT, pnl REAL)""")
    c.commit()
    c.close()
    return db, tmp_path / "etat.json"


def _trade(db, ticket, *, minutes, sl=4100.0, tp=4200.0,
           sl_vif=None, tp_vif=None, source=None, dest="admin_live"):
    quand = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO personal_trades (pair,direction,status,mt5_ticket,"
            "destination_id,close_reason,closed_at,stop_loss,take_profit,"
            "sl_at_close,tp_at_close,niveaux_source,pnl) "
            "VALUES ('XAU/USD','buy','CLOSED',?,?,'SL',?,?,?,?,?,?,-12.5)",
            (ticket, dest, quand, sl, tp, sl_vif, tp_vif, source))
    return quand


def _curseur(etat, minutes=600):
    etat.write_text(json.dumps({
        "curseur": (datetime.now(timezone.utc)
                    - timedelta(minutes=minutes)).isoformat()}))


def test_le_premier_passage_n_alerte_pas_sur_le_passe(bac):
    """Sans curseur, la sonde ne juge RIEN : les clôtures antérieures au
    déploiement n'ont légitimement aucun niveau, crier dessus noierait la
    vraie première vérification."""
    db, etat = bac
    _trade(db, 1, minutes=5000, source=None)
    mod, envois = _charger(db, etat)

    assert mod.main() == 0
    assert envois == []
    assert json.loads(etat.read_text())["curseur"], "le curseur doit être posé"


def test_une_cloture_trop_recente_n_est_PAS_jugee(bac):
    """Entre la clôture et l'écriture en base il y a `mt5_sync`. Juger tout de
    suite déclarerait « capture manquante » sur une ligne simplement pas encore
    synchronisée."""
    db, etat = bac
    _curseur(etat)
    _trade(db, 2, minutes=3, source=None)
    mod, envois = _charger(db, etat, GRACE_MIN="20")

    assert mod.main() == 0
    assert envois == [], "une ligne trop récente ne prouve rien"


def test_le_curseur_ne_depasse_pas_une_ligne_non_jugee(bac):
    """Sinon la clôture trop récente ne reviendrait jamais — une régression
    disparaîtrait par le simple fait d'être arrivée tard."""
    db, etat = bac
    _curseur(etat)
    avant = json.loads(etat.read_text())["curseur"]
    _trade(db, 3, minutes=2, source=None)
    mod, _ = _charger(db, etat, GRACE_MIN="20")

    mod.main()

    assert json.loads(etat.read_text())["curseur"] == avant


def test_la_premiere_cloture_jugee_declenche_la_verification(bac):
    db, etat = bac
    _curseur(etat)
    _trade(db, 4, minutes=60, sl=4100.0, sl_vif=4150.0, tp_vif=4200.0,
           source="monitor")
    mod, envois = _charger(db, etat, GRACE_MIN="20")

    assert mod.main() == 0
    assert len(envois) == 1
    assert "marche" in envois[0]["titre"]
    assert "4150.0" in envois[0]["corps"]
    assert "BOUG" in envois[0]["corps"], "l'écart doit être signalé"
    assert json.loads(etat.read_text())["verification_faite"] is True


def test_un_niveau_identique_a_l_origine_ne_se_fait_pas_passer_pour_une_preuve(bac):
    """La capture peut marcher sans rien démontrer : si le stop n'a pas bougé,
    la colonne recopie l'origine. Le dire, plutôt que laisser croire."""
    db, etat = bac
    _curseur(etat)
    _trade(db, 5, minutes=60, sl=4100.0, tp=4200.0,
           sl_vif=4100.0, tp_vif=4200.0, source="monitor")
    mod, envois = _charger(db, etat, GRACE_MIN="20")

    mod.main()

    assert "ne le démontre pas encore" in envois[0]["corps"]
    assert "BOUG" not in envois[0]["corps"]


def test_apres_verification_la_sonde_se_tait_si_tout_va_bien(bac):
    db, etat = bac
    etat.write_text(json.dumps({
        "curseur": (datetime.now(timezone.utc)
                    - timedelta(minutes=600)).isoformat(),
        "verification_faite": True}))
    _trade(db, 6, minutes=60, sl_vif=4150.0, tp_vif=4200.0, source="monitor")
    mod, envois = _charger(db, etat, GRACE_MIN="20")

    mod.main()

    assert envois == [], "une sonde de panne ne commente pas le succès"


def test_apres_verification_une_capture_manquante_ALERTE(bac):
    """Le cœur : c'est le chemin qui doit crier, et le seul qui compte."""
    db, etat = bac
    etat.write_text(json.dumps({
        "curseur": (datetime.now(timezone.utc)
                    - timedelta(minutes=600)).isoformat(),
        "verification_faite": True}))
    _trade(db, 7, minutes=60, source=None)
    mod, envois = _charger(db, etat, GRACE_MIN="20")

    mod.main()

    assert len(envois) == 1
    assert "sans niveaux retenus" in envois[0]["titre"]
    assert "définitivement perdu" in envois[0]["corps"]


def test_kraken_n_est_pas_surveille(bac):
    """Kraken n'a pas de monitor MT5 : l'inclure ferait crier la sonde sur des
    trades qu'elle ne surveille pas."""
    db, etat = bac
    etat.write_text(json.dumps({
        "curseur": (datetime.now(timezone.utc)
                    - timedelta(minutes=600)).isoformat(),
        "verification_faite": True}))
    _trade(db, 8, minutes=60, source=None, dest="admin_kraken")
    mod, envois = _charger(db, etat, GRACE_MIN="20")

    mod.main()

    assert envois == []


def test_une_base_illisible_n_est_pas_aucune_cloture(bac):
    db, etat = bac
    _curseur(etat)
    avant = json.loads(etat.read_text())["curseur"]
    with sqlite3.connect(db) as c:
        c.execute("DROP TABLE personal_trades")
    mod, envois = _charger(db, etat, GRACE_MIN="20")

    assert mod.main() == 1
    assert len(envois) == 1
    assert "illisible" in envois[0]["titre"]
    assert "on ne sait pas" in envois[0]["corps"]
    assert json.loads(etat.read_text())["curseur"] == avant
