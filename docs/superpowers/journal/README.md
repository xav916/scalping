# Journal d'expériences — Recherche edge

Ce dossier contient le **journal d'expériences** du projet Scalping Radar à partir du **2026-04-25** (pivot recherche, voir `docs/superpowers/specs/2026-04-25-research-portfolio-master.md`).

## Pourquoi un journal

Après 6 semaines de tests parallèles sur 3 tracks (Horizon / Alt-data / Trend-following), sans journal on a :
- Perte de traçabilité — "qu'est-ce que j'ai testé exactement avec quels paramètres ?"
- Re-test inconscient — refaire la même expérience 2 mois plus tard
- Biais de confirmation — ne se souvenir que des résultats qui plaisaient
- Pas de comparaison rigoureuse entre tracks au gate de décision

Le journal est la pièce qui sépare un projet de recherche d'un projet de tinkering.

## Format

Une expérience = un fichier daté `YYYY-MM-DD-track-X-titre-court.md` à la racine de ce dossier (pas de sous-dossiers : le tri chronologique alphabétique fait le travail).

## Template

Voir `_template.md`.

## Index courant

Mettre à jour `INDEX.md` après chaque expérience close (verdict POSITIVE / NEGATIVE / NEUTRAL).

## Règles

1. **Une hypothèse par expérience** — si tu testes "macro features ET horizon H4 en même temps", c'est 2 expériences (ou alors une expérience croisée explicitement).
2. **Critères go/no-go fixés AVANT** de regarder le résultat. Sinon biais.
3. **Verdict final écrit en une ligne** : "Hypothèse X **CONFIRMÉE** / **INFIRMÉE** / **INDÉCISE** par expérience Y avec [résultat chiffré]".
4. **Pas de re-écriture rétroactive** — si on s'aperçoit qu'une expérience était mal protocolée, on ouvre une nouvelle expérience qui cite l'ancienne, on ne réécrit pas l'ancienne.
5. **Commits git pour tout** — chaque expérience close = un commit minimum, avec le fichier journal dans le commit.
