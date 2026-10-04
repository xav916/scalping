"""Ouvrir un horizon sans ouvrir ses motifs RETRECIT en silence.

## Le defaut reel, trouve le 2026-10-04

L'or a recu une derogation d'HORIZON pour les six echelles :

    MT5_BRIDGE_HORIZON_OVERRIDES
      {"XAU/USD": {"admin_live": ["5min","15min","30min","1h","4h","1d"]}}

Et une derogation de MOTIFS pour cinq d'entre elles :

    MT5_BRIDGE_PATTERN_OVERRIDES
      {"XAU/USD": {"5min":[8 motifs], "15min":[...], "30min":[9],
                   "4h":[...], "1d":[...]}}          # ni `1h`, ni `60min`

⛔ Les deux portes ne lisent PAS le nom de la meme facon :

- la porte d'HORIZON **normalise** — `1h` et `60min` y sont le meme horizon ;
- la porte de MOTIFS lit la chaine **BRUTE** (`par_paire.get(horizon)`), et la
  production estampille `60min`.

Resultat : l'or a 60 min franchissait la porte d'horizon, puis **retombait sur
la liste globale** — qui vaut DEUX motifs (`range_bounce_up/down`) au lieu de
huit. Aucun message, aucune trace : une derogation a moitie posee ressemble
exactement a une derogation posee.

🔑 BTC et ETH portent deja les DEUX cles, `1h` ET `60min`. La lecon avait ete
apprise une fois sans etre appliquee ailleurs — c'est precisement ce qu'un
test doit empecher.

## Ce qui est verrouille ici

Une paire qui ouvre un horizon et qui possede une liste de motifs doit couvrir
cet horizon **dans toutes ses orthographes**. Sinon le detecteur le signale.

⚠️ Une paire SANS aucune derogation de motifs n'est pas signalee : elle
retombe volontairement sur la liste globale, c'est le reglage par defaut et
non un oubli.
"""
from __future__ import annotations

from scripts.verifier_derogations import ALIAS, horizons_sans_motifs


# ─── Le defaut historique, reproduit ────────────────────────────────────────

def test_attrape_le_defaut_REEL_de_l_or():
    """Six horizons ouverts, cinq couverts : le 60 min doit etre signale."""
    horizons = {"XAU/USD": {"admin_live":
                            ["5min", "15min", "30min", "1h", "4h", "1d"]}}
    motifs = {"XAU/USD": {"5min": ["a"], "15min": ["a"], "30min": ["a"],
                          "4h": ["a"], "1d": ["a"]}}
    trous = horizons_sans_motifs(horizons, motifs)
    # Les DEUX orthographes manquent : ni `1h`, ni `60min`. La production
    # estampille `60min`, donc c'est celle-la qui faisait mal — mais les deux
    # doivent etre posees, sinon le trou revient au premier changement.
    assert trous == [("XAU/USD", "1h"), ("XAU/USD", "60min")], trous


def test_ne_signale_RIEN_quand_les_deux_orthographes_sont_la():
    """BTC porte `1h` ET `60min` — c'est la forme correcte."""
    horizons = {"BTC/USD": {"admin_live": ["5min", "1h"]}}
    motifs = {"BTC/USD": {"5min": ["a"], "1h": ["a"], "60min": ["a"]}}
    assert horizons_sans_motifs(horizons, motifs) == []


def test_UNE_SEULE_orthographe_ne_suffit_pas():
    """⛔ Le coeur du defaut : `1h` seul laisse passer un setup estampille
    `60min`, et inversement. Les deux sont exigees."""
    horizons = {"X/USD": {"admin_live": ["1h"]}}
    assert horizons_sans_motifs(horizons, {"X/USD": {"1h": ["a"]}}) == \
        [("X/USD", "60min")]
    assert horizons_sans_motifs(horizons, {"X/USD": {"60min": ["a"]}}) == \
        [("X/USD", "1h")]


def test_une_paire_SANS_derogation_de_motifs_n_est_pas_signalee():
    """⚠️ Elle retombe volontairement sur la liste globale. C'est le reglage
    par defaut, pas un oubli — le signaler noierait le vrai defaut."""
    horizons = {"EUR/USD": {"admin_live": ["5min", "4h"]}}
    assert horizons_sans_motifs(horizons, {}) == []
    assert horizons_sans_motifs(horizons, {"AUTRE/USD": {"4h": ["a"]}}) == []


def test_une_liste_de_motifs_VIDE_compte_comme_absente():
    """`par_paire.get(horizon)` ne retient une liste que si elle est NON vide
    (`isinstance(...) and liste`). Une liste vide retombe donc sur le global,
    exactement comme une cle manquante."""
    horizons = {"X/USD": {"admin_live": ["4h"]}}
    assert horizons_sans_motifs(horizons, {"X/USD": {"4h": [], "5min": ["a"]}}) \
        == [("X/USD", "4h")]


def test_le_JOUR_n_a_PAS_d_alias_exige():
    """⛔ Correction apportee par un test qui a ECHOUE. Ma premiere version
    exigeait `1day` en face de `1d` — mais rien n'estampille jamais `1day` :
    `horizon.HORIZONS` dit `1d`, et le flux long porte `tf: '1d'`. Seul
    `bougies_du_pont._ECHELLES` connait `1day`, et c'est pour LIRE des
    bougies, pas pour marquer un setup.

    🔑 Exiger une cle que personne ne produit aurait signale un faux trou sur
    toutes les paires ouvertes au jour. Un detecteur qui crie a tort finit
    ignore — donc pire qu'absent.
    """
    horizons = {"X/USD": {"admin_live": ["1d"]}}
    assert horizons_sans_motifs(
        horizons, {"X/USD": {"1d": ["a"], "5min": ["a"]}}) == []


def test_les_horizons_sans_alias_ne_sont_exiges_qu_une_fois():
    horizons = {"X/USD": {"admin_live": ["5min", "15min", "30min", "4h"]}}
    motifs = {"X/USD": {"5min": ["a"], "15min": ["a"], "30min": ["a"],
                        "4h": ["a"]}}
    assert horizons_sans_motifs(horizons, motifs) == []


def test_plusieurs_destinations_sont_fusionnees():
    """Une paire ouverte a 4h sur une route et a 1d sur une autre doit couvrir
    les deux : la derogation de motifs est GLOBALE, pas par destination."""
    horizons = {"X/USD": {"admin_live": ["4h"], "admin_legacy": ["1d"]}}
    motifs = {"X/USD": {"4h": ["a"]}}
    assert horizons_sans_motifs(horizons, motifs) == [("X/USD", "1d")]


def test_une_configuration_absurde_ne_fait_pas_tomber_le_detecteur():
    """⚠️ Ces valeurs viennent de variables d'environnement : elles peuvent
    etre de n'importe quelle forme. Un detecteur qui leve sur une config
    abimee ne detecte plus rien."""
    assert horizons_sans_motifs(None, None) == []
    assert horizons_sans_motifs("pas un dict", {}) == []
    assert horizons_sans_motifs({"X": "pas un dict"}, {}) == []
    assert horizons_sans_motifs({"X": {"d": "pas une liste"}}, {}) == []
    assert horizons_sans_motifs({"X": {"d": ["4h"]}}, {"X": "pas un dict"}) == []


def test_les_ALIAS_couvrent_les_deux_sens():
    """La table doit etre symetrique, sinon le detecteur serait aveugle dans
    un sens."""
    for a, b in (("1h", "60min"),):
        assert b in ALIAS.get(a, ()), f"{a} -> {b} manquant"
        assert a in ALIAS.get(b, ()), f"{b} -> {a} manquant"
