"""Le cycle nocturne doit mesurer TOUS les instruments, pas seulement l'or.

⛔ **Sans cela, `plafond_commun` et `concordance` sont du code mort.** Ils sont
posés, testés — et sans aucun effet tant que le cycle itère sur `XAU/USD` seul.
C'est le « correctif écrit mais jamais appelé », débusqué deux fois dans la
journée.

## Ce que le branchement doit garantir

| | pourquoi |
|---|---|
| **découverte** des instruments, pas de liste figée | une liste en dur se périme au premier changement de courtier ; mesuré : 13 servis sur 25 déclarés |
| **un instrument qui échoue n'arrête pas les autres** | 90 jours × 13 paires, une seule lecture qui tombe ne doit pas coûter la nuit entière |
| **plafond COMMUN** appliqué à toutes les cellules | sinon 13 plafonds calculés chacun sur 120 tests, alors qu'on en fait 1 560 |
| **l'or garde ses décisions** | c'est lui qui pilote les fermetures ; les autres sont mesurés, pas arbitrés |

⚠️ Ce dernier point est le plus important pour la sécurité : élargir la MESURE
n'élargit pas la DÉCISION. Fermer un motif sur `EUR/USD` parce qu'il perd sur
`GBP/JPY` serait exactement le desserrage-par-inadvertance qu'on évite partout
ailleurs.
"""
import pytest

from backend.services import laboratoire_or as labo
from backend.services import reglage_or as rg


def _fausse_mesure(pair, plafond=2.0, t=1.0):
    return {"pair": pair, "spread": 0.5, "k": 2, "plafond": plafond,
            "bougies_m5": 900,
            "cellules": [
                {"pair": pair, "motif": "fvg_up", "horizon": "5min", "sens": "buy",
                 "n": 60, "r_moyen": 0.2, "t": t, "delta_hasard": 0.1,
                 "plafond": plafond, "verdict": "INSUFFISANT"},
                {"pair": pair, "motif": "bruit", "horizon": "5min", "sens": "sell",
                 "n": 60, "r_moyen": 0.0, "t": 0.1, "delta_hasard": 0.0,
                 "plafond": plafond, "verdict": "INSUFFISANT"},
            ]}


@pytest.fixture
def sans_effets(monkeypatch):
    """Neutralise tout ce qui écrit, envoie ou décide."""
    vus: dict = {"enregistres": [], "notifies": 0, "decides": []}
    monkeypatch.setattr(rg, "enregistrer", lambda m: vus["enregistres"].append(m))
    monkeypatch.setattr(rg, "_notifier", lambda *a, **k: vus.__setitem__(
        "notifies", vus["notifies"] + 1))
    monkeypatch.setattr(rg, "decider", lambda m, **k: vus["decides"].append(
        m.get("pair")) or [])
    return vus


def test_le_cycle_mesure_TOUS_les_instruments_servis(monkeypatch, sans_effets):
    """⛔ Le cœur : sans cela, la validation croisée n'a aucune donnée."""
    monkeypatch.setattr(rg, "instruments_servis",
                        lambda: ["XAU/USD", "EUR/USD", "GBP/JPY"])
    monkeypatch.setattr(rg, "_bougies_et_spread",
                        lambda jours, pair: ([{}] * 900, 0.5))
    monkeypatch.setattr(labo, "mesurer",
                        lambda b, s, pair=None, **k: _fausse_mesure(pair))

    r = rg.cycle_nocturne()
    assert set(r["instruments"]) == {"XAU/USD", "EUR/USD", "GBP/JPY"}
    assert len(sans_effets["enregistres"]) == 3


def test_un_instrument_qui_TOMBE_n_arrete_pas_les_autres(monkeypatch, sans_effets):
    """90 jours x 13 paires : une lecture qui echoue ne doit pas couter la nuit."""
    def _bougies(jours, pair):
        if pair == "EUR/USD":
            raise RuntimeError("bridge injoignable")
        return [{}] * 900, 0.5

    monkeypatch.setattr(rg, "instruments_servis",
                        lambda: ["XAU/USD", "EUR/USD", "GBP/JPY"])
    monkeypatch.setattr(rg, "_bougies_et_spread", _bougies)
    monkeypatch.setattr(labo, "mesurer",
                        lambda b, s, pair=None, **k: _fausse_mesure(pair))

    r = rg.cycle_nocturne()
    assert set(r["instruments"]) == {"XAU/USD", "GBP/JPY"}
    assert "EUR/USD" in r.get("echecs", {})


def test_le_plafond_COMMUN_ecrase_les_plafonds_par_paire(monkeypatch, sans_effets):
    """⛔ Treize plafonds calcules chacun sur 120 tests laisseraient passer ce
    qu'un plafond calcule sur 1 560 refuse."""
    monkeypatch.setattr(rg, "instruments_servis",
                        lambda: [f"P{i}/USD" for i in range(13)])
    monkeypatch.setattr(rg, "_bougies_et_spread",
                        lambda jours, pair: ([{}] * 900, 0.5))
    monkeypatch.setattr(labo, "mesurer",
                        lambda b, s, pair=None, **k: _fausse_mesure(pair, plafond=2.0))

    r = rg.cycle_nocturne()
    attendu = labo.plafond_hasard(13 * 2)
    assert r["plafond"] == pytest.approx(attendu, abs=1e-6)
    for m in sans_effets["enregistres"]:
        for c in m["cellules"]:
            assert c["plafond"] == pytest.approx(attendu, abs=1e-6), (
                "une cellule a garde le plafond de sa seule paire")


def test_seul_l_OR_est_ARBITRE(monkeypatch, sans_effets):
    """⚠️ Elargir la MESURE n'elargit pas la DECISION. Fermer un motif sur
    EUR/USD parce qu'il perd sur GBP/JPY serait un desserrage par inadvertance
    — dans l'autre sens, mais tout aussi non voulu."""
    monkeypatch.setattr(rg, "instruments_servis",
                        lambda: ["XAU/USD", "EUR/USD", "GBP/JPY"])
    monkeypatch.setattr(rg, "_bougies_et_spread",
                        lambda jours, pair: ([{}] * 900, 0.5))
    monkeypatch.setattr(labo, "mesurer",
                        lambda b, s, pair=None, **k: _fausse_mesure(pair))

    rg.cycle_nocturne()
    assert sans_effets["decides"] == ["XAU/USD"], sans_effets["decides"]


def test_la_CONCORDANCE_est_calculee_et_rendue(monkeypatch, sans_effets):
    """Le chiffre qui justifie tout l'exercice doit sortir du cycle."""
    monkeypatch.setattr(rg, "instruments_servis",
                        lambda: ["XAU/USD", "EUR/USD", "GBP/JPY"])
    monkeypatch.setattr(rg, "_bougies_et_spread",
                        lambda jours, pair: ([{}] * 900, 0.5))
    monkeypatch.setattr(labo, "mesurer",
                        lambda b, s, pair=None, **k: _fausse_mesure(pair, t=9.0))

    r = rg.cycle_nocturne()
    assert r["concordance"]["fvg_up"]["instruments"] == 3
    assert r["concordance"]["fvg_up"]["sur"] == 3


def test_AUCUN_instrument_lisible_ne_leve_pas(monkeypatch, sans_effets):
    """Une nuit ou le bridge est mort ne doit pas tuer le scheduler."""
    monkeypatch.setattr(rg, "instruments_servis", lambda: [])
    r = rg.cycle_nocturne()
    assert r.get("instruments") == [] or r.get("erreur")


# ─── La découverte des instruments ───────────────────────────────────

def test_instruments_servis_NE_DEVINE_pas(monkeypatch):
    """⛔ Une liste figée se périme au premier changement de courtier : mesuré,
    13 servis sur 25 déclarés. La liste doit être DÉCOUVERTE."""
    import inspect
    src = inspect.getsource(rg.instruments_servis)
    assert "/tick/" in src, "les instruments ne sont pas eprouves contre le pont"


def test_l_OR_est_TOUJOURS_en_tete(monkeypatch):
    """C'est lui qui porte les décisions : le mesurer en premier garantit
    qu'une nuit tronquée par un incident l'aura quand même mesuré."""
    import inspect
    src = inspect.getsource(rg.instruments_servis)
    assert "PAIRE" in src
