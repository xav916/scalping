"""La BOUCLE LÉGÈRE — deux boucles, comme Xavier l'a demandé.

> Xavier, 2026-10-11 : « Sépare en deux boucles. »

## Ce que ces tests garantissent

1. **Inerte par défaut** — `BOUCLE_LEGERE_SEC` absent ⇒ rien ne démarre.
2. La bougie **en cours** est bâtie des ticks, et son étiquette vient de la
   **dernière fermée**, jamais de l'horloge murale (le décalage serveur du pont
   dérive de 93 min en une heure).
3. Les **fermées** sont relues à cadence fixe, **pas** à chaque passage.
4. Un motif **déjà annoncé** ne réveille pas deux fois ; un **nouveau** seau
   remet les compteurs à zéro.
5. La chaîne lourde n'est **jamais** lancée deux fois en moins du repos.
6. **Aucune exception ne sort** de la boucle.

## ⛔ CE QU'ILS NE PROUVENT PAS

Que ça gagne de l'argent. Sept zéros indépendants du 2026-10-11 disent que la
direction n'existe à aucune échelle ni à aucun instant, **dont un banc dédié à
cette question** (décider au tick contre décider à la clôture : **0/4**). Cette
boucle retire une latence et un gaspillage ; elle ne rend pas les motifs
prédictifs.
"""
from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from backend.models.schemas import Candle
from backend.services import boucle_legere as BL


def _c(label, o, h, l, c):
    return Candle(timestamp=label, open=o, high=h, low=l, close=c, volume=0.0)


def _serie(n, depart=dt.datetime(2026, 10, 9, 12, 0, tzinfo=dt.timezone.utc)):
    return [_c(depart + dt.timedelta(minutes=5 * i), 4150.0 + i, 4151.0 + i,
               4149.0 + i, 4150.5 + i) for i in range(n)]


@pytest.fixture(autouse=True)
def _propre(monkeypatch):
    for v in ("BOUCLE_LEGERE_SEC", "BOUCLE_LEGERE_PAIRS",
              "BOUCLE_LEGERE_RATES_SEC"):
        monkeypatch.delenv(v, raising=False)
    yield


# ─── ① Inerte par défaut ─────────────────────────────────────────────────

def test_inerte_par_defaut():
    assert BL.config() == (0.0, [])


@pytest.mark.parametrize("brut", ["", "   ", "0", "-1", "deux-cents-ms", "abc"])
def test_une_valeur_illisible_ou_nulle_desarme(monkeypatch, brut):
    monkeypatch.setenv("BOUCLE_LEGERE_SEC", brut)
    secondes, _ = BL.config()
    assert secondes == 0.0


def test_le_plancher_de_50_ms(monkeypatch):
    """⚠️ Le tick de l'or arrive ~3 fois par seconde (mesuré sur 3 298 970
    ticks) : sous 50 ms on inonde le pont sans gagner de fraîcheur."""
    monkeypatch.setenv("BOUCLE_LEGERE_SEC", "0.001")
    monkeypatch.setenv("BOUCLE_LEGERE_PAIRS", "XAU/USD")
    assert BL.config() == (0.05, ["XAU/USD"])


def test_les_paires_suivent_la_liste_blanche_du_reel(monkeypatch):
    monkeypatch.setenv("BOUCLE_LEGERE_SEC", "0.2")
    monkeypatch.setenv("MT5_BRIDGE_LIVE_WHITELIST_PAIRS", "XAU/USD")
    assert BL.config() == (0.2, ["XAU/USD"])


def test_une_liste_explicite_prime(monkeypatch):
    monkeypatch.setenv("BOUCLE_LEGERE_SEC", "0.2")
    monkeypatch.setenv("MT5_BRIDGE_LIVE_WHITELIST_PAIRS", "XAU/USD,EUR/USD")
    monkeypatch.setenv("BOUCLE_LEGERE_PAIRS", "xau/usd")
    assert BL.config() == (0.2, ["XAU/USD"])


# ─── ② L'étiquette vient de la dernière fermée ───────────────────────────

def test_le_seau_suit_la_derniere_fermee():
    derniere = dt.datetime(2026, 10, 9, 12, 25, tzinfo=dt.timezone.utc)
    assert BL.seau_en_cours(derniere, "5min") == dt.datetime(
        2026, 10, 9, 12, 30, tzinfo=dt.timezone.utc)
    assert BL.seau_en_cours(derniere, "1min") == dt.datetime(
        2026, 10, 9, 12, 26, tzinfo=dt.timezone.utc)


def test_une_echelle_inconnue_ne_fabrique_aucun_seau():
    """⛔ On ne DEVINE pas une durée de seau."""
    assert BL.seau_en_cours(dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc),
                            "3min") is None


def test_la_bougie_en_cours_est_batie_des_ticks():
    etiq = dt.datetime(2026, 10, 9, 12, 30, tzinfo=dt.timezone.utc)
    b = BL.bougie_en_cours(etiq, [4150.0, 4153.0, 4148.0, 4151.0])
    assert (b.open, b.high, b.low, b.close) == (4150.0, 4153.0, 4148.0, 4151.0)
    assert b.timestamp == etiq


def test_aucun_tick_ne_fabrique_aucune_bougie():
    """⛔ Fabriquer un doji depuis la dernière clôture ferait voir à
    `detect_patterns` une bougie qui n'a jamais eu lieu."""
    etiq = dt.datetime(2026, 10, 9, 12, 30, tzinfo=dt.timezone.utc)
    assert BL.bougie_en_cours(etiq, []) is None


# ─── ③ Les fermées sont relues à CADENCE, pas à chaque passage ───────────

class _Faux:
    """Un pont factice qui compte ses appels."""

    def __init__(self, fermees, prix=4150.0):
        self.fermees = fermees
        self.prix = prix
        self.n_rates = 0
        self.n_tick = 0

    async def fetch_candles(self, pair, interval, outputsize):
        self.n_rates += 1
        return list(self.fermees)

    def prix_courant(self, pair):
        self.n_tick += 1
        return self.prix


def _brancher(monkeypatch, faux, detections=()):
    from backend.services import bougies_du_pont as BP
    monkeypatch.setattr(BP, "fetch_candles", faux.fetch_candles)
    monkeypatch.setattr(BP, "prix_courant", faux.prix_courant)
    import backend.services.pattern_detector as PD
    monkeypatch.setattr(PD, "detect_patterns",
                        lambda serie, pair: list(detections))


@pytest.mark.asyncio
async def test_les_fermees_ne_sont_relues_qu_a_la_cadence(monkeypatch):
    """🔑 LE DÉFAUT DE MON PREMIER JET, et il était muet : je ne relisais que
    si `fermees` était VIDE — donc jamais. Le seau n'avançait plus et la bougie
    en cours grossissait indéfiniment."""
    faux = _Faux(_serie(50))
    _brancher(monkeypatch, faux)
    monkeypatch.setenv("BOUCLE_LEGERE_RATES_SEC", "5")
    etat = BL.EtatPaire()
    # 25 passages espacés de 200 ms = 5,0 s de temps simulé
    for k in range(26):
        await BL.un_passage("XAU/USD", etat, "5min", 50, maintenant=0.2 * k)
    assert faux.n_tick == 26, "le tick, lui, est lu à CHAQUE passage"
    assert faux.n_rates == 2, f"/rates attendu 2 fois, vu {faux.n_rates}"


@pytest.mark.asyncio
async def test_une_relecture_vide_ne_jette_pas_l_historique(monkeypatch):
    """⚠️ Un hoquet du pont ne doit pas aveugler la boucle."""
    faux = _Faux(_serie(50))
    _brancher(monkeypatch, faux)
    etat = BL.EtatPaire()
    await BL.un_passage("XAU/USD", etat, "5min", 50, maintenant=0.0)
    assert len(etat.fermees) == 50
    faux.fermees = []
    await BL.un_passage("XAU/USD", etat, "5min", 50, maintenant=100.0)
    assert len(etat.fermees) == 50, "l'historique a été jeté sur un vide"


@pytest.mark.asyncio
async def test_sans_aucune_bougie_on_ne_detecte_rien(monkeypatch):
    faux = _Faux([])
    _brancher(monkeypatch, faux)
    etat = BL.EtatPaire()
    assert await BL.un_passage("XAU/USD", etat, "5min", 50, 0.0) == set()


@pytest.mark.asyncio
async def test_un_tick_illisible_n_invente_pas_de_prix(monkeypatch):
    """⛔ Rejouer le dernier prix connu ferait passer un pont muet pour un
    marché calme, et ce mensonge-là ne remonte nulle part."""
    faux = _Faux(_serie(50))
    faux.prix = None
    _brancher(monkeypatch, faux)
    etat = BL.EtatPaire()
    assert await BL.un_passage("XAU/USD", etat, "5min", 50, 0.0) == set()
    assert etat.prix == []


# ─── ④ Un motif déjà annoncé ne réveille pas deux fois ───────────────────

class _Motif:
    def __init__(self, nom, sens):
        self.pattern_type = nom
        self.direction = sens


def test_le_meme_motif_n_est_nouveau_qu_une_fois():
    d = [_Motif("pin_bar_down", "sell")]
    assert BL.motifs_nouveaux(d, set()) == {"pin_bar_down:sell"}
    assert BL.motifs_nouveaux(d, {"pin_bar_down:sell"}) == set()


def test_le_sens_fait_partie_de_la_cle():
    """🔑 `pin_bar_down` et `pin_bar_up` sur le même seau sont DEUX
    événements."""
    d = [_Motif("pin_bar", "buy"), _Motif("pin_bar", "sell")]
    assert BL.motifs_nouveaux(d, set()) == {"pin_bar:buy", "pin_bar:sell"}
    assert BL.motifs_nouveaux(d, {"pin_bar:buy"}) == {"pin_bar:sell"}


def test_un_nouveau_seau_oublie_les_prix_ET_les_motifs():
    """⛔ Oublier les prix sans oublier les motifs rendrait la boucle MUETTE
    pour le reste de la session sur toute figure déjà vue une fois."""
    etat = BL.EtatPaire()
    etat.prix = [4150.0, 4151.0]
    etat.vus = {"pin_bar_down:sell"}
    etat.nouveau_seau(dt.datetime(2026, 10, 9, 12, 35, tzinfo=dt.timezone.utc))
    assert etat.prix == []
    assert etat.vus == set()


@pytest.mark.asyncio
async def test_le_meme_motif_sur_deux_passages_ne_sort_qu_une_fois(monkeypatch):
    faux = _Faux(_serie(50))
    _brancher(monkeypatch, faux, detections=[_Motif("pin_bar_down", "sell")])
    etat = BL.EtatPaire()
    a = await BL.un_passage("XAU/USD", etat, "5min", 50, 0.0)
    b = await BL.un_passage("XAU/USD", etat, "5min", 50, 0.2)
    assert a == {"pin_bar_down:sell"}
    assert b == set()


@pytest.mark.asyncio
async def test_la_serie_passee_au_detecteur_porte_la_bougie_EN_COURS(monkeypatch):
    """La 50ᵉ bougie doit être celle qu'on vient de bâtir des ticks, pas une
    51ᵉ fermée."""
    faux = _Faux(_serie(50), prix=4199.0)
    vues = {}
    from backend.services import bougies_du_pont as BP
    monkeypatch.setattr(BP, "fetch_candles", faux.fetch_candles)
    monkeypatch.setattr(BP, "prix_courant", faux.prix_courant)
    import backend.services.pattern_detector as PD
    monkeypatch.setattr(PD, "detect_patterns",
                        lambda serie, pair: vues.update(serie=serie) or [])
    etat = BL.EtatPaire()
    await BL.un_passage("XAU/USD", etat, "5min", 50, 0.0)
    serie = vues["serie"]
    assert len(serie) == 50
    assert serie[-1].close == 4199.0, "la dernière n'est pas la bougie en cours"
    assert serie[-1].timestamp == serie[-2].timestamp + dt.timedelta(minutes=5)


# ─── ⑤ Le repos entre deux réveils ──────────────────────────────────────

def test_rien_de_nouveau_ne_reveille_pas():
    etat = BL.EtatPaire()
    assert BL.reveil_du(set(), etat, 100.0) is False


def test_le_repos_empeche_deux_chaines_qui_se_chevauchent():
    """⛔ La chaîne lourde prend 0,5 à 1,9 s. Deux réveils à 200 ms d'écart
    décideraient sur un état de positions que le premier n'a pas écrit — la
    fabrique à doublons, qui a déjà coûté huit copies du même message le
    2026-10-07."""
    etat = BL.EtatPaire()
    assert BL.reveil_du({"a:buy"}, etat, 100.0, repos_sec=2.0) is True
    etat.dernier_reveil = 100.0
    assert BL.reveil_du({"b:sell"}, etat, 100.5, repos_sec=2.0) is False
    assert BL.reveil_du({"b:sell"}, etat, 102.5, repos_sec=2.0) is True


# ─── ⑥ Aucune exception ne sort ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_exception_ne_tue_pas_la_boucle(monkeypatch):
    """⛔ Un job asyncio qui lève meurt en SILENCE — le défaut du
    `gather(return_exceptions=True)` qui avalait tout le 2026-10-09."""
    tours = {"n": 0}

    async def explose(*a, **k):
        tours["n"] += 1
        raise RuntimeError("le pont a hoqueté")

    monkeypatch.setattr(BL, "un_passage", explose)
    await BL.boucle("XAU/USD", "5min", 50, 0.0,
                    reveiller=lambda *a: None,
                    arret=lambda: tours["n"] >= 3)
    assert tours["n"] == 3, "la boucle s'est arrêtée sur la première exception"


@pytest.mark.asyncio
async def test_la_boucle_reveille_bien_l_appelant(monkeypatch):
    faux = _Faux(_serie(50))
    _brancher(monkeypatch, faux, detections=[_Motif("pin_bar_down", "sell")])
    reveils = []

    async def reveiller(pair, motifs):
        reveils.append((pair, sorted(motifs)))

    tours = {"n": 0}
    vrai = BL.un_passage

    async def compte(*a, **k):
        tours["n"] += 1
        return await vrai(*a, **k)

    monkeypatch.setattr(BL, "un_passage", compte)
    await BL.boucle("XAU/USD", "5min", 50, 0.0, reveiller,
                    arret=lambda: tours["n"] >= 2)
    assert reveils == [("XAU/USD", ["pin_bar_down:sell"])], (
        "un seul réveil attendu : le second passage revoit le MÊME motif")


@pytest.mark.asyncio
async def test_une_annulation_sort_proprement(monkeypatch):
    async def dort(*a, **k):
        await asyncio.sleep(10)
        return set()

    monkeypatch.setattr(BL, "un_passage", dort)
    t = asyncio.create_task(
        BL.boucle("XAU/USD", "5min", 50, 0.2, reveiller=lambda *a: None))
    await asyncio.sleep(0.05)
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t


# ─── ⑦ L'arbitrage : les deux boucles ne tournent JAMAIS ensemble ────────

def test_la_legere_desarme_le_cycle_rapide():
    """⛔ Les deux armés, l'or recevrait deux chaînes lourdes concurrentes et
    le verrou de `run_analysis_cycle` en jetterait une — mais LAQUELLE dépend
    de l'ordonnancement. Le comportement cesse d'être reproductible, et une
    mesure sur un système irreproductible ne vaut rien."""
    from backend.services.scheduler import arbitrer_les_boucles
    assert arbitrer_les_boucles(0.2, ["XAU/USD"], 5, ["XAU/USD"]) == (0, [])


def test_sans_la_legere_le_cycle_rapide_est_intact():
    from backend.services.scheduler import arbitrer_les_boucles
    assert arbitrer_les_boucles(0.0, [], 5, ["XAU/USD"]) == (5, ["XAU/USD"])
    assert arbitrer_les_boucles(0.2, [], 5, ["XAU/USD"]) == (5, ["XAU/USD"])
    assert arbitrer_les_boucles(0.0, ["XAU/USD"], 5, ["XAU/USD"]) == (
        5, ["XAU/USD"])


@pytest.mark.asyncio
async def test_le_reveil_force_UNE_paire_jamais_la_liste_vide(monkeypatch):
    """⛔ LE PIÈGE. `univers_force=[]` est FAUSSE en Python, donc
    `restreint = bool(univers_force)` vaudrait False et on lancerait un cycle
    COMPLET — 54 paires et 24 s de travail, sur un réveil de 200 ms."""
    from backend.services import scheduler as S

    vus = []

    async def faux_cycle(univers_force=None):
        vus.append(univers_force)

    monkeypatch.setattr(S, "run_analysis_cycle", faux_cycle)

    async def fausse_boucle(pair, interval, combien, periode, reveiller,
                            arret=None):
        await reveiller(pair, {"pin_bar_down:sell"})

    monkeypatch.setattr(S.boucle_legere, "boucle", fausse_boucle)
    await S._boucle_legere_job("XAU/USD", 0.2)
    assert vus == [["XAU/USD"]], f"univers_force attendu ['XAU/USD'], vu {vus}"
    assert vus[0], "une liste VIDE déclencherait un cycle COMPLET"
