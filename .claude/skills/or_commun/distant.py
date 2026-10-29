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
