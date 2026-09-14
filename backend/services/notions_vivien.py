"""Le dictionnaire des notions DECLAREES — et ce qu'il manque pour les mesurer.

⛔ **Le verrou que ce module implemente** (2026-09-14). SIX titres de videos
sont connus, et le contenu d'aucun ne l'est :

    « 5 etapes pour prendre des trades gagnants »
    « Ma strategie en 3 etapes »
    « Tu achetes ou tu vends ? »
    « Ne trade plus sans connaitre ces elements »
    « Comment tu veux performer sans connaitre ces raccourcis ? »
    « Que faire dans ce contexte ? »

⚠️ **PROVENANCE EXACTE, et elle compte.** Ces titres viennent d'UN message de
Xavier, le 2026-09-12 a 13:20 UTC — et ce message etait lui-meme un document
de recherche qu'il transmettait : « *La reponse que je vais te donner, ces
dessous est un scrap de toutes les notions qu'evoque Vivian Legendary Trading
dans ces videos Facebook* ». Le document dit textuellement que le contenu
audio « doit encore etre decode ».

⛔ **Xavier n'a donc JAMAIS enonce ces regles**, et il ne s'est jamais engage a
le faire. Ecrire « en attente de SES regles » lui ferait porter une dette qu'il
n'a pas contractee — corrige le 2026-09-14 apres qu'il ait demande la citation.

⛔ **Et rien ici n'est verifie de premiere main.** Les durees (16 s, 37 s) et
la mention d'un « index public » proviennent du meme document transmis. Aucune
video n'a ete ouverte, aucun index consulte. Ma premiere version ecrivait
« index public Vivien_Legendary, releve le 2026-09-12 » comme si nous l'avions
lu : c'est le glissement exact que ce module est cense empecher.

Aucune heure de code n'ouvre ces titres. Inventer les cinq etapes fabriquerait
« un robot inspire de Vivien » en croyant reproduire sa methode — exactement ce
que le document refuse par ecrit.

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

# ─── Le statut d'une etape : d'ou vient-elle, exactement ────────────
#
# ⛔ Trois statuts, jamais deux. Fondre RAPPORTE et RECONSTRUIT ferait passer
# notre lecture pour sa parole — et c'est precisement ce qui fabrique « un
# robot inspire de Vivien » qu'on croit fidele.
RAPPORTE = "RAPPORTE"        # restitue tel quel par l'indexation automatique
RECONSTRUIT = "RECONSTRUIT"  # un mot corrige par le contexte, pas entendu
MANQUANT = "MANQUANT"        # l'indexation coupe avant — trou, pas hypothese

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
    # ─── VERROUILLEES : titre rapporte, contenu inconnu ───────────────
    # ⛔ Les six champs valent None. Ce n'est pas un oubli, c'est l'etat du
    # savoir. Les remplir de memoire serait une invention.
    #
    # ⚠️ `source` dit d'ou vient le TITRE, pas la regle — et il dit aussi que
    # rien n'a ete verifie de premiere main. C'est ce qui garde separable
    # « ce qui est dit », « ce qui est rapporte » et « ce que nous deduisons ».
    {"nom": "cinq_etapes",
     "titre": "5 etapes pour prendre des trades gagnants",
     "source": "Titre de video, rapporte dans le message de Xavier du 2026-09-12 13:20 UTC — lui-meme un document de recherche transmis. Contenu jamais consulte de premiere main.",
     # ⛔ QUATRE etapes sur cinq, rapportees par Xavier le 2026-09-14 depuis
     # une indexation AUTOMATIQUE de la video. La cinquieme est coupee avant
     # restitution. Xavier l'a ecrit lui-meme : « je ne veux surtout pas la
     # fabriquer a partir de ce qu'on connait deja de Vivien ».
     #
     # ⚠️ Les deux RECONSTRUIT sont des corrections de contexte, pas des mots
     # entendus. Le texte brut est garde a cote : si la reconstruction est
     # fausse, elle reste rattrapable.
     "etapes": (
         {"n": 1, "statut": RECONSTRUIT, "texte": "Ouvrir TradingView",
          "brut": "ouf TradingView",
          "note": "« ouf » corrige en « ouvre » par le contexte"},
         {"n": 2, "statut": RAPPORTE,
          "texte": "Trouver une zone d'accumulation",
          "brique": "AUCUNE — nous n'avons pas de detecteur d'accumulation"},
         {"n": 3, "statut": RAPPORTE,
          "texte": "Tracer le Volume Profile sur cette zone",
          "brique": "market_profile — mais TPO, pas volume (le volume existe "
                    "depuis le 12/09 et n'est pas encore utilise ici)"},
         {"n": 4, "statut": RECONSTRUIT,
          "texte": "Attendre une prise de liquidite (liquidity grab)",
          "brut": "grade de liquidite",
          "note": "« grade » corrige en « grab » par le contexte",
          "brique": "liquidity_sweep — deja code"},
         {"n": 5, "statut": MANQUANT,
          "texte": "[MANQUANT — declencheur exact a recuperer]",
          "note": "L'indexation coupe avant. Ni retest, ni BOS, ni delta : "
                  "aucune preuve. Une video de 16 s ou un enregistrement "
                  "d'ecran permettrait de la lire."},
     )},
    {"nom": "strategie_trois_etapes",
     "titre": "Ma strategie en 3 etapes",
     "source": "Titre de video, rapporte dans le message de Xavier du 2026-09-12 13:20 UTC — lui-meme un document de recherche transmis. Contenu jamais consulte de premiere main."},
    {"nom": "acheter_ou_vendre",
     "titre": "Tu achetes ou tu vends ?",
     "source": "Titre de video, rapporte dans le message de Xavier du 2026-09-12 13:20 UTC — lui-meme un document de recherche transmis. Contenu jamais consulte de premiere main."},
    # ⛔ Celle-ci manquait a ma premiere version : six titres, j'en avais
    # declare cinq. Une notion oubliee est une notion qu'on n'attendra jamais.
    {"nom": "ne_trade_plus_sans_ces_elements",
     "titre": "Ne trade plus sans connaitre ces elements",
     "source": "Titre de video, rapporte dans le message de Xavier du 2026-09-12 13:20 UTC — lui-meme un document de recherche transmis. Contenu jamais consulte de premiere main."},
    {"nom": "les_raccourcis",
     "titre": "Comment tu veux performer sans connaitre ces raccourcis ?",
     "source": "Titre de video, rapporte dans le message de Xavier du 2026-09-12 13:20 UTC — lui-meme un document de recherche transmis. Contenu jamais consulte de premiere main."},
    {"nom": "que_faire_dans_ce_contexte",
     "titre": "Que faire dans ce contexte ?",
     "source": "Titre de video, rapporte dans le message de Xavier du 2026-09-12 13:20 UTC — lui-meme un document de recherche transmis. Contenu jamais consulte de premiere main."},
)


def par_nom(nom: str) -> dict:
    for n in NOTIONS:
        if n["nom"] == nom:
            return n
    raise KeyError(f"notion inconnue : {nom!r}")


def manques(notion: dict) -> tuple[str, ...]:
    """Ce qui manque : les six lignes, ET les etapes non restituees.

    ⛔ Les etapes sont une condition **separee** des six lignes. Sans cela,
    completer les six champs en devinant l'etape manquante rouvrirait la porte
    — c'est exactement la porte que Xavier a demande de tenir fermee :
    « notre automate ne prendrait aucun trade tant qu'on n'a pas formalise la
    cinquieme condition ».
    """
    out = [c for c in CHAMPS if not notion.get(c)]
    out += [f"etape_{e['n']}" for e in notion.get("etapes", ())
            if e.get("statut") == MANQUANT]
    return tuple(out)


def avancement(notion: dict) -> str:
    """« 4/5 » — combien d'etapes sont restituees. Vide si aucune connue."""
    etapes = notion.get("etapes", ())
    if not etapes:
        return ""
    connues = sum(1 for e in etapes if e.get("statut") != MANQUANT)
    return f"{connues}/{len(etapes)}"


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
        etat = avancement(n)
        out.append(f"{n['nom']} « {n.get('titre', '?')} »"
                   f"{f' — etapes {etat}' if etat else ''} — manque : "
                   f"{', '.join(manques(n))} "
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
