# Confluence sync

GitHub Action qui, a chaque PR mergee sur `main`, ajoute une ligne dans la
section **Historique des changements** des pages Confluence cibles de
l'espace `SCALP` (https://coudercxavier.atlassian.net/wiki/spaces/SCALP).

## Comment cibler une page depuis une PR

Deux moyens, non exclusifs :

### 1. Via label PR (recommande)

Ajoute un ou plusieurs labels `confluence:<slug>` a la PR. Le mapping
label -> page_id est dans [`.github/confluence-pages.json`](../confluence-pages.json).

Exemples :
- PR qui modifie `backend/services/meanrev_trader.py` -> label `confluence:meanrev`
- PR qui change le bridge IBKR -> label `confluence:ibkr`
- PR transverse (ex: refactor sim_gate utilise par 10 pipelines) -> plusieurs
  labels : `confluence:sim-gate`, `confluence:meanrev`, `confluence:scalp`, ...

### 2. Via section dans le PR body

Dans le corps de la PR, ajoute une ligne commencant par
`Confluence-Pages:` suivie des IDs de pages, separes par virgules :

```
Confluence-Pages: 2719746, 2785349
```

Utile pour one-shot sans creer un nouveau label.

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
