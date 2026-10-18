# -*- coding: utf-8 -*-
"""
Verification statique des scripts de l'extension, HORS Revit.

    "<pyRevit>\\bin\\cengines\\CPY3123\\python.exe" _dev\\verif_scripts.py
    "<pyRevit>\\bin\\cengines\\CPY3123\\python.exe" _dev\\verif_scripts.py "chemin/script.py" ...

Sans argument, verifie lib/*.py plus les script.py de l'outil Export IFC.

Ce que ca attrape, et qu'une simple compilation ne voit pas :
  1. imports de l'API Revit dans le mauvais namespace (ex. DataStorage importe
     depuis Autodesk.Revit.DB alors qu'il vit dans DB.ExtensibleStorage) ;
  2. appels vers un module de lib/ qui n'expose pas le nom appele ;
  3. self.attribut lu mais jamais assigne dans la classe ;
  4. syntaxe Python 3 seulement (f-strings, arguments keyword-only), refusee
     par IronPython 2.7 qui reste le moteur de Revit 2024.

Le fichier api_types_revit2024.txt contient les types publics de RevitAPI.dll et
RevitAPIUI.dll de Revit 2024 (version minimale supportee par l'extension), au
format "namespace|Type". Pour le regenerer apres une mise a jour de Revit, voir
la commande PowerShell en fin de fichier.
"""

import ast
import io
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FICHIER_API = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "api_types_revit2024.txt")

_EXPORT = os.path.join(RACINE, "STR Bim Tools.tab", "Base.panel",
                       "Export.pulldown")

CIBLES_DEFAUT = [
    os.path.join(RACINE, "lib", "str_ui.py"),
    os.path.join(RACINE, "lib", "str_ifc.py"),
    os.path.join(RACINE, "lib", "str_progress_sta.py"),
    os.path.join(RACINE, "lib", "str_progress_revit.py"),
    os.path.join(_EXPORT, "Export IFC.pushbutton", "script.py"),
    os.path.join(_EXPORT, "Export PDF-DWG multiple.pushbutton", "script.py"),
    os.path.join(_EXPORT, "Export PDF-DWG Vue Active.pushbutton", "script.py"),
]

# Membres herites de System.Windows.Window et des classes .NET de base : lus sans
# etre assignes dans la classe Python, ce qui est normal.
HERITES = set("""
Close Show ShowDialog Dispatcher Title Width Height MinWidth MinHeight Content
Background ResizeMode Topmost WindowStartupLocation Closing IsEnabled Visibility
""".split())


def charger(chemins):
    arbres = {}
    for chemin in chemins:
        if not os.path.isfile(chemin):
            print("ABSENT : " + chemin)
            continue
        src = io.open(chemin, encoding="utf-8").read()
        # Cle = dossier parent + nom : l'extension contient une vingtaine de
        # fichiers nommes script.py, une cle sur le seul nom de base en aurait
        # verifie un seul en ecrasant les autres en silence.
        nom = os.path.basename(chemin)
        parent = os.path.basename(os.path.dirname(chemin))
        if nom == "script.py":
            nom = "{0}/{1}".format(parent, nom)
        try:
            arbres[nom] = (ast.parse(src), src)
        except SyntaxError as ex:
            print("SYNTAXE {0}:{1} -> {2}".format(nom, ex.lineno, ex.msg))
    return arbres


def noms_publics(arbre):
    trouves = set()
    for noeud in arbre.body:
        if isinstance(noeud, (ast.FunctionDef, ast.ClassDef)):
            trouves.add(noeud.name)
        elif isinstance(noeud, ast.Assign):
            for cible in noeud.targets:
                if isinstance(cible, ast.Name):
                    trouves.add(cible.id)
        elif isinstance(noeud, (ast.Import, ast.ImportFrom)):
            for alias in noeud.names:
                trouves.add(alias.asname or alias.name.split(".")[0])
    return trouves


def charger_api():
    api = {}
    if not os.path.isfile(FICHIER_API):
        return api
    for ligne in io.open(FICHIER_API, encoding="utf-8-sig"):
        ligne = ligne.strip()
        if "|" in ligne:
            ns, nom = ligne.split("|", 1)
            api.setdefault(ns, set()).add(nom)
    return api


def verifier_imports_revit(arbres, api, problemes):
    if not api:
        print("NB : api_types_revit2024.txt absent, controle des imports "
              "Revit ignore.")
        return
    for nom_fichier, (arbre, _src) in arbres.items():
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.ImportFrom) or not noeud.module:
                continue
            if not noeud.module.startswith("Autodesk.Revit"):
                continue
            if noeud.module not in api:
                problemes.append("{0}:{1} -> namespace inconnu : {2}".format(
                    nom_fichier, noeud.lineno, noeud.module))
                continue
            for alias in noeud.names:
                if alias.name in api[noeud.module]:
                    continue
                ailleurs = [ns for ns, noms in api.items()
                            if alias.name in noms]
                problemes.append("{0}:{1} -> {2} absent de {3}{4}".format(
                    nom_fichier, noeud.lineno, alias.name, noeud.module,
                    " (present dans " + ", ".join(ailleurs) + ")"
                    if ailleurs else " (introuvable dans l'API)"))


def verifier_modules_lib(arbres, problemes):
    api_lib = dict((nom.replace(".py", ""), noms_publics(arbre))
                   for nom, (arbre, _s) in arbres.items()
                   if nom.startswith("str_"))
    for nom_fichier, (arbre, _src) in arbres.items():
        courant = nom_fichier.replace(".py", "")
        for noeud in ast.walk(arbre):
            if (isinstance(noeud, ast.Attribute)
                    and isinstance(noeud.value, ast.Name)
                    and noeud.value.id in api_lib
                    and noeud.value.id != courant
                    and noeud.attr not in api_lib[noeud.value.id]):
                problemes.append("{0}:{1} -> {2}.{3} n'existe pas".format(
                    nom_fichier, noeud.lineno, noeud.value.id, noeud.attr))


def verifier_attributs(arbres, problemes):
    for nom_fichier, (arbre, _src) in arbres.items():
        for classe in [n for n in ast.walk(arbre)
                       if isinstance(n, ast.ClassDef)]:
            assignes, methodes, lus = set(), set(), {}
            # Attributs de classe : MAX = 50 dans le corps de la classe est bien
            # accessible via self.MAX, sans affectation sur self.
            for noeud in classe.body:
                if isinstance(noeud, ast.Assign):
                    for cible in noeud.targets:
                        if isinstance(cible, ast.Name):
                            assignes.add(cible.id)
            for noeud in ast.walk(classe):
                if isinstance(noeud, ast.FunctionDef):
                    methodes.add(noeud.name)
                cibles = []
                if isinstance(noeud, ast.Assign):
                    cibles = list(noeud.targets)
                elif isinstance(noeud, ast.AugAssign):
                    cibles = [noeud.target]
                deplie = []
                while cibles:
                    cible = cibles.pop()
                    if isinstance(cible, (ast.Tuple, ast.List)):
                        cibles.extend(cible.elts)
                    else:
                        deplie.append(cible)
                for cible in deplie:
                    if (isinstance(cible, ast.Attribute)
                            and isinstance(cible.value, ast.Name)
                            and cible.value.id == "self"):
                        assignes.add(cible.attr)
            for noeud in ast.walk(classe):
                if (isinstance(noeud, ast.Attribute)
                        and isinstance(noeud.value, ast.Name)
                        and noeud.value.id == "self"
                        and isinstance(noeud.ctx, ast.Load)):
                    lus.setdefault(noeud.attr, noeud.lineno)
            for attr, ligne in sorted(lus.items(), key=lambda kv: kv[1]):
                if (attr not in assignes and attr not in methodes
                        and attr not in HERITES):
                    problemes.append(
                        "{0}:{1} -> self.{2} lu mais jamais assigne ({3})"
                        .format(nom_fichier, ligne, attr, classe.name))


def verifier_syntaxe_py2(arbres, problemes):
    for nom_fichier, (arbre, _src) in arbres.items():
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.JoinedStr):
                problemes.append(
                    "{0}:{1} -> f-string, refusee par IronPython 2.7".format(
                        nom_fichier, noeud.lineno))
            if (isinstance(noeud, ast.arguments)
                    and getattr(noeud, "kwonlyargs", None)):
                problemes.append(
                    "{0} -> argument keyword-only, refuse par IronPython 2.7"
                    .format(nom_fichier))


def main():
    cibles = sys.argv[1:] or CIBLES_DEFAUT
    arbres = charger(cibles)
    if not arbres:
        print("Rien a verifier.")
        return 1

    problemes = []
    verifier_imports_revit(arbres, charger_api(), problemes)
    verifier_modules_lib(arbres, problemes)
    verifier_attributs(arbres, problemes)
    verifier_syntaxe_py2(arbres, problemes)

    for nom in sorted(arbres):
        print("  lu : {0} ({1} lignes)".format(nom,
                                               arbres[nom][1].count("\n") + 1))
    if problemes:
        print("")
        print("PROBLEMES ({0}) :".format(len(problemes)))
        for p in problemes:
            print("  - " + p)
        return 1
    print("")
    print("OK : imports Revit, appels inter-modules, attributs self. et "
          "syntaxe IronPython 2.7 valides.")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# Regeneration de api_types_revit2024.txt (PowerShell 7, hors Revit) :
#
#   $lignes = New-Object Collections.Generic.List[string]
#   foreach ($dll in @("C:\Program Files\Autodesk\Revit 2024\RevitAPI.dll",
#                      "C:\Program Files\Autodesk\Revit 2024\RevitAPIUI.dll")) {
#     $fs = [IO.File]::OpenRead($dll)
#     $pe = New-Object System.Reflection.PortableExecutable.PEReader($fs)
#     $md = [System.Reflection.Metadata.PEReaderExtensions]::GetMetadataReader($pe)
#     foreach ($h in $md.TypeDefinitions) {
#       $td = $md.GetTypeDefinition($h)
#       if (($td.Attributes -band [System.Reflection.TypeAttributes]::Public) -eq 0) { continue }
#       $ns = $md.GetString($td.Namespace); $n = $md.GetString($td.Name)
#       if ($ns) { $lignes.Add("$ns|$n") }
#     }
#     $pe.Dispose(); $fs.Dispose()
#   }
#   $lignes | Sort-Object -Unique | Set-Content _dev\api_types_revit2024.txt -Encoding UTF8
