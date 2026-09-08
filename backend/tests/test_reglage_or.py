"""Le réajustement automatique de l'or : ce qu'il a le droit de décider seul.

## ⛔ Ce qui est vraiment testé ici

Un automate qui modifie les règles de déclenchement est dangereux par nature.
Les tests ne vérifient donc pas qu'il sait fermer — ça, c'est facile — mais
**qu'il refuse d'agir** dans les quatre cas où il ne doit pas :

1. sur une seule nuit,
2. sur un verdict qui oscille,
3. sur un motif qu'il n'a pas lui-même fermé,
4. quand il ne resterait plus assez de motifs sur l'horizon.

Et qu'il **dit** ce qu'il fait — un mécanisme silencieux qui éteint des choses,
c'est l'incident du kill-switch oublié.
"""
from __future__ import annotations

import io
import sqlite3

import pytest

from backend.services import laboratoire_or as labo
from backend.services import reglage_or as rg


@pytest.fixture(autouse=True)
def _base_neuve(tmp_path, monkeypatch):
    chemin = str(tmp_path / "essai.db")
    _JOUR[0] = 0
    monkeypatch.setattr(rg, "_db", lambda: chemin)
    rg._cache.clear()
    monkeypatch.setattr(rg, "_CACHE_S", 0.0)      # jamais de cache en test
    yield
    rg._cache.clear()


def _cellule(motif, verdict, horizon="5min", sens="buy", n=90, t=-3.5,
             r=-0.40, delta=-0.33):
    return {"horizon": horizon, "motif": motif, "sens": sens, "n": n,
            "r_moyen": r, "t": t, "delta_hasard": delta, "plafond": 2.55,
            "verdict": verdict}


def _mesure(cellules):
    return {"pair": rg.PAIRE, "cellules": cellules, "k": len(cellules),
            "plafond": 2.55}


_JOUR = [0]     # avance d'un test à l'autre grâce au fixture `_base_neuve`


def _nuits(cellules_par_nuit, meme_soir=False):
    """Enregistre plusieurs nuits — un JOUR chacune, sauf `meme_soir`.

    ⚠️ Le compteur avance entre les appels : sans cela, deux séries écrites
    dans le même test retomberaient sur les mêmes dates, et chaque cellule
    porterait DEUX verdicts pour la même nuit. C'est ce qu'a révélé le test de
    réouverture, et c'est ce qui a fait trouver le vrai défaut en dessous.
    """
    from datetime import datetime, timedelta, timezone
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    derniere = None
    import backend.services.reglage_or as m
    for cellules in cellules_par_nuit:
        ecart = (timedelta(minutes=_JOUR[0]) if meme_soir
                 else timedelta(days=_JOUR[0]))
        quand = (base + ecart).strftime("%Y-%m-%d %H:%M:%S")
        _JOUR[0] += 1
        vrai = m._maintenant
        m._maintenant = lambda q=quand: q
        try:
            derniere = _mesure(cellules)
            rg.enregistrer(derniere)
        finally:
            m._maintenant = vrai
    return derniere


# ── Fermer ───────────────────────────────────────────────────────────

def _huit_motifs(sauf=None, verdict_du_fautif=labo.REFUTE):
    """Un horizon garni, pour que le plancher ne s'en mêle pas."""
    noms = ["momentum_up", "engulfing_bullish", "breakout_up", "range_bounce_up",
            "range_bounce_down", "momentum_down", "engulfing_bearish",
            "breakout_down"]
    out = [_cellule(n, labo.INSUFFISANT, t=0.5, r=0.01, delta=0.0) for n in noms]
    if sauf:
        out.append(_cellule(sauf, verdict_du_fautif))
    return out


def test_TROIS_nuits_de_refus_ferment_le_motif():
    derniere = _nuits([_huit_motifs("poc_return_up")] * rg.NUITS_CONSECUTIVES)
    actions = rg.decider(derniere)
    fermees = [a for a in actions if a["action"] == rg.FERMER]
    assert [a["motif"] for a in fermees] == ["poc_return_up"]
    assert ("5min", "poc_return_up") in rg.fermetures(frais=True)


def test_UNE_seule_nuit_ne_ferme_RIEN():
    """⛔ Le premier garde-fou. Un t qui passe le seuil une fois n'est pas une
    découverte, c'est une soirée."""
    derniere = _nuits([_huit_motifs("poc_return_up")])
    assert rg.decider(derniere) == []
    assert rg.fermetures(frais=True) == set()


def test_un_verdict_qui_OSCILLE_ne_ferme_rien():
    """⚠️ Sinon la porte battrait tous les soirs, et le système tradrait une
    règle différente chaque nuit."""
    derniere = _nuits([
        _huit_motifs("poc_return_up", labo.REFUTE),
        _huit_motifs("poc_return_up", labo.INSUFFISANT),
        _huit_motifs("poc_return_up", labo.REFUTE),
    ])
    assert [a for a in rg.decider(derniere) if a["action"] == rg.FERMER] == []


def test_la_preuve_est_ECRITE_dans_la_decision():
    """⛔ « Fermé » sans le chiffre qui l'a décidé est indéfendable trois
    semaines plus tard."""
    derniere = _nuits([_huit_motifs("poc_return_up")] * rg.NUITS_CONSECUTIVES)
    a = [x for x in rg.decider(derniere) if x["action"] == rg.FERMER][0]
    assert "-0.40 R" in a["detail"]
    assert "90 trades" in a["detail"]
    assert "2.55" in a["detail"]
    assert "3 nuits" in a["detail"]


# ── Rouvrir ──────────────────────────────────────────────────────────

def test_il_rouvre_ce_qu_il_a_FERME():
    _nuits([_huit_motifs("poc_return_up")] * rg.NUITS_CONSECUTIVES)
    rg.decider(_mesure(_huit_motifs("poc_return_up")))
    assert ("5min", "poc_return_up") in rg.fermetures(frais=True)

    bon = _cellule("poc_return_up", labo.RETENU, t=3.6, r=0.35, delta=0.30)
    derniere = _nuits([_huit_motifs() + [bon]] * rg.NUITS_CONSECUTIVES)
    actions = rg.decider(derniere)
    assert [a["motif"] for a in actions if a["action"] == rg.ROUVRIR] == \
        ["poc_return_up"]
    assert rg.fermetures(frais=True) == set()


def test_il_n_OUVRE_JAMAIS_ce_qu_il_n_a_pas_ferme():
    """🔑 LA règle. « Ne jamais desserrer les portes » : un automate qui peut
    s'accorder des permissions n'a plus de garde-fou."""
    bon = _cellule("un_motif_jamais_ouvert", labo.RETENU, t=9.0, r=1.2, delta=1.1)
    derniere = _nuits([_huit_motifs() + [bon]] * rg.NUITS_CONSECUTIVES)
    actions = rg.decider(derniere)
    assert [a for a in actions if a["action"] == rg.ROUVRIR] == []


def test_le_module_ne_sait_PAS_ouvrir_du_tout():
    """⛔ Vérifié sur le code : aucune action « ouvrir » n'existe. La règle est
    structurelle, pas une branche qu'on pourrait oublier de tester."""
    src = io.open("backend/services/reglage_or.py", encoding="utf-8").read()
    assert '"ouvrir"' not in src and "'ouvrir'" not in src
    assert src.count("INSERT OR REPLACE INTO labo_or_fermetures") == 1


# ── Le plancher ──────────────────────────────────────────────────────

def test_il_REFUSE_de_vider_un_horizon():
    """⛔ Un mécanisme qui éteint tout en silence, c'est le kill-switch oublié
    du 2026-07-13. Ici il s'arrête AVANT, et il le dit."""
    trois = [_cellule(n, labo.REFUTE) for n in ("a", "b", "c")]
    derniere = _nuits([trois] * rg.NUITS_CONSECUTIVES)
    actions = rg.decider(derniere)
    assert [a["action"] for a in actions] == [rg.REFUSE_PLANCHER] * 3
    assert rg.fermetures(frais=True) == set()


def test_le_refus_est_DIT_dans_le_message():
    trois = [_cellule(n, labo.REFUTE) for n in ("a", "b", "c")]
    derniere = _nuits([trois] * rg.NUITS_CONSECUTIVES)
    texte = " ".join(rg.lignes(rg.decider(derniere)))
    assert "Fermeture refusée" in texte
    assert "trop peu de motifs" in texte


# ── L'interrupteur ───────────────────────────────────────────────────

def test_DESARME_il_propose_mais_n_applique_RIEN(monkeypatch):
    monkeypatch.setattr(rg, "ARME", False)
    derniere = _nuits([_huit_motifs("poc_return_up")] * rg.NUITS_CONSECUTIVES)
    actions = rg.decider(derniere)
    assert [a["motif"] for a in actions if a["action"] == rg.FERMER] == \
        ["poc_return_up"]
    assert rg.fermetures(frais=True) == set()       # rien n'a bougé
    assert "DÉSARMÉ" in " ".join(rg.lignes(actions))


def test_l_interrupteur_est_REGLABLE_sans_redeploiement():
    src = io.open("backend/services/reglage_or.py", encoding="utf-8").read()
    assert 'os.getenv("REGLAGE_OR_ARME"' in src


# ── La lecture par la production ─────────────────────────────────────

def test_une_base_ILLISIBLE_ne_ferme_rien(monkeypatch):
    """⛔ fail-OUVERT assumé. L'inverse fermerait des motifs sur une erreur
    d'entrée-sortie — une panne d'infra deviendrait une décision de trading."""
    monkeypatch.setattr(rg, "_db", lambda: "/chemin/qui/n/existe/pas/x.db")
    rg._cache.clear()
    assert rg.fermetures(frais=True) == set()


def test_la_cascade_de_motifs_SOUSTRAIT_les_fermetures_EN_DERNIER():
    """⛔ L'ordre décide de tout. Placée avant la couche additive, la
    soustraction serait annulée par elle."""
    src = io.open("backend/services/mt5_bridge.py", encoding="utf-8").read()
    i_extras = src.index('extras = getattr(dest, "extra_patterns"')
    i_labo = src.index("from backend.services.reglage_or import fermetures")
    assert i_extras < i_labo
    # et rien ne rajoute de motifs après
    apres = src[i_labo:src.index("return base", i_labo)]
    assert "|=" not in apres


def test_un_motif_FERME_disparait_vraiment_des_motifs_autorises(monkeypatch):
    """🔑 Le test qui compte : la décision de la nuit doit changer ce que la
    production autorise, sans redéploiement."""
    from backend.services import mt5_bridge as mb

    class _E:
        def __init__(self, v): self.value = v

    class _S:
        pair = "XAU/USD"
        horizon = "5min"
        pattern = _E("poc_return_up")

    class _D:
        destination_id = "admin_legacy"
        allowed_patterns = None
        extra_patterns = ["poc_return_up", "poc_return_down"]

    avant = mb._patterns_autorises(_S(), _D())
    assert "poc_return_up" in avant

    _nuits([_huit_motifs("poc_return_up")] * rg.NUITS_CONSECUTIVES)
    rg.decider(_mesure(_huit_motifs("poc_return_up")))
    rg._cache.clear()

    apres = mb._patterns_autorises(_S(), _D())
    assert "poc_return_up" not in apres
    assert "poc_return_down" in apres        # ⚠️ l'autre jambe reste ouverte


def test_les_dates_ecrites_n_ont_PAS_le_T_de_l_ISO():
    """⛔ Le piège de fenêtre SQLite, croisé six fois dans ce dépôt : `T`
    (0x54) > espace (0x20), donc un `>= datetime('now')` ne filtre plus rien."""
    assert "T" not in rg._maintenant()
    _nuits([_huit_motifs("poc_return_up")])
    with sqlite3.connect(rg._db()) as c:
        for (quand,) in c.execute("SELECT mesure_le FROM labo_or_cellules"):
            assert "T" not in quand, quand


def test_TROIS_passages_le_MEME_soir_ne_font_pas_trois_nuits():
    """⛔ LE défaut trouvé en écrivant ces tests. Ma première version comptait
    les horodatages distincts : trois lancements du labo dans la même soirée
    valaient « trois nuits de suite », et une seule séance de mesure suffisait
    à fermer un motif. Tout le garde-fou sautait.

    ⚠️ Une nuit est un JOUR. Quand un jour porte plusieurs passages, on retient
    le dernier — le plus informé.
    """
    derniere = _nuits([_huit_motifs("poc_return_up")] * 5, meme_soir=True)
    assert [a for a in rg.decider(derniere) if a["action"] == rg.FERMER] == []
    assert rg.fermetures(frais=True) == set()


# ── Le cycle de la nuit ──────────────────────────────────────────────

def test_le_cycle_est_DANS_le_conteneur_pas_en_cron_hote():
    """⛔ `/opt/scalping/scripts` a deja diverge du depot : huit correctifs y
    sont restes morts une journee entiere. Un job APScheduler execute forcement
    le code deploye."""
    src = io.open("backend/services/scheduler.py", encoding="utf-8").read()
    assert 'id="laboratoire_or_nightly"' in src
    assert "from backend.services.reglage_or import cycle_nocturne" in src


def test_une_nuit_SANS_bougies_ne_decide_rien(monkeypatch):
    """⚠️ Une panne du pont ne doit pas se lire comme « aucun motif ne perd »,
    ni fermer quoi que ce soit."""
    monkeypatch.setattr(rg, "_bougies_et_spread",
                        lambda j: (_ for _ in ()).throw(RuntimeError("pont HS")))
    r = rg.cycle_nocturne()
    assert "erreur" in r
    assert rg.fermetures(frais=True) == set()


def test_TROP_PEU_de_bougies_saute_la_nuit(monkeypatch):
    """⛔ Mesurer 90 jours sur 3 jours de donnees rendrait des cellules
    minuscules — et le plafond du hasard ne protege pas d'un echantillon
    tronque, il protege du nombre d'essais."""
    monkeypatch.setattr(rg, "_bougies_et_spread", lambda j: ([{}] * 100, 0.2))
    assert "erreur" in rg.cycle_nocturne()


def test_RIEN_a_signaler_n_envoie_AUCUN_message(monkeypatch):
    """⛔ Le bruit quotidien est ce qui a noye l'alerte de sauvegarde S3 pendant
    cinq nuits. Un message par nuit « rien a dire » la renoierait."""
    envois = []
    monkeypatch.setattr(rg, "lignes", lambda *a, **k: ["x"])
    import httpx
    monkeypatch.setattr(httpx, "post", lambda *a, **k: envois.append(a))
    rg._notifier(_mesure([_cellule("m", labo.INSUFFISANT)]), [])
    assert envois == []


def test_une_FERMETURE_dit_qu_elle_vaut_pour_l_argent_REEL(monkeypatch):
    """🔑 La couche soustractive s'applique a TOUTES les destinations. Le
    message doit le dire : c'est une decision de trading, pas une note de
    laboratoire."""
    recu = {}

    class _R:
        @staticmethod
        def raise_for_status(): return None

    def _post(url, json=None, headers=None, timeout=None):
        recu.update(json or {})
        return _R()

    import httpx
    monkeypatch.setattr(httpx, "post", _post)
    monkeypatch.setenv("INFRA_TELEGRAM_TOKEN", "jeton")
    rg._notifier(_mesure([_cellule("poc_return_up", labo.REFUTE)]),
                 [{"action": rg.FERMER, "horizon": "5min",
                   "motif": "poc_return_up", "pair": rg.PAIRE, "detail": "x"}])
    assert "argent réel compris" in recu.get("body", "")
    assert "ne ferme aucune position ouverte" in recu.get("body", "").replace(
        "\n", " ")


def test_le_canal_utilise_EXISTE_vraiment():
    """⛔ Ma premiere version passait `"sales"` — un alias accepte a l'entree de
    l'endpoint mais ABSENT de la table des libelles. `libelle_avec_picto` levait
    `KeyError`, et le `except` large l'avalait : aucune notification, aucun
    bruit. Le nom vient desormais de `canal_pour`, la seule source."""
    from backend.services.canaux_telegram import canal_pour, libelle_avec_picto
    src = io.open("backend/services/reglage_or.py", encoding="utf-8").read()
    assert 'canal = canal_pour(' in src
    assert 'canal = "sales"' not in src
    libelle_avec_picto(canal_pour("admin_live"))     # ne doit pas lever
