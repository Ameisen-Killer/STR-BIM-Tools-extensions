# -*- coding: utf-8 -*-
"""
Verification de syntaxe IronPython 2.7 (moteur de pyRevit dans Revit 2024+),
HORS Revit, avec un vrai Python 2.7. Lance par GitHub Actions dans un
conteneur python:2.7 (.github/workflows/controle.yml) :

    python2.7 _dev/syntaxe_py27.py [dossier]

Compile chaque .py du dossier (dossiers caches exclus) comme le ferait
IronPython 2.7 et signale les erreurs de syntaxe. Les scripts commencant par
"#! python3" tournent sous CPython 3 dans pyRevit et sont ignores, comme les
copies de sauvegarde (nom contenant backup, ancien ou _old).
"""

from __future__ import print_function

import os
import re
import sys

SAUVEGARDE = re.compile(br"(?i)backup|ancien|_old\b")


def echapper(valeur, propriete=False):
    valeur = valeur.replace("%", "%25").replace("\r", "%0D") \
        .replace("\n", "%0A")
    if propriete:
        valeur = valeur.replace(":", "%3A").replace(",", "%2C")
    return valeur


def fichiers(racine):
    for dossier, sous, noms in os.walk(racine):
        sous[:] = sorted(s for s in sous
                         if not s.startswith(b".") and s != b"__pycache__")
        for nom in sorted(noms):
            if nom.endswith(b".py") and not SAUVEGARDE.search(nom):
                yield os.path.join(dossier, nom)


def main():
    # Chemins en octets : les noms de dossier accentues (Modelisation...)
    # passent quel que soit le locale du conteneur.
    racine = sys.argv[1] if len(sys.argv) > 1 else "."
    if not isinstance(racine, bytes):
        racine = racine.encode("utf-8")
    github = bool(os.environ.get("GITHUB_ACTIONS"))
    erreurs, total = 0, 0
    for chemin in fichiers(racine):
        with open(chemin, "rb") as f:
            source = f.read()
        if source.startswith(b"#!") and b"python3" in source.split(b"\n")[0]:
            continue
        total += 1
        relatif = os.path.relpath(chemin, racine).replace(os.sep.encode(), b"/")
        nom = relatif.decode("utf-8", "replace")
        try:
            # dont_inherit : le "from __future__" de ce fichier ne doit pas
            # s'appliquer aux scripts verifies.
            compile(source.replace(b"\r\n", b"\n"), relatif, "exec", 0, True)
        except SyntaxError as ex:
            erreurs += 1
            message = u"{0} : syntaxe refusee par IronPython 2.7".format(
                ex.msg if isinstance(ex.msg, type(u"")) else
                ex.msg.decode("utf-8", "replace"))
            print(u"  ERREUR {0}:{1} -> {2}".format(nom, ex.lineno, message))
            if github:
                print(u"::error file={0},line={1},title={2}::{3}".format(
                    echapper(nom, True), ex.lineno or 1,
                    echapper(u"Syntaxe IronPython 2.7", True),
                    echapper(message)))
    print(u"{0} scripts compiles avec Python {1}.{2} : {3} erreur(s).".format(
        total, sys.version_info[0], sys.version_info[1], erreurs))
    return 1 if erreurs else 0


if __name__ == "__main__":
    sys.exit(main())
