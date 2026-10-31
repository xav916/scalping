"""Le jeton public utilisé PAR LES TESTS, et son hash. Une seule source.

## Pourquoi ce module

Constat d'audit S-1 : le vrai jeton d'infrastructure était écrit en clair dans
**six fichiers de tests**, en plus des 36 scripts et des 4 documents. Un
secret recopié dans des tests est un secret publié : les tests sont lus,
clonés et exécutés partout.

🔑 **Un jeton de test n'est pas un secret** — il n'ouvre rien. Mais il doit
être **le même partout**, sinon chaque fichier porte sa propre valeur et la
divergence revient par la porte qu'on vient de fermer.

⛔ Et il ne commence **pas** par `shdw_` : le garde-fou
`test_aucun_jeton_dans_le_depot` refuse cette chaîne dans tout fichier suivi,
y compris ici. Un jeton de test qui déclencherait l'alarme rendrait l'alarme
inutilisable.
"""
from __future__ import annotations

import hashlib

#: Jeton en clair utilisé par les tests. Aucune valeur en production.
JETON_PUBLIC_DE_TEST = "jeton-de-test-or-2026"

#: Son SHA-256, ce que `SHADOW_PUBLIC_TOKEN_HASH` vaut pendant les tests.
HASH_PUBLIC_DE_TEST = hashlib.sha256(
    JETON_PUBLIC_DE_TEST.encode()).hexdigest()
