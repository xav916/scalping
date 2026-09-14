"""Le dictionnaire des notions DECLAREES — et ce qu'il manque pour les mesurer.

⛔ **Le verrou que ce module implemente** (2026-09-14). Cinq notions du corpus
sont verifiees comme existantes, mais leur contenu est inconnu :

    « 5 etapes pour prendre des trades gagnants »
    « ma strategie en 3 etapes »
    « Tu achetes ou tu vends ? »
    « Comment tu veux performer sans connaitre ces raccourcis ? »
    « Que faire dans ce contexte ? »

Aucune heure de code ne les ouvre. Inventer les cinq etapes fabriquerait « un
robot inspire de Vivien » en croyant reproduire sa methode — exactement ce que
Xavier a refuse par ecrit le 12/09.

🔑 **Ce qui EST implementable, c'est le verrou lui-meme.** Une notion se
declare ici en six lignes, et rien de plus :

    declencheur · invalidation · sens · echelle · stop · cible

Tant qu'une ligne manque, la notion est INCOMPLETE : elle ne produit aucune
chaine, et `lignes_manquantes()` dit precisement ce qui manque. Le systeme sait
alors ce qu'il ne sait pas — au lieu de l'ignorer en silence. Le jour ou les
six lignes arrivent, la chaine se mesure **sans une ligne de code**.

## Les trois refus que ce module tient

1. **Une notion incomplete ne produit AUCUNE chaine.** Le laboratoire ne mesure
   jamais une regle a moitie devinee : un verdict sur une regle inventee serait
   pire qu'aucun verdict, parce qu'il aurait l'air d'un resultat.
2. **Une notion sans `source` leve.** C'est la seule chose qui garde lisible la
   frontiere entre « ce qu'il dit » et « ce que nous avons deduit ».
3. **Un nom inconnu leve** — motif, predicat, ou sens qui contredit son
   declencheur. Meme doctrine que `_PREDICATS` : un nom mal orthographie
   mesurerait la chaine SANS sa condition, et le verdict serait faux sans que
   rien ne le dise. Le sens est verifie contre `_est_un_achat` — le defaut du
   14/09, ou neuf motifs haussiers vendaient, est ne d'un `else` muet.

⚠️ **Ajouter une notion RELEVE le plafond du hasard pour tout le monde.** Une
notion declaree est un test de plus ; elle se paie en exigence sur toutes les
autres cellules. C'est voulu — et c'est pourquoi on declare, on ne cherche pas.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Les six lignes qui rendent une notion mesurable. Ni plus — chaque champ
# supplementaire serait un degre de liberte de plus — ni moins.
CHAMPS: tuple[str, ...] = (
    "declencheur",      # le motif qui declenche l'entree
    "invalidation",     # ce qui tue le setup avant l'entree
    "sens",             # buy / sell
    "echelle",          # 5min, 15min, 30min, 1h...
    "stop",             # ou se place le SL, en mots
    "cible",            # ou se place le TP, en mots
)


NOTIONS: tuple[dict, ...] = (
    # ─── VERROUILLEES : titre verifie, contenu inconnu ────────────────
    # ⛔ Les six champs valent None. Ce n'est pas un oubli, c'est l'etat du
    # savoir : la duree indexee de « 5 etapes » est de 16 secondes et aucune
    # transcription n'existe. Les remplir de memoire serait une invention.
    {"nom": "cinq_etapes",
     "source": "Video « 5 etapes pour prendre des trades gagnants » (16 s, "
               "index public Vivien_Legendary, releve le 2026-09-12)"},
    {"nom": "strategie_trois_etapes",
     "source": "Video « ma strategie en 3 etapes » (annonce sur le canal)"},
    {"nom": "acheter_ou_vendre",
     "source": "Video « Tu achetes ou tu vends ? » (37 s, index public)"},
    {"nom": "les_raccourcis",
     "source": "Video « Comment tu veux performer sans connaitre ces "
               "raccourcis ? »"},
    {"nom": "que_faire_dans_ce_contexte",
     "source": "Video « Que faire dans ce contexte ? »"},
)


def par_nom(nom: str) -> dict:
    for n in NOTIONS:
        if n["nom"] == nom:
            return n
    raise KeyError(f"notion inconnue : {nom!r}")


def manques(notion: dict) -> tuple[str, ...]:
    """Les champs des six lignes qui manquent encore a cette notion."""
    return tuple(c for c in CHAMPS if not notion.get(c))


def completes(notions: tuple[dict, ...] | None = None) -> tuple[dict, ...]:
    return tuple(n for n in (NOTIONS if notions is None else notions)
                 if not manques(n))


def incompletes(notions: tuple[dict, ...] | None = None) -> tuple[dict, ...]:
    return tuple(n for n in (NOTIONS if notions is None else notions)
                 if manques(n))


def lignes_manquantes(notions: tuple[dict, ...] | None = None) -> list[str]:
    """Ce qu'il manque, notion par notion — lisible dans un message."""
    out = []
    for n in incompletes(notions):
        out.append(f"{n['nom']} — manque : {', '.join(manques(n))} "
                   f"[{n.get('source', 'SANS SOURCE')}]")
    return out


def _valider(notion: dict) -> None:
    """Fail-closed : tout ce qui pourrait se mesurer de travers LEVE ici.

    ⛔ **Appelee sur TOUTE notion declaree, pas seulement sur les completes.**
    Un motif mal orthographie dans une notion a moitie remplie resterait sinon
    invisible jusqu'au jour ou elle se complete — c'est-a-dire le jour ou on
    cesse de la relire. On verifie ce qui est present, tout de suite.
    """
    from backend.models.schemas import PatternType
    from backend.services.laboratoire_or import _PREDICATS
    from backend.services.pattern_detector import _est_un_achat

    nom = notion.get("nom", "?")
    if not notion.get("source"):
        raise ValueError(
            f"notion {nom!r} sans source : impossible de distinguer ce qui est "
            f"dit de ce qui est deduit")

    declencheur = notion.get("declencheur")
    if not declencheur:
        return                      # notion verrouillee : rien d'autre a juger

    connus = {p.value: p for p in PatternType}
    for motif in (declencheur, *notion.get("maillons", ()),
                  *notion.get("invalidation", ())):
        if motif not in connus:
            raise ValueError(
                f"notion {nom!r} : motif inconnu {motif!r} — un nom mal "
                f"orthographie mesurerait autre chose sous ce nom")

    for predicat in notion.get("predicats", ()):
        if predicat not in _PREDICATS:
            raise ValueError(
                f"notion {nom!r} : predicat inconnu {predicat!r} — la chaine "
                f"serait mesuree SANS sa condition")

    if not notion.get("sens"):
        return                      # le sens viendra avec les six lignes
    attendu = "buy" if _est_un_achat(connus[declencheur]) else "sell"
    if str(notion["sens"]).lower() != attendu:
        raise ValueError(
            f"notion {nom!r} : sens {notion['sens']!r} contredit son "
            f"declencheur {declencheur!r}, qui est un {attendu}")


def chaines(notions: tuple[dict, ...] | None = None) -> tuple[dict, ...]:
    """Les chaines mesurables — **uniquement** celles qui sont completes.

    ⚠️ Les incompletes sont ignorees en silence ICI, mais jamais ailleurs :
    `lignes_manquantes()` existe pour qu'elles restent visibles.
    """
    source = NOTIONS if notions is None else notions
    for n in source:
        _valider(n)             # ⛔ TOUTES, pas seulement les completes
    out = []
    for n in completes(source):
        out.append({
            "nom": f"notion:{n['nom']}",
            "motifs": tuple({n["declencheur"], *n.get("maillons", ())}),
            "declencheur": n["declencheur"],
            "predicats": tuple(n.get("predicats", ())),
            "fenetre": int(n.get("fenetre", 0) or 0),
            "invalidants": tuple(n.get("invalidation", ())),
        })
    if out:
        logger.info("notions_vivien: %d chaine(s) declaree(s) mesuree(s)",
                    len(out))
    return tuple(out)
