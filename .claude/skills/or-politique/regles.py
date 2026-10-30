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


def juger_destination(dest: dict, listes_blanches: dict,
                      filtres_backend: dict | None = None) -> list[dict]:
    """Les cinq verdicts, dans l'ordre, pour UNE destination.

    ⛔ DEUX mecanismes de filtre, et le VIDE veut dire l'INVERSE des deux
    cotes. `listes_blanches` porte les listes MT5, ou la porte fait
    `if LIVE_WHITELIST_PAIRS and ...` : vide => AUCUN filtrage.
    `filtres_backend` porte les filtres en opt-in STRICT (Kraken depuis le
    2026-10-30), ou vide => RIEN ne passe, donc protection maximale.

    🔑 La semantique est portee par la MAP ou la destination apparait, et
    jamais deduite de son nom : deduire aurait ete un fait reconstruit de
    plus, et c'est exactement ce que cette skill cherche a reduire.
    """
    nom = dest.get("destination_id")
    reel = bool(dest.get("reel"))
    liste = listes_blanches.get(nom)
    backend = (filtres_backend or {})
    a_filtre_backend = nom in backend

    # 1 — argent reel sans filtre de paires
    if not reel:
        r1 = _v(1, "filtre de paires", NON_APPLICABLE,
                "destinations_registry.is_real_money", "reel=False")
    elif a_filtre_backend:
        paires = sorted(backend.get(nom) or ())
        r1 = _v(1, "filtre de paires", CONFORME,
                "filtre backend en opt-in strict (vide = tout bloque)",
                ("%d paire(s) : %s" % (len(paires), ", ".join(paires)))
                if paires else
                "aucune paire inscrite : tout est bloque")
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
    elif gf is None or gf == {}:
        r2 = _v(2, "garde-fous du pont", FAIL, "/health garde_fous",
                "aucun champ publie -- on ne peut pas verifier ce qui protege")
    elif gf:
        try:
            num_champs = len(gf)
            r2 = _v(2, "garde-fous du pont", CONFORME, "/health garde_fous",
                    "%d champ(s) publie(s)" % num_champs)
        except TypeError:
            r2 = _v(2, "garde-fous du pont", ILLISIBLE, "/health garde_fous",
                    "presente mais non interpretable: %s" % type(gf).__name__)
    else:
        r2 = _v(2, "garde-fous du pont", FAIL, "/health garde_fous",
                "aucun champ publie -- on ne peut pas verifier ce qui protege")

    # 3 — seuil de confiance
    seuil = dest.get("min_confidence")
    if not reel:
        r3 = _v(3, "seuil de confiance", NON_APPLICABLE,
                "destinations_registry.is_real_money", "reel=False")
    elif seuil is None:
        r3 = _v(3, "seuil de confiance", FAIL, "BridgeConfig.min_confidence",
                "seuil=%s" % seuil)
    else:
        try:
            seuil_num = float(seuil)
            if seuil_num <= 0:
                r3 = _v(3, "seuil de confiance", FAIL, "BridgeConfig.min_confidence",
                        "seuil=%s" % seuil)
            else:
                r3 = _v(3, "seuil de confiance", CONFORME,
                        "BridgeConfig.min_confidence", "seuil=%s" % seuil)
        except (ValueError, TypeError):
            r3 = _v(3, "seuil de confiance", ILLISIBLE, "BridgeConfig.min_confidence",
                    "non interpretable: %s" % seuil)

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
