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
import os
import pathlib
import subprocess

# ─── Cible, reglable sans redeployer la skill (2026-10-31) ────────────────
#
# ⚠️ L'adresse a DEJA change une fois dans ce projet, et un repli perime
# ecrit en dur dans `deploy-v2.sh` a coute une demi-heure le 2026-09-15 :
# « une adresse de secours fausse coute exactement au moment ou on en a
# besoin ». D'ou l'ouverture par l'environnement.
#
# ⛔ Le defaut est l'IP PUBLIQUE, pas l'adresse Tailscale : celle-ci
# (`100.103.107.75`) est INJOIGNABLE depuis le bac a sable Bash, alors que
# la publique l'est.
#
# ⛔ Noms DISTINCTS de `SCALPING_HOST`, deliberement : cette variable-la est
# lue par `deploy-v2.sh`, dont le defaut est l'adresse Tailscale. Partager le
# nom ferait pointer cette skill vers un hote injoignable des que quelqu'un
# regle l'autre outil.
HOTE = os.getenv("OR_HOTE") or "ec2-user@13.63.77.180"
CONTENEUR = os.getenv("OR_CONTENEUR") or "scalping-radar"
CLE = os.getenv("OR_CLE_SSH") or "scalping-key.pem"


def executer(depot: pathlib.Path, src: str,
             timeout: int = 120) -> subprocess.CompletedProcess:
    """Lance `src` dans le conteneur. Non testee cote reseau.

    ⛔ `-n` est ABSENT : il fermerait le stdin dont on se sert. `docker exec`
    prend `-i`, sinon le conteneur ne recoit pas le flux.
    """
    return subprocess.run(
        commande(depot),
        input=src, capture_output=True, text=True, timeout=timeout)


def commande(depot: pathlib.Path) -> list[str]:
    """La commande ssh, isolee pour etre TESTABLE sans reseau.

    🔑 `executer` ne peut pas se tester (elle sort de la machine) ; la
    construction de sa commande, si. C'est la seule partie qui peut se
    tromper en silence — une cle au mauvais chemin, un `-i` oublie sur
    `docker exec`, un hote pris a la mauvaise variable.
    """
    return ["ssh", "-i", str(depot / CLE),
            "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes",
            HOTE, "sudo docker exec -i %s python3 -" % CONTENEUR]


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
