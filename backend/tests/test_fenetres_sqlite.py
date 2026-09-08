"""Le piège de fenêtre SQLite : `T` contre espace.

⛔ Les dates de ce dépôt sont stockées en **ISO 8601 avec un `T`** —
`2026-09-08T18:06:41.547505+00:00` — alors que `datetime('now', ...)` de SQLite
rend une **espace** : `2026-09-08 17:06:41`.

En comparaison de chaînes, `T` vaut 0x54 et l'espace 0x20. Donc **toute ligne
du même jour est « supérieure » à n'importe quelle borne du même jour**, et la
fenêtre ne filtre RIEN. La requête rend la journée entière — sans erreur, sans
avertissement, avec un résultat parfaitement crédible.

## Ce que ça avait déjà coûté

- **04/09** : la mesure de saturation Twelve Data
  ([[project_saturation_twelvedata_2026_09_04]]).
- **08/09** : la déduplication du backtest portait sur la journée au lieu d'une
  heure, et mes propres mesures « sur 20 minutes » rendaient la journée entière
  — ce qui m'a fait annoncer une anomalie qui n'existait pas.

⚠️ **La sévérité dépend de la longueur de la fenêtre**, et je l'avais d'abord
surestimée. Sur une borne à −7 jours, les dates plus anciennes se comparent
correctement par leur préfixe : seules les lignes du **jour de la borne**
échappent (366 sur 49 259, mesuré). Le défaut n'est TOTAL que sur les fenêtres
courtes, où la borne tombe aujourd'hui et où toutes les lignes du jour la
dépassent.

🔑 La forme du défaut : *une fenêtre qui ne filtre pas se lit comme une fenêtre
qui filtre.* Rien ne distingue les deux à l'œil.

## La parade

`replace(colonne,'T',' ')` normalise avant de comparer, et fonctionne pour les
DEUX formats — utile car `pair_admission_state.state_since` en contenait 13 au
format espace, écrites par deux watchdogs.

⚠️ `date('now')` reste SÛR : il rend `2026-09-08`, et la comparaison de préfixe
est correcte pour les deux formats. Ce test ne le signale donc pas.
"""
from __future__ import annotations

import io
import pathlib
import re

RACINE = pathlib.Path(__file__).resolve().parents[2]
DOSSIERS = ("backend", "scripts", "mt5-bridge", "kraken-bridge")
SUFFIXES = (".py", ".sh")

# Une comparaison : un opérateur d'ordre, puis `datetime('now'` sur la même
# ligne. `=` seul (une écriture) n'est pas concerné.
COMPARAISON = re.compile(r"[<>]=?[^\n]*datetime\(\s*['\"]now['\"]")


def _fichiers():
    for d in DOSSIERS:
        base = RACINE / d
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if f.suffix in SUFFIXES and "/tests/" not in f.as_posix() \
                    and "\\tests\\" not in str(f):
                yield f


def test_aucune_fenetre_ne_compare_une_date_ISO_a_datetime_now():
    """⛔ Le garde-fou. Toute comparaison d'ordre contre `datetime('now',...)`
    doit normaliser la colonne — sinon elle ne filtre rien."""
    fautifs = []
    for f in _fichiers():
        try:
            texte = io.open(f, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        for n, ligne in enumerate(texte.splitlines(), 1):
            if ligne.lstrip().startswith(("#", "--")):
                continue          # les commentaires citent le défaut réparé
            if COMPARAISON.search(ligne) and "replace(" not in ligne:
                fautifs.append(f"{f.relative_to(RACINE).as_posix()}:{n}")
    assert not fautifs, (
        "fenêtre SQLite comparée sans normaliser le `T` — elle ne filtrera "
        f"rien : {fautifs}")


def test_la_normalisation_fait_bien_ce_qu_on_croit():
    """⚠️ Le test ci-dessus vérifie une FORME. Celui-ci vérifie que la forme
    en question produit le bon résultat — sinon on épingle un rituel."""
    import sqlite3

    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE t (quand TEXT)")
    c.executemany("INSERT INTO t VALUES (?)", [
        ("2026-09-08T18:06:41.547505+00:00",),   # récent, format T
        ("2026-09-08T00:01:00+00:00",),          # vieux, même jour
        ("2026-09-08 00:02:00",),                # vieux, format espace
    ])
    borne = "2026-09-08 17:00:00"

    sans = c.execute(
        "SELECT COUNT(*) FROM t WHERE quand >= ?", (borne,)).fetchone()[0]
    avec = c.execute(
        "SELECT COUNT(*) FROM t WHERE replace(quand,'T',' ') >= ?",
        (borne,)).fetchone()[0]

    assert sans == 2, "sans normalisation, les lignes du matin passent aussi"
    assert avec == 1, "avec normalisation, seule la récente passe"


def test_date_now_reste_autorise():
    """⚠️ `date('now')` rend `2026-09-08` : la comparaison de préfixe est juste
    pour les deux formats. L'interdire aurait été un faux positif."""
    import sqlite3

    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE t (quand TEXT)")
    c.executemany("INSERT INTO t VALUES (?)", [
        ("2026-09-08T18:06:41+00:00",),
        ("2026-09-07T23:59:59+00:00",),
    ])
    n = c.execute(
        "SELECT COUNT(*) FROM t WHERE quand >= ?", ("2026-09-08",)).fetchone()[0]
    assert n == 1
