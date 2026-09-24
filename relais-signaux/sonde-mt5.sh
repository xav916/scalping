#!/bin/bash
# BUT : chercher ou MetaTrader 5 range les messages des canaux MQL5, sur une
#       machine LINUX (MT5 sous Wine). LECTURE SEULE.
#
# Jumelle de `sonde-mt5.ps1`, pour le cas ou MT5 ne tourne pas sur un Windows
# mais sur l'EC2 via Wine. Les deux repondent a la meme question : les messages
# du canal sont-ils sur le disque ? Si oui, un lecteur local suffit — pas de
# scraping de mql5.com, pas d'identifiants deposes dans un service.
#
# ⛔ Je NE SAIS PAS ou MT5 les range, et je ne l'invente pas. Cette sonde le
# DECOUVRE.
#
# ⛔ Elle n'ecrit RIEN, n'ouvre aucune connexion, ne lit aucun secret. Elle rend
# des CHEMINS et des COMPTES d'occurrences — jamais le contenu des fichiers, qui
# peut porter autre chose que des messages de canal.
#
# Emploi :  bash sonde-mt5.sh  [motif]
set -uo pipefail

MOTIF="${1:-Orvion}"
TAILLE_MAX_KO=65536          # 64 Mo : les historiques de bougies pesent des Go,
                             # les messages d'un canal sont petits.

echo "=== 1. MT5 est-il installe sur cette machine ? ==="
# ⚠️ On cherche l'executable AVANT les donnees : sans terminal, un dossier
# MetaQuotes residuel ne voudrait rien dire.
trouve_exe=0
for racine in "$HOME" /opt /srv /home; do
  [ -d "$racine" ] || continue
  while IFS= read -r f; do
    echo "  terminal : $f"; trouve_exe=1
  done < <(find "$racine" -maxdepth 8 -iname 'terminal64.exe' 2>/dev/null | head -20)
done
[ "$trouve_exe" -eq 0 ] && echo "  aucun terminal64.exe trouve"

echo
echo "=== 2. Dossiers de donnees MetaQuotes ==="
dossiers=()
while IFS= read -r d; do
  echo "  $d"; dossiers+=("$d")
done < <(find "$HOME" /opt /srv /home -maxdepth 10 -type d -iname 'MetaQuotes' 2>/dev/null | head -20)
if [ ${#dossiers[@]} -eq 0 ]; then
  echo "  aucun."
  echo
  echo "  => MT5 de bureau n'est pas installe ici. Si le terminal tourne"
  echo "     ailleurs (VPS Windows), lancer sonde-mt5.ps1 la-bas."
  exit 0
fi

echo
echo "=== 3. Recherche de « $MOTIF » (lecture seule, <= 64 Mo par fichier) ==="
# ⚠️ ASCII *et* UTF-16LE. MT5 est un binaire Windows : ses fichiers peuvent
# porter l'un ou l'autre, et ne chercher qu'en ASCII raterait la moitie des cas
# sans le dire. `grep -a` traite le binaire comme du texte ; le motif espace
# (O\0r\0v\0i\0o\0n) attrape l'UTF-16LE.
motif_utf16=$(printf '%s' "$MOTIF" | sed 's/./&\x00/g')
examines=0; touches=0
for d in "${dossiers[@]}"; do
  while IFS= read -r f; do
    examines=$((examines + 1))
    n_ascii=$(grep -a -c -F -- "$MOTIF" "$f" 2>/dev/null || echo 0)
    n_utf16=$(grep -a -c -F -- "$motif_utf16" "$f" 2>/dev/null || echo 0)
    if [ "$n_ascii" -gt 0 ] || [ "$n_utf16" -gt 0 ]; then
      touches=$((touches + 1))
      printf '  TROUVE  %s\n' "$f"
      printf '          ascii=%s utf16=%s | %s octets | %s\n' \
             "$n_ascii" "$n_utf16" \
             "$(stat -c %s "$f" 2>/dev/null)" "$(stat -c %y "$f" 2>/dev/null | cut -d. -f1)"
    fi
  done < <(find "$d" -type f -size -"${TAILLE_MAX_KO}"k -size +0 2>/dev/null)
done

echo
echo "=== Bilan ==="
echo "  fichiers examines         : $examines"
echo "  fichiers portant le motif : $touches"
if [ "$touches" -eq 0 ]; then
  cat <<'TXT'

  Rien trouve. Trois lectures possibles :
   1. Le canal n'est suivi que sur le MOBILE — s'y abonner AUSSI depuis ce
      terminal, laisser arriver quelques messages, puis relancer.
   2. MT5 ne conserve pas les messages sur le disque (cache memoire seul, ou
      base chiffree). La lecture locale est alors sans issue.
   3. Ce n'est pas la machine qui porte le terminal abonne.
TXT
else
  echo
  echo "  Envoyez-moi ces chemins et ces tailles. Je regarde si le format est"
  echo "  exploitable AVANT d'ecrire la moindre ligne de lecteur."
fi
