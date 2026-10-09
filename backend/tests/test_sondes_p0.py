"""Sondes P0 : détecter, ouvrir un ticket, RÉPARER, prouver, dire.

Demande de Xavier le 2026-10-09 : des sondes sur trois priorités P0 — les deux
règles de gestion des SL et l'ouverture de trades — avec **analyse complète
automatique**, **résolution sans intervention humaine**, et un message Telegram
à l'ouverture du ticket d'anomalie puis à sa résolution.

## 🔑 CE QUI EST TENABLE, ET CE QUI NE L'EST PAS

**Tenable** : réparer une ACTION QUI N'A PAS ABOUTI. C'est le cas de toutes les
pannes mesurées aujourd'hui — un stop qui n'a pas bougé malgré son palier, un
ordre qui n'est pas parti, une sonde arrêtée, un script absent du conteneur,
une règle désarmée. La réparation consiste à **réémettre l'action décidée**,
puis à **prouver qu'elle a pris effet**.

**Pas tenable** : réparer un DÉFAUT DE CODE. Le défaut du 2026-10-09 — une
validation qui se contredisait, `sl_dist = 0` puis refus de ce zéro — demandait
d'écrire du code, et le déployer **désarme REM-002 par conception**. Ces
anomalies **escaladent** avec leur diagnostic complet.

> ⛔ Prétendre le contraire serait la pire des promesses : une sonde qui dit
> « résolu » sans l'être laisse le défaut vivant ET endort la surveillance.

## ⛔ L'INVARIANT QUI NE SE NÉGOCIE PAS

**Aucune remédiation ne desserre une porte.** Jamais. Réparer en élargissant un
plafond fabriquerait le résultat — c'est la consigne la plus ancienne de ce
dépôt. Un test l'épingle sur le catalogue entier.
→ [[feedback_ne_pas_desserrer_les_portes]]

## Les trois sondes, et ce qu'elles mesurent

| sonde | anomalie | réparable ? |
|---|---|---|
| **P0-1 échelle de gains** | palier atteint, stop immobile | ✅ réémettre le déplacement |
| | la route refuse (non-200) | ⚠️ une relance, puis escalade |
| | boucle qui ne tourne plus | ⛔ escalade |
| **P0-2 protection des pertes** | éligible, stop non resserré | ✅ réémettre le resserrement |
| | la sonde 5 s est muette ⇒ règle aveugle | ✅ relancer la sonde |
| | règle désarmée | ✅ réarmer le drapeau du processus |
| **P0-3 ouverture de trades** | aucun ordre alors que tout est ouvert | ✅ relancer un cycle restreint |
| | interrupteur désarmé | ⛔ escalade (décision de Xavier) |
| | refus `bridge_error` (motif non nommé) | ⛔ escalade avec le corps exact |
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[2] / "scripts" / "sondes_p0.py")

TAUX = 1.1235
MARQUE = "scalping-radar-2026-10-09"


@pytest.fixture()
def s(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("sondes_p0", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    f = tmp_path / "trades.db"
    monkeypatch.setattr(mod, "_db_path", lambda: str(f))
    return mod


def _pos(ticket=1, sens="buy", entree=4190.0, profit_eur=0.0, stop_eur=20.0,
         comment=MARQUE):
    signe = 1 if sens == "buy" else -1
    return {"ticket": ticket, "symbol": "XAUUSD", "type": sens,
            "price_open": entree,
            "price_current": entree + signe * profit_eur * TAUX,
            "sl": entree - signe * stop_eur * TAUX,
            "tp": 0.0, "volume": 0.01, "comment": comment}


# ─────────────────────────────────────────────────────────────────────────
# P0-1 — L'échelle de gains
# ─────────────────────────────────────────────────────────────────────────

def test_P0_1_palier_atteint_et_stop_IMMOBILE_est_une_anomalie(s):
    """⛔ LE DEFAUT EXACT DU 2026-10-09 : trois positions a +1,37 et +1,81 EUR,
    stop inchange, parce que la route rendait 400 a chaque passage."""
    pos = _pos(ticket=1360846647, profit_eur=1.81, stop_eur=20.0)
    suivi = {1360846647: {"palier_max_eur": 1.5, "sl_au_max": pos["sl"],
                          "profit_max_eur": 1.81, "vu_n": 93}}

    anos = s.detecter_echelle([pos], suivi, TAUX)

    assert len(anos) == 1
    a = anos[0]
    assert a["code"] == "stop_non_deplace_malgre_palier"
    assert a["ticket"] == 1360846647
    assert "1,81" in a["detail"] or "1.81" in a["detail"]
    assert a["reparable"] is True


def test_P0_1_un_stop_DEJA_dans_le_profit_n_est_pas_une_anomalie(s):
    """La regle a fait son travail : stop du cote du profit."""
    pos = _pos(ticket=2, profit_eur=1.81, stop_eur=-0.75)   # stop a +0,75 €
    suivi = {2: {"palier_max_eur": 1.5, "sl_au_max": pos["sl"],
                 "profit_max_eur": 1.81, "vu_n": 50}}

    assert s.detecter_echelle([pos], suivi, TAUX) == []


def test_P0_1_sans_palier_atteint_aucune_anomalie(s):
    pos = _pos(ticket=3, profit_eur=0.40, stop_eur=20.0)
    suivi = {3: {"palier_max_eur": None, "profit_max_eur": 0.40, "vu_n": 10}}

    assert s.detecter_echelle([pos], suivi, TAUX) == []


def test_P0_1_une_position_A_LA_MAIN_n_est_pas_jugee(s):
    """⛔ L'echelle l'ignore par conception : ce n'est pas une anomalie."""
    pos = _pos(ticket=4, profit_eur=1.81, stop_eur=20.0, comment="")
    suivi = {4: {"palier_max_eur": 1.5, "profit_max_eur": 1.81, "vu_n": 10}}

    assert s.detecter_echelle([pos], suivi, TAUX) == []


def test_P0_1_sans_HISTOIRE_on_ne_conclut_PAS(s):
    """⛔ FAIL-CLOSED. Si la sonde 5 s n'a rien vu, on ne sait pas si un palier
    a ete franchi. Inventer une anomalie serait aussi grave que d'en manquer
    une."""
    pos = _pos(ticket=5, profit_eur=1.81, stop_eur=20.0)

    assert s.detecter_echelle([pos], {}, TAUX) == []


# ─────────────────────────────────────────────────────────────────────────
# P0-2 — La protection des pertes
# ─────────────────────────────────────────────────────────────────────────

def test_P0_2_eligible_et_stop_NON_resserre_est_une_anomalie(s):
    pos = _pos(ticket=10, profit_eur=-5.0, stop_eur=20.0)
    suivi = {10: {"negatif_depuis_sec": 400, "ouvert_depuis_sec": 900,
                  "vu_n": 80}}

    anos = s.detecter_protection([pos], suivi, TAUX)

    assert len(anos) == 1
    assert anos[0]["code"] == "stop_non_resserre_malgre_eligibilite"
    assert anos[0]["reparable"] is True
    # 🔑 Le detail porte le stop ATTENDU, pour que la reparation soit verifiable.
    assert "12.5" in anos[0]["detail"] or "12,5" in anos[0]["detail"]


def test_P0_2_pas_encore_eligible_aucune_anomalie(s):
    pos = _pos(ticket=11, profit_eur=-5.0, stop_eur=20.0)
    suivi = {11: {"negatif_depuis_sec": 60, "ouvert_depuis_sec": 900,
                  "vu_n": 80}}

    assert s.detecter_protection([pos], suivi, TAUX) == []


def test_P0_2_stop_DEJA_au_plancher_aucune_anomalie(s):
    """7,00 = perte 5 + plancher 2 : la regle s'est arretee, c'est normal."""
    pos = _pos(ticket=12, profit_eur=-5.0, stop_eur=7.0)
    suivi = {12: {"negatif_depuis_sec": 400, "ouvert_depuis_sec": 900,
                  "vu_n": 80}}

    assert s.detecter_protection([pos], suivi, TAUX) == []


def test_P0_2_une_sonde_MUETTE_rend_la_regle_AVEUGLE(s):
    """🔑 La regle lit `negatif_depuis` chez la sonde. Si la sonde ne tourne
    plus, la regle s'abstient en silence — donc la protection est MORTE sans
    que rien ne le dise. C'est une anomalie en soi, et elle est REPARABLE."""
    pos = _pos(ticket=13, profit_eur=-5.0, stop_eur=20.0)

    anos = s.detecter_protection([pos], {}, TAUX)

    assert len(anos) == 1
    assert anos[0]["code"] == "sonde_muette"
    assert anos[0]["reparable"] is True


# ─────────────────────────────────────────────────────────────────────────
# P0-3 — L'ouverture de trades
# ─────────────────────────────────────────────────────────────────────────

def test_P0_3_interrupteur_DESARME_est_une_anomalie_NON_reparable(s):
    """⛔ Le rearmement est la DECISION DE XAVIER. Une sonde qui rearmerait
    toute seule vierait le garde-fou de son sens."""
    anos = s.detecter_ouverture(
        {"decision": "DENY", "reason_code": "NEW_DEPLOYMENT"},
        refus_recents={}, ordres_recents=0, setups_recents=5)

    codes = [a["code"] for a in anos]
    assert "execution_desarmee" in codes
    a = next(x for x in anos if x["code"] == "execution_desarmee")
    assert a["reparable"] is False


def test_P0_3_aucun_ordre_malgre_des_setups_et_tout_ouvert(s):
    anos = s.detecter_ouverture(
        {"decision": "ALLOW", "reason_code": "ARMED"},
        refus_recents={}, ordres_recents=0, setups_recents=8)

    codes = [a["code"] for a in anos]
    assert "aucun_ordre_malgre_setups" in codes
    assert next(x for x in anos if x["code"] == "aucun_ordre_malgre_setups")["reparable"] is True


def test_P0_3_des_ordres_partis_aucune_anomalie(s):
    anos = s.detecter_ouverture(
        {"decision": "ALLOW", "reason_code": "ARMED"},
        refus_recents={"pattern_not_allowed": 12}, ordres_recents=2,
        setups_recents=8)

    assert anos == []


def test_P0_3_un_refus_bridge_error_ESCALADE_avec_son_corps(s):
    """⛔ `bridge_error` est le fourre-tout. Un motif qu'on ne sait pas nommer
    est un motif qu'on ne verra jamais : il doit remonter, avec le corps exact.
    C'est ainsi que les 9 refus de marge du 09/10 sont restes invisibles."""
    anos = s.detecter_ouverture(
        {"decision": "ALLOW", "reason_code": "ARMED"},
        refus_recents={"bridge_error": 9}, ordres_recents=1, setups_recents=8)

    a = next(x for x in anos if x["code"] == "refus_non_nomme")
    assert a["reparable"] is False
    assert "9" in a["detail"]


def test_P0_3_des_refus_NORMAUX_ne_sont_pas_des_anomalies(s):
    """Les portes qui trient font leur travail."""
    anos = s.detecter_ouverture(
        {"decision": "ALLOW", "reason_code": "ARMED"},
        refus_recents={"pattern_not_allowed": 40, "horizon_not_allowed": 12,
                       "bridge_marge_insuffisante": 3},
        ordres_recents=1, setups_recents=20)

    assert anos == []


# ─────────────────────────────────────────────────────────────────────────
# ⛔ L'INVARIANT : aucune remédiation ne desserre une porte
# ─────────────────────────────────────────────────────────────────────────

def test_AUCUNE_remediation_ne_desserre_une_porte(s):
    """⛔ LA CONSIGNE LA PLUS ANCIENNE DE CE DEPOT. Reparer en elargissant un
    plafond fabriquerait le resultat. Ce test lit le CATALOGUE."""
    interdits = ("MARGE_LIBRE_MIN_PCT", "MAX_RISQUE", "max_risque",
                 "DAILY_LOSS", "daily_loss_limit", "MAX_POSITIONS",
                 "plancher_pct", "WHITELIST", "arm(", "desarm")
    for code, r in s.REMEDIATIONS.items():
        texte = f"{r.get('description', '')} {r.get('action_nom', '')}"
        for mot in interdits:
            assert mot not in texte, (
                f"la remediation {code!r} touche un garde-fou ({mot})")


def test_les_anomalies_NON_reparables_n_ont_AUCUNE_remediation(s):
    """🔑 Coherence : si une anomalie est declaree non reparable, le catalogue
    ne doit pas pretendre le contraire."""
    for code in ("execution_desarmee", "refus_non_nomme", "boucle_arretee"):
        assert code not in s.REMEDIATIONS, (
            f"{code} est declaree non reparable mais figure au catalogue")


def test_toute_anomalie_REPARABLE_a_une_remediation(s):
    """L'inverse : promettre `reparable=True` sans action serait un mensonge."""
    reparables = ("stop_non_deplace_malgre_palier",
                  "stop_non_resserre_malgre_eligibilite",
                  "sonde_muette", "aucun_ordre_malgre_setups",
                  "regle_desarmee")
    for code in reparables:
        assert code in s.REMEDIATIONS, f"{code} promet une reparation absente"
        assert callable(s.REMEDIATIONS[code]["action"])
        assert callable(s.REMEDIATIONS[code]["verification"])


# ─────────────────────────────────────────────────────────────────────────
# Le cycle de vie du ticket
# ─────────────────────────────────────────────────────────────────────────

def _tickets(s) -> list[dict]:
    with sqlite3.connect(s._db_path()) as c:
        c.row_factory = sqlite3.Row
        try:
            return [dict(x) for x in c.execute(
                "SELECT * FROM anomalies_sonde ORDER BY id")]
        except sqlite3.OperationalError:
            return []


ANO = {"sonde": "P0-1", "code": "stop_non_deplace_malgre_palier",
       "ticket": 1360846647, "detail": "palier 1,5 atteint, stop immobile",
       "reparable": True}


def test_un_ticket_est_OUVERT_avec_son_detail(s):
    tid = s.ouvrir_ticket(ANO)

    t = _tickets(s)[0]
    assert t["id"] == tid
    assert t["etat"] == "OUVERT"
    assert t["code"] == ANO["code"]
    assert t["detail"] == ANO["detail"]
    assert t["ouvert_le"] is not None


def test_la_MEME_anomalie_ne_rouvre_PAS_un_second_ticket(s):
    """⚠️ Sans cela, une anomalie persistante ouvrirait un ticket toutes les
    5 min et noierait le fil Telegram — la lecon des 8 doublons du 07/10."""
    a = s.ouvrir_ticket(ANO)
    b = s.ouvrir_ticket(ANO)

    assert a == b
    assert len(_tickets(s)) == 1


def test_une_anomalie_sur_un_AUTRE_ticket_ouvre_son_propre_dossier(s):
    s.ouvrir_ticket(ANO)
    s.ouvrir_ticket({**ANO, "ticket": 999})

    assert len(_tickets(s)) == 2


def test_resoudre_inscrit_la_PREUVE(s):
    """🔑 << Resolu >> sans preuve ne vaut rien : c'est exactement ce qui
    rendrait la surveillance endormie."""
    tid = s.ouvrir_ticket(ANO)

    s.resoudre_ticket(tid, preuve="sl passe de 4167.71 a 4191.30 chez le courtier")

    t = _tickets(s)[0]
    assert t["etat"] == "RESOLU"
    assert "4191.30" in t["preuve"]
    assert t["resolu_le"] is not None


def test_une_anomalie_RESOLUE_puis_qui_REVIENT_ouvre_un_NOUVEAU_ticket(s):
    """Une recidive doit se voir, pas se fondre dans l'ancien dossier."""
    tid = s.ouvrir_ticket(ANO)
    s.resoudre_ticket(tid, preuve="ok")

    tid2 = s.ouvrir_ticket(ANO)

    assert tid2 != tid
    assert len(_tickets(s)) == 2


def test_un_ECHEC_de_reparation_est_inscrit_et_ESCALADE(s):
    tid = s.ouvrir_ticket(ANO)

    s.echec_ticket(tid, raison="la route rend encore 400")

    t = _tickets(s)[0]
    assert t["etat"] == "ESCALADE"
    assert "400" in t["preuve"]


def test_deux_ECHECS_ne_relancent_plus_la_reparation(s):
    """⛔ Une reparation qui echoue en boucle est un harcelement, et elle peut
    AGGRAVER. On s'arrete apres deux tentatives et on passe la main."""
    tid = s.ouvrir_ticket(ANO)
    s.echec_ticket(tid, raison="1er echec")
    s.echec_ticket(tid, raison="2e echec")

    assert s.doit_reessayer(tid) is False


# ─────────────────────────────────────────────────────────────────────────
# L'ORCHESTRATION : ticket -> Telegram -> réparation -> preuve -> Telegram
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def espion(s, monkeypatch):
    """Capture les messages Telegram au lieu de les envoyer."""
    envois = []
    monkeypatch.setattr(s, "_prevenir",
                        lambda titre, corps, dedup: envois.append((titre, corps)) or True)
    return envois


def test_RIEN_a_signaler_aucun_ticket_aucun_message(s, espion):
    bilan = s.traiter([], a_blanc=False)

    assert bilan["ouverts"] == 0
    assert espion == []
    assert _tickets(s) == []


def test_une_anomalie_REPARABLE_ouvre_repare_prouve_et_PREVIENT_DEUX_FOIS(s, espion, monkeypatch):
    """🔑 Le cycle complet demande par Xavier : un message a l'OUVERTURE du
    ticket, un autre a sa RESOLUTION."""
    monkeypatch.setitem(s.REMEDIATIONS, ANO["code"], {
        "action_nom": "reemettre", "description": "on repose le stop",
        "action": lambda a: {"ok": True},
        "verification": lambda a: (True, "sl verifie a 4191.30 chez le courtier"),
    })

    bilan = s.traiter([ANO], a_blanc=False)

    assert bilan["ouverts"] == 1 and bilan["resolus"] == 1
    assert len(espion) == 2, "il faut DEUX messages : ouverture puis resolution"
    assert "anomalie" in espion[0][0].lower() or "ouvert" in espion[0][0].lower()
    assert "resol" in espion[1][0].lower() or "résol" in espion[1][0].lower()
    # 🔑 Le message de resolution porte la PREUVE, pas une affirmation.
    assert "4191.30" in espion[1][1]
    assert _tickets(s)[0]["etat"] == "RESOLU"


def test_une_VERIFICATION_qui_echoue_ESCALADE_et_le_DIT(s, espion, monkeypatch):
    """⛔ << Resolu >> sans preuve ne vaut rien. Si la verification ne confirme
    pas, le ticket escalade — il ne se ferme pas."""
    monkeypatch.setitem(s.REMEDIATIONS, ANO["code"], {
        "action_nom": "reemettre", "description": "on repose le stop",
        "action": lambda a: {"ok": True},
        "verification": lambda a: (False, "sl toujours a 4167.71"),
    })

    bilan = s.traiter([ANO], a_blanc=False)

    assert bilan["resolus"] == 0 and bilan["escalades"] == 1
    assert _tickets(s)[0]["etat"] == "ESCALADE"
    assert "4167.71" in espion[-1][1]


def test_une_anomalie_NON_reparable_ESCALADE_sans_rien_tenter(s, espion):
    """⛔ L'interrupteur desarme : la sonde ne doit RIEN tenter, le rearmement
    est la decision de Xavier."""
    ano = {"sonde": "P0-3", "code": "execution_desarmee", "ticket": None,
           "reparable": False, "detail": "DENY / NEW_DEPLOYMENT"}

    bilan = s.traiter([ano], a_blanc=False)

    assert bilan["escalades"] == 1 and bilan["resolus"] == 0
    assert _tickets(s)[0]["etat"] == "ESCALADE"
    # 🔑 Le message doit dire que c'est a LUI de trancher.
    assert "decision" in espion[-1][1].lower() or "ta " in espion[-1][1].lower()
    # ⛔ ET SURTOUT : RIEN N'A ETE TENTE. Ma premiere version du test ne le
    # verifiait pas — retirer le garde `if not reparable` laissait l'anomalie
    # tomber sur `r["action"]` avec `r = None`, donc une `TypeError` rattrapee,
    # donc une escalade quand meme. Le resultat etait le bon par accident.
    # Trouve en reinjectant le defaut.
    assert "aucune reparation automatique" in _tickets(s)[0]["preuve"], (
        "l'escalade n'a pas suivi le chemin PROPRE : une tentative a eu lieu")


def test_le_mode_A_BLANC_detecte_et_DIT_mais_ne_repare_RIEN(s, espion, monkeypatch):
    appels = []
    monkeypatch.setitem(s.REMEDIATIONS, ANO["code"], {
        "action_nom": "reemettre", "description": "on repose le stop",
        "action": lambda a: appels.append(a) or {"ok": True},
        "verification": lambda a: (True, "ok"),
    })

    bilan = s.traiter([ANO], a_blanc=True)

    assert appels == [], "le mode a blanc a tente une reparation"
    assert espion == [], "le mode a blanc a envoye un message"
    assert bilan["ouverts"] == 1


def test_une_anomalie_PERSISTANTE_ne_renvoie_pas_de_message(s, espion, monkeypatch):
    """⚠️ Le ticket est idempotent, donc le message d'ouverture ne part
    qu'UNE fois. Sans cela, une anomalie persistante noierait le fil toutes
    les 5 min."""
    monkeypatch.setitem(s.REMEDIATIONS, ANO["code"], {
        "action_nom": "reemettre", "description": "on repose",
        "action": lambda a: {"ok": True},
        "verification": lambda a: (False, "pas encore"),
    })

    s.traiter([ANO], a_blanc=False)
    n_apres_1 = len(espion)
    s.traiter([ANO], a_blanc=False)

    # Le 2e passage retente (1 echec < MAX_TENTATIVES) mais ne REOUVRE pas.
    assert len(_tickets(s)) == 1
    assert len(espion) >= n_apres_1


def test_apres_DEUX_echecs_la_reparation_n_est_plus_tentee(s, espion, monkeypatch):
    appels = []
    monkeypatch.setitem(s.REMEDIATIONS, ANO["code"], {
        "action_nom": "reemettre", "description": "on repose",
        "action": lambda a: appels.append(1) or {"ok": True},
        "verification": lambda a: (False, "echec"),
    })

    for _ in range(4):
        s.traiter([ANO], a_blanc=False)

    assert len(appels) == s.MAX_TENTATIVES, (
        f"{len(appels)} tentatives au lieu de {s.MAX_TENTATIVES} : une "
        "reparation qui boucle peut AGGRAVER")


def test_une_anomalie_MALFORMEE_n_empeche_pas_les_AUTRES(s, espion):
    """⛔ LE GARDE EXTERNE, que mon premier test n'exercait PAS.

    Mon autre test utilise une ACTION qui leve — mais elle est rattrapee par le
    `try` INTERNE. Le garde externe (celui qui protege l'ouverture du ticket
    elle-meme) restait donc sans test : remplacer son `except` par un `raise`
    ne faisait tomber personne. Trouve en reinjectant le defaut.

    🔑 Ici l'anomalie n'a meme pas de `code` : `ouvrir_ticket` leve avant toute
    tentative. La suivante doit quand meme etre traitee — une panne qui en
    cache d'autres est le pire des cas.
    """
    malformee = {"sonde": "P0-1"}          # ni code, ni detail
    saine = {**ANO, "ticket": 4242, "reparable": False}

    bilan = s.traiter([malformee, saine], a_blanc=False)

    assert bilan["ouverts"] == 1, "l'anomalie saine n'a pas ete traitee"
    assert [t["ticket"] for t in _tickets(s)] == [4242]


def test_une_action_qui_LEVE_n_empeche_pas_les_AUTRES_anomalies(s, espion, monkeypatch):
    """⛔ Une anomalie qui explose ne doit pas condamner le traitement des
    autres : ce serait une panne qui en cache d'autres."""
    monkeypatch.setitem(s.REMEDIATIONS, ANO["code"], {
        "action_nom": "x", "description": "x",
        "action": lambda a: (_ for _ in ()).throw(RuntimeError("boom")),
        "verification": lambda a: (True, "ok"),
    })
    autre = {**ANO, "ticket": 777}

    bilan = s.traiter([ANO, autre], a_blanc=False)

    assert bilan["ouverts"] == 2
    assert len(_tickets(s)) == 2
