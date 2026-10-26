"""Analyse des sections d'une pre-inscription ou d'un verdict.

Les titres du depot VARIENT : releve du 25/10, le critere apparait sous six
formes ("## LE CRITERE", "..., POSE AVANT DE REGARDER", "..., pose d'avance")
et les predictions sous sept, avec et sans accents. On compare donc sur une
forme NORMALISEE, jamais sur la chaine exacte.

REVISE LE 2026-10-26 : `section()` avait ete modifiee pour retenir le titre
ou le mot-cle apparait le plus tot (au lieu du premier titre du document).
Ce correctif etait PIRE que le defaut qu'il corrigeait : il n'est pas stable
par ajout en fin de fichier (un titre de verdict commencant par "Critere"
aurait produit une fausse accusation de falsification dans or-verdict), et il
a fait tomber `compter_predictions()` de 6 a 0 sur deux fichiers reels. Depuis
cette revision, `or-verdict` ne hache plus la section en prose mais le bloc
`CRITERE-MACHINE` (voir `bloc_machine_texte()`) : la prose peut etre reecrite
sans engager l'empreinte, et l'heuristique n'a plus de raison d'etre. Retour
a la regle simple : le PREMIER titre qui correspond, dans l'ordre du document.
"""
from __future__ import annotations

import re
import unicodedata

_MACHINE = re.compile(r"<!--\s*CRITERE-MACHINE\s*(.*?)-->", re.S)
_TITRE = re.compile(r"^(#{1,6})\s+(.*)$")
_PREDICTION = re.compile(r"^\s*(\d+)\.\s+\S")


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, sans ponctuation decorative."""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", sans_accent.lower()).strip()


def section(markdown: str, mot_cle: str) -> str | None:
    """Le corps de la premiere section dont le titre contient `mot_cle`.

    Premier titre qui correspond dans l'ORDRE DU DOCUMENT -- pas une
    heuristique sur la position du mot-cle dans le titre. Stable par ajout en
    fin de fichier : ajouter plus loin dans le document un titre qui
    correspond aussi ne change jamais le resultat.

    Rend `None` si aucun titre ne correspond -- l'appelant DOIT traiter ce cas
    comme un refus, jamais comme une section vide.
    """
    cle = normaliser(mot_cle)
    lignes = markdown.splitlines()
    debut = niveau = None
    for i, ligne in enumerate(lignes):
        m = _TITRE.match(ligne)
        if not m:
            continue
        if debut is None:
            if cle in normaliser(m.group(2)):
                debut, niveau = i + 1, len(m.group(1))
            continue
        if len(m.group(1)) <= niveau:
            return "\n".join(lignes[debut:i]).strip()
    if debut is None:
        return None
    return "\n".join(lignes[debut:]).strip()


def compter_predictions(markdown: str) -> int:
    """Le nombre de predictions NUMEROTEES de la section des predictions.

    Les puces ne comptent pas : une prediction doit etre numerotee pour etre
    citable dans un verdict ("ma prediction n 2 est fausse").
    """
    corps = section(markdown, "prediction")
    if corps is None:
        return 0
    return sum(1 for ligne in corps.splitlines() if _PREDICTION.match(ligne))


def bloc_machine_texte(markdown: str) -> str | None:
    """Le texte BRUT du bloc `CRITERE-MACHINE` (entre les marqueurs), ou `None`.

    Sert a l'empreinte du critere (`or-verdict`) : on hache ce texte, pas la
    prose environnante. Le bloc est delimite par un marqueur unique, non
    ambigu, et contient precisement ce qui ne doit pas bouger -- les seuils.
    """
    m = _MACHINE.search(markdown)
    if not m:
        return None
    return m.group(1).strip()


def bloc_machine(markdown: str) -> dict | None:
    """Le bloc `CRITERE-MACHINE`, ou `None` s'il est absent.

    Format `cle: valeur`, une par ligne. Deviner un seuil dans de la prose
    francaise serait fragile et silencieusement faux : on exige un bloc lisible
    par une machine, comme le `config.json` de trader-skill.
    """
    texte = bloc_machine_texte(markdown)
    if texte is None:
        return None
    out: dict = {}
    for ligne in texte.splitlines():
        if ":" not in ligne:
            continue
        cle, _, valeur = ligne.partition(":")
        cle, valeur = cle.strip(), valeur.strip()
        if cle and valeur:
            out[cle] = valeur
    return out or None
