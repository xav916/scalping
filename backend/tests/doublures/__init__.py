"""Doublures de modules absents de la plateforme de test.

Une doublure ne vit ici que si elle a une source de verite INDEPENDANTE qui
la compare au vrai module quand celui-ci est disponible. Sans ce temoin, une
doublure rend les tests verts et faux.
"""
