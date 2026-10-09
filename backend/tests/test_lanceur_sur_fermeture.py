"""Le lanceur sur fermeture — demandé par Xavier le 2026-10-08.

> « Je trouve que le fait d'attendre 3 minutes est un peu long. Peut-on
> redévelopper le lanceur ? […] qu'il soit à l'écoute des threads fermés. »

Ce que ces tests protègent, dans l'ordre d'importance :

1. **L'inertie par défaut.** Un lanceur qui s'allume au déploiement changerait
   la cadence de l'argent réel sans que personne l'ait demandé.
2. **Les trois sites de fermeture.** `mt5_sync` ferme un trade à TROIS
   endroits ; en oublier un rendrait le lanceur muet pour une partie des
   fermetures — le défaut le plus dur à voir, parce qu'il marche la plupart
   du temps.
3. **Le verrou.** Deux cycles concurrents, c'est deux fois les bougies en
   mémoire sur une instance où le radar seul prend 1,83 Gio sur 3,75.
4. **Les trois gardes du cycle restreint** : pas de `_latest_overview`, pas de
   `_last_cycle_at`, pas de battement. La troisième est une garde de
   sécurité : `bridge_monitor` lit `radar_cycle_heartbeat` pour détecter un
   radar mort.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from backend.services import lanceur_sur_fermeture as L

_RACINE = Path(__file__).resolve().parents[2]
_SRC_LANCEUR = _RACINE / "backend" / "services" / "lanceur_sur_fermeture.py"
_SRC_SYNC = _RACINE / "backend" / "services" / "mt5_sync.py"
_SRC_SCHED = _RACINE / "backend" / "services" / "scheduler.py"


@pytest.fixture(autouse=True)
def _table_rase():
    L._DERNIER_LANCEMENT.clear()
    yield
    L._DERNIER_LANCEMENT.clear()


# ─── 1. ⛔ INERTE PAR DÉFAUT ───────────────────────────────────────────────

def test_INERTE_quand_rien_n_est_regle(monkeypatch):
    """🔑 LE test qui compte : sans réglage, le lanceur ne part pas."""
    monkeypatch.delenv("LANCEUR_SUR_FERMETURE", raising=False)
    assert L.arme() is False
    assert L.motif_de_refus("XAU/USD") == "lanceur_desarme"


def test_le_defaut_du_SOURCE_est_bien_desarme():
    """⛔ Épingle le défaut dans le FICHIER, pas dans le harnais : un `"1"`
    arrivé là par inadvertance armerait la production au prochain
    déploiement, sans que personne l'ait demandé."""
    ligne = next(l for l in _SRC_LANCEUR.read_text(encoding="utf-8").splitlines()
                 if "LANCEUR_SUR_FERMETURE" in l and "getenv" in l)
    assert '"0"' in ligne, "le defaut n'est plus inerte : %r" % ligne


@pytest.mark.parametrize("valeur", ["1", "true", "on", "YES", "True"])
def test_s_arme_sur_les_formes_usuelles(monkeypatch, valeur):
    monkeypatch.setenv("LANCEUR_SUR_FERMETURE", valeur)
    assert L.arme() is True


@pytest.mark.parametrize("valeur", ["0", "false", "off", "", "nope"])
def test_reste_desarme_sur_tout_le_reste(monkeypatch, valeur):
    monkeypatch.setenv("LANCEUR_SUR_FERMETURE", valeur)
    assert L.arme() is False


# ─── 2. La portée : l'or, et ce qui est déclaré ───────────────────────────

def test_par_defaut_il_n_ecoute_QUE_l_or(monkeypatch):
    monkeypatch.delenv("LANCEUR_PAIRES", raising=False)
    assert L.paires_ecoutees() == {"XAU/USD"}


def test_une_autre_paire_est_refusee(monkeypatch):
    monkeypatch.setenv("LANCEUR_SUR_FERMETURE", "1")
    monkeypatch.delenv("LANCEUR_PAIRES", raising=False)
    assert L.motif_de_refus("EUR/USD") == "paire_non_ecoutee"
    assert L.motif_de_refus("XAU/USD") is None


def test_une_paire_absente_ne_fait_pas_tomber(monkeypatch):
    monkeypatch.setenv("LANCEUR_SUR_FERMETURE", "1")
    for vide in (None, "", "   "):
        assert L.motif_de_refus(vide) == "paire_inconnue"


# ─── 3. Le délai de garde ─────────────────────────────────────────────────

def test_deux_fermetures_dans_la_meme_passe_ne_lancent_QU_UNE_fois(monkeypatch):
    """⚠️ Une passe de synchro peut réconcilier plusieurs clôtures d'un coup."""
    monkeypatch.setenv("LANCEUR_SUR_FERMETURE", "1")
    monkeypatch.setenv("LANCEUR_COOLDOWN_SEC", "60")
    assert L.motif_de_refus("XAU/USD") is None
    L._DERNIER_LANCEMENT["XAU/USD"] = __import__("time").monotonic()
    motif = L.motif_de_refus("XAU/USD")
    assert motif and motif.startswith("cooldown_"), motif


def test_un_cooldown_ILLISIBLE_ne_vaut_pas_zero(monkeypatch):
    """⛔ Un réglage cassé ne doit pas ouvrir la porte à une rafale."""
    monkeypatch.setenv("LANCEUR_COOLDOWN_SEC", "soixante")
    assert L._cooldown_sec() == 60.0


def test_le_cooldown_est_PAR_PAIRE(monkeypatch):
    monkeypatch.setenv("LANCEUR_SUR_FERMETURE", "1")
    monkeypatch.setenv("LANCEUR_PAIRES", "XAU/USD,XAG/USD")
    L._DERNIER_LANCEMENT["XAU/USD"] = __import__("time").monotonic()
    assert L.motif_de_refus("XAU/USD").startswith("cooldown_")
    assert L.motif_de_refus("XAG/USD") is None


# ─── 4. Ce qu'il fait VRAIMENT quand il part ──────────────────────────────

def test_il_appelle_le_cycle_de_PRODUCTION_avec_l_univers_restreint(monkeypatch):
    """🔑 Il ne contient aucune analyse : il rappelle le chemin éprouvé.
    Écrire ici une analyse allégée aurait créé une doublure qui dérive."""
    monkeypatch.setenv("LANCEUR_SUR_FERMETURE", "1")
    vus = []

    async def _faux_cycle(univers_force=None):
        vus.append(univers_force)

    import backend.services.scheduler as sched
    monkeypatch.setattr(sched, "run_analysis_cycle", _faux_cycle)

    r = asyncio.run(L.relancer_apres_fermeture("XAU/USD", ticket=42))
    assert r == "relance"
    assert vus == [["XAU/USD"]]


def test_le_temps_est_pose_AVANT_le_lancement(monkeypatch):
    """🔑 Sinon un cycle de 20 s laisserait passer une 2e relance pendant
    qu'il tourne."""
    monkeypatch.setenv("LANCEUR_SUR_FERMETURE", "1")
    pendant = {}

    async def _faux_cycle(univers_force=None):
        pendant["motif"] = L.motif_de_refus("XAU/USD")

    import backend.services.scheduler as sched
    monkeypatch.setattr(sched, "run_analysis_cycle", _faux_cycle)
    asyncio.run(L.relancer_apres_fermeture("XAU/USD"))
    assert pendant["motif"].startswith("cooldown_"), pendant


def test_un_cycle_qui_TOMBE_ne_propage_pas(monkeypatch):
    """⚠️ Appelé depuis la réconciliation : une relance ratée ne doit pas
    empêcher la clôture d'être enregistrée."""
    monkeypatch.setenv("LANCEUR_SUR_FERMETURE", "1")

    async def _cycle_casse(univers_force=None):
        raise RuntimeError("pont muet")

    import backend.services.scheduler as sched
    monkeypatch.setattr(sched, "run_analysis_cycle", _cycle_casse)
    assert asyncio.run(L.relancer_apres_fermeture("XAU/USD")) == "echec_RuntimeError"


def test_desarme_il_n_appelle_RIEN(monkeypatch):
    monkeypatch.delenv("LANCEUR_SUR_FERMETURE", raising=False)
    appels = []

    async def _faux_cycle(univers_force=None):
        appels.append(univers_force)

    import backend.services.scheduler as sched
    monkeypatch.setattr(sched, "run_analysis_cycle", _faux_cycle)
    assert asyncio.run(L.relancer_apres_fermeture("XAU/USD")) == "lanceur_desarme"
    assert appels == []


# ─── 5. ⛔ LES TROIS SITES DE FERMETURE ───────────────────────────────────

def test_TOUS_les_sites_de_fermeture_passent_par_L_ENTONNOIR():
    """⛔ Le test le plus important de ce fichier. `mt5_sync` ferme une
    position à trois endroits ; si un quatrième apparaît sans prévenir le
    lanceur, le lanceur sera muet pour ces clôtures-là — et il marchera quand
    même la plupart du temps, ce qui le rend indétectable à l'usage.

    🔑 **CE QUE CE TEST VÉRIFIE A CHANGÉ LE 2026-10-09, et il est devenu plus
    strict.** Avant, il comptait les COPIES de deux lignes (`_notify…` puis
    `_relancer…`) et vérifiait qu'elles allaient par paires. Trois copies de
    deux lignes, c'est trois occasions d'en oublier une.

    Depuis l'adoption des positions ouvertes dans le terminal MT5, la décision
    de prévenir le lanceur n'est plus la même pour tout le monde : une
    fermeture faite à la main par Xavier ne doit RIEN relancer. Il fallait donc
    un endroit, et un seul, où cette décision se prend — `_apres_cloture`.

    L'invariant est maintenant à deux volets, et le second est celui qui
    manquait :
      1. chaque site de fermeture appelle l'entonnoir ;
      2. **personne n'appelle le lanceur en dehors de l'entonnoir** — c'est ce
         qui empêche un futur site de court-circuiter la décision.
    """
    src = _SRC_SYNC.read_text(encoding="utf-8")

    sites = re.findall(r"^[ \t]+await _apres_cloture\(int\(ticket\), ",
                       src, re.M)
    assert len(sites) >= 3, (
        "%d site(s) de fermeture trouve(s) au lieu de 3 au moins : soit un "
        "site a disparu, soit il ne passe plus par l'entonnoir" % len(sites))

    # Volet 2 : hors du corps de `_apres_cloture`, aucun appel direct.
    debut = src.index("async def _apres_cloture(")
    fin = src.index("async def _reconcile_open_trades(")
    hors_entonnoir = src[:debut] + src[fin:]
    for interdit in ("_notify_close_telegram(", "_relancer_apres_fermeture("):
        appels = re.findall(r"await " + re.escape(interdit), hors_entonnoir)
        assert appels == [], (
            "%s est appele HORS de `_apres_cloture` : ce site-la echappe a la "
            "decision, et relancerait sur une fermeture a la main" % interdit)


def test_l_entonnoir_NE_RELANCE_PAS_une_ligne_adoptee():
    """⛔ Le dégât qu'on évite : `_relancer_apres_fermeture` n'a aucun garde sur
    `is_auto`. Sans ce filtre, fermer une position à la main dans le terminal
    aurait relancé un ordre d'ARGENT RÉEL de l'expérience TP 2 €."""
    import asyncio

    from backend.services import mt5_sync

    appels = []

    async def _espion(ticket):
        appels.append(ticket)

    vrai_notif = mt5_sync._notify_close_telegram
    vrai_relance = mt5_sync._relancer_apres_fermeture
    mt5_sync._notify_close_telegram = _espion
    mt5_sync._relancer_apres_fermeture = _espion
    try:
        asyncio.run(mt5_sync._apres_cloture(123, True))
        assert appels == [], "une ligne adoptee a declenche un effet de bord"
        asyncio.run(mt5_sync._apres_cloture(456, False))
        assert appels == [456, 456], (
            "une cloture AUTOMATIQUE doit, elle, notifier ET relancer")
    finally:
        mt5_sync._notify_close_telegram = vrai_notif
        mt5_sync._relancer_apres_fermeture = vrai_relance


def test_la_paire_vient_de_la_BASE_et_non_de_la_charge_utile():
    """🔑 Le site de `/deals` ne porte AUCUNE paire : la deviner aurait rendu
    le lanceur muet sur ce site-là, en silence."""
    src = _SRC_SYNC.read_text(encoding="utf-8")
    bloc = src[src.index("async def _relancer_apres_fermeture("):]
    bloc = bloc[:bloc.index("def _select_open_auto_tickets")]
    assert "_fetch_closed_trade_for_notify(ticket)" in bloc
    assert 'trade.get("pair")' in bloc


# ─── 6. Le cycle restreint : ses trois gardes ────────────────────────────

def _corps_du_cycle() -> str:
    """⚠️ Ancré depuis la signature, et borné à la fonction suivante : un
    `if restreint:` existe à plusieurs endroits, et une ancre ambiguë avait
    déjà produit une tranche VIDE — donc un test qui passe sur rien."""
    src = _SRC_SCHED.read_text(encoding="utf-8")
    debut = src.index("async def run_analysis_cycle(")
    fin = src.index("async def cockpit_broadcast_cycle(")
    corps = src[debut:fin]
    assert len(corps) > 2000, "tranche suspecte (%d caracteres)" % len(corps)
    return corps


def test_le_cycle_accepte_un_univers_force():
    assert "async def run_analysis_cycle(univers_force: list[str] | None = None)" \
        in _SRC_SCHED.read_text(encoding="utf-8")


def test_l_univers_force_est_une_INTERSECTION_pas_une_substitution():
    """⛔ Une paire hors univers n'a ni destination ni portée : l'analyser
    produirait un setup que rien ne peut router."""
    corps = _corps_du_cycle()
    assert "p.upper() in demande" in corps
    assert "univers = [p for p in univers if p.upper() in demande]" in corps


def test_un_cycle_restreint_ne_publie_PAS_l_apercu():
    """⛔ `_latest_overview` alimente l'interface : le remplacer par la seule
    paire relancée ferait disparaître les dix-neuf autres de l'écran."""
    corps = _corps_du_cycle()
    i = corps.index("_latest_candles_by_pair = all_candles")
    assert "if restreint:" in corps[max(0, i - 900):i], (
        "aucune garde avant la publication de l'apercu")


def test_un_cycle_restreint_n_ecrit_AUCUN_battement():
    """🔑 LA garde de sécurité. `bridge_monitor` lit `radar_cycle_heartbeat`
    depuis le 2026-05-09 pour détecter un radar mort. Des battements écrits
    par des lancements de l'or feraient passer un cycle COMPLET bloqué pour
    vivant : l'alerte deviendrait muette."""
    corps = _corps_du_cycle()
    i = corps.index("record_cycle(")
    avant = corps[max(0, i - 900):i]
    assert "raise _PasDeBattement()" in avant, (
        "le battement n'est pas garde pour un cycle restreint")
    assert "except _PasDeBattement:" in corps


def test_un_cycle_restreint_ne_rajeunit_PAS_l_horloge():
    corps = _corps_du_cycle()
    i = corps.index("_last_cycle_at = cycle_started_at")
    assert "if not restreint:" in corps[max(0, i - 400):i]


# ─── 7. Le verrou ─────────────────────────────────────────────────────────

def test_le_verrou_EMPECHE_vraiment_deux_cycles(monkeypatch):
    """🔑 Éprouvé par le COMPORTEMENT, pas par lecture : deux appels
    concurrents, un seul doit entrer."""
    import backend.services.scheduler as sched

    entrees = []

    async def _corps_lent(univers_force=None):
        entrees.append(univers_force)
        await asyncio.sleep(0.05)

    monkeypatch.setattr(sched, "_run_analysis_cycle_verrouille", _corps_lent)

    async def _les_deux():
        await asyncio.gather(
            sched.run_analysis_cycle(univers_force=["XAU/USD"]),
            sched.run_analysis_cycle(univers_force=["XAU/USD"]),
        )

    asyncio.run(_les_deux())
    assert len(entrees) == 1, (
        "deux cycles sont entres en meme temps : %r" % (entrees,))


def test_le_lanceur_n_ATTEND_pas_derriere_un_cycle(monkeypatch):
    """⚠️ Attendre serait pire que ne rien faire : le lanceur arriverait
    après le tour d'horloge qu'il voulait devancer, et relancerait sur des
    bougies déjà analysées."""
    import backend.services.scheduler as sched
    corps = _corps_du_cycle()
    i = corps.index("if _verrou_cycle.locked():")
    bloc = corps[i:i + 400]
    assert "return" in bloc, "le cycle attend au lieu de renoncer"
    assert "await _verrou_cycle.acquire()" not in bloc
