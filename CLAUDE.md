# Consignes pour Claude

Extension pyRevit « STR BIM Tools » de Tony VARIN (Revit 2024 et supérieur). Les postes se mettent
à jour avec le bouton **Update** de pyRevit, qui lit la branche `main`.

## Enchaînement

- Lire le code → modifier → contrôles ci-dessous → commit → **push sur `main`, systématiquement et
  sans redemander** (demande de Tony, 20.11.2026) → dire à Tony ce qu'il doit tester dans Revit
  après Update.
- Session cloud : la branche `claude/…` imposée ne met rien à jour sur les postes. Pousser le même
  commit sur `main` dans la foulée : `git push origin <branche>:main`.
- Rien ne tourne dans Revit depuis une session Claude : le dire clairement, ne jamais présenter un
  outil comme testé. Une action qui écrit dans la maquette est à essayer d'abord sur une copie.

## Contrôles avant de pousser

- `python3 -B _dev/controle_auto.py --depot-public` : 0 erreur, pas de nouvel avertissement.
- `python3 -B _dev/verif_scripts.py "<chemin>/script.py"` sur chaque script touché.
- La syntaxe IronPython 2.7 (`_dev/syntaxe_py27.py`) demande un vrai Python 2.7 : elle est vérifiée
  par la tâche GitHub « Controle STR BIM Tools » à chaque push. Suivre cette tâche jusqu'à
  `completed / success`.

## Conventions des outils

- Moteur IronPython 2.7 (Revit 2024) : pas de f-string, pas de `nonlocal`, chaînes accentuées en
  `u"..."`, `# -*- coding: utf-8 -*-` en première ligne.
- Titre du bouton, infobulle, auteur, version et `min_revit_ver` dans `bundle.yaml` ; pas de
  `__title__` ni de `__doc__` dans le script. `version:` reste égal à `SCRIPT_VERSION`.
- Un nouveau bouton doit être cité dans le `layout` du `bundle.yaml` de son menu, sinon il
  n'apparaît pas dans le ruban.
- Imports et code sous un `try` global qui finit par `_show_fatal` (TaskDialog), pour qu'une erreur
  de chargement s'affiche au lieu de laisser l'outil muet.
- Fenêtres : charte de `lib/str_ui.py`, pied de page « v… | STR BIM Tools by Tony Varin », XAML en
  ASCII pur (les libellés accentués sont posés par le code après chargement).
- Préférences par poste dans `prefs.json` à côté du script (ignoré par git).
- Outils FGH : mêmes filtres de collecte et même appariement par ADN que « Sync Reservations » ;
  un outil qui s'en écarte ne parle plus des mêmes réservations.
- Dépôt public : aucun fichier ni import CAN 241, aucune donnée de projet ou de client.
