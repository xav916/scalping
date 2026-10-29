# `or-politique` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Une skill `or-politique` qui juge la configuration déclarée des destinations actives et sort en non-zéro si une destination en argent réel n'a pas de filtre de paires, ou si ce qui la protège n'est pas lisible — et l'extraction du transport SSH dans `or_commun`, partagé par les trois skills qui s'en servent.

**Architecture:** Patron du pack : **juge pur** testé, **collecteur impur** non testé. Le transport SSH devient `or_commun/distant.py`, en **deux** fonctions parce que les deux implémentations existantes sont à deux niveaux différents — `or-porte` rend le `CompletedProcess` brut (ses appelants parsent `{` ou `[`), `or-etat` parse et lève.

**Tech Stack:** Python bibliothèque standard (`json`, `pathlib`, `subprocess`, `argparse`). `pytest`. `ssh` + `docker exec -i`, charge par **stdin**.

**Spec:** `docs/superpowers/specs/2026-10-30-or-politique-design.md` (commit `8dc27ec`)

## Global Constraints

- ⛔ **Lecture seule.** Aucun ordre, aucun armement, aucune écriture de données en production.
- ⛔ **Elle ne BLOQUE rien** : pas de câblage de déploiement, pas de sonde Telegram. Rapport + code de sortie.
- ⛔ **Fail-closed.** Fait illisible, destination inconnue, production injoignable ⇒ **FAIL** ou code 2, jamais « conforme ».
- 🔑 **Chaque règle nomme la SOURCE qui décide et la valeur lue.**
- 🔑 **Elle juge la configuration DÉCLARÉE, pas le comportement observé** — sonder est impossible, `execution_globale_fermee` court-circuite tout (prouvé : 25 couples sur 25).
- Nommage **français**, aligné sur `or-etat` / `or-porte`.
- Codes de sortie : `0` conforme · `1` au moins un FAIL · `2` n'a pas pu juger.
- ⛔ **Aucun `tests/__init__.py`** et aucun nom de fichier de test déjà employé dans le pack — c'est la collision introduite le 29/10 et corrigée en `a59f7a4`. Noms déjà pris : `test_juger.py`, `test_juger_etat.py`, `test_transport.py`, `test_charge.py`, `test_contraintes_lot.py`, `test_derive.py`, `test_lot.py`, `test_main.py`, `test_preinscrire.py`, `test_verdict.py`, `test_forme_placebo.py`, `test_forme_seuil.py`, `test_sections.py`.
- L'idiome d'import de `or_commun`, **déjà en service** dans `or-verdict/verdict.py:50` : `sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))` puis `from or_commun import …`.

## File Structure

| fichier | responsabilité |
|---|---|
| `.claude/skills/or_commun/distant.py` | `executer()` (transport) et `derniere_ligne_json()` (analyse) |
| `.claude/skills/or_commun/tests/test_distant.py` | les deux fonctions, déménagés depuis `or-etat` |
| `.claude/skills/or-etat/etat.py` | perd sa copie privée, compose les deux fonctions |
| `.claude/skills/or-porte/porte.py` | perd sa copie privée, ses **3** appelants utilisent les deux fonctions |
| `.claude/skills/or-politique/regles.py` | les cinq règles, pures |
| `.claude/skills/or-politique/politique.py` | juge pur + collecteur + `main()` |
| `.claude/skills/or-politique/SKILL.md` | description à phrases déclenchantes |
| `.claude/skills/or-politique/tests/test_regles.py` | les cinq règles dans leurs deux sens |
| `.claude/skills/or-politique/tests/test_temoin_politique.py` | la configuration réelle du 30/10 |
| `.claude/skills/or-politique/tests/test_derive_listes.py` | dérive du mappage, dans le conteneur |

**Le contrat `etat_config`** — ce que le collecteur rend et ce que le juge consomme, fixé ici une fois :

```json
{
  "fingerprint_running": "a4d9aedeee17",
  "rem002_allowed": false,
  "rem002_reason": "DISARMED_MANUALLY",
  "listes_blanches": {"admin_live": ["XAU/USD"], "admin_legacy": ["AUD/USD"]},
  "destinations": [
    {"destination_id": "admin_kraken", "bridge_type": "kraken",
     "reel": true, "min_confidence": 42.0,
     "classes_porte": ["crypto"], "classes_registre": ["crypto", "metal"],
     "connue_du_registre": true, "garde_fous": {}}
  ]
}
```

`listes_blanches` ne contient **que** les destinations pour lesquelles la porte applique une liste ; une destination absente de ce dict n'a **aucun** filtre. `garde_fous` vide signifie « le pont ne publie rien ». `classes_porte` vient de `allowed_asset_classes`, `classes_registre` du registre — l'écart est la règle 5.

---

### Task 1: `or_commun/distant.py` — le transport partagé, en deux fonctions

**Files:**
- Create: `.claude/skills/or_commun/distant.py`
- Create: `.claude/skills/or_commun/tests/test_distant.py`
- Delete: `.claude/skills/or-etat/tests/test_transport.py` (son contenu déménage)

**Interfaces:**
- Consumes: rien.
- Produces: `executer(depot: pathlib.Path, src: str, timeout: int = 120) -> subprocess.CompletedProcess` · `derniere_ligne_json(sortie: subprocess.CompletedProcess, prefixe: str = "{")` — rend l'objet ou le tableau JSON de la **dernière** ligne commençant par `prefixe`, **lève** `RuntimeError` sinon.

- [ ] **Step 1: Write the failing test**

Créer `.claude/skills/or_commun/tests/test_distant.py` :

```python
"""Le transport vers le conteneur, et l'analyse de ce qu'il rend.

Mesure du 2026-10-29 : une charge MULTI-LIGNES passee en argument de
`python3 -c` apres `json.dumps` arrive sur UNE seule ligne avec des `\\n`
litteraux. Bash ne les interprete pas entre guillemets doubles, et Python lit
le backslash comme une continuation de ligne :

    SyntaxError: unexpected character after line continuation character

Le defaut a persiste dans `or-etat` PARCE QUE le correctif d'`or-porte`
n'etait pas partage : deux copies, une seule reparee. D'ou ce module.
"""
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from or_commun import distant  # noqa: E402

MULTILIGNE = (
    "import json\n"
    "def f():\n"
    "    return 1\n"
    "print(json.dumps({'a':f()}))"
)


class _FauxRun:
    def __init__(self, stdout="", stderr=""):
        self.argv = None
        self.kwargs = None
        self._out = types.SimpleNamespace(
            stdout=stdout, stderr=stderr, returncode=0)

    def __call__(self, argv, **kw):
        self.argv, self.kwargs = argv, kw
        return self._out


def test_la_charge_passe_par_STDIN_et_non_par_la_ligne_de_commande(monkeypatch):
    faux = _FauxRun()
    monkeypatch.setattr(distant.subprocess, "run", faux)
    distant.executer(pathlib.Path("."), MULTILIGNE)
    commande = " ".join(faux.argv)
    assert "python3 -c" not in commande
    assert "python3 -" in commande
    assert "docker exec -i" in commande, "-i relaie le stdin dans le conteneur"
    assert "-n" not in faux.argv, "-n fermerait le stdin qu'on utilise"
    assert faux.kwargs.get("input") == MULTILIGNE


def test_aucun_fragment_de_la_charge_dans_la_commande(monkeypatch):
    faux = _FauxRun()
    monkeypatch.setattr(distant.subprocess, "run", faux)
    distant.executer(pathlib.Path("."), MULTILIGNE)
    for morceau in faux.argv:
        assert "def f()" not in morceau
        assert "\\n" not in morceau


def test_le_timeout_par_defaut_est_120(monkeypatch):
    """Unifie sur le PLUS GRAND des deux : un delai plus court sur la charge
    la plus grosse (12 Ko du vivier) serait le mauvais defaut."""
    faux = _FauxRun()
    monkeypatch.setattr(distant.subprocess, "run", faux)
    distant.executer(pathlib.Path("."), "print(1)")
    assert faux.kwargs.get("timeout") == 120


def test_la_DERNIERE_ligne_json_est_prise():
    """La banniere ssh ecrit sur stdout a chaque appel."""
    sortie = types.SimpleNamespace(
        stdout='** banniere ssh\n{"a": 1}\n{"a": 2}\n', stderr="", returncode=0)
    assert distant.derniere_ligne_json(sortie) == {"a": 2}


def test_un_tableau_est_lisible_avec_son_prefixe():
    sortie = types.SimpleNamespace(
        stdout='** banniere\n[{"pair": "XAU/USD"}]\n', stderr="", returncode=0)
    assert distant.derniere_ligne_json(sortie, prefixe="[") == [
        {"pair": "XAU/USD"}]


def test_une_sortie_illisible_LEVE_au_lieu_de_rendre_None():
    sortie = types.SimpleNamespace(
        stdout="pas du json", stderr="erreur distante", returncode=1)
    with pytest.raises(RuntimeError, match="erreur distante"):
        distant.derniere_ligne_json(sortie)


def test_le_message_d_erreur_porte_stderr_quand_il_existe():
    sortie = types.SimpleNamespace(
        stdout="", stderr="SyntaxError: quelque chose", returncode=1)
    with pytest.raises(RuntimeError, match="SyntaxError"):
        distant.derniere_ligne_json(sortie)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest .claude/skills/or_commun/tests/test_distant.py -v`
Expected: FAIL — `ImportError: cannot import name 'distant'`

- [ ] **Step 3: Write minimal implementation**

Créer `.claude/skills/or_commun/distant.py` :

```python
"""Executer une charge Python dans le conteneur de production, et la lire.

⛔ La charge passe par STDIN, jamais en argument de `python3 -c`. Une charge
MULTI-LIGNES passee en argument arrive sur UNE seule ligne avec des `\\n`
litteraux : bash ne les interprete pas entre guillemets doubles, et Python lit
le backslash comme une continuation de ligne. Mesure du 2026-10-29, verifiee
jusqu'a 50 Ko par stdin.

🔑 Ce module existe parce que la DUPLICATION a coute : le defaut ci-dessus a
persiste dans `or-etat` pendant des semaines alors qu'`or-porte` l'avait
corrige — deux copies, une seule reparee.

Deux fonctions et pas une, parce que les appelants n'ont pas tous le meme
besoin : `or-porte` lit tantot un objet, tantot un tableau.
"""
from __future__ import annotations

import json
import pathlib
import subprocess

HOTE = "ec2-user@13.63.77.180"
CONTENEUR = "scalping-radar"


def executer(depot: pathlib.Path, src: str,
             timeout: int = 120) -> subprocess.CompletedProcess:
    """Lance `src` dans le conteneur. Non testee cote reseau.

    ⛔ `-n` est ABSENT : il fermerait le stdin dont on se sert. `docker exec`
    prend `-i`, sinon le conteneur ne recoit pas le flux.
    """
    return subprocess.run(
        ["ssh", "-i", str(depot / "scalping-key.pem"),
         "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes",
         HOTE, "sudo docker exec -i %s python3 -" % CONTENEUR],
        input=src, capture_output=True, text=True, timeout=timeout)


def derniere_ligne_json(sortie: subprocess.CompletedProcess,
                        prefixe: str = "{"):
    """La DERNIERE ligne commencant par `prefixe`, analysee.

    La derniere et non la premiere : la banniere ssh ecrit sur stdout a chaque
    appel. ⛔ Leve plutot que de rendre `None` — avaler le silence est ce qui
    avait rendu le defaut d'`or-etat` invisible : les champs manquaient, et le
    message accusait le symptome.
    """
    for ligne in reversed(sortie.stdout.splitlines()):
        if ligne.strip().startswith(prefixe):
            return json.loads(ligne)
    raise RuntimeError("la production n'a rien rendu de lisible : %s"
                       % (sortie.stderr or sortie.stdout)[-300:])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest .claude/skills/or_commun/tests/ -v`
Expected: PASS — 7 nouveaux + 8 existants = 15

- [ ] **Step 5: Remove the superseded copy of the tests**

```bash
git rm .claude/skills/or-etat/tests/test_transport.py
```

Ses trois tests sont repris, élargis, dans `test_distant.py`. ⚠️ `or-etat` reste
vert : son `etat.py` n'est pas encore modifié (c'est la tâche 2).

Run: `python -m pytest .claude/skills/or-etat/tests/ -v`
Expected: PASS — 11 tests (les 14 moins les 3 déménagés)

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/or_commun/distant.py \
        .claude/skills/or_commun/tests/test_distant.py
git rm --cached -q .claude/skills/or-etat/tests/test_transport.py 2>/dev/null || true
git add -A .claude/skills/or-etat/tests
git commit -m "or_commun : extraire le transport ssh, partage par les trois skills"
```

---

### Task 2: brancher `or-etat` sur `or_commun`

**Files:**
- Modify: `.claude/skills/or-etat/etat.py`
- Test: `.claude/skills/or-etat/tests/test_branchement_etat.py`

**Interfaces:**
- Consumes: `distant.executer`, `distant.derniere_ligne_json` (Task 1).
- Produces: aucun nouveau symbole public. `collecter()` garde sa signature `(depot) -> dict`.

- [ ] **Step 1: Write the failing test**

Créer `.claude/skills/or-etat/tests/test_branchement_etat.py` :

```python
"""`or-etat` ne doit plus porter sa propre copie du transport."""
import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import etat  # noqa: E402

SOURCE = pathlib.Path(etat.__file__).read_text(encoding="utf-8")


def test_plus_de_copie_privee_du_transport():
    assert "_executer_a_distance" not in SOURCE, \
        "le transport doit venir de or_commun, pas d'une copie locale"


def test_le_module_importe_or_commun_distant():
    arbre = ast.parse(SOURCE)
    importe = any(
        isinstance(n, ast.ImportFrom) and n.module == "or_commun"
        and any(a.name == "distant" for a in n.names)
        for n in ast.walk(arbre))
    assert importe, "attendu : `from or_commun import distant`"


def test_aucun_appel_subprocess_direct_ne_reste():
    """Tout passe par `distant.executer` desormais."""
    assert "subprocess.run" not in SOURCE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest .claude/skills/or-etat/tests/test_branchement_etat.py -v`
Expected: FAIL sur les trois — la copie privée est encore là.

- [ ] **Step 3: Write minimal implementation**

Dans `.claude/skills/or-etat/etat.py` : supprimer la fonction
`_executer_a_distance` **entière**, retirer `import subprocess`, ajouter sous
les imports existants :

```python
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from or_commun import distant  # noqa: E402
```

Puis remplacer les deux appels dans `collecter` :

```python
    brut = distant.derniere_ligne_json(distant.executer(depot, pyt))
    ...
    brut.update(distant.derniere_ligne_json(distant.executer(depot, pont)))
    return brut
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest .claude/skills/or-etat/tests/ -v`
Expected: PASS — 11 + 3 = 14

Puis **en vrai** : `python .claude/skills/or-etat/etat.py`
Expected: `=> DESARME, verifie sur les 3 voies`, exit **0**, les deux ponts à
200. ⓘ Un `exit 1` isolé peut arriver si un pont ne répond pas à cette
seconde-là — c'est le comportement JUSTE ; relancer trois fois et rapporter.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/or-etat/
git commit -m "or-etat : utiliser le transport partage de or_commun"
```

---

### Task 3: brancher `or-porte` sur `or_commun`

**Files:**
- Modify: `.claude/skills/or-porte/porte.py`
- Test: `.claude/skills/or-porte/tests/test_branchement_porte.py`

**Interfaces:**
- Consumes: `distant.executer`, `distant.derniere_ligne_json` (Task 1).
- Produces: aucun nouveau symbole. `collecter()`, `_lot_depuis_vivier()` et `main()` gardent leurs signatures.

- [ ] **Step 1: Write the failing test**

Créer `.claude/skills/or-porte/tests/test_branchement_porte.py` :

```python
"""`or-porte` ne doit plus porter sa propre copie du transport.

Ses TROIS appelants doivent passer par `or_commun.distant`, et le mode vivier
doit continuer de lire un TABLEAU (prefixe `[`) et non un objet.
"""
import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import porte  # noqa: E402

SOURCE = pathlib.Path(porte.__file__).read_text(encoding="utf-8")


def test_plus_de_copie_privee_du_transport():
    assert "_executer_a_distance" not in SOURCE


def test_le_module_importe_or_commun_distant():
    arbre = ast.parse(SOURCE)
    assert any(
        isinstance(n, ast.ImportFrom) and n.module == "or_commun"
        and any(a.name == "distant" for a in n.names)
        for n in ast.walk(arbre))


def test_aucun_appel_subprocess_direct_ne_reste():
    assert "subprocess.run" not in SOURCE


def test_le_mode_vivier_lit_toujours_un_TABLEAU():
    """Le vivier rend une liste de couples : perdre le prefixe `[` le
    casserait en silence, et le lot serait vide au lieu d'echouer."""
    assert 'prefixe="["' in SOURCE or "prefixe='['" in SOURCE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest .claude/skills/or-porte/tests/test_branchement_porte.py -v`
Expected: FAIL sur les quatre.

- [ ] **Step 3: Write minimal implementation**

Dans `.claude/skills/or-porte/porte.py` : supprimer `_executer_a_distance`,
retirer `import subprocess`, ajouter l'idiome d'import de `or_commun`, puis
réécrire les **trois** sites :

- dans `collecter` : `brut = distant.derniere_ligne_json(distant.executer(depot, src))`, en gardant le test `if "erreur" in brut:` qui lève avec la liste des destinations connues ;
- dans `_lot_depuis_vivier` : `couples = distant.derniere_ligne_json(distant.executer(depot, src), prefixe="[")` ;
- tout autre appel résiduel au transport.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest .claude/skills/or-porte/tests/ -v`
Expected: PASS — 58 + 4 = 62

Puis **en vrai**, les deux :
- `python .claude/skills/or-porte/porte.py --lot or/exemple-lot.json --no-write` → 10 couples, tous `BLOCK execution_globale_fermee`
- `python .claude/skills/or-porte/porte.py --depuis-vivier admin_kraken --no-write` → **22** couples

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/or-porte/
git commit -m "or-porte : utiliser le transport partage de or_commun"
```

---

### Task 4: `or-politique/regles.py` — les cinq règles, pures

**Files:**
- Create: `.claude/skills/or-politique/regles.py`
- Create: `.claude/skills/or-politique/__init__.py` (vide)
- Test: `.claude/skills/or-politique/tests/test_regles.py`

⛔ **Pas de `tests/__init__.py`** (collision du 29/10).

**Interfaces:**
- Consumes: le contrat `etat_config` (voir File Structure).
- Produces: `CONFORME = "CONFORME"`, `FAIL = "FAIL"`, `ILLISIBLE = "ILLISIBLE"`, `WARN = "WARN"`, `NON_APPLICABLE = "NON_APPLICABLE"` · `juger_destination(dest: dict, listes_blanches: dict) -> list[dict]` — rend **cinq** verdicts, un par règle, chacun `{"regle": int, "titre": str, "verdict": str, "source": str, "valeur": str}`.

- [ ] **Step 1: Write the failing test**

Créer `.claude/skills/or-politique/tests/test_regles.py` :

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import regles as R  # noqa: E402

# admin_kraken, releve REEL du 2026-10-30.
KRAKEN = {
    "destination_id": "admin_kraken", "bridge_type": "kraken", "reel": True,
    "min_confidence": 42.0, "classes_porte": ["crypto"],
    "classes_registre": ["crypto", "metal"], "connue_du_registre": True,
    "garde_fous": {},
}
# admin_live, releve REEL du 2026-10-30.
LIVE = {
    "destination_id": "admin_live", "bridge_type": "mt5", "reel": True,
    "min_confidence": 42.0, "classes_porte": ["energy", "forex", "metal"],
    "classes_registre": ["energy", "equity", "forex", "metal"],
    "connue_du_registre": True,
    "garde_fous": {"max_open_positions": 10, "max_daily_loss_pct": 10.0},
}
LEGACY = dict(LIVE, destination_id="admin_legacy", reel=False,
              classes_registre=["energy", "forex", "metal"])
BLANCHES = {"admin_live": ["XAU/USD"], "admin_legacy": ["AUD/USD"]}


def _regle(dest, n, blanches=BLANCHES):
    return next(v for v in R.juger_destination(dest, blanches)
                if v["regle"] == n)


def test_cinq_verdicts_un_par_regle():
    v = R.juger_destination(KRAKEN, BLANCHES)
    assert [x["regle"] for x in v] == [1, 2, 3, 4, 5]


def test_regle1_FAIL_sur_argent_reel_sans_filtre():
    v = _regle(KRAKEN, 1)
    assert v["verdict"] == R.FAIL
    assert "admin_kraken" in v["valeur"] or "aucun" in v["valeur"].lower()


def test_regle1_CONFORME_quand_une_liste_existe():
    assert _regle(LIVE, 1)["verdict"] == R.CONFORME


def test_regle1_NON_APPLICABLE_sans_argent_reel():
    assert _regle(LEGACY, 1)["verdict"] == R.NON_APPLICABLE


def test_regle2_FAIL_quand_garde_fous_vide_et_argent_reel():
    assert _regle(KRAKEN, 2)["verdict"] == R.FAIL


def test_regle2_CONFORME_quand_le_pont_publie_ses_gardes():
    assert _regle(LIVE, 2)["verdict"] == R.CONFORME


def test_regle3_FAIL_sur_seuil_nul_ou_absent():
    for mauvais in (0, 0.0, None):
        assert _regle(dict(LIVE, min_confidence=mauvais), 3)["verdict"] == R.FAIL
    assert _regle(LIVE, 3)["verdict"] == R.CONFORME


def test_regle4_FAIL_si_inconnue_du_registre():
    v = _regle(dict(LIVE, connue_du_registre=False), 4)
    assert v["verdict"] == R.FAIL


def test_regle5_WARN_et_jamais_FAIL_sur_divergence():
    assert _regle(LIVE, 5)["verdict"] == R.WARN
    assert _regle(KRAKEN, 5)["verdict"] == R.WARN
    coherent = dict(LIVE, classes_registre=LIVE["classes_porte"])
    assert _regle(coherent, 5)["verdict"] == R.CONFORME


def test_chaque_verdict_nomme_sa_SOURCE_et_sa_VALEUR():
    for v in R.juger_destination(KRAKEN, BLANCHES):
        assert v["source"], "regle %d sans source" % v["regle"]
        assert v["valeur"] != "", "regle %d sans valeur lue" % v["regle"]


def test_argent_reel_sans_filtre_ET_sans_garde_rend_DEUX_fail():
    """Les deux disent la meme inquietude par deux chemins : les fondre en un
    seul motif ferait croire qu'il n'y a qu'un probleme."""
    faux = [v for v in R.juger_destination(KRAKEN, BLANCHES)
            if v["verdict"] == R.FAIL]
    assert len(faux) == 2
    assert {v["regle"] for v in faux} == {1, 2}


def test_admin_legacy_ne_declenche_AUCUN_fail():
    """Une skill qui alerte sur un compte papier crie au loup."""
    assert not [v for v in R.juger_destination(LEGACY, BLANCHES)
                if v["verdict"] == R.FAIL]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest .claude/skills/or-politique/tests/test_regles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'regles'`

- [ ] **Step 3: Write minimal implementation**

Créer `.claude/skills/or-politique/__init__.py` vide, puis
`.claude/skills/or-politique/regles.py` :

```python
"""Les cinq regles de politique, pures.

Chaque regle nomme la SOURCE qui decide et la VALEUR lue : une regle sans
source est un avis, pas un verdict.

⛔ Aucune regle ne propose de desserrer une limite comme correctif. Si la
seule issue est d'elargir une liste blanche, c'est une DECISION a prendre.
"""
from __future__ import annotations

CONFORME = "CONFORME"
FAIL = "FAIL"
ILLISIBLE = "ILLISIBLE"
WARN = "WARN"
NON_APPLICABLE = "NON_APPLICABLE"


def _v(n, titre, verdict, source, valeur):
    return {"regle": n, "titre": titre, "verdict": verdict,
            "source": source, "valeur": str(valeur)}


def juger_destination(dest: dict, listes_blanches: dict) -> list[dict]:
    """Les cinq verdicts, dans l'ordre, pour UNE destination."""
    nom = dest.get("destination_id")
    reel = bool(dest.get("reel"))
    liste = listes_blanches.get(nom)

    # 1 — argent reel sans filtre de paires
    if not reel:
        r1 = _v(1, "filtre de paires", NON_APPLICABLE,
                "destinations_registry.is_real_money", "reel=False")
    elif liste:
        r1 = _v(1, "filtre de paires", CONFORME,
                "mt5_bridge.*_WHITELIST_PAIRS",
                "%d paire(s) : %s" % (len(liste), ", ".join(sorted(liste))))
    else:
        r1 = _v(1, "filtre de paires", FAIL,
                "mt5_bridge.*_WHITELIST_PAIRS",
                "aucune liste blanche n'est appliquee a %s" % nom)

    # 2 — argent reel sans garde-fou lisible
    gf = dest.get("garde_fous")
    if not reel:
        r2 = _v(2, "garde-fous du pont", NON_APPLICABLE,
                "destinations_registry.is_real_money", "reel=False")
    elif gf:
        r2 = _v(2, "garde-fous du pont", CONFORME, "/health garde_fous",
                "%d champ(s) publie(s)" % len(gf))
    else:
        r2 = _v(2, "garde-fous du pont", FAIL, "/health garde_fous",
                "aucun champ publie -- on ne peut pas verifier ce qui protege")

    # 3 — seuil de confiance
    seuil = dest.get("min_confidence")
    if not reel:
        r3 = _v(3, "seuil de confiance", NON_APPLICABLE,
                "destinations_registry.is_real_money", "reel=False")
    elif seuil is None or float(seuil) <= 0:
        r3 = _v(3, "seuil de confiance", FAIL, "BridgeConfig.min_confidence",
                "seuil=%s" % seuil)
    else:
        r3 = _v(3, "seuil de confiance", CONFORME,
                "BridgeConfig.min_confidence", "seuil=%s" % seuil)

    # 4 — destination active inconnue du registre
    if dest.get("connue_du_registre"):
        r4 = _v(4, "connue du registre", CONFORME,
                "destinations_registry.is_known", "oui")
    else:
        r4 = _v(4, "connue du registre", FAIL,
                "destinations_registry.is_known",
                "active mais absente du registre : on ne peut pas savoir si "
                "c'est de l'argent reel")

    # 5 — divergence des classes d'actif : WARN, jamais FAIL
    porte = set(dest.get("classes_porte") or ())
    registre = set(dest.get("classes_registre") or ())
    if porte == registre:
        r5 = _v(5, "classes d'actif", CONFORME,
                "BridgeConfig.allowed_asset_classes", ", ".join(sorted(porte)))
    else:
        r5 = _v(5, "classes d'actif", WARN,
                "BridgeConfig.allowed_asset_classes (le registre DIVERGE)",
                "porte=%s / registre=%s"
                % (", ".join(sorted(porte)) or "-",
                   ", ".join(sorted(registre)) or "-"))
    return [r1, r2, r3, r4, r5]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest .claude/skills/or-politique/tests/test_regles.py -v`
Expected: PASS — 12 tests

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/or-politique/__init__.py \
        .claude/skills/or-politique/regles.py \
        .claude/skills/or-politique/tests/test_regles.py
git commit -m "or-politique : les cinq regles, chacune nommant sa source et sa valeur"
```

---

### Task 5: le juge, le collecteur, la ligne de commande et `SKILL.md`

**Files:**
- Create: `.claude/skills/or-politique/politique.py`
- Create: `.claude/skills/or-politique/SKILL.md`
- Test: `.claude/skills/or-politique/tests/test_temoin_politique.py`

**Interfaces:**
- Consumes: `regles.juger_destination` (Task 4), `distant.executer` / `distant.derniere_ligne_json` (Task 1).
- Produces: `juger(etat: dict) -> tuple[int, list[str]]` · `collecter(depot) -> dict` · `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing test — le témoin**

Créer `.claude/skills/or-politique/tests/test_temoin_politique.py` :

```python
"""Temoin a reponse connue d'avance, etablie AVANT la skill et PAS depuis la
table qu'elle lira : mesures des 29 et 30/10 sur la production.

    is_real_money : admin_live True · admin_kraken True · admin_legacy False
    LIVE_WHITELIST_PAIRS   = {XAU/USD}
    LEGACY_WHITELIST_PAIRS = {12 paires}
                             (rien pour kraken)
    admin_kraken /health garde_fous = {}
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import politique as P  # noqa: E402
import regles as R  # noqa: E402

ETAT = {
    "fingerprint_running": "a4d9aedeee17",
    "rem002_allowed": False, "rem002_reason": "DISARMED_MANUALLY",
    "listes_blanches": {"admin_live": ["XAU/USD"],
                        "admin_legacy": ["AUD/USD", "EUR/USD"]},
    "destinations": [
        {"destination_id": "admin_legacy", "bridge_type": "mt5", "reel": False,
         "min_confidence": 42.0, "classes_porte": ["energy", "forex", "metal"],
         "classes_registre": ["energy", "forex", "metal"],
         "connue_du_registre": True, "garde_fous": {"max_open_positions": 10}},
        {"destination_id": "admin_live", "bridge_type": "mt5", "reel": True,
         "min_confidence": 42.0, "classes_porte": ["energy", "forex", "metal"],
         "classes_registre": ["energy", "equity", "forex", "metal"],
         "connue_du_registre": True, "garde_fous": {"max_open_positions": 10}},
        {"destination_id": "admin_kraken", "bridge_type": "kraken",
         "reel": True, "min_confidence": 42.0, "classes_porte": ["crypto"],
         "classes_registre": ["crypto", "metal"],
         "connue_du_registre": True, "garde_fous": {}},
    ],
}


def test_le_verdict_global_est_1_sur_la_config_reelle():
    code, _ = P.juger(ETAT)
    assert code == 1


def test_admin_kraken_est_nomme_sur_DEUX_regles():
    _, lignes = P.juger(ETAT)
    texte = "\n".join(lignes)
    assert "admin_kraken" in texte
    faux = [v for v in R.juger_destination(ETAT["destinations"][2],
                                           ETAT["listes_blanches"])
            if v["verdict"] == R.FAIL]
    assert {v["regle"] for v in faux} == {1, 2}


def test_aucun_FAIL_sur_admin_legacy():
    faux = [v for v in R.juger_destination(ETAT["destinations"][0],
                                           ETAT["listes_blanches"])
            if v["verdict"] == R.FAIL]
    assert faux == []


def test_la_sortie_nomme_l_empreinte_et_l_armement():
    _, lignes = P.juger(ETAT)
    texte = "\n".join(lignes)
    assert "a4d9aedeee17" in texte
    assert "DISARMED_MANUALLY" in texte


def test_la_sortie_dit_qu_elle_juge_la_config_DECLAREE():
    _, lignes = P.juger(ETAT)
    assert "declar" in "\n".join(lignes).lower()


def test_les_trois_destinations_apparaissent():
    _, lignes = P.juger(ETAT)
    texte = "\n".join(lignes)
    for nom in ("admin_legacy", "admin_live", "admin_kraken"):
        assert nom in texte


def test_empreinte_absente_rend_2_et_ne_juge_rien():
    code, lignes = P.juger(dict(ETAT, fingerprint_running=None))
    assert code == 2
    assert "empreinte" in "\n".join(lignes).lower()


def test_aucune_destination_active_rend_2():
    """Une production sans destination active est invraisemblable, donc
    suspecte : on ne rend pas « conforme »."""
    code, _ = P.juger(dict(ETAT, destinations=[]))
    assert code == 2


def test_une_config_entierement_saine_rend_0():
    """Temoin POSITIF : sans lui, un « 1 » permanent passerait pour normal."""
    sain = {
        "fingerprint_running": "abc123", "rem002_allowed": False,
        "rem002_reason": "DISARMED_MANUALLY",
        "listes_blanches": {"admin_live": ["XAU/USD"]},
        "destinations": [
            {"destination_id": "admin_live", "bridge_type": "mt5",
             "reel": True, "min_confidence": 42.0,
             "classes_porte": ["metal"], "classes_registre": ["metal"],
             "connue_du_registre": True,
             "garde_fous": {"max_open_positions": 10}},
        ],
    }
    code, _ = P.juger(sain)
    assert code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest .claude/skills/or-politique/tests/test_temoin_politique.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'politique'`

- [ ] **Step 3: Write the judge, the collector and the CLI**

Créer `.claude/skills/or-politique/politique.py` :

```python
"""Refuser une configuration qui laisse de l'argent reel sans garde.

⛔ Elle juge la configuration DECLAREE, jamais le comportement observe. Sonder
la porte serait plus fort, et c'est IMPOSSIBLE : `execution_globale_fermee` est
sa premiere clause et court-circuite tout tant que REM-002 est desarme (prouve
le 29/10 : 25 couples sur 25). Elle dit donc si une protection est DECLAREE,
pas si elle FONCTIONNE.

Lecture seule. Elle ne bloque rien : rapport et code de sortie.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from or_commun import distant  # noqa: E402

import regles as R  # noqa: E402

_CHARGE = '''
import json, sys
sys.path.insert(0, "/app")
from backend.services import bridge_destinations as BD
from backend.services import destinations_registry as RG
from backend.services import mt5_bridge as M

# Le mappage destination <-> liste blanche n'existe que sous forme de
# `if dest_id_wl == "admin_live"` dans la porte : c'est le SEUL fait
# reconstruit ici, et il est declare dans SKILL.md.
BLANCHES = {}
for nom, cst in (("admin_live", "LIVE_WHITELIST_PAIRS"),
                 ("admin_legacy", "LEGACY_WHITELIST_PAIRS")):
    v = getattr(M, cst, None)
    if v:
        BLANCHES[nom] = sorted(v)

def gardes(d):
    try:
        from backend.services import plafond_arbitrage as P
        s = P._lire_health(d.destination_id, avec_compte=False) or {}
    except Exception:
        s = {}
    return s.get("garde_fous") or {}

dests = []
for d in BD.admin_destinations():
    i = d.destination_id
    dests.append({
        "destination_id": i,
        "bridge_type": getattr(d, "bridge_type", "mt5"),
        "reel": bool(RG.is_real_money(i)),
        "min_confidence": getattr(d, "min_confidence", None),
        "classes_porte": sorted(getattr(d, "allowed_asset_classes", ()) or ()),
        "classes_registre": sorted(
            getattr(RG.get(i), "asset_classes", ()) or ()) if RG.get(i) else [],
        "connue_du_registre": bool(RG.is_known(i)),
        "garde_fous": gardes(d),
    })

from backend.services import global_execution_switch as G
det = G.execution_allowed().as_details()
print(json.dumps({
    "fingerprint_running": det.get("fingerprint_running"),
    "rem002_allowed": G.execution_allowed().allowed,
    "rem002_reason": det.get("reason_code"),
    "listes_blanches": BLANCHES,
    "destinations": dests,
}))
'''


def juger(etat: dict) -> tuple[int, list[str]]:
    """`(code, lignes)`. JAMAIS 0 sur une information absente."""
    empreinte = etat.get("fingerprint_running")
    if not empreinte:
        return 2, ["ECHEC : empreinte de code illisible -- un verdict calcule "
                   "contre un code inconnu est NUL, rien n'est juge."]
    dests = etat.get("destinations") or []
    if not dests:
        return 2, ["ECHEC : aucune destination active -- invraisemblable, donc "
                   "suspect. On ne rend pas « conforme »."]

    blanches = etat.get("listes_blanches") or {}
    lignes = ["=== or-politique | empreinte_code %s" % empreinte,
              "  armement : %s (%s)"
              % ("OUVERT" if etat.get("rem002_allowed") else "FERME",
                 etat.get("rem002_reason")),
              "  ⚠️ seule la configuration DECLAREE est jugee, pas son "
              "fonctionnement (REM-002 court-circuite toute sonde)",
              ""]

    n_fail = n_warn = 0
    for d in dests:
        lignes.append("  %-14s bridge=%-12s argent reel=%s"
                      % (d.get("destination_id"), d.get("bridge_type"),
                         "OUI" if d.get("reel") else "non"))
        for v in R.juger_destination(d, blanches):
            if v["verdict"] == R.FAIL:
                n_fail += 1
            elif v["verdict"] == R.WARN:
                n_warn += 1
            lignes.append("      %d. %-22s %-15s %s [%s]"
                          % (v["regle"], v["titre"], v["verdict"],
                             v["valeur"], v["source"]))
        lignes.append("")

    lignes.append("=> %d FAIL, %d WARN sur %d destination(s) active(s)"
                  % (n_fail, n_warn, len(dests)))
    return (1 if n_fail else 0), lignes


def collecter(depot: pathlib.Path) -> dict:
    """Interroge la production en LECTURE SEULE. Non testee (reseau)."""
    return distant.derniere_ligne_json(distant.executer(depot, _CHARGE))


def main(argv: list[str] | None = None) -> int:
    depot = pathlib.Path(__file__).resolve().parents[3]
    ap = argparse.ArgumentParser(
        description="Refuser une configuration sans garde.")
    ap.add_argument("--json", action="store_true", dest="en_json")
    a = ap.parse_args(argv)
    try:
        etat = collecter(depot)
    except Exception as e:  # noqa: BLE001
        print("ECHEC : production injoignable ou illisible (%s) -- rien n'est "
              "juge" % e)
        return 2
    try:
        code, lignes = juger(etat)
    except Exception as e:  # noqa: BLE001
        print("ECHEC : le jugement a leve (%s) -- rien n'est conclu" % e)
        return 2
    if a.en_json:
        print(json.dumps(etat, indent=2, ensure_ascii=False))
    else:
        for l in lignes:
            print(l)
    return code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes, then run it for real**

Run: `python -m pytest .claude/skills/or-politique/tests/ -v`
Expected: PASS — 12 + 9 = 21

Puis : `python .claude/skills/or-politique/politique.py`
Expected: exit **1**, `admin_kraken` en FAIL sur les règles **1 et 2**,
`admin_live` conforme sur la 1, aucun FAIL sur `admin_legacy`, et un WARN de
règle 5 sur `admin_live` et `admin_kraken`.

- [ ] **Step 5: Write `SKILL.md`**

Créer `.claude/skills/or-politique/SKILL.md` :

```markdown
---
name: or-politique
description: >-
  Refuse une configuration qui laisse une destination en argent reel sans
  filtre de paires, ou dont les garde-fous ne sont pas lisibles. A utiliser
  quand on demande « la configuration est-elle saine », « qu'est-ce qui
  protege l'argent reel », « peut-on rearmer », « quelles destinations sont
  actives », ou AVANT toute decision de rearmement. Rend un verdict par
  destination et par regle, chacun nommant la SOURCE qui decide et la valeur
  lue. Lecture seule : elle ne passe aucun ordre, n'arme rien, ne bloque
  aucun deploiement.
argument-hint: "[--json]"
---

# or-politique

```bash
python .claude/skills/or-politique/politique.py
python .claude/skills/or-politique/politique.py --json
```

Codes de sortie : `0` conforme · `1` au moins un FAIL · `2` n'a pas pu juger.

## ⚠️ Ce qu'elle juge, et ce qu'elle ne juge pas

Elle dit si une protection est **DECLAREE**, pas si elle **FONCTIONNE**. Les
deux questions sont distinctes, et seule la premiere est repondable tant que
l'IA est coupee : `execution_globale_fermee` est la premiere clause de la
porte et court-circuite toute sonde (mesure du 29/10 : 25 couples sur 25).

## Les cinq regles

| # | regle | verdict si violee |
|---|---|---|
| 1 | argent reel sans filtre de paires | **FAIL** |
| 2 | argent reel sans garde-fou lisible | **FAIL** |
| 3 | argent reel avec `min_confidence <= 0` | **FAIL** |
| 4 | destination active absente du registre | **FAIL** |
| 5 | classes du registre differentes de celles de la porte | **WARN** |

La 5 n'est qu'un WARN : la production se comporte correctement puisque c'est le
`BridgeConfig` qui tranche. Le risque est qu'un **humain** lise le registre.

## Le seul fait reconstruit

Le mappage destination <-> liste blanche n'existe que sous forme de
`if dest_id_wl == "admin_live"` dans `mt5_bridge.py:1100-1117`. Il est donc
reconstruit ici, et `tests/test_derive_listes.py` echoue si la production
ajoute, retire ou renomme une liste blanche. Tout le reste est LU depuis la
production.

## Exige

Un acces SSH a l'EC2 par `scalping-key.pem` a la racine du depot.
```

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/or-politique/
git commit -m "or-politique : juge, collecteur, ligne de commande et SKILL.md"
```

---

### Task 6: dérive du mappage, et la recette

**Files:**
- Create: `.claude/skills/or-politique/tests/test_derive_listes.py`

**Interfaces:**
- Consumes: tout ce qui précède. Produces: aucun symbole.

- [ ] **Step 1: Write the drift test**

Créer `.claude/skills/or-politique/tests/test_derive_listes.py` :

```python
"""Le mappage destination <-> liste blanche est le SEUL fait reconstruit.

Il n'existe que sous forme de `if dest_id_wl == "admin_live"` dans la porte.
Si la production ajoute, retire ou renomme une liste blanche, le verdict de
`or-politique` devient faux EN SILENCE. Ce test echoue a la place.

Il ne tourne que dans le conteneur (il importe la production) et se saute
proprement ailleurs.
"""
import pytest

prod = pytest.importorskip("backend.services.mt5_bridge",
                           reason="hors conteneur de production")

ATTENDUES = {"LIVE_WHITELIST_PAIRS", "LEGACY_WHITELIST_PAIRS"}


def test_les_constantes_de_liste_blanche_sont_exactement_celles_attendues():
    trouvees = {n for n in dir(prod) if n.endswith("_WHITELIST_PAIRS")}
    assert trouvees == ATTENDUES, (
        "la production porte %s ; or-politique reconstruit le mappage pour %s. "
        "Une liste blanche ajoutee ou renommee rend le verdict faux."
        % (sorted(trouvees), sorted(ATTENDUES)))
```

- [ ] **Step 2: Run the local suite and confirm it skips cleanly**

Run: `python -m pytest .claude/skills/or-politique/tests/ -v`
Expected: 21 passed **et** 1 skipped — ⓘ sauf si le dépôt complet est
importable depuis ce poste, auquel cas il **tourne et passe**, ce qui est plus
fort. Relever le compte réel.

- [ ] **Step 3: Run the drift test inside the container**

```bash
cd /c/Users/xav91/Scalping/scalping
tar cf - .claude/skills/or-politique .claude/skills/or_commun | ssh -i scalping-key.pem \
  -o BatchMode=yes -o StrictHostKeyChecking=no ec2-user@13.63.77.180 \
  'sudo docker exec -i -w /app scalping-radar tar xf - && \
   sudo docker exec -i -w /app scalping-radar python -m pytest \
   .claude/skills/or-politique/tests/test_derive_listes.py -v'
```

Expected: PASS. Si ÉCHEC, la production porte une liste blanche de plus :
corriger `_CHARGE` **et** `ATTENDUES`, puis s'arrêter et le signaler.

- [ ] **Step 4: Run the recipe — les cinq critères de la spec**

```bash
python .claude/skills/or-politique/politique.py ; echo "exit $?"
python -m pytest .claude/skills/or-etat/tests/ .claude/skills/or-porte/tests/ \
  .claude/skills/or-politique/tests/ .claude/skills/or-preinscription/tests/ \
  .claude/skills/or-verdict/tests/ .claude/skills/or_commun/tests/ -q
python .claude/skills/or-etat/etat.py ; echo "exit $?"
```

Consigner la sortie réelle dans le rapport, et vérifier :

1. exit **1**, `admin_kraken` nommé sur les règles **1 ET 2**, montrées séparément ;
2. les **trois** destinations présentes avec leur `bridge_type` et leur statut ;
3. la règle 5 avertit sur `admin_live` (`equity`) et `admin_kraken` (`metal`) ;
4. les **six** suites passent **en une seule commande** ;
5. `or-etat` rend toujours `=> DESARME`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/or-politique/tests/test_derive_listes.py
git commit -m "or-politique : test de derive du mappage et recette en production"
```

---

## Self-Review

**1. Couverture de la spec.** Extraction dans `or_commun` et déménagement des
tests (T1) · branchements des deux skills existantes (T2, T3) · les cinq règles
avec source et valeur (T4) · juge, collecteur, CLI, `SKILL.md`, et la
déclaration « configuration déclarée » (T5) · dérive du mappage et recette
(T6). Le témoin, positif **et** négatif, est en T5.

**2. Placeholders.** Aucun. Les cinq règles, les trois branchements, les cinq
critères de recette et les deux témoins sont énumérés nommément.

**3. Cohérence des types.** `juger_destination(dest, listes_blanches) -> list[dict]`
rend toujours cinq verdicts ; `juger(etat) -> (int, list[str])` ;
`executer(...) -> CompletedProcess` et `derniere_ligne_json(sortie, prefixe)`
partout. `regles` est importé `R` dans les deux fichiers de test et dans
`politique.py`.

**Deux écarts assumés et dits.** ⓘ Le timeout partagé est unifié à **120 s**,
celui d'`or-porte` : un délai plus court sur la charge la plus grosse (12 Ko du
vivier) serait le mauvais défaut, et `or-etat` n'y perd rien. ⓘ La règle 2 et
la règle 1 tomberont **toutes les deux** sur `admin_kraken` ; c'est voulu, et
le rapport doit les montrer séparément plutôt que fondues en un motif.
