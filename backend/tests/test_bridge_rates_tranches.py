"""`/rates` : découper la plage, et DIRE où reprendre.

## ⛔ LES DEUX DÉFAUTS, mesurés le 2026-10-08

**1. Une plage large échoue en bloc.** Mesure sur le pont RÉEL :

```
    7 j  -> n=1454   tronque=False
   30 j  -> n=5000   tronque=True
  180 j  -> n=5000   tronque=True
  365 j  -> ERREUR  copy_rates_range a echoue: (-2, 'Terminal: Invalid params')
 1095 j  -> ERREUR  idem
```

365 jours de M5 = **105 120 barres**, et le terminal MT5 plafonne son
historique en mémoire (le même an **découpé en tranches de 60 jours passe**,
six fois sur six). Ce n'est donc pas une plage impossible, c'est une plage
**trop large pour un seul appel**.

**2. La troncature est muette sur l'endroit où reprendre.** `brut[:MAX_BOUGIES]`
garde les **plus anciennes** et pose `tronque: true`. Un appelant qui veut la
suite doit **devinner** à quelle date relancer. Le laboratoire s'en sort parce
qu'il pagine lui-même par 10 jours (2 880 barres, sous le plafond) — mais rien
n'empêche l'appelant suivant de lire 24 jours en croyant en lire 180.

> ⚠️ Et c'est bien ce qui m'est arrivé : j'ai conclu « `/rates` rend 0 bougie »
> en lisant la clé `rates` au lieu de `bougies`. Le défaut annoncé n'existait
> pas ; ceux-ci existent.

🔑 Le correctif ne change **rien** pour un appelant existant : la réponse garde
ses champs, la troncature garde les plus anciennes (c'est le bon sens pour
avancer), et un champ `suite_from` s'ajoute pour dire où reprendre.
"""
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "mt5-bridge" / "bridge.py"


def _charger():
    """Extrait le bloc du découpage du source et l'exécute seul.

    ⚠️ La tranche part de `_SECONDES_PAR_BARRE`, qui fait partie de ce qui est
    testé : l'injecter à la main laisserait passer un changement de ses valeurs
    dans le source.

    ⛔ `MAX_TRANCHES`, lui, est injecté — il vit DANS la section de
    configuration, loin de la fonction, parce qu'une dizaine de harnais
    extraient des tranches de ce source et les exécutent SANS `os`. Le poser
    près de la fonction cassait trois tests du moniteur sur du code juste.
    """
    src = _SRC.read_text(encoding="utf-8")
    debut = src.index("_SECONDES_PAR_BARRE = {")
    fin = src.index("def _decalage_serveur_sec(")
    mod = types.ModuleType("bridge_tranches")
    # `os.getenv` est lu dans ce bloc : on fournit un `os` sans variables.
    # ⛔ ON N'INJECTE PLUS `timedelta`. Le 2026-10-08 je l'ai injecte alors que
    # `bridge.py` ne l'importait PAS : les 9 tests passaient et le pont rendait
    # 500 sur `/rates`. Un harnais qui fournit un nom absent du source
    # affirme sur un objet factice — exactement le defaut de
    # `SimpleNamespace(reel=True)` deja paye ici.
    #
    # Les noms viennent donc du source lui-meme, et
    # `test_le_source_IMPORTE_bien_timedelta` epingle l'import.
    mod.__dict__.update({"datetime": datetime, "timezone": timezone,
                         "MAX_TRANCHES": 2000})
    for ligne in src.splitlines():
        if ligne.startswith("from datetime import"):
            exec(ligne, mod.__dict__)
            break
    exec(compile(src[debut:fin], str(_SRC), "exec"), mod.__dict__)
    return mod


A = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_une_plage_courte_reste_UNE_tranche():
    """⚠️ Ne pas decouper ce qui n'a pas besoin de l'etre : chaque tranche est
    un appel au terminal."""
    m = _charger()
    t = m._tranches_de_plage(A, A + timedelta(days=7), "M5", 5000)
    assert len(t) == 1
    assert t[0] == (A, A + timedelta(days=7))


def test_un_an_de_M5_est_decoupe():
    """365 j de M5 = 105 120 barres. En un appel, le terminal refuse."""
    m = _charger()
    t = m._tranches_de_plage(A, A + timedelta(days=365), "M5", 5000)
    assert len(t) > 1
    # 5 000 barres de 5 min = 17,36 jours : une vingtaine de tranches
    assert 15 <= len(t) <= 40, len(t)


def test_les_tranches_COUVRENT_toute_la_plage_sans_trou():
    """🔑 L'INVARIANT : bout à bout, et rien entre deux."""
    m = _charger()
    fin = A + timedelta(days=365)
    t = m._tranches_de_plage(A, fin, "M5", 5000)
    assert t[0][0] == A
    assert t[-1][1] == fin
    for (_a1, b1), (a2, _b2) in zip(t, t[1:]):
        assert b1 == a2, "trou ou recouvrement entre deux tranches"


def test_les_tranches_sont_ORDONNEES_du_plus_ancien_au_plus_recent():
    """La pagination avance dans le temps : l'ordre fait partie du contrat."""
    m = _charger()
    t = m._tranches_de_plage(A, A + timedelta(days=100), "M5", 5000)
    assert all(a < b for a, b in t)
    assert t == sorted(t)


def test_un_horizon_LONG_demande_moins_de_tranches():
    """D1 porte 288 fois moins de barres que M5 : une seule tranche suffit."""
    m = _charger()
    t5 = m._tranches_de_plage(A, A + timedelta(days=365), "M5", 5000)
    t1j = m._tranches_de_plage(A, A + timedelta(days=365), "D1", 5000)
    assert len(t1j) == 1
    assert len(t5) > len(t1j)


def test_un_horizon_INCONNU_ne_leve_PAS_et_decoupe_serre():
    """⛔ Chemin d'un appel reel : lever ici rendrait 500 au lieu de donnees.

    Un horizon non repertorie retombe sur la minute — la granularite la plus
    FINE, donc le decoupage le plus prudent. Se tromper doit decouper plus,
    jamais moins.
    """
    m = _charger()
    t = m._tranches_de_plage(A, A + timedelta(days=30), "ZZ9", 5000)
    assert len(t) > 1
    assert t[0][0] == A and t[-1][1] == A + timedelta(days=30)


def test_une_plage_vide_ou_inversee_rend_une_liste_VIDE():
    m = _charger()
    assert m._tranches_de_plage(A, A, "M5", 5000) == []
    assert m._tranches_de_plage(A, A - timedelta(days=1), "M5", 5000) == []


def test_un_plafond_absurde_ne_boucle_PAS_sans_fin():
    """⚠️ Un `barres_max` nul ou negatif ferait une boucle infinie et
    emporterait le pont — donc le chemin d'un ordre reel."""
    m = _charger()
    for mauvais in (0, -1, None):
        t = m._tranches_de_plage(A, A + timedelta(days=2), "M5", mauvais)
        assert 1 <= len(t) <= 2000, (mauvais, len(t))
        assert t[0][0] == A and t[-1][1] == A + timedelta(days=2)


def test_le_nombre_de_tranches_reste_BORNE_sur_dix_ans():
    """Dix ans de M1 = 5,2 millions de barres. Le découpage ne doit pas
    fabriquer des dizaines de milliers d'appels au terminal."""
    m = _charger()
    t = m._tranches_de_plage(A, A + timedelta(days=3650), "M1", 5000)
    assert len(t) <= 2000, len(t)
    assert t[-1][1] == A + timedelta(days=3650)


def test_le_source_IMPORTE_bien_timedelta():
    """⛔ LE DEFAUT DU 2026-10-08, et le seul test qui l'aurait attrape.

    `_tranches_de_plage` utilise `timedelta`. `bridge.py` ne l'importait pas.
    Mes neuf tests passaient parce que MON harnais le fournissait, et le pont
    REEL rendait `500 Internal Server Error` sur `/rates` :

        File "bridge.py", line 2311, in _tranches_de_plage
        NameError: name 'timedelta' is not defined

    🔑 Un harnais qui fournit un nom que le source n'a pas ne teste pas le
    source : il teste sa propre complaisance.
    """
    src = _SRC.read_text(encoding="utf-8")
    ligne = next((l for l in src.splitlines()
                  if l.startswith("from datetime import")), "")
    assert "timedelta" in ligne, (
        f"`timedelta` absent de l'import datetime du pont : {ligne!r}")


def test_les_bornes_NAIVES_sont_declarees_UTC_avant_comparaison():
    """⛔ LE 500 DU 2026-10-08, trouvé en rebouclant la pagination.

    `suite_from` est **aware** (`+00:00`), et les appelants écrivent souvent
    `to` **sans** fuseau. Comparer les deux lève `TypeError`, et le pont
    rendait `500 Internal Server Error` — sur un endpoint que l'admission du
    WTI utilise.

    ⚠️ Le défaut était **latent** : n'importe quel appelant mélangeant les deux
    formes le déclenchait, bien avant la pagination. C'est elle qui l'a mis au
    jour, elle ne l'a pas créé.

    Les bornes sont documentées UTC : une borne sans fuseau est de l'UTC qui ne
    se déclare pas, et le pont le déclare pour elle.
    """
    src = _SRC.read_text(encoding="utf-8")
    # ⚠️ On part de `def rates(` : `if fin <= debut:` existe AUSSI dans
    # `_tranches_de_plage`, plus haut dans le fichier, et une ancre ambigue
    # rendait une tranche VIDE — un test qui passe sur rien.
    depart = src.index("def rates():")
    bloc = src[depart:src.index("if fin <= debut:", depart)]
    assert "debut.tzinfo is None" in bloc, (
        "la borne `from` naive n'est plus normalisee : la comparaison levera")
    assert "fin.tzinfo is None" in bloc, (
        "la borne `to` naive n'est plus normalisee : la comparaison levera")
