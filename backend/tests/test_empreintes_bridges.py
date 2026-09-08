"""Le vérificateur d'empreintes des bridges, et ses exceptions.

`scripts/verifier-empreintes-bridges.sh` compare l'empreinte annoncée par
chaque bridge à celle de sa source versionnée. Il porte un dictionnaire
`ACCEPTEES` : des dérives **reconnues**, épinglées sur les DEUX empreintes,
qui s'affichent avec leur motif au lieu de crier.

⛔ Ce fichier n'avait AUCUN test avant le 2026-09-08 — découvert en constatant
que ses épingles étaient périmées et que rien ne l'avait dit.

## Le défaut que ces tests rendent impossible

Une exception qui **survit à la dérive qu'elle couvre** est un trou : elle
accepterait en silence ce couple exact s'il revenait. Le 06/09 deux épingles
avaient été posées ; le 08/09 le déploiement de la poche « or » a redémarré
les deux bridges MT5, les rendant conformes — et les épingles sont devenues
des portes ouvertes que plus rien ne surveillait.

🔑 Rien ne crie quand une exception devient inutile. C'est le geste qu'on
oublie, donc celui qu'un test doit exiger.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re

SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
          / "scripts" / "verifier-empreintes-bridges.sh")


def _acceptees() -> dict:
    """Extrait le dictionnaire `ACCEPTEES` du script, sans l'exécuter.

    ⚠️ C'est un script shell qui embarque du Python : on ne peut ni l'importer
    ni le lancer ici. On lit donc la littérale, en AST.
    """
    src = io.open(SCRIPT, encoding="utf-8").read()
    m = re.search(r"^ACCEPTEES = (\{.*?\})$", src, re.S | re.M)
    assert m, "`ACCEPTEES` introuvable — le script a changé de forme"
    return ast.literal_eval(m.group(1))


def test_le_dictionnaire_reste_LISIBLE():
    """Si le script change de forme, ce test le dit avant les autres."""
    assert isinstance(_acceptees(), dict)


def test_AUCUNE_derive_epinglee_aujourd_hui():
    """⛔ Le garde-fou à deux clés. Épingler une dérive doit exiger un geste
    DÉLIBÉRÉ — ici et dans ce test — parce qu'une exception oubliée est une
    alarme désarmée qui a l'air armée.

    Quand tu ajoutes une épingle légitime, mets-la aussi dans ce test avec sa
    date et son motif : c'est ce qui rendra visible le jour où elle a survécu
    à sa cause.
    """
    epinglees = _acceptees()
    assert epinglees == {}, (
        "des dérives sont épinglées sans être déclarées ici — vérifier "
        f"qu'elles existent ENCORE avant de les accepter : {list(epinglees)}")


def test_une_epingle_porte_les_DEUX_empreintes():
    """🔑 La clé est (destination, dépôt, bridge). Épingler la seule empreinte
    du bridge accepterait n'importe quel dépôt en face — et la dérive
    suivante passerait avec."""
    for cle in _acceptees():
        assert isinstance(cle, tuple) and len(cle) == 3, cle
        assert all(isinstance(x, str) and x for x in cle), cle


def test_le_script_DISTINGUE_injoignable_de_derive():
    """⚠️ Un bridge muet n'est pas une dérive : le dire ainsi enverrait
    chercher un écart de version là où il y a une panne réseau."""
    src = io.open(SCRIPT, encoding="utf-8").read()
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "INJOIGNABLE" in code
    assert "PAS D EMPREINTE" in code


def test_le_script_couvre_les_QUATRE_bridges():
    """⛔ Un bridge absent de la liste n'est pas surveillé, et son absence ne
    produit aucune erreur — exactement le silence que ce script existe pour
    supprimer."""
    src = io.open(SCRIPT, encoding="utf-8").read()
    for did in ("admin_live", "admin_legacy", "admin_kraken",
                "admin_kraken_spot"):
        assert did in src, did
