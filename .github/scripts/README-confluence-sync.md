# Confluence sync

GitHub Action qui, a chaque PR mergee sur `main`, ajoute une ligne dans la
section **Historique des changements** des pages Confluence cibles de
l'espace `SCALP` (https://coudercxavier.atlassian.net/wiki/spaces/SCALP).

## Comment cibler une page depuis une PR

Trois sources, UNION des cibles. Zero intervention manuelle dans le cas
nominal : le mapping `files` du JSON derive automatiquement les pages
depuis les fichiers modifies.

### 1. Automatique : mapping `files` (recommande, nominal)

Le mapping `files` de [`.github/confluence-pages.json`](../confluence-pages.json)
associe des patterns `fnmatch` (globs) aux page_ids concernes :

```json
"files": {
  "backend/services/meanrev_trader.py": ["2719746"],
  "backend/services/trader_*.py": ["2588886", "2785332"],
  "backend/services/*_watchdog.py": ["2719796"]
}
```

A chaque PR, le script fetch `/pulls/{n}/files` via l'API GitHub et union
toutes les pages matchees. Aucune action manuelle n'est necessaire tant
que le mapping couvre les fichiers modifies.

Requiert `GITHUB_TOKEN` (pre-provisionne par Actions, deja dans le
workflow). Sans token, cette source est ignoree silencieusement.

### 2. Via label PR (fallback / override explicite)

Ajoute un ou plusieurs labels `confluence:<slug>` a la PR. Le mapping
`labels` du JSON associe le slug a un page_id.

Exemples d'usage :
- PR qui touche la doc d'une page sans toucher le code (ajout manuel du
  label pour l'historique)
- PR transverse qui concerne une page conceptuelle (ex: `confluence:rem-002`)
  non reliee a un fichier precis

### 3. Via section dans le PR body (override one-shot)

Dans le corps de la PR, ligne commencant par `Confluence-Pages:` :

```
Confluence-Pages: 2719746, 2785349
```

Utile pour cibler ad-hoc sans creer un label ni toucher le mapping.

## Ce qui est ajoute

Pour chaque page cible, une entree HTML dans la section
"Historique des changements" :

```html
<li><strong>2026-11-15</strong> — <a href="https://github.com/xav916/scalping/pull/123">PR #123</a> Titre de la PR <em>(@auteur)</em></li>
```

Idempotent : si la PR est deja listee (via son numero dans un href `pull/N`
ou `PR #N`), elle est skip. Possibilite de re-run sans doublon.

## Setup initial (one-time, par le proprietaire du repo)

### Secrets GitHub

Repo settings -> Secrets and variables -> Actions -> New repository secret :

| Secret | Valeur |
|---|---|
| `CONFLUENCE_EMAIL` | Email Atlassian du compte (ex: `couderc.xavier@gmail.com`) |
| `CONFLUENCE_API_TOKEN` | API token Atlassian, cree sur https://id.atlassian.com/manage-profile/security/api-tokens |
| `CONFLUENCE_BASE_URL` | `https://coudercxavier.atlassian.net/wiki` |

### Labels GitHub

Repo settings -> Labels -> ajouter les labels `confluence:*` listes dans
[`.github/confluence-pages.json`](../confluence-pages.json). Couleur suggeree
pour les differencier des autres labels.

## Ajouter une nouvelle page au mapping

1. Creer la page dans Confluence (espace `SCALP`).
2. Noter son ID (dans l'URL, ex : `/pages/2719746/...`).
3. Ajouter une entree dans `.github/confluence-pages.json` :

```json
"confluence:ma-feature": "2719746"
```

4. Creer le label `confluence:ma-feature` dans les settings GitHub.
5. Commit + push. Les futures PRs avec ce label seront syncees.

## Debug local

Pour tester sans attendre un merge :

```bash
export GITHUB_EVENT_PATH=/tmp/fake-event.json
export CONFLUENCE_EMAIL=...
export CONFLUENCE_API_TOKEN=...
export CONFLUENCE_BASE_URL=https://coudercxavier.atlassian.net/wiki

cat > $GITHUB_EVENT_PATH <<'EOF'
{
  "pull_request": {
    "number": 999,
    "title": "Test sync",
    "body": "Confluence-Pages: 2719746",
    "html_url": "https://github.com/xav916/scalping/pull/999",
    "merged": true,
    "user": {"login": "test-user"},
    "labels": []
  }
}
EOF

python .github/scripts/confluence_sync.py
```

## Limites connues

- Le script n'ajoute que des entrees d'historique. Il ne cree pas de
  nouvelles pages (pour une nouvelle feature sans page existante, cree la
  page manuellement d'abord puis ajoute-la au mapping).
- Pas de rollback automatique en cas d'erreur sur une page (les pages
  precedentes du run restent mises a jour). L'action retourne exit 1 si
  au moins une page a echoue.
- L'ordre d'injection place la nouvelle entree en haut de la liste
  (dernier en premier). Si tu veux l'ordre inverse, modifier
  `_inject_entry` pour inserer avant `</ul>` au lieu d'apres `<ul>`.

