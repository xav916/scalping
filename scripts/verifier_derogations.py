#!/usr/bin/env python3
"""Detecte les derogations a MOITIE posees — celles qui retrecissent en silence.

    python scripts/verifier_derogations.py          # lit la config en vigueur

## Le defaut qu'il attrape, trouve le 2026-10-04

L'or avait une derogation d'HORIZON pour les six echelles, et une derogation
de MOTIFS pour cinq d'entre elles. Les deux portes ne lisent pas le nom de la
meme facon :

- la porte d'HORIZON **normalise** — `1h` et `60min` y sont le meme horizon ;
- la porte de MOTIFS lit la chaine **BRUTE** (`par_paire.get(horizon)` dans
  `mt5_bridge`), et la production estampille `60min`.

⛔ L'or franchissait donc la porte d'horizon a 60 min, puis retombait sur la
liste GLOBALE — deux motifs (`range_bounce_up/down`) au lieu de huit. Sans un
message, sans une trace : une derogation a moitie posee ressemble exactement a
une derogation posee.

🔑 BTC et ETH portaient deja les DEUX cles. La lecon avait ete apprise une
fois sans etre appliquee ailleurs — c'est le genre d'oubli qu'un humain ne
voit pas et qu'une boucle voit toujours.

⚠️ Ce script ne corrige RIEN. Il nomme, et il sort en 1 s'il a trouve, pour
qu'un cron puisse s'en servir.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Orthographes qui designent le MEME horizon ET que la production peut
# reellement estampiller. ⚠️ Doit rester symetrique : un tableau a sens unique
# rendrait le detecteur aveugle dans l'autre sens.
#
# ⛔ `1day` N'Y EST PAS, et c'est une correction. Ma premiere version l'exigeait
# en face de `1d` — mais rien n'estampille jamais `1day` : `horizon.HORIZONS`
# dit `1d`, et le flux long porte `tf: '1d'`. Seul `bougies_du_pont._ECHELLES`
# connait `1day`, et c'est pour LIRE des bougies, pas pour marquer un setup.
#
# 🔑 Un test l'a montre en echouant. Exiger une cle que personne ne produit
# aurait signale un faux trou sur toutes les paires ouvertes au jour — et un
# detecteur qui crie a tort finit ignore, ce qui le rend pire qu'absent.
ALIAS: dict[str, tuple[str, ...]] = {
    "1h": ("60min",),
    "60min": ("1h",),
}


def horizons_sans_motifs(horizon_overrides, pattern_overrides) -> list[tuple]:
    """Rend les (paire, orthographe) ouvertes a l'horizon mais sans motifs.

    ⚠️ Une paire SANS aucune derogation de motifs n'est pas signalee : elle
    retombe volontairement sur la liste globale, c'est le reglage par defaut
    et non un oubli.

    ⚠️ Une liste de motifs VIDE compte comme absente, parce que
    `mt5_bridge` ne la retient que si elle est non vide
    (`isinstance(...) and liste`).

    ⚠️ Tout est verifie avant d'etre lu : ces valeurs viennent de variables
    d'environnement et peuvent avoir n'importe quelle forme. Un detecteur qui
    leve sur une config abimee ne detecte plus rien.
    """
    if not isinstance(horizon_overrides, dict):
        return []
    if not isinstance(pattern_overrides, dict):
        pattern_overrides = {}

    trous: list[tuple] = []
    for paire, par_dest in sorted(horizon_overrides.items()):
        motifs = pattern_overrides.get(paire)
        if not isinstance(motifs, dict) or not motifs:
            continue  # aucune derogation de motifs : repli volontaire
        if not isinstance(par_dest, dict):
            continue

        ouverts: set[str] = set()
        for liste in par_dest.values():
            if isinstance(liste, (list, tuple, set, frozenset)):
                ouverts |= {str(h) for h in liste}

        exiges: set[str] = set()
        for h in ouverts:
            exiges.add(h)
            exiges |= set(ALIAS.get(h, ()))

        for h in sorted(exiges):
            liste = motifs.get(h)
            if not (isinstance(liste, (list, tuple, set, frozenset)) and liste):
                trous.append((paire, h))
    return trous


def main() -> int:
    from config.settings import (MT5_BRIDGE_HORIZON_OVERRIDES,
                                 MT5_BRIDGE_PATTERN_OVERRIDES,
                                 MT5_BRIDGE_ALLOWED_PATTERNS)

    trous = horizons_sans_motifs(MT5_BRIDGE_HORIZON_OVERRIDES,
                                 MT5_BRIDGE_PATTERN_OVERRIDES)
    repli = len(MT5_BRIDGE_ALLOWED_PATTERNS or ())
    if not trous:
        print("✅ aucune dérogation à moitié posée")
        return 0

    print(f"⛔ {len(trous)} dérogation(s) d'horizon SANS motifs — "
          f"elles retombent sur la liste globale de {repli} motif(s) :\n")
    for paire, h in trous:
        poses = sorted(k for k in (MT5_BRIDGE_PATTERN_OVERRIDES.get(paire) or {}))
        print(f"   {paire:10s} horizon ouvert « {h} » — "
              f"clés de motifs posées : {', '.join(poses)}")
    print("\n🔑 La porte d'horizon NORMALISE les noms, celle des motifs lit la "
          "chaîne BRUTE. Il faut les deux orthographes (`1h` ET `60min`).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
