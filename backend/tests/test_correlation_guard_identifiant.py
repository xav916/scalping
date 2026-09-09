"""Le garde de corrélation ne doit pas se désarmer sur une confusion de TYPE.

⛔ **L'incident du 2026-09-08.** Deux objets circulent dans ce dépôt pour
désigner un compte : `BridgeConfig` porte `destination_id`, le `Destination` du
registre porte `id`. Passer le second là où le code attendait le premier faisait
rendre `None` à `limite()`, donc `0`, donc **ILLIMITÉ** — en silence, sur un
chemin d'argent réel. `_identifiant()` a été posé pour accepter les deux formes.

⛔ **Ce que ce test ajoute (2026-09-09).** Le correctif s'est arrêté à
`limite()`. `pari_deja_pris` et `couples_non_mesures` — qui reçoivent le MÊME
objet — appelaient encore `positions_ouvertes(getattr(dest, "destination_id",
""))`. Avec un `Destination`, cela vaut `positions_ouvertes("")` : aucune
position trouvée, donc **aucun pari en cause, donc rien de bloqué**.

Le garde ne levait aucune erreur. Il répondait « tu peux y aller ».

> **Un correctif ne se propage pas seul aux routes jumelles.**

⚠️ Le défaut était LATENT : l'unique appelant de production passe bien un
`BridgeConfig`. Ce test existe pour qu'il le reste — et pour que la prochaine
route qui appellera ce module ne redécouvre pas le trou à ses frais.

Cf. [[project_deux_portes_or_2026_09_08]] · [[project_kraken_stops_depuis_fill_2026_08_19]]
"""
from types import SimpleNamespace

import pytest

from backend.services import correlation_guard as cg


class _Ouvertes:
    """Remplace `positions_ouvertes` — et se comporte comme la VRAIE.

    ⛔ Ma première version rendait les positions quel que soit l'identifiant
    reçu. Le test du registre passait alors **pour une mauvaise raison** : le
    garde trouvait ses deux positions même avec une chaîne vide. Un test qui
    fabrique lui-même le comportement du système qu'il vérifie valide sa propre
    fiction — c'est le défaut que ce dépôt a déjà payé sur `slippage_pips`.

    La vraie fonction filtre par compte : un identifiant vide ne désigne aucun
    compte et rend une liste vide. On reproduit cela, sinon on ne prouve rien.
    """

    def __init__(self, positions, compte="admin_legacy"):
        self.positions = positions
        self.compte = compte
        self.vus: list[str] = []

    def __call__(self, destination_id):
        self.vus.append(destination_id)
        if destination_id != self.compte:
            return []
        return list(self.positions)


@pytest.fixture
def deux_positions_correlees(monkeypatch):
    faux = _Ouvertes([("XAG/USD", "buy"), ("AUD/USD", "buy")])
    monkeypatch.setattr(cg, "positions_ouvertes", faux)
    monkeypatch.setitem(cg.LIMITE_PAR_PAIRE, ("admin_legacy", "XAU/USD"), 1)
    return faux


# `BridgeConfig` : ce que passe l'appelant de production aujourd'hui.
BRIDGE = SimpleNamespace(destination_id="admin_legacy")
# `Destination` du registre : la forme qui a désarmé `limite()` le 08/09.
REGISTRE = SimpleNamespace(id="admin_legacy")


def test_le_garde_bloque_avec_un_BridgeConfig(deux_positions_correlees):
    """Le cas nominal — sans lui, le test suivant ne prouverait rien."""
    pris, en_cause = cg.pari_deja_pris(BRIDGE, "XAU/USD", "buy")
    assert pris is True
    assert len(en_cause) == 2


def test_le_garde_bloque_AUSSI_avec_l_objet_du_registre(deux_positions_correlees):
    """⛔ Le cœur : la même situation, l'autre forme d'objet, le même verdict.

    Avant ce correctif, `positions_ouvertes("")` rendait une liste vide et le
    garde répondait « tu peux y aller » — sans erreur, sans log, sur un chemin
    d'argent réel.
    """
    pris, en_cause = cg.pari_deja_pris(REGISTRE, "XAU/USD", "buy")
    assert pris is True, (
        "le garde s'est désarmé sur une confusion de type — "
        f"identifiants transmis à positions_ouvertes : "
        f"{deux_positions_correlees.vus}"
    )
    assert len(en_cause) == 2


def test_l_identifiant_transmis_n_est_JAMAIS_vide(deux_positions_correlees):
    """La cause directe, verrouillée pour elle-même : une chaîne vide ne
    désigne aucun compte, et `positions_ouvertes` y répond « rien d'ouvert »."""
    cg.pari_deja_pris(REGISTRE, "XAU/USD", "buy")
    cg.couples_non_mesures(REGISTRE, "XAU/USD", "buy")
    assert "" not in deux_positions_correlees.vus
    assert deux_positions_correlees.vus == ["admin_legacy", "admin_legacy"]


def test_couples_non_mesures_voit_les_memes_positions(monkeypatch):
    """La fonction jumelle doit lire le même compte, sinon le trou de mesure
    se compterait sur un compte vide — et paraîtrait inexistant."""
    faux = _Ouvertes([("DOGE/USD", "buy")])  # couple jamais mesuré
    monkeypatch.setattr(cg, "positions_ouvertes", faux)
    monkeypatch.setitem(cg.LIMITE_PAR_PAIRE, ("admin_legacy", "XAU/USD"), 1)

    assert cg.couples_non_mesures(REGISTRE, "XAU/USD", "buy") == ["DOGE/USD buy"]
    assert faux.vus == ["admin_legacy"]
