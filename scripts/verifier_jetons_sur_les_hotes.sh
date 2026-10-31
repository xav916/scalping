#!/usr/bin/env bash
# Verifie que SHADOW_PUBLIC_TOKEN_HASH et INFRA_NOTIFY_TOKEN sont LUES sur
# chaque hote, AVANT de fusionner la branche chore/dettes-audit-septembre.
#
# ⛔ Ce script n'affiche JAMAIS la valeur d'un secret. Il affiche la longueur,
# les 8 premiers caracteres du sha256, et un verdict. Rien d'autre.
#
# 🔑 Pourquoi « lues » et pas « presentes » : une variable ecrite dans un .env
# que le processus ne charge pas est absente POUR LUI. Le code livre refuse de
# demarrer sans elle ; c'est donc l'environnement du PROCESSUS qu'il faut
# interroger, pas le fichier. « Present dans le .env » n'est pas une preuve.
#
# Usage :
#   bash scripts/verifier_jetons_sur_les_hotes.sh
#   HOTE=ec2-user@13.63.77.180 bash scripts/verifier_jetons_sur_les_hotes.sh
set -uo pipefail

HOTE="${HOTE:-ec2-user@13.63.77.180}"
CLE="${CLE:-scalping-key.pem}"

echo "=== 1/2 — le conteneur backend (celui qui REFUSE de demarrer sans) ==="
ssh -i "$CLE" -o StrictHostKeyChecking=no "$HOTE" \
  'sudo docker exec scalping-radar sh -c '"'"'
for v in SHADOW_PUBLIC_TOKEN_HASH INFRA_NOTIFY_TOKEN; do
  eval val=\$$v
  if [ -z "$val" ]; then
    echo "  ⛔ $v : ABSENTE de l environnement du processus"
  else
    n=$(printf %s "$val" | wc -c)
    e=$(printf %s "$val" | sha256sum | cut -c1-8)
    echo "  ✅ $v : lue, $n caracteres, empreinte $e"
  fi
done
'"'"''

echo ""
echo "=== 2/2 — le code livre les accepte-t-il ? (import reel, pas un echo) ==="
ssh -i "$CLE" -o StrictHostKeyChecking=no "$HOTE" \
  'sudo docker exec -i scalping-radar python3 -' <<'PY'
import hashlib
import os

# Ce script tourne AVANT la fusion : le conteneur porte alors encore
# l ancien code, qui n a pas `exiger_jeton_public`. Ce n est pas une panne,
# c est la situation attendue -- il faut le DIRE, pas lever une trace.
try:
    from config.settings import exiger_jeton_public, jeton_public_configure
    DEPLOYE = True
except ImportError:
    DEPLOYE = False
    print("  ℹ️  code PAS ENCORE DEPLOYE sur cet hote (exiger_jeton_public")
    print("     absente de config.settings). Normal avant la fusion : on ne")
    print("     verifie donc ici que la PRESENCE des variables, ci-dessus.")

infra = (os.environ.get("INFRA_NOTIFY_TOKEN") or "").strip()
hash_pose = (os.environ.get("SHADOW_PUBLIC_TOKEN_HASH") or "").strip()

if DEPLOYE:
    print("  jeton_public_configure() :", jeton_public_configure())
    try:
        h = exiger_jeton_public()
        hexa = all(c in "0123456789abcdef" for c in h)
        print("  ✅ exiger_jeton_public() rend %d caracteres, hexadecimal=%s"
              % (len(h), hexa))
    except RuntimeError as e:
        print("  ⛔ exiger_jeton_public() LEVE :", str(e)[:140])
        print("     => le conteneur REFUSERA de demarrer. Poser la variable.")

print("  %s INFRA_NOTIFY_TOKEN : %s"
      % (("✅" if infra else "⛔"),
         ("%d caracteres" % len(infra)) if infra else "ABSENTE"))

# ⛔ Le controle qui compte vraiment, et que « les deux sont presentes » ne
# donne pas : le hash pose est-il bien celui du jeton ? Sinon chaque
# notification s authentifie contre un hash etranger et rend 403 -- en
# silence, parce qu une notification qui echoue ne notifie personne.
if infra and hash_pose:
    calcule = hashlib.sha256(infra.encode()).hexdigest()
    if calcule == hash_pose:
        print("  ✅ CONCORDANCE : sha256(INFRA_NOTIFY_TOKEN) == "
              "SHADOW_PUBLIC_TOKEN_HASH")
    else:
        print("  ⛔ DISCORDANCE : le hash pose n est PAS celui du jeton.")
        print("     Les deux variables sont presentes et le systeme est")
        print("     pourtant casse : toute notification rendra 403.")
elif infra or hash_pose:
    print("  ⛔ une seule des deux est posee -- la concordance est")
    print("     invérifiable, et les notifications echoueront.")
PY

echo ""
echo "⚠️ A refaire sur les DEUX autres hotes (pont MT5 Windows, pont Kraken)"
echo "   avant toute fusion. Aucune fenetre de coupure n est acceptee."
echo ""
echo "NOTE -- un troisieme controle existe, mais il ne peut tourner qu APRES"
echo "le deploiement : verifier qu un script d exploitation SORT EN ERREUR"
echo "quand la variable manque. Le lancer AVANT executerait le code ANCIEN,"
echo "celui qui porte encore un jeton par defaut : il enverrait donc une"
echo "vraie notification au lieu de refuser. Apres deploiement :"
echo ""
echo "  ssh -i $CLE $HOTE \\"
echo "    'sudo docker exec -i -e INFRA_NOTIFY_TOKEN= scalping-radar \\"
echo "       python3 /app/scripts/notify_saturation_risque.py; echo code=\$?'"
echo ""
echo "  attendu : code=1, et le message qui dit quoi poser."
