"""Insere la route /ticks dans une copie du pont, EN BINAIRE.

⛔ Pourquoi en binaire : mon premier jet a lu puis reecrit le fichier en mode
texte avec `newline="\\r\\n"`, et la taille obtenue (227 016 octets pour
+7 872 caracteres ajoutes) ne collait pas avec l'arithmetique des fins de
ligne. Plutot que de supposer, on ne touche plus aux octets : on MESURE la fin
de ligne dominante du fichier cible, on l'epouse pour la route inseree, et on
verifie que tout le reste du fichier est intact octet pour octet.
"""
import hashlib
import io
import os

S = os.path.dirname(os.path.abspath(__file__))
ANCRE = b'@app.route("/order_check", methods=["POST"])'
ATTENDU = "B85EC3B010CD9781CA0B11A0C5BD9CBA3A628029111D1D5328114C07A6BE0309"

orig = open(os.path.join(S, "br4.sauf"), "rb").read()
h = hashlib.sha256(orig).hexdigest().upper()
print(f"original : {len(orig)} octets   sha256 {h[:16]}...")
assert h == ATTENDU, "la copie locale n'est plus celle de la production"

n_crlf = orig.count(b"\r\n")
n_lf = orig.count(b"\n") - n_crlf
print(f"   CRLF {n_crlf}   LF seuls {n_lf}")
crlf = n_crlf > n_lf
fin_ligne = b"\r\n" if crlf else b"\n"
print(f"   fin de ligne dominante : {'CRLF' if crlf else 'LF'}")

route_txt = io.open(os.path.join(S, "route_ticks.py"), encoding="utf-8").read()
route = fin_ligne.join(x.encode("utf-8") for x in route_txt.split("\n"))
print(f"route a inserer : {len(route)} octets, "
      f"{route_txt.count(chr(10))} lignes")

assert orig.count(ANCRE) == 1, f"ancre vue {orig.count(ANCRE)} fois"
assert b'"/ticks"' not in orig, "une route /ticks existe deja"

neuf = orig.replace(ANCRE, route + ANCRE, 1)
cible = os.path.join(S, "bridge_patche.py")
open(cible, "wb").write(neuf)

print()
print(f"patche : {len(neuf)} octets   (+{len(neuf) - len(orig)})")
print(f"   sha256 : {hashlib.sha256(neuf).hexdigest().upper()}")

# ⛔ Le reste du fichier doit etre INTACT, octet pour octet.
avant, apres = orig.split(ANCRE, 1)
assert neuf.startswith(avant), "le debut du fichier a change"
assert neuf.endswith(apres), "la fin du fichier a change"
assert len(neuf) == len(orig) + len(route), "taille inattendue"
print("   ✅ tout le fichier d'origine est INTACT, octet pour octet")
print("   ✅ seule la route est inseree, juste avant /order_check")

import py_compile
py_compile.compile(cible, doraise=True, cfile=os.path.join(S, "bp.pyc"))
print("   ✅ le fichier patche compile")
